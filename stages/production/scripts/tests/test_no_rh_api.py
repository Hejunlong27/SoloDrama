"""test_no_rh_api.py —— 守住「禁止调用任何 RunningHub API」这条硬约束。

用户强制命令（2026-11-04）：**禁止调用任何 rh 的 api**。

这个文件存在的理由不是「多一份测试」，而是：删掉运行库之后，让这条约束仍然
**每次跑测试都被检查一遍**。否则它只是一段历史，不是约束。

三层：
  [A] 静态：仓库里不能有任何把 runninghub 域名拼进 URL/请求的地方
  [B] 动态：守卫装上之后，连 RH 必须抛 RemoteForbidden（含各种域名变体）
  [C] 旁路：即使有系统代理（socket 层只看到 127.0.0.1），URL 层也要拦住

[C] 是实测踩出来的：本机环境有 `HTTPS_PROXY=http://127.0.0.1:60629`，
只打 socket 补丁时 `urlopen("https://www.runninghub.ai")` 会**成功** ——
请求发给本地代理，代理替你连出去。只测 [B] 会得到一个假的安全感。
"""

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve()
# parents: [0]=tests [1]=scripts [2]=production [3]=stages [4]=仓库根
STAGES = HERE.parents[3]
ROOT = HERE.parents[4]

sys.path.insert(0, str(STAGES))
import _netguard as NG                     # noqa: E402


# ---------------------------------------------------------------------------
# [A] 静态扫描
# ---------------------------------------------------------------------------
# 允许出现 "runninghub" 字样的地方（都是**说明性**的，不是可执行请求）：
#   · _netguard.py 本身：黑名单定义
#   · 本测试：断言用
#   · docs 与注释：历史说明
ALLOW_FILES = {
    "stages/_netguard.py",
}

# 这些写法才叫「真的能发出请求」：域名出现在字符串里且紧邻 URL 结构
_URL_HINT = re.compile(
    r"""(?:https?://[^\s"'<>]*runninghub[^\s"'<>]*)|"""
    r"""(?:runninghub\.[a-z]{2,}[^\s"'<>]*)""",
    re.IGNORECASE,
)


def _py_files():
    for base in (ROOT / "stages", ROOT / "web", ROOT / "tools"):
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            yield p


def test_static_no_rh_endpoint_in_code():
    """代码里不许出现 runninghub 的 URL 字面量（注释除外）。"""
    hits = []
    for p in _py_files():
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if rel in ALLOW_FILES or "/tests/" in rel or p.name.startswith("test_"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):        # 纯注释行跳过
                continue
            # 去掉行内注释再判
            code = line.split("  #", 1)[0]
            if _URL_HINT.search(code):
                hits.append("%s:%d  %s" % (rel, lineno, stripped[:100]))
    assert not hits, "发现可执行的 RunningHub 端点：\n  " + "\n  ".join(hits)


def test_no_runninghub_client_module():
    """出片/出图的 RH 客户端模块整体不存在。"""
    for rel in ("stages/video/workflow", "stages/production/scripts/rh_doctor.py",
                "stages/production/scripts/gen_assets_rh_workflow.py",
                "stages/production/scripts/_site.py",
                "configs/capabilities/rh.h3.multiref.v1.json",
                "configs/capabilities/rh.upscale.v1.json"):
        assert not (ROOT / rel).exists(), "应已删除但仍存在：%s" % rel


def test_no_rh_env_injected():
    """子进程环境里不再注入任何 RUNNINGHUB_* 变量。"""
    rp = ROOT / "web" / "core" / "runner.py"
    text = rp.read_text(encoding="utf-8")
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        # 只查「真的往 env 里写」的行
        if "env[[" in s or "env.setdefault" in s or "environ[[" in s:
            assert "RUNNINGHUB" not in s, "仍在注入平台变量：%s" % s


# ---------------------------------------------------------------------------
# [B] 动态：黑名单必须真的拦得住
# ---------------------------------------------------------------------------
def test_guard_installed():
    NG.install()
    assert NG._installed, "守卫没有装上"


def test_rh_domains_blocked():
    """各种写法都要拦，一个不漏。"""
    cases = [
        "www.runninghub.ai",
        "runninghub.ai",
        "api.runninghub.cn",
        "RUNNINGHUB.AI",           # 大小写
        "www.runninghub.ai:443",   # 带端口
        "rh-api.runninghub.ai",
        "runninghub-proxy.internal",
    ]
    for h in cases:
        try:
            NG.check_host(h)
        except NG.RemoteForbidden:
            continue
        raise AssertionError("未拦住：%s" % h)


def test_local_still_allowed():
    """拦住 RH 不能把本机也拦了 —— 否则出图出片全废。"""
    for h in ("127.0.0.1", "localhost", "::1", "192.168.1.9", "10.0.0.5",
              "127.0.0.1:8188", "[::1]:8188"):
        NG.check_host(h)                       # 不抛即通过


def test_allow_remote_does_not_unlock_rh(monkeypatch):
    """SOLODRAMA_ALLOW_REMOTE=1 只放宽普通远端，RH 仍然不可达。"""
    monkeypatch.setenv("SOLODRAMA_ALLOW_REMOTE", "1")
    assert NG._allow_remote()
    NG.check_host("api.openai.com")            # 普通远端：放过
    try:
        NG.check_host("www.runninghub.ai")
    except NG.RemoteForbidden:
        return
    raise AssertionError("开了 allow_remote 之后 RH 竟然能连 —— 这是最危险的回归")


# ---------------------------------------------------------------------------
# [C] 旁路：有系统代理时 URL 层必须拦住（socket 层看不见真实目标）
# ---------------------------------------------------------------------------
def test_url_layer_blocks_behind_proxy(monkeypatch):
    """模拟「只看得见代理地址」的场景。

    做法：把 COMFY 之外的地址伪装成代理 —— 直接质疑 urllib 的入口判定。
    这里不复刻代理实现（太重），而是直接验证 URL 层的判据函数：
    `check_url` 必须只看 URL 本身，不看最终连到哪。
    """
    NG.install()
    import urllib.request as ur
    for url in ("https://www.runninghub.ai/task/openapi/create",
                "https://api.runninghub.cn/v1/run"):
        try:
            ur.urlopen(url, timeout=1)         # 不该走到网络
        except NG.RemoteForbidden:
            continue
        except Exception as e:                 # noqa: BLE001
            raise AssertionError("%s 未被守卫拦下，实际抛 %s" % (url, type(e).__name__))
        raise AssertionError("%s 竟然请求出去了" % url)


def test_check_url_ignores_scheme_tricks():
    """file:// / data: 不是网络请求，不拦；http/https 必须判。"""
    NG.check_url("file:///D:/tmp/a.png")
    NG.check_url("data:image/png;base64,AAAA")
    for u in ("http://www.runninghub.ai/x", "https://www.runninghub.ai/x",
              "ws://www.runninghub.ai/x"):
        try:
            NG.check_url(u)
        except NG.RemoteForbidden:
            continue
        raise AssertionError("未拦住：%s" % u)


# ---------------------------------------------------------------------------
# 自跑
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import os

    fails = []
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            if fn.__code__.co_argcount:
                class _MP:
                    def setenv(self, k, v): os.environ[k] = v
                fn(_MP())
            else:
                fn()
            print("[OK  ] %s" % name)
        except AssertionError as e:
            fails.append((name, str(e)))
            print("[FAIL] %s\n       %s" % (name, e))
        except Exception as e:                 # noqa: BLE001
            fails.append((name, repr(e)))
            print("[ERR ] %s\n       %r" % (name, e))
    print("\n%d 失败" % len(fails))
    sys.exit(1 if fails else 0)
