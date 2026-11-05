"""test_netguard_trusted.py —— 受信远端（云端镜像）这条窄口子

为什么单独测
------------
`_netguard` 的原则不变量是「**没人声明过的域名一律出不去**」。云端接入加了一条
`SOLODRAMA_TRUSTED_HOSTS`，它必须满足三条，缺一条就等于把边界拆了：

  1. **不点名就不放**：默认状态下云端域名照旧被拒（不能因为「支持云」就默认放开）；
  2. **只放点名的**：通配只匹配子域，后缀本身、以及 `a.suffix.evil.com` 这类都不放；
  3. **黑名单优先**：受信名单**不能**覆盖 `FORBID_SUBSTRINGS`（平台变体永远拦）。

外加一条工程约束：名单是模块级缓存，所以 `reset_trusted()` 必须真的让新值生效 ——
否则测试会「看起来通过」，线上改环境变量却要重启才生效。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve()
STAGES = HERE.parents[3]
sys.path.insert(0, str(STAGES))

import _netguard as NG  # noqa: E402

CLOUD = "abc-8188.container.x-gpu.com"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """每个用例都从「无受信、不放开」开始，避免相互污染。"""
    for k in ("SOLODRAMA_TRUSTED_HOSTS", "DRAMA_TRUSTED_HOSTS", "SOLODRAMA_ALLOW_REMOTE",
              "SOLODRAMA_ALLOW_RH"):
        monkeypatch.delenv(k, raising=False)
    NG.reset_trusted()
    yield
    NG.reset_trusted()


def test_default_denies_cloud_host():
    """★ 第一条不变量：支持云端 ≠ 默认放开云端。"""
    with pytest.raises(NG.RemoteForbidden):
        NG.check_host(CLOUD)


def test_named_host_allowed(monkeypatch):
    monkeypatch.setenv("SOLODRAMA_TRUSTED_HOSTS", "*.container.x-gpu.com")
    NG.reset_trusted()
    NG.check_host(CLOUD)                      # 不抛 = 放行
    NG.check_url("https://abc-8188.container.x-gpu.com/probe?x=1")


def test_wildcard_is_narrow(monkeypatch):
    monkeypatch.setenv("SOLODRAMA_TRUSTED_HOSTS", "*.container.x-gpu.com")
    NG.reset_trusted()
    # 后缀本身不是实例地址
    with pytest.raises(NG.RemoteForbidden):
        NG.check_host("container.x-gpu.com")
    # 前缀伪装（真正的域名在 evil.com）
    with pytest.raises(NG.RemoteForbidden):
        NG.check_host("abc.container.x-gpu.com.evil.com")
    # 其他域名不受影响
    with pytest.raises(NG.RemoteForbidden):
        NG.check_host("evil.example.com")


def test_exact_host(monkeypatch):
    monkeypatch.setenv("SOLODRAMA_TRUSTED_HOSTS", "abc-8188.container.x-gpu.com")
    NG.reset_trusted()
    NG.check_host(CLOUD)
    with pytest.raises(NG.RemoteForbidden):
        NG.check_host("def-8188.container.x-gpu.com"), "精确名单不该覆盖兄弟实例"


def test_blacklist_wins_over_trusted(monkeypatch):
    """★ 受信名单不许覆盖黑名单：`rh-api` 变体永远拦。"""
    monkeypatch.setenv("SOLODRAMA_TRUSTED_HOSTS", "*.runninghub.ai,rh-api.runninghub.ai")
    NG.reset_trusted()
    with pytest.raises(NG.RemoteForbidden):
        NG.check_host("rh-api.runninghub.ai")


def test_case_and_port(monkeypatch):
    monkeypatch.setenv("SOLODRAMA_TRUSTED_HOSTS", "*.Container.X-GPU.com ")
    NG.reset_trusted()
    NG.check_host("ABC-8188.CONTAINER.X-GPU.COM")
    NG.check_host("abc-8188.container.x-gpu.com:8188")
    NG.check_url("https://abc-8188.container.x-gpu.com:8188/")


def test_reset_trusted_makes_new_value_effective(monkeypatch):
    """缓存必须可清 —— 否则「改了环境变量却要重启」这种坑会被带进 8 小时长任务。"""
    monkeypatch.setenv("SOLODRAMA_TRUSTED_HOSTS", "*.container.x-gpu.com")
    NG.reset_trusted()
    assert NG._is_trusted(CLOUD)
    monkeypatch.setenv("SOLODRAMA_TRUSTED_HOSTS", "other.example")
    assert NG._is_trusted(CLOUD), "未清缓存时应仍读旧值（这是缓存语义）"
    NG.reset_trusted()
    assert not NG._is_trusted(CLOUD)


def test_would_allow_matches_check(monkeypatch):
    """`would_allow()` 是给上层「先解释再执行」用的，结论必须与真判一致。"""
    assert NG.would_allow("127.0.0.1") is True
    assert NG.would_allow("192.168.1.9") is True
    assert NG.would_allow("evil.example.com") is False
    assert NG.would_allow("rh-api.runninghub.ai") is False
    assert NG.would_allow(CLOUD) is False
    monkeypatch.setenv("SOLODRAMA_TRUSTED_HOSTS", "*.container.x-gpu.com")
    NG.reset_trusted()
    assert NG.would_allow(CLOUD) is True
    NG.check_host(CLOUD)


def test_allow_remote_still_wins_but_is_separate(monkeypatch):
    """ALLOW_REMOTE 仍能放开一切（大模型网关用），且与受信名单互不依赖。"""
    monkeypatch.setenv("SOLODRAMA_ALLOW_REMOTE", "1")
    NG.reset_trusted()
    NG.check_host("evil.example.com")
    assert NG.would_allow("evil.example.com") is False, "粗开关不改变 would_allow 的窄口径"


def test_selfcheck_all_green(monkeypatch):
    rows = NG.selfcheck()
    bad = [(n, d) for n, ok, d in rows if not ok]
    assert not bad, "守卫自检有失败项：%s" % bad


def test_local_still_allowed(monkeypatch):
    """云端改造不许伤到本机链路 —— 这条是本轮的唯一回滚承诺。"""
    for h in ("127.0.0.1", "localhost", "::1", "192.168.1.9", "10.0.0.2"):
        NG.check_host(h)
