"""_netguard.py —— 网络出口守卫：默认只打本机，出网必须被显式开启。

为什么要有这一层，而不是只靠「默认配置指向本地」：
  「默认选本地」拦不住误操作。一个旧项目的 model-plan.json、一次复制粘贴、
  一段从别处抄来的调用 —— 都会让某个镜头在没人注意的时候上传到外部平台。
  配置是软的，出口是硬的。

三个出口，默认全关：
  · 本机与内网          → 一直放行（ComfyUI 就住在这里）
  · 平台通道（runninghub） → 要 SOLODRAMA_ALLOW_RH=1
  · 其他远端（大模型网关） → 要 SOLODRAMA_ALLOW_REMOTE=1

★ 「默认关」不等于「删掉」。平台通道是一等公民：显式选了 `--engine workflow`
  或直接运行 RH 脚本，走的通；但任何**没有声明意图**的代码路径都出不去。
  开闸由调用方负责，`allow_platform()` 是唯一的正规入口。

为什么平台域名不并进 ALLOW_REMOTE：
  那一个开关放行的是「除黑名单外的一切远端」。为了跑一次 RH 就把整个互联网
  放开，等于用一个粗开关换掉一个精确边界。

失败时抛 RemoteForbidden（继承 OSError）：现有 `except OSError` 的代码能接住，
只是提示会变成「网络出口守卫拒绝」，而不是难懂的 socket 错。
"""

from __future__ import annotations

import contextlib
import os
import socket
import sys
import urllib.parse

# 永久黑名单：这些是「看起来像平台出口的变体」，任何情况下都不放行。
# 平台正式域名单独放在 _PLATFORM_SUBSTRINGS 里 —— 那个可以显式开闸。
FORBID_SUBSTRINGS = (
    "rh-api",
    "rhapi",
)

# 平台通道域名。默认拦，`SOLODRAMA_ALLOW_RH=1` 才放行（见 allow_platform）。
_PLATFORM_SUBSTRINGS = (
    "runninghub",
)

# ---- 白名单：本机与内网 -----------------------------------------------------
# 顺序重要：先判 loopback/内网，再谈是否需要 allow_remote。
_LOCAL_EXACT = {"localhost", "localhost.localdomain", "ip6-localhost", "::1", ""}
_LOCAL_SUFFIXES = (".localhost", ".local", ".lan", ".internal", ".home.arpa")


class RemoteForbidden(OSError):
    """出站请求被守卫拒绝（非本机地址 / 命中平台黑名单）。"""


def _truthy(name: str, legacy: str = "") -> bool:
    v = (os.environ.get(name) or (os.environ.get(legacy) if legacy else "") or "").strip()
    return v not in ("", "0", "false", "False", "no")


def _allow_remote() -> bool:
    return _truthy("SOLODRAMA_ALLOW_REMOTE", "DRAMA_ALLOW_REMOTE")


def _allow_platform() -> bool:
    """平台通道（RunningHub）是否已开闸。

    ★ 故意不合并进 ALLOW_REMOTE：后者放行的是「除黑名单外的一切远端」。
    """
    return _truthy("SOLODRAMA_ALLOW_RH", "DRAMA_ALLOW_RH")


def allow_platform() -> None:
    """开闸：把平台出口对本进程（及子进程）打开。

    只有**确实要调用平台通道**的代码才调它 —— 选 `--engine workflow`、
    跑 rh_doctor、跑 gen_assets_rh_workflow。调用的位置本身就是意图声明，
    所以不需要额外参数。

    开闸后一直有效：长任务要 fork 子进程（run.py / 批量出片），
    子进程继承环境变量才连得上。用完不关是刻意的 —— 关掉反而会让
    「父进程放行、子进程被拦」变成一条极难排查的故障。
    """
    os.environ["SOLODRAMA_ALLOW_RH"] = "1"


@contextlib.contextmanager
def platform_allowed():
    """临时开闸（只在 with 块内有效）。

    给**一次性的探测**用：连接中心的「测试 RunningHub」按一下连一次，
    连完立刻恢复关闭状态。这里不能用 allow_platform()，因为 Web 服务是
    常驻进程 —— 一次点击把闸永久打开，之后任何代码路径都能出网。
    """
    prev = os.environ.get("SOLODRAMA_ALLOW_RH")
    os.environ["SOLODRAMA_ALLOW_RH"] = "1"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("SOLODRAMA_ALLOW_RH", None)
        else:
            os.environ["SOLODRAMA_ALLOW_RH"] = prev


def _is_private_ip(host: str) -> bool:
    """RFC1918 + CGNAT + 链路本地。不引入 ipaddress 之外的依赖。"""
    try:
        import ipaddress

        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified)


def check_host(host: str, *, port: int | None = None, where: str = "") -> None:
    """判定这个目标主机能不能连。不能就连抛。"""
    h = (host or "").strip().lower()
    # `http.client` 在代理场景下给的是 `127.0.0.1:60629` 这种「主机:端口」串，
    # 直接丢给 ipaddress 会解析失败、被当成「非内网」而误拒本机 ComfyUI。
    if h.startswith("["):                       # [::1]:8188
        h = h[1:h.find("]")] if "]" in h else h[1:]
    elif h.count(":") == 1:                     # host:port（IPv4 / 域名）
        _h, _p = h.rsplit(":", 1)
        if _p.isdigit():
            h, port = _h, port or int(_p)
    if not h:
        return
    for pat in FORBID_SUBSTRINGS:
        if pat in h:
            raise RemoteForbidden(
                "网络出口守卫拒绝访问 %r（%s）：该主机名是平台出口的变体，任何情况下都不放行。"
                "平台通道请用正式域名（www.runninghub.ai / .cn）。" % (h, where or "出站请求"))

    # ★ 平台判定放在本地白名单**之前**。
    #   `runninghub-proxy.internal` 这种名字会被 .internal 当成内网直接放过 ——
    #   而它恰恰是「起了个内网名字、实际朝外的中转域名」，最该拦的一类。
    #   顺序反过来就等于给了一条绕过审核的旁路。
    for pat in _PLATFORM_SUBSTRINGS:
        if pat in h:
            if _allow_platform():
                return
            raise RemoteForbidden(
                "网络出口守卫拒绝访问 %r（%s）：平台通道默认关闭。\n"
                "  要用 RunningHub：把出片改成 `drama video run --engine workflow`"
                "（或跑 RH 专用脚本，它们会自己开闸）；\n"
                "  临时手动放行：set SOLODRAMA_ALLOW_RH=1。\n"
                "  默认通道是本地 ComfyUI，不需要这一步。" % (h, where or "出站请求"))

    if h in _LOCAL_EXACT or h.endswith(_LOCAL_SUFFIXES):
        return
    if _is_private_ip(h):
        return

    if _allow_remote():
        return
    raise RemoteForbidden(
        "网络出口守卫拒绝访问 %r（%s）：只允许本机与内网地址。"
        "确需访问远端（例如大模型网关）请设 SOLODRAMA_ALLOW_REMOTE=1。" % (h, where or "出站请求"))


def check_url(url: str, *, where: str = "") -> None:
    u = urllib.parse.urlsplit(str(url or ""))
    if u.scheme and u.scheme not in ("http", "https", "ws", "wss"):
        return                     # file:// / data: 之类不走网络
    check_host(u.hostname or "", port=u.port, where=where or url)


# ---- 打补丁 -----------------------------------------------------------------
_installed = False


def install(*, force: bool = False) -> bool:
    """给出口打补丁（幂等）。返回是否本次新装。"""
    global _installed
    if _installed and not force:
        return False

    _orig_gai = socket.getaddrinfo
    _orig_cc = socket.create_connection

    def guarded_getaddrinfo(host, port, *a, **kw):
        # 这里拿得到「域名」，是黑名单的最可靠判定点：即使有人绕过 urllib
        # 自己 new 一个 socket，DNS 解析这一步也躲不开。
        if isinstance(host, bytes):
            try:
                host = host.decode("utf-8", "ignore")
            except Exception:      # noqa: BLE001
                host = ""
        check_host(str(host or ""), port=port, where="DNS 解析")
        return _orig_gai(host, port, *a, **kw)

    def guarded_create_connection(address, *a, **kw):
        try:
            h, p = address[0], address[1]
        except (TypeError, IndexError):
            h, p = address, None
        if isinstance(h, bytes):
            h = h.decode("utf-8", "ignore")
        check_host(str(h or ""), port=p, where="建立连接")
        return _orig_cc(address, *a, **kw)

    socket.getaddrinfo = guarded_getaddrinfo            # type: ignore[assignment]
    socket.create_connection = guarded_create_connection  # type: ignore[assignment]

    _patch_urllib()    # ★ 必须：有系统代理时 socket 层只看到 127.0.0.1（见下）
    _patch_httpx()
    _patch_httpclient()

    _installed = True
    return True


def _patch_urllib() -> None:
    """按 **URL** 拦 urllib。

    ★ 为什么 socket 层的补丁不够（2026-11-04 实测踩到）：
      很多机器设了 `HTTPS_PROXY=http://127.0.0.1:60629`（Clash / 公司代理 / 沙箱都这样）。
      此时 urlopen 真正连的是 127.0.0.1，socket 层看到的 host 是 `127.0.0.1` —— 白名单放行 ——
      然后代理替你连到目标站点。**只看 socket 层，守卫形同虚设。**
      所以在 urlopen 入口按原始 URL 再判一次，这一层不看代理。
    """
    import urllib.request as _ur

    if getattr(_ur, "_solodrama_guarded", False):
        return
    _orig_urlopen = _ur.urlopen

    def guarded_urlopen(url, *a, **kw):  # noqa: ANN001
        if isinstance(url, str):
            check_url(url, where="urllib.urlopen")
        else:
            # Request 对象：get_full_url() 才是真正会去的主机
            try:
                check_url(url.get_full_url(), where="urllib.urlopen(Request)")
            except AttributeError:
                pass
        return _orig_urlopen(url, *a, **kw)

    _ur.urlopen = guarded_urlopen                     # type: ignore[assignment]
    _ur._solodrama_guarded = True                     # type: ignore[attr-defined]


def _patch_httpclient() -> None:
    """按 **host** 拦 http.client（含代理隧道 CONNECT 的目标）。

    urllib 之上还有一层：真正确立连接的是 HTTPConnection。它的 host 在代理场景下
    是代理地址，但 `set_tunnel(host)` 会带着**真实目标**，那一处也必须判。
    """
    try:
        import http.client as _hc
    except Exception:         # noqa: BLE001
        return
    if getattr(_hc, "_solodrama_guarded", False):
        return
    _orig_init = _hc.HTTPConnection.__init__
    _orig_tunnel = _hc.HTTPConnection.set_tunnel

    def guarded_init(self, host, *a, **kw):  # noqa: ANN001
        check_host(str(host or ""), where="HTTPConnection")
        return _orig_init(self, host, *a, **kw)

    def guarded_tunnel(self, host, *a, **kw):  # noqa: ANN001
        check_host(str(host or ""), where="HTTP 代理隧道")
        return _orig_tunnel(self, host, *a, **kw)

    _hc.HTTPConnection.__init__ = guarded_init       # type: ignore[method-assign]
    _hc.HTTPConnection.set_tunnel = guarded_tunnel   # type: ignore[method-assign]
    _hc._solodrama_guarded = True                    # type: ignore[attr-defined]


def _patch_httpx() -> None:
    try:
        import httpx          # noqa: F401
    except Exception:         # noqa: BLE001  —— 没装就不管，运行期其它层照样拦
        return
    if getattr(httpx, "_solodrama_guarded", False):
        return
    _orig_init = httpx.Client.__init__
    _orig_send = httpx.Client.send

    def guarded_client_init(self, *a, **kw):  # noqa: ANN001
        base = kw.get("base_url")
        if base:
            check_url(str(base), where="httpx.Client base_url")
        return _orig_init(self, *a, **kw)

    def guarded_send(self, request, *a, **kw):  # noqa: ANN001
        # 代理场景下 base_url 可能是代理，真正目标在 request.url 上
        try:
            check_url(str(request.url), where="httpx.send")
        except AttributeError:
            pass
        return _orig_send(self, request, *a, **kw)

    httpx.Client.__init__ = guarded_client_init     # type: ignore[method-assign]
    httpx.Client.send = guarded_send                # type: ignore[method-assign]
    httpx._solodrama_guarded = True                 # type: ignore[attr-defined]



def selfcheck() -> list:
    """返回 (名称, 是否通过, 说明) 三元的列表，供 preflight / 测试复用。"""
    rows = []
    for name, fn, want_block in (
        ("本机 127.0.0.1", lambda: check_host("127.0.0.1"), False),
        ("本机 localhost", lambda: check_host("localhost"), False),
        ("内网 192.168.1.9", lambda: check_host("192.168.1.9"), False),
        # 平台通道：默认拦，开了 SOLODRAMA_ALLOW_RH 才放 —— 期望值随开关变，
        # 否则自检会在「已经显式选了 RH」的机器上报假失败。
        ("平台 .ai", lambda: check_host("www.runninghub.ai"), not _allow_platform()),
        ("平台 .cn 子域", lambda: check_host("api.runninghub.cn"), not _allow_platform()),
        # 变体永久拦：即使开了平台闸也不放行。
        ("平台变体（永久）", lambda: check_host("rh-api.runninghub.ai"), True),
        ("外部站点", lambda: check_host("example.com"), not _allow_remote()),
    ):
        try:
            fn()
            blocked = False
        except RemoteForbidden:
            blocked = True
        ok = blocked == want_block
        rows.append((name, ok, "已拦截" if blocked else "放行"))
    return rows


if __name__ == "__main__":
    ok_all = True
    print("网络出口守卫 · 自检（%s）" % ("允许远端" if _allow_remote() else "仅本机+内网"))
    for name, ok, detail in selfcheck():
        print("  %s %-22s %s" % ("[OK] " if ok else "[FAIL]", name, detail))
        ok_all = ok_all and ok
    sys.exit(0 if ok_all else 1)
