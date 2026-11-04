"""test_netguard_platform.py —— 守住「平台通道默认关闭、本地通道是默认」。

原来的 test_no_rh_api.py 断言的是「代码里不许有任何 RH 调用」。那条约束
在 2026-11-04 被推翻：平台通道作为**可选**能力保留下来，默认仍走本机。
所以这里守的东西跟着变 —— 不再是「不存在」，而是三条不变量：

  1. 默认状态：平台域名一律不可达（含各种变体）。不需要任何人记得设开关。
  2. 显式状态：开闸之后能连，且**只有**平台正式域名能连（变体永远不放）。
  3. 结构状态：本地通道的代码路径根本不经过开闸那一步 —— 于是「默认不出网」
     不依赖某个默认值恰好没被改。

第 3 条是重点。前两条测的是守卫，第 3 条测的是「调用点长在哪」：
只要 `cmd_video_run` 的本地分支在开闸之前 return，本地通道就不可能出网，
哪怕有人把 model-plan.json 改成 runninghub。

★ 曾经踩过：[C] 组只测 socket 层会得到假的安全感。本机有
  HTTPS_PROXY=http://127.0.0.1:60629 时 socket 只看到 127.0.0.1，
  代理替你连出去。所以 URL 层必须单独测。
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

# 平台正式域名：默认拦、开闸放
PLATFORM_HOSTS = [
    "www.runninghub.ai",
    "runninghub.ai",
    "api.runninghub.cn",
    "RUNNINGHUB.AI",           # 大小写
    "www.runninghub.ai:443",   # 带端口
    "runninghub-proxy.internal",
    # 变体：永久拦，开闸也不放
    "rh-api.runninghub.ai",
]


def _clear_switch():
    """把开关拨回默认关，避免受调用方环境影响。"""
    import os
    for k in ("SOLODRAMA_ALLOW_RH", "DRAMA_ALLOW_RH"):
        os.environ.pop(k, None)


# ---------------------------------------------------------------------------
# [A] 默认状态：不设任何开关时，一条都出不去
# ---------------------------------------------------------------------------
def test_guard_installed():
    NG.install()
    assert NG._installed, "守卫没有装上"


def test_default_blocks_every_platform_host():
    _clear_switch()
    assert not NG._allow_platform(), "默认状态不该是开闸的"
    for h in PLATFORM_HOSTS:
        try:
            NG.check_host(h)
        except NG.RemoteForbidden:
            continue
        raise AssertionError("默认状态未拦住：%s" % h)


def test_local_still_allowed():
    """拦住平台不能把本机也拦了 —— 否则出图出片全废。"""
    for h in ("127.0.0.1", "localhost", "::1", "192.168.1.9", "10.0.0.5",
              "127.0.0.1:8188", "[::1]:8188"):
        NG.check_host(h)                       # 不抛即通过


# ---------------------------------------------------------------------------
# [B] 显式开闸：正式域名放行，变体永不放行
# ---------------------------------------------------------------------------
def test_allow_platform_unlocks_official_hosts():
    _clear_switch()
    NG.allow_platform()
    try:
        assert NG._allow_platform()
        for h in ("www.runninghub.ai", "api.runninghub.cn", "www.runninghub.ai:443"):
            NG.check_host(h)                   # 不抛即通过
    finally:
        _clear_switch()


def test_variants_never_unlocked():
    """`rh-api.*` 这类变体是永久黑名单，开了闸也不放。

    ★ 为什么单独设一条永久黑名单：这些名字常出现在「镜像 / 中转 / 代理」上，
      放行它们等于给了一条绕过审核的旁路。真要用平台就用正式域名。
    """
    _clear_switch()
    NG.allow_platform()
    try:
        for h in ("rh-api.runninghub.ai", "rhapi.example.com"):
            try:
                NG.check_host(h)
            except NG.RemoteForbidden:
                continue
            raise AssertionError("变体被放行了：%s" % h)
    finally:
        _clear_switch()


def test_allow_remote_does_not_unlock_platform(monkeypatch):
    """SOLODRAMA_ALLOW_REMOTE=1 只放宽普通远端，平台通道仍然关闭。

    ★ 这是最容易写错的一条：为了跑大模型网关顺手开了 ALLOW_REMOTE，
      不该同时把平台出口也打开 —— 那是用粗开关换掉精确边界。
    """
    _clear_switch()
    monkeypatch.setenv("SOLODRAMA_ALLOW_REMOTE", "1")
    try:
        assert NG._allow_remote()
        NG.check_host("api.openai.com")        # 普通远端：放过
        try:
            NG.check_host("www.runninghub.ai")
        except NG.RemoteForbidden:
            return
        raise AssertionError("开了 allow_remote 之后平台竟然能连 —— 这是最危险的回归")
    finally:
        _clear_switch()


def test_platform_scope_is_temporary():
    """platform_allowed() 退出后必须恢复关闭。

    ★ 连接中心的「测试」就走这条路。Web 是常驻进程，一次点击把闸永久
      打开，等于之后任何代码路径都能出网。
    """
    _clear_switch()
    with NG.platform_allowed():
        assert NG._allow_platform()
        NG.check_host("www.runninghub.ai")
    assert not NG._allow_platform(), "退出 with 之后闸没关上"
    try:
        NG.check_host("www.runninghub.ai")
    except NG.RemoteForbidden:
        return
    raise AssertionError("退出 with 之后平台仍然可达")


# ---------------------------------------------------------------------------
# [C] 旁路：有系统代理时 URL 层必须拦住（socket 层看不见真实目标）
# ---------------------------------------------------------------------------
def test_url_layer_blocks_by_default():
    _clear_switch()
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
    """file:// / data: 不是网络请求，不拦；http/https/ws 必须判。"""
    _clear_switch()
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
# [D] 结构：默认通道不经过开闸代码
# ---------------------------------------------------------------------------
def _drama_src() -> str:
    return (ROOT / "stages" / "production" / "scripts" / "drama.py").read_text(
        encoding="utf-8")


def test_local_branch_returns_before_gate():
    """`cmd_video_run` 里本地分支必须先 return，开闸在后。

    ★ 这条测的是顺序，不是能力。顺序一旦反了（先开闸再判断引擎），
      本地通道也会带着闸跑 —— 那时「默认不出网」就只剩一句注释。
    """
    src = _drama_src()
    i = src.find("def cmd_video_run(")
    assert i > 0, "找不到 cmd_video_run"
    body = src[i:i + 1200]
    i_local = body.find("return cmd_video_local(args)")
    i_gate = body.find("_allow_platform_egress()")
    assert i_local > 0, "本地分支不见了"
    assert i_gate > 0, "平台通道没有开闸调用 —— 那 RH 会被自己的守卫拦住"
    assert i_local < i_gate, (
        "顺序错了：开闸在本地分支之前。本地通道也会带着闸跑，"
        "默认不出网就成了空话。")


def test_video_run_defaults_to_local():
    """`video run --engine` 默认必须是 local。"""
    src = _drama_src()
    # 不能写 [^)]*? —— `choices=('local', 'workflow')` 里的右括号会提前截断。
    m = re.search(r"add_argument\(\s*['\"]--engine['\"].{0,200}?default=(['\"])(\w+)\1",
                  src, re.S)
    assert m, "找不到 --engine 参数定义"
    assert m.group(2) == "local", "--engine 默认值变成了 %s" % m.group(2)


def test_new_project_defaults_to_local():
    """新建项目默认必须是本地引擎（曾经默认 runninghub，一建出来就指向云端）。"""
    for rel in ("stages/production/scripts/drama.py",
                "stages/production/scripts/init_project.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        m = re.search(r"['\"]--video-engine['\"].{0,200}?default=(['\"])([\w]+)\1", src, re.S)
        assert m, "%s 里找不到 --video-engine" % rel
        assert m.group(2) == "local_comfyui", (
            "%s 的 --video-engine 默认值是 %s —— 新项目不该一建出来就指向平台通道"
            % (rel, m.group(2)))


def test_platform_scripts_open_their_own_gate():
    """RH 专用脚本必须自己开闸。

    否则用户手动跑 `python stages/video/workflow/scripts/run.py` 会被
    出口守卫拦下，而报错信息指向的是「网络问题」，不是「你没设开关」。
    运行 RH 专用脚本本身就是意图声明，不该再要一个环境变量。
    """
    for rel in ("stages/video/workflow/scripts/run.py",
                "stages/production/scripts/rh_doctor.py",
                "stages/production/scripts/gen_assets_rh_workflow.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "SOLODRAMA_ALLOW_RH" in src or "allow_platform" in src, (
            "%s 没有开闸声明，手动跑会被守卫拦下" % rel)


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
