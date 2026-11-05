"""cloud/transport.py —— 素材/产物在「本机 ↔ 实例」之间搬运

为什么不用 ComfyUI 自己的接口搬
------------------------------
`/upload/image` 只接收**单张图**并塞进 input 目录，`/view` 只能取 output 目录里的文件。
而云端批量生产的真实需求是「整包进、整包出」：制作包（剧本/提示词/参考图）、
成片目录、日志与台账。这些不是 ComfyUI 的职责，硬塞进去只会把产物命名搞乱。

实现选择：**OpenSSH 客户端**（`scp`），而不是自己写 SFTP
--------------------------------------------------------
* Windows 10+ / macOS / Linux 都自带 `ssh` / `scp`，零依赖；
* 认证交给系统（密钥 / ssh-agent / 已配置的 known_hosts），本模块**不碰密码**；
* `XGY_SSH_PASSWORD` 只作为「提示用户自己配好免密」的存在，绝不拼进命令行 ——
  拼进 argv 等于把密码写进进程列表和 shell 历史。

★ 密码不落地的代价是「必须配密钥」。这是刻意的：云端实例通常几分钟就销毁，
  密码认证在无人值守场景下一定会卡在交互提示上（`Are you sure you want to continue connecting?`），
  比配一次密钥更麻烦。
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import time
import sys

from .provisioner import Instance


class TransportError(RuntimeError):
    """搬运失败（含「本机没有 scp」这种环境问题）。"""


def _bin(name: str) -> str:
    p = shutil.which(name)
    if not p:
        raise TransportError(
            "本机找不到 %s。Windows 请在「设置 → 应用 → 可选功能」里装 OpenSSH 客户端；\n"
            "  macOS / Linux 一般自带。也可以用 --no-copy 手动搬文件。" % name)
    return p


def _target(inst: Instance, user: str = "", port: int = 0) -> str:
    host = (inst.ssh_host or "").strip()
    if not host:
        raise TransportError(
            "实例 %s 没有 SSH 地址（响应缺 ssh_host，或手动模式下 cloud.ssh.host 没填）。\n"
            "  纯 HTTP 拓扑（只调 ComfyUI 接口）不需要搬运，可以跳过 push/pull。" % inst.id)
    return "%s@%s" % (user or "root", host)


# ★ 2026-11-05（云端实测反馈）：仙宫云的 sshd 在**磁盘 IO 饱和**时握手会被重置
#   （`kex_exchange_identification: Connection reset`），而此时端口是通的、进程也在 ——
#   看起来像网络问题，实际是系统资源问题（网盘下载 66 GB、cat 合并 9 GB、GPU 满载都会触发）。
#   另外连续几十次连接会触发**限流**，恢复窗口约 60 秒。
#   所以：只对「连接类」错误重试，且退避要给足（3 → 15 → 60）。
_SCP_BACKOFF = (3, 15, 60)
_SCP_CONN_HINTS = ("connection reset", "connection refused", "connection timed out",
                   "kex_exchange_identification", "broken pipe", "connection closed",
                   "network is unreachable", "no route to host")


def _scp_once(cmd: list, src: str, dst: str, timeout: float) -> dict:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        raise TransportError("scp 超时（%.0fs）：%s → %s" % (timeout, src, dst)) from exc
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    if p.returncode != 0:
        raise TransportError("scp 失败（退出码 %d）：%s\n  %s"
                             % (p.returncode, " ".join(cmd[0:1] + ["…"]), out[-500:]))
    return {"ok": True, "src": src, "dst": dst, "bytes": _size_of(src)}


def _scp(src: str, dst: str, *, port: int, key: str = "", recursive: bool = True,
         timeout: float = 1800) -> dict:
    cmd = [_bin("scp"), "-o", "StrictHostKeyChecking=accept-new",
           "-o", "BatchMode=yes"]        # BatchMode：不许弹交互，弹了就是失败
    if port and int(port) != 22:
        cmd += ["-P", str(int(port))]     # ★ scp 用大写 -P（ssh 是小写 -p）
    if key:
        cmd += ["-i", str(pathlib.Path(key).expanduser())]
    if recursive:
        cmd += ["-r"]
    cmd += [src, dst]

    last: Exception | None = None
    for attempt, wait in enumerate((0,) + _SCP_BACKOFF):
        if wait:
            print("  [SSH] 连接被重置或限流，%.0f 秒后重试（第 %d 次）…" % (wait, attempt))
            time.sleep(wait)
        try:
            return _scp_once(cmd, src, dst, timeout)
        except TransportError as exc:
            msg = str(exc).lower()
            if not any(h in msg for h in _SCP_CONN_HINTS):
                raise                                # 文件不存在之类：重试没有意义
            last = exc
    raise TransportError("scp 连续 %d 次连接失败（已按 3/15/60 秒退避）：%s\n"
                         "  · 实例高 IO 时 sshd 会假死，等负载降下来再试\n"
                         "  · 高频连接会被限流，间隔 60 秒以上才恢复\n"
                         "  · 只跑 HTTP 通道可以不搬文件（跳过 push/pull）"
                         % (len(_SCP_BACKOFF) + 1, last)) from last


def _size_of(path: str) -> int:
    """本地路径才算大小；远端路径返回 0（不去为「统计大小」再连一次）。"""
    p = pathlib.Path(path)
    try:
        if p.is_file():
            return p.stat().st_size
        if p.is_dir():
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        pass
    return 0


class Transport:
    """一台实例的搬运器。`cfg.cloud.ssh` 提供 user/port/key_path。"""

    def __init__(self, inst: Instance, cfg: dict, *, remote_root: str = "", log=print):
        self.inst = inst
        self.cloud = cfg["cloud"]
        ssh = self.cloud.get("ssh") or {}
        self.user = str(ssh.get("user") or "root")
        self.port = int(ssh.get("port") or inst.ssh_port or 22)
        self.key = str(ssh.get("key_path") or "")
        self.remote_root = (remote_root or str(self.cloud.get("workspace_root")
                                              or "/root/cloud")).rstrip("/")
        self.log = log

    def push(self, local: str, remote: str = "") -> dict:
        """本机 → 实例。`remote` 留空 = 放到实例工作区根下同名。"""
        src = str(pathlib.Path(local).expanduser())
        if not os.path.exists(src):
            raise TransportError("要上传的路径不存在：%s" % src)
        dest = remote or (self.remote_root + "/" + pathlib.Path(src).name)
        self.log("[push] %s → %s:%s" % (os.path.basename(src),
                                        self.inst.ssh_host or "?", dest))
        return _scp(src, "%s:%s" % (_target(self.inst, self.user, self.port), dest),
                    port=self.port, key=self.key)

    def pull(self, remote: str, local: str) -> dict:
        """实例 → 本机（成片、日志、台账）。"""
        dst = str(pathlib.Path(local).expanduser())
        pathlib.Path(dst).parent.mkdir(parents=True, exist_ok=True)
        self.log("[pull] %s:%s → %s" % (self.inst.ssh_host or "?", remote, dst))
        return _scp("%s:%s" % (_target(self.inst, self.user, self.port), remote), dst,
                    port=self.port, key=self.key)

    def available(self) -> tuple[bool, str]:
        """能不能搬（CLI 自检用）。"""
        try:
            _bin("scp")
            _target(self.inst, self.user, self.port)
        except TransportError as exc:
            return False, str(exc).splitlines()[0]
        return True, ""


def has_ssh() -> bool:
    return bool(shutil.which("scp") and shutil.which("ssh"))


def ssh_hint() -> str:
    """给用户的「配免密」三步（不涉及密码，只涉及密钥）。"""
    return ("  · 生成密钥（一次）：ssh-keygen -t ed25519\n"
            "  · 拷到实例：scp -P <端口> ~/.ssh/id_ed25519.pub root@<host>:~/.ssh/authorized_keys\n"
            "  · 配进 settings.json：cloud.ssh.key_path\n"
            "  ★ 不要把 SSH 密码写进配置：无人值守时它一定卡在交互提示上。")


if __name__ == "__main__":                      # pragma: no cover
    print("scp: %s" % (shutil.which("scp") or "缺失"))
    print("ssh: %s" % (shutil.which("ssh") or "缺失"))
    sys.exit(0 if has_ssh() else 1)
