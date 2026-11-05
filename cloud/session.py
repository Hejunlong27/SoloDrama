"""cloud/session.py —— 任务级镜像生命周期：**要跑才开，跑完就关**

为什么需要这一层
----------------
`Provisioner` 只提供原语（建 / 等 / 停），它不知道「任务」什么时候开始、什么时候结束。
于是使用者必须记得两条命令：跑之前 `cloud up`，跑之后 `cloud down`。**人会忘**。
忘的不是操作，是钱：一台 4090 开一夜是 ￥38（1.59×24）。

`Lease` 把这件事变成 `with` 语句：

    with Lease(cfg, ws, name="盲婚", url=cfg_url) as lease:
        run_batch(lease.url)
        lease.usage(episodes=1, segments=8)
    # 退出即停机（且无论成功、失败、Ctrl-C）

三条语义（都不是「顺手加的」，各自对应一类事故）
------------------------------------------------
1. **只停自己开的**（`owned`）。复用一台别人正在跑的机器，跑完替人关掉 = 另一种事故。
   与 `comfy_boot.py` 同一条原则：只停自己启动的。要关别人的，用 `cloud down --instance`。
2. **失败也停**。`__exit__` 不看异常类型 —— 出片失败时机器更该停（那时没人会想起来）。
3. **没端点就借**。`endpoints` 未配时不会假装能建，而是接管已有地址（`attach`），
   照常跑、照常探活，只是**不停机**（因为不是我们开的）。这让「今天就可用」与
   「配好后自动省钱」共存。

与 `auto_stop_after_idle_min` 的分工
------------------------------------
`Lease` 管**正常路径**（任务结束即停）。`Provisioner.reap()` 管**异常路径**
（进程被 kill、机器重启、压根没走到 finally）。两者都以本地状态里的
`last_used_at` 为依据，所以不会互相打架。
"""
from __future__ import annotations

import contextlib
import os
import time

from . import config as CFG
from . import health as HEALTH
from .provisioner import CloudNotConfigured, CostGuard, Instance, Provisioner


class CloudNotReady(RuntimeError):
    """实例没能就绪（探活/等待超时）。已按要求停机，异常里带原因。"""


class Lease:
    """一次任务对一台云端实例的独占使用期。``with`` 退出即释放。"""

    def __init__(self, cfg: dict | None = None, *, ws=None, name: str = "", url: str = "",
                 keep: bool = False, workflow: str = "", timeout_min: float | None = None,
                 log=print):
        self.cfg = cfg or CFG.effective()
        self.ws = ws
        self.name = name or ("solodrama-%s" % time.strftime("%Y%m%d-%H%M"))
        self.url = (url or "").rstrip("/")
        self.keep = bool(keep)
        self.workflow = workflow
        self.timeout_min = timeout_min
        self.log = log
        self.prov = Provisioner(self.cfg, ws=ws, log=log)
        self.inst: Instance | None = None
        self.owned = False
        self._usage = {"episodes": 0, "segments": 0}

    # —— 上下文 ——
    def __enter__(self) -> "Lease":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release(failed=exc is not None)
        return False                       # 异常照原样抛，不吞

    # —— 取机器 ——
    def acquire(self) -> Instance:
        """拿到一台**就绪**的实例：复用 → 开机 → 新建 → 借。四个分支都要说清走的是哪条。"""
        inst, owned = self._resolve()
        self.inst, self.owned = inst, owned
        # 地址立刻进环境：子进程（出片脚本）只认 COMFYUI_URL
        if inst.http_url:
            os.environ["COMFYUI_URL"] = inst.http_url

        if owned:
            ok = self.prov.wait_ready(inst, self.timeout_min or None,
                                      workflow_path=self.workflow)
        else:
            res = HEALTH.probe(inst.http_url, self.workflow)
            ok = bool(res.get("ok"))
            if not ok:
                self.log("  [未就绪] %s\n%s" % (inst.http_url, HEALTH.render(res, indent="    ")))
        if not ok:
            # 自己开的机器没就绪 → 已由 wait_ready 停掉；借来的不动
            raise CloudNotReady(
                "实例 %s 未能就绪（%s）。%s"
                % (inst.id, inst.http_url or "无地址",
                   "已自动停机，避免空转计费。" if owned else "该实例不是本次启动的，未自动停机。"))
        self.prov.touch(inst)
        self.log("[就绪] %s（%s）" % (inst.id, "本次启动，结束即停" if owned
                                      else "复用已有实例，不替你停机"))
        return inst

    def _resolve(self) -> tuple:
        """四个分支按「成本从低到高」排：复用 < 借 < 开机 < 新建。"""
        prov = self.prov
        # ① 本地记录里有同名在跑 → 复用（不建、不开机、也不替你停）
        rows = prov.state.load()
        for iid, r in rows.items():
            if (r.get("name") == self.name
                    and str(r.get("state") or "").lower() in ("running", "ready", "started")):
                return prov.instance_from_state(iid, rows), False
        # ② 给了地址 → 直接借用（拓扑 B/C，或控制台手动开的机器）
        if self.url:
            return prov.attach(self.url, name=self.name), False
        # ③ 上游有同名但已停机 → 开机（省一次冷建，数据盘还在）→ 这次是我们开的，负责关
        stopped = prov.find_stopped(self.name)
        if stopped is not None:
            return prov.start(stopped), True
        # ④ 新建（内部已含「同名在跑则复用」与成本护栏）
        try:
            inst = prov.create(self.name)
            # ★ 所有权以 create() 的判定为准：它内部可能命中「同名在跑」而**复用**，
            #   那种情况不算我们开的（测试抓到过一次：这里写死 True 会替人停机）。
            return inst, bool(inst.owned)
        except CostGuard:
            raise
        except CloudNotConfigured as exc:
            raise CloudNotConfigured(
                "%s\n  本次任务没有可用的实例地址，也没有可用的建实例端点。\n"
                "  · 手边有实例：--comfy-url https://<实例>-8188.container.x-gpu.com\n"
                "  · 想让它自己开：把 cloud.endpoints 的 create/list/stop 填上" % exc) from exc

    # —— 记账 ——
    def usage(self, *, episodes: int = 0, segments: int = 0) -> None:
        """记录本次任务产出（停机时写进台账）。"""
        self._usage = {"episodes": int(episodes or 0), "segments": int(segments or 0)}
        if self.inst is not None:
            try:
                self.prov.note_usage(self.inst, **self._usage)
            except Exception:                             # noqa: BLE001 —— 记账不该拖垮任务
                pass

    # —— 归还 ——
    def release(self, *, failed: bool = False) -> dict | None:
        """结束任务：自己开的机器停机并记账；借来的只提示。"""
        if self.inst is None:
            return None
        if not self.owned:
            self.log("[保留] 实例 %s 不是本次启动的，未自动停机。"
                     "确需关掉：python -m cloud down --instance %s" % (self.inst.id, self.inst.id))
            return None
        if self.keep:
            self.log("[保留] 按 --cloud-lifecycle keep 保留实例 %s（★ 仍在计费）" % self.inst.id)
            return None
        note = "任务%s收尾" % ("失败" if failed else "完成")
        try:
            return self.prov.stop(self.inst, note=note)
        except Exception as exc:                          # noqa: BLE001
            self.log("[FAIL] 停机失败：%s\n       立刻手动停：python -m cloud down --instance %s"
                     % (str(exc).splitlines()[0][:160], self.inst.id))
            return None

    # —— 便捷属性 ——
    @property
    def instance(self) -> Instance | None:
        return self.inst

    @property
    def http_url(self) -> str:
        return (self.inst.http_url if self.inst else "") or ""


@contextlib.contextmanager
def lease_for(cfg: dict | None = None, **kw):
    """函数式写法（给不支持 with 的调用点用）。"""
    L = Lease(cfg, **kw)
    with L:
        yield L
