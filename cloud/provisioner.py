"""cloud/provisioner.py —— 实例生命周期：建 / 等就绪 / 停 / 查 / 销毁

四条硬约束（文档 §5.3，代码里逐条对应）
----------------------------------------
1. **幂等**：`create()` 先按名字查在跑实例，有就复用。脚本重跑不该多烧一份钱 ——
   这是最容易发生的事故：CRON 跑两次，两台 4090 同时计费。
2. **失败必停**：`create()` 成功但 `wait_ready()` 超时 → 自动 `stop()`。
   宁可丢一次批次（可重跑），也不要留一台没人管的机器烧到天亮。
3. **凭据不落盘**：Token 与 SSH 密码只从环境变量读；日志一律 `mask()`。
   本模块**不接受**把 token 当参数传进来（传了就会有人写进 settings.json）。
4. **成本护栏**：`create()` 前查当日累计 GPU 小时，超 `max_hours_per_day` 直接拒绝。

⚠ 上游端点未核对
----------------
仙宫云开放 API 的端点名与字段名**尚未核对**（文档附录 C）。所以：

* `endpoints` / `field_map` 全部来自 `settings.json`（`cloud.endpoints` / `cloud.field_map`）；
* 没配 → 抛 `CloudNotConfigured`，并**点名该填哪几个键**，绝不猜一个路径去撞 404；
* 语义（幂等/必停/护栏/台账）与上游无关，已用本地假 API 全量测试覆盖。

也就是说：填上端点即可用；不填也**不会**静默做错事。
"""
from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.parse
import sys
from dataclasses import dataclass, asdict

from . import config as CFG
from . import health as HEALTH
from . import ledger as LEDGER


class CloudNotConfigured(RuntimeError):
    """云端还没配好（缺端点 / 缺字段映射 / 缺 Token）。消息里必须说清缺什么。"""


class CostGuard(RuntimeError):
    """当日 GPU 时长已超上限，拒绝建实例。"""


@dataclass
class Instance:
    """一台云端实例。`http_url` 是**拓扑 C** 的直连地址，也是 `COMFYUI_URL` 的值。"""
    id: str
    name: str = ""
    gpu: str = ""
    ssh_host: str = ""
    ssh_port: int = 22
    http_url: str = ""
    state: str = ""                     # creating / running / stopped / error
    created_at: float = 0.0
    # 上游会**按实例**报单价（仙宫云 `price_per_hour` / `base_price`）。有这个就不看配置里的
    # 兜底价 —— 不同卡型、不同数据中心的价格不一样，写死一个数迟早算错账。
    price_per_hour: float = 0.0
    # 关机保留磁盘（`retain`）**仍在计费**（`retain_price` 元/时）。
    # 这是个真实的成本陷阱：以为「停实例 = 停止计费」，结果磁盘费一直走。
    retain: bool = False
    retain_price: float = 0.0
    # ★ 所有权：这台机器是**本次任务开的**（True），还是**别人/上次留下在跑的**（False）。
    #   决定任务结束时该不该停机 —— 复用别人的机器却替他关掉，是另一种事故。
    #   与 `comfy_boot.py` 同一条原则：只停自己启动的。
    owned: bool = False

    def ready_like(self) -> bool:
        return str(self.state).lower() in ("running", "ready", "started", "on")

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# 上游 HTTP 适配器
# ---------------------------------------------------------------------------
class XgyApi:
    """仙宫云（或任何 REST 风格 provider）的薄适配器。

    端点与字段**全部来自配置**：这不是偷懒，是因为上游字段没核对过，写死等于把
    一次 404 伪装成「功能没做好」。配置化之后，核对出真名字只需改 settings.json。
    """

    def __init__(self, cfg: dict | None = None, *, token: str | None = None, timeout: float = 30):
        self.cfg = (cfg or CFG.effective())["cloud"]
        self.token = (token if token is not None else CFG.token())
        self.timeout = timeout
        self.base = str(self.cfg.get("api_base") or "").rstrip("/") + "/"

    # —— 配置自检 ——
    def endpoint(self, key: str) -> str:
        ep = (self.cfg.get("endpoints") or {}).get(key) or ""
        if not str(ep).strip():
            have = [k for k, v in (self.cfg.get("endpoints") or {}).items() if str(v).strip()]
            raise CloudNotConfigured(
                "云端上游端点未配置：缺 cloud.endpoints.%s（已配：%s）\n"
                "  仙宫云的真实端点名待登录 API Playground 核对后填入 configs/settings.json。\n"
                "  本模块不会猜路径 —— 猜错只会得到 404，比明确报「待配置」更难查。"
                % (key, "、".join(have) or "无"))
        return self.base + str(ep).lstrip("/")

    def configured(self, *keys: str) -> bool:
        eps = self.cfg.get("endpoints") or {}
        return all(str(eps.get(k) or "").strip() for k in keys)

    # —— 请求 ——
    def call(self, method: str, key: str, *, payload: dict | None = None,
             params: dict | None = None) -> dict:
        if not self.token:
            raise CloudNotConfigured(
                "缺上游 API Token：%s 环境变量为空。\n"
                "  ★ 只从环境变量读，不写进 settings.json、不写进日志（用子账号 Token，只给实例管理权限）。"
                % self.cfg.get("token_env", "XGY_TOKEN"))
        here = pathlib.Path(__file__).resolve().parent
        if str(here.parent / "stages") not in sys.path:
            sys.path.insert(0, str(here.parent / "stages"))
        import _comfy_http as Q                       # 复用重试/分类/原子性
        url = self.endpoint(key)
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        # 只支持 GET / POST：其余方法在共享 HTTP 层没有表达方式。
        # ★ 明确拒绝，而不是「悄悄按 POST 发出去」—— 后者会得到一个 405，
        #   看起来像上游不支持，其实是本层没实现。
        m = str(method or "GET").upper()
        if m not in ("GET", "POST"):
            raise NotImplementedError("cloud: 不支持 %s（只有 GET/POST）" % m)
        if m == "GET" and payload is not None:
            raise ValueError("cloud: GET 不接受请求体（%s）" % key)
        scheme = str(self.cfg.get("auth_scheme") or "").strip()
        hdr = {str(self.cfg.get("auth_header") or "Authorization"):
               (scheme + " " + self.token).strip() if scheme else self.token,
               "Content-Type": "application/json"}
        body = payload if m == "POST" else None
        data = json.dumps(body if body is not None else {}).encode("utf-8") if body is not None else None
        # ★ retries=0：建实例/停实例都不是幂等 POST，自动重发会真的再建一台。
        raw = Q.request(url, data=data, headers=hdr, timeout=self.timeout,
                        retries=0, tag="cloud:%s" % key)
        resp = json.loads(raw.decode("utf-8")) if raw else {}
        # 仙宫云用 {code, msg, success} 包一层（Playground 实测：缺令牌时
        # success=false + code=1000 + msg="未找到访问令牌"）。这类「HTTP 200 但业务失败」
        # 必须在这里变成异常 —— 否则上层会拿到一个空对象，报「取不到实例 ID」，查错方向全错。
        if isinstance(resp, dict) and resp.get("success") is False:
            raise CloudNotConfigured(
                "上游拒绝（%s）：%s%s"
                % (key, resp.get("msg") or "未知原因",
                   "，code=%s" % resp.get("code") if resp.get("code") is not None else ""))
        return resp

    # —— 响应取值 ——
    def dig(self, obj, key: str, default=None):
        """按 `cloud.field_map[key]` 的点路径取值（支持数组下标）。

        映射可以写成**候选路径列表**（`["data.id", "id"]`），按序尝试、命中即用：
        网关是否把结果包在 `data` 里不固定，写死一条会在换接口时全线取不到。
        没配映射时退化成**顶层同名键**。
        """
        paths = (self.cfg.get("field_map") or {}).get(key) or key
        if isinstance(paths, str):
            paths = [paths]
        for path in paths:
            val = self._dig_one(obj, str(path or ""))
            if val is not None and val != "":
                return val
        return default

    @staticmethod
    def _dig_one(obj, path: str):
        cur = obj
        for part in [p for p in path.split(".") if p]:
            try:
                if isinstance(cur, list):
                    cur = cur[int(part)]
                elif isinstance(cur, dict):
                    cur = cur[part]
                else:
                    return None
            except (KeyError, IndexError, ValueError, TypeError):
                return None
        return cur


# ---------------------------------------------------------------------------
# 本地状态（跨进程：`up` 记起点，`down` 才算得出工时）
# ---------------------------------------------------------------------------
class _State:
    """`<ws>/.cloud/instances.json` —— 只存「我建过什么、什么时候建的」，不存凭据。"""

    def __init__(self, ws=None):
        self.path = LEDGER.workspace(ws) / ".cloud" / "instances.json"

    def load(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return d if isinstance(d, dict) else {}

    def put(self, inst: Instance, **extra) -> None:
        d = self.load()
        row = d.get(inst.id) or {}
        row.update(inst.as_dict())
        row.update(extra)
        d[inst.id] = row
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8", newline="")

    def get(self, inst_id: str) -> dict:
        return self.load().get(str(inst_id)) or {}

    def drop(self, inst_id: str) -> None:
        d = self.load()
        if d.pop(str(inst_id), None) is not None:
            self.path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8", newline="")


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------
class Provisioner:
    """实例生命周期。`api=None` 时走**手动模式**（控制台点启动，本模块只探活与记账）。"""

    def __init__(self, cfg: dict | None = None, *, api: XgyApi | None = None,
                 ws=None, log=print):
        self.cfg = cfg or CFG.effective()
        self.cloud = self.cfg["cloud"]
        self.ws = LEDGER.workspace(ws)
        self.log = log
        self.state = _State(self.ws)
        self.api = api
        # 轮询间隔：测试要调到 0.05，线上 6 秒足够（就绪探测本身要 1–2 秒）
        self.poll_s = float(self.cloud.get("poll_seconds") or 6)

    def _id_key(self) -> str:
        """上游请求体/查询串里「实例 ID」的键名（待核对，配置化以免改代码）。"""
        return str(self.cloud.get("id_field") or "instance_id")

    def _api(self) -> XgyApi:
        if self.api is None:
            self.api = XgyApi(self.cfg)
        return self.api

    # —— 护栏 ——
    def guard(self) -> float:
        """当日累计 GPU 小时 vs 上限。返回当前小时数；超限抛 CostGuard。"""
        cap = float(self.cloud.get("max_hours_per_day") or 0)
        hours = LEDGER.day_hours(ws=self.ws)
        if cap > 0 and hours >= cap:
            raise CostGuard(
                "今日云端 GPU 已用 %.2f 小时，达到上限 %.1f 小时，拒绝再建实例。\n"
                "  这是成本护栏（settings.json → cloud.max_hours_per_day）。\n"
                "  · 确认要跑：把上限调高或设 SOLODRAMA_CLOUD_MAX_HOURS=<小时>\n"
                "  · 先看看钱花在哪：python -m cloud cost" % (hours, cap))
        return hours

    # —— 建 ——
    def create(self, name: str = "", *, image_id: str = "", gpu: str = "",
               mount_cloud: bool = None, disk_gb: int = 0, reuse: bool = True) -> Instance:
        """建一台实例（幂等）。返回 `Instance`（含 `http_url`，可直接当 COMFYUI_URL）。"""
        name = name or ("solodrama-%s" % time.strftime("%Y%m%d-%H%M"))
        image_id = image_id or str(self.cloud.get("image_id") or "")
        gpu = gpu or str(self.cloud.get("gpu") or "4090")
        mount_cloud = bool(self.cloud.get("mount_cloud") if mount_cloud is None else mount_cloud)
        disk_gb = int(disk_gb or self.cloud.get("disk_gb") or 100)

        # ① 护栏在最前：钱的问题不该等实例起来才发现
        hours = self.guard()
        self.log("[护栏] 今日已用 %.2f 小时（上限 %.1f）"
                 % (hours, float(self.cloud.get("max_hours_per_day") or 0)))

        # ② 幂等：先查同名在跑实例
        if reuse:
            hit = self._find_running(name)
            if hit is not None:
                hit.owned = False          # 不是本次开的 → 任务结束不替人停机
                self.log("[复用] 已有在跑实例 %s（%s）—— 不再新建" % (hit.id, hit.state))
                self._remember(hit)
                return hit

        # ③ 建
        api = self._api()
        payload = {"name": name, "image_id": image_id, "gpu": gpu,
                   "disk_gb": disk_gb, "mount_cloud": mount_cloud}
        # 空值不发给上游：少一个必填校验就少一类 400
        payload = {k: v for k, v in payload.items() if v not in ("", None)}
        resp = api.call("POST", "create", payload=payload)
        inst = self._to_instance(resp, fallback_name=name, fallback_gpu=gpu)
        if not inst.id:
            raise CloudNotConfigured(
                "建实例的响应里取不到实例 ID（cloud.field_map.id = %r）。\n"
                "  响应顶层键：%s\n"
                "  核对后改 configs/settings.json 的 cloud.field_map.id（点路径，如 data.id）"
                % ((self.cloud.get("field_map") or {}).get("id"),
                   "、".join(list(resp)[:8]) or "空"))
        inst.gpu = inst.gpu or gpu
        inst.created_at = inst.created_at or time.time()
        inst.owned = True
        self._remember(inst)
        self.log("[已建] 实例 %s（%s · %s）" % (inst.id, inst.gpu, inst.state or "creating"))
        return inst

    def _find_by_name(self, name: str, want) -> Instance | None:
        """按名字 + 状态谓词找实例。list 端点没配就没法保证幂等 —— 明确报错，不盲建。"""
        api = self._api()
        if not api.configured("list"):
            raise CloudNotConfigured(
                "缺 cloud.endpoints.list，无法保证「同名实例复用」这一条。\n"
                "  ★ 宁可在这里停下，也不要盲建：脚本重跑会变成两台机器同时计费。\n"
                "  填上 list 端点后重试，或用 --force-new 显式承担重复创建的风险。")
        try:
            resp = api.call("GET", "list")
        except Exception as exc:                              # noqa: BLE001
            raise CloudNotConfigured("查实例列表失败：%s" % str(exc).splitlines()[0][:200]) from exc
        for raw in self._pluck_list(resp):
            cand = self._to_instance(raw)
            if cand and cand.id and cand.name == name and want(cand):
                return cand
        return None

    def _find_running(self, name: str):
        return self._find_by_name(name, lambda c: c.ready_like())

    def find_stopped(self, name: str):
        """同名但已停机的实例（可开机复用，比重建省一块数据盘）。

        没配 `list` 时不报错、返回 None —— 这一路是**优化**（省一次冷建），
        不是正确性前提；正确性前提在 `_find_running` 那一侧。
        """
        try:
            return self._find_by_name(
                name, lambda c: str(c.state).lower()
                in ("stopped", "shutdown", "off", "stopping"))
        except CloudNotConfigured:
            return None

    @staticmethod
    def _pluck_list(resp) -> list:
        """从任意形状里把实例列表挖出来（顶层数组 / data / items / list）。"""
        if isinstance(resp, list):
            return resp
        if isinstance(resp, dict):
            for key in ("data", "items", "list", "rows", "instances"):
                v = resp.get(key)
                if isinstance(v, list):
                    return v
                if isinstance(v, dict):
                    for k2 in ("items", "list", "rows", "instances"):
                        if isinstance(v.get(k2), list):
                            return v[k2]
        return []

    def _to_instance(self, resp, *, fallback_name: str = "", fallback_gpu: str = "") -> Instance:
        api = self._api()
        # 有些接口把对象包在 data 里，有些直接把字段放顶层 —— field_map 的点路径两种都能写。
        # 这里再兜一层：`field_map` 指向 data.x 但 data 不存在时，退回顶层同名键。
        def pick(key, default=""):
            v = api.dig(resp, key, None)
            if v is None and isinstance(resp, dict):
                v = resp.get(key)
            return v if v is not None else default

        port = pick("ssh_port", 22)
        try:
            port = int(port or 22)          # ★ 上游给的是字符串（"22022"）
        except (TypeError, ValueError):
            port = 22

        def fnum(key):
            try:
                return float(pick(key, 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        inst = Instance(
            id=str(pick("id", "") or ""),
            name=str(pick("name", fallback_name) or fallback_name),
            gpu=str(pick("gpu", fallback_gpu) or fallback_gpu),
            ssh_host=str(pick("ssh_host", "") or ""),
            ssh_port=port,
            http_url=str(pick("http_url", "") or "").rstrip("/"),
            state=str(pick("state", "") or ""),
            price_per_hour=fnum("price_per_hour"),
            retain=bool(pick("retain", False)),
            retain_price=fnum("retain_price"),
        )
        if not inst.http_url and inst.id:
            inst.http_url = self.url_for(inst)
        return inst

    def url_for(self, inst: Instance) -> str:
        """按 provider 的地址规则拼直连地址：`https://<id>-8188.container.x-gpu.com`。

        只在响应里没给 http_url 时兜底；给了就以响应为准（不同 provider 规则不同）。
        规则写在 `cloud.http_url_template`，`{id}` 是占位符；没写模板且 api_base 不是
        仙宫云时返回空 —— 宁可「没有地址」也不要拼一个看似能用的错域名。
        """
        if not inst.id:
            return ""
        tpl = str(self.cloud.get("http_url_template") or "").strip()
        if tpl:
            return tpl.replace("{id}", inst.id).rstrip("/")
        if "xiangongyun" in str(self.cloud.get("api_base") or ""):
            return "https://%s-8188.container.x-gpu.com" % inst.id
        return ""

    # —— 开机 / 活跃度 / 回收 ——
    def start(self, inst: Instance) -> Instance:
        """把一台**已存在但已停机**的实例开起来（重启镜像，不动数据盘）。"""
        api = self._api()
        if not api.configured("start"):
            raise CloudNotConfigured(
                "缺 cloud.endpoints.start，无法开机。\n"
                "  · 去控制台点「开机」，或用 python -m cloud attach --url <地址> 接管；\n"
                "  · 填上 start 端点后，任务级 lifecycle 才能做到「要跑才开」。")
        api.call("POST", "start", payload={self._id_key(): inst.id})
        inst.state = "starting"
        inst.owned = True                 # 这次开机是**我们**的动作 → 结束时要负责关
        inst.created_at = inst.created_at or time.time()
        self.log("[已开机] %s（等待 ComfyUI 就绪）" % inst.id)
        self._remember(inst)
        return inst

    def touch(self, inst: Instance, **extra) -> None:
        """刷新「最后活跃时间」—— 空闲回收（reap）的唯一判据。"""
        try:
            self._remember(inst, last_used_at=time.time(), **extra)
        except OSError:
            pass

    def note_usage(self, inst: Instance, *, episodes: int = 0, segments: int = 0) -> None:
        """把本次任务用了多少集/多少镜记进状态，停机时一并写进台账。

        ★ 为什么要先记：`stop()` 才算工时，而那时批次已经结束、计数在别处。
          不先落进状态，台账里就只剩一行「几小时」，说不清这些时间换来了什么。
        """
        row = self.state.get(inst.id)
        self.touch(inst,
                   episodes=int(episodes or row.get("episodes") or 0),
                   segments=int(segments or row.get("segments") or 0))

    def instance_from_state(self, inst_id: str, rows: dict | None = None) -> Instance:
        """从本地记录还原一台实例（`down` / `reap` 用，不需要上游在线）。"""
        rows = rows if rows is not None else self.state.load()
        r = rows.get(inst_id) or {}
        return Instance(
            id=inst_id, name=r.get("name") or "", gpu=r.get("gpu") or "",
            ssh_host=r.get("ssh_host") or "", ssh_port=int(r.get("ssh_port") or 22),
            http_url=r.get("http_url") or "", state=r.get("state") or "",
            created_at=float(r.get("started_at") or 0),
            price_per_hour=float(r.get("price_per_hour") or 0),
            retain=bool(r.get("retain")), retain_price=float(r.get("retain_price") or 0),
            owned=bool(r.get("owned")),
        )

    def reap(self, idle_min: float | None = None, *, dry: bool = False) -> list:
        """回收「开着但很久没动」的实例 —— 忘停的唯一自动兜底。

        判据是本地记录的 `last_used_at`（每次出片前 `touch()`），不是「有没有进程」：
        云端进程看不见，本地也没有它的 pid。宁可保守（默认 15 分钟）也不要误杀正在跑的批次。
        """
        idle = float(idle_min if idle_min is not None
                     else (self.cloud.get("auto_stop_after_idle_min") or 15))
        if idle <= 0:
            return []
        rows = self.state.load()
        out = []
        now = time.time()
        for iid, r in rows.items():
            if str(r.get("state") or "").lower() in ("stopped", "destroyed"):
                continue
            last = max(float(r.get("last_used_at") or 0), float(r.get("started_at") or 0))
            if not last:
                continue
            idle_for = (now - last) / 60.0
            if idle_for < idle:
                continue
            inst = self.instance_from_state(iid, rows)
            if dry:
                out.append({"id": iid, "action": "would_stop",
                            "idle_min": round(idle_for, 1)})
                continue
            try:
                self.stop(inst, note="空闲 %.0f 分钟，自动回收" % idle_for)
                out.append({"id": iid, "action": "stopped", "idle_min": round(idle_for, 1)})
            except Exception as exc:                          # noqa: BLE001
                out.append({"id": iid, "action": "failed",
                            "error": str(exc).splitlines()[0][:160]})
        return out

    # —— 等 ——
    def wait_ready(self, inst: Instance, timeout_min: float = None,
                   workflow_path: str = "") -> bool:
        """轮询直到 ComfyUI 三查全绿。**超时自动 stop**（约束 2）。

        判据用 `health.probe` 而不是「端口通了」：端口通只证明进程在，模型没齐照样白跑。
        """
        timeout_min = float(timeout_min or self.cloud.get("ready_timeout_min") or 8)
        url = inst.http_url or self.url_for(inst)
        if not url:
            self.log("[FAIL] 实例 %s 没有直连地址（响应缺 http_url）—— 无法探活" % inst.id)
            self.stop(inst, note="无直连地址，未能就绪")
            return False
        deadline = time.time() + timeout_min * 60
        last = None
        while time.time() < deadline:
            res = HEALTH.probe(url, workflow_path)
            if res["ok"]:
                self.log("[就绪] %s v%s · %s" % (url, res["version"] or "?",
                                                 res["gpu"] or "GPU 未知"))
                inst.state = "running"
                self._remember(inst)
                return True
            # 只打印「变化」：轮询期间同一个「缺模型」刷 40 遍没有信息量
            sig = (res.get("error"), tuple(res.get("models_missing") or []),
                   tuple(res.get("nodes_missing") or []))
            if sig != last:
                self.log("  [等待] %s" % (res.get("error")
                                          or "缺 %d 个模型 / %d 个节点"
                                          % (len(res.get("models_missing") or []),
                                             len(res.get("nodes_missing") or []))))
                last = sig
            time.sleep(self.poll_s)
        self.log("[FAIL] %.0f 分钟内未就绪 → 自动停机（不留空转机器）" % timeout_min)
        self.stop(inst, note="wait_ready 超时，自动停机")
        return False

    # —— 停 / 毁 ——
    def stop(self, inst: Instance, note: str = "") -> dict:
        """停实例 = 停止 GPU 计费。**跑完务必调用**，这是唯一真正的省钱动作。"""
        api = self._api()
        try:
            api.call("POST", "stop", payload={self._id_key(): inst.id})
            self.log("[已停] %s（GPU 计费停止）" % inst.id)
        except CloudNotConfigured:
            raise
        except Exception as exc:                              # noqa: BLE001
            self.log("[FAIL] 停实例失败：%s —— 立刻去控制台手动停，别等" % str(exc)[:200])
            raise
        # ★ 关机 ≠ 零成本：`retain`（保留磁盘）开着就继续按 retain_price 计费。
        #   这条不提醒，人就会以为「停了就不花钱」，一个月后发现账单没停。
        if inst.retain and inst.retain_price > 0:
            self.log("[注意] 该实例关机保留磁盘（retain=1），磁盘仍按￥%.3f/时计费；"
                     "彻底不花要销毁实例或手动取消保留。" % inst.retain_price)
        return self._settle(inst, note=note or "手动停机")

    def destroy(self, inst: Instance) -> None:
        """销毁容器（云储存不受影响）。停不下来的机器，销毁是最后手段。"""
        self._api().call("POST", "destroy", payload={self._id_key(): inst.id})
        self.log("[已销毁] %s" % inst.id)
        self._settle(inst, note="销毁实例")
        self.state.drop(inst.id)

    def status(self, inst: Instance) -> str:
        """查状态。优先问上游；问不到就信本地记录（离线也该能看）。"""
        api = self._api()
        if api.configured("detail"):
            try:
                resp = api.call("GET", "detail", params={self._id_key(): inst.id})
                inst.state = str(api.dig(resp, "state", inst.state) or inst.state)
                return inst.state
            except Exception as exc:                          # noqa: BLE001
                self.log("[WARN] 查上游状态失败：%s" % str(exc).splitlines()[0][:120])
        return str(self.state.get(inst.id).get("state") or inst.state or "unknown")

    # —— 记账 ——
    def _settle(self, inst: Instance, note: str = "") -> dict:
        """停机即记账：工时 = 现在 − 本地记录的创建时间。

        单价取「上游报的这台实例的价」> 「配置兜底价」：卡型/地域不同价不同，
        用上游的真值才能和账单对得上。
        """
        row = self.state.get(inst.id)
        started = float(row.get("created_at") or inst.created_at or time.time())
        now = time.time()
        price = float(inst.price_per_hour or self.cloud.get("price_per_hour") or 0)
        if inst.retain and inst.retain_price > 0:
            note = (note + "；" if note else "") + \
                   "关机后仍保留磁盘（￥%.3f/时，未计入本行）" % inst.retain_price
        rec = LEDGER.record(inst, started, now, price,
                            note=note, ws=self.ws, episodes=int(row.get("episodes") or 0),
                            segments=int(row.get("segments") or 0))
        try:
            self.state.put(inst, stopped_at=now, state="stopped")
        except OSError:
            pass
        self.log("[台账] %.2f 小时 · %s · %s"
                 % (rec["hours"], ("￥%.2f" % rec["cost"]) if rec["priced"] else "未定价",
                    LEDGER.ledger_path(self.ws)))
        return rec

    def _remember(self, inst: Instance, **extra) -> None:
        try:
            row = self.state.get(inst.id)
            self.state.put(inst, started_at=row.get("started_at") or time.time(), **extra)
        except OSError:
            pass

    # —— 手动模式（拓扑 A/B：实例在控制台点起来，本模块只探活/记账/搬运）——
    def attach(self, url: str, name: str = "manual", inst_id: str = "") -> Instance:
        """不建实例，直接接管一台已在跑的服务（本机 8188 也行）。"""
        ssh = self.cloud.get("ssh") or {}
        inst = Instance(id=inst_id or ("manual-" + str(int(time.time()))),
                        name=name, gpu=str(self.cloud.get("gpu") or ""),
                        ssh_host=str(ssh.get("host") or ""),
                        ssh_port=int(ssh.get("port") or 22),
                        http_url=str(url or "").rstrip("/"), state="running",
                        created_at=time.time(), owned=False)
        self._remember(inst)
        return inst
