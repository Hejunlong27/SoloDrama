#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_comfy_boot.py —— 本地 ComfyUI「按需启动」（离线：不起真进程、不联网）

盯的都是**会静默出事**的路径：

1. **发现安装**：命令参数必须复刻桌面版那三件套（模型路径 yaml + input/output 目录）。
   少了 `--extra-model-paths-config` 会「找不到模型」，表现像装坏了 —— 这种错
   不会抛异常，只会让人对着「模型缺失」排查半天。
2. **只对 loopback 启动**：远程地址必须只探测。判错的话会在本机白起一个实例、白占显存，
   而用户以为它在连另一台机器。
3. **在线就 attach**：端口上已经有 ComfyUI（用户手动开的桌面版）时不能再起一个。
4. **端口被非 ComfyUI 占用**：必须报「被占用」而不是硬起（硬起会 bind 失败，
   在用户眼里就是「点了启动没反应」）。
5. **就绪后回填监听 pid**：实测 0.42 的 main.py 会再拉一个子进程 bind 端口，
   锁里只记 spawn pid 的话，「停止」会误判 not_listener 而永远停不掉。
6. **停止只停自己的**：端口上的监听者不是我们启动的，必须拒绝。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "stages" / "assets" / "comfyui"))

import comfy_boot as B  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def section(name):
    print("\n[%s]" % name)


class Sandbox:
    """临时运行时目录 + 可预测的「外部世界」（probe / 进程 / 端口）。"""

    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="comfyboot-test-"))
        self._env = {k: os.environ.get(k) for k in
                     ("SOLODRAMA_VAR", "APPDATA", "COMFYUI_HOME", "COMFYUI_PYTHON",
                      "SOLODRAMA_COMFY_AUTOSTART", "DRAMA_COMFY_AUTOSTART", "COMFYUI_URL")}
        os.environ["SOLODRAMA_VAR"] = str(self.tmp / "var")
        for k in ("COMFYUI_HOME", "COMFYUI_PYTHON", "SOLODRAMA_COMFY_AUTOSTART",
                  "DRAMA_COMFY_AUTOSTART", "COMFYUI_URL"):
            os.environ.pop(k, None)
        self._orig = {n: getattr(B, n) for n in
                      ("probe", "spawn", "pid_alive", "_port_pids", "discover")}
        return self

    def __exit__(self, *exc):
        for n, fn in self._orig.items():
            setattr(B, n, fn)
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _offline():
    return {"online": False, "base_url": "http://127.0.0.1:8188", "version": "", "gpu": "",
            "vram_free_gb": 0.0, "vram_total_gb": 0.0, "reason": "refused"}


def _online():
    return {"online": True, "base_url": "http://127.0.0.1:8188", "version": "0.42.1",
            "gpu": "RTX 4060", "vram_free_gb": 0.6, "vram_total_gb": 8.0, "reason": ""}


# ---------------------------------------------------------------------------
def test_parse_url():
    section("1. 地址解析：loopback 判定")
    u = B.parse_url("127.0.0.1:8188")
    check(u["ok"] and u["loopback"] and u["port"] == 8188, "裸地址应补 http 并识别 8188")
    check(B.parse_url("http://localhost:9000")["loopback"], "localhost 算本机")
    check(not B.parse_url("http://192.168.1.9:8188")["loopback"], "局域网地址不算本机")
    check(B.parse_url("https://example.com")["port"] == 443, "https 默认 443")


def test_build_argv():
    section("2. 启动参数：复刻桌面版三件套，白名单过滤")
    inst = {"python": "py.exe", "main_py": "main.py", "args": ["--enable-manager", "--feature-flag"],
            "extra_model_paths": "m.yaml", "input_dir": "in", "output_dir": "out"}
    argv = B.build_argv(inst, 8188)
    joined = " ".join(argv)
    check(argv[:3] == ["py.exe", "-s", "main.py"], "解释器 + -s + main.py 在最前，实际 %s" % argv[:3])
    check("--port 8188" in joined and "--listen 127.0.0.1" in joined, "必须显式给端口与监听地址")
    check("--extra-model-paths-config m.yaml" in joined, "模型路径 yaml 不能丢（丢了会误报模型缺失）")
    check("--input-directory in" in joined and "--output-directory out" in joined,
          "input/output 目录不能丢（丢了产物会落进安装目录）")
    check("--feature-flag" not in joined, "桌面版私有参数必须被白名单挡掉")
    check("--enable-manager" in joined, "launchArgs 里的白名单参数要保留")


def test_discover_desktop():
    section("3. 发现安装：从桌面版登记表还原命令行")
    with Sandbox() as box:
        appdata = box.tmp / "Roaming"
        os.environ["APPDATA"] = str(appdata)
        desktop = appdata / "Comfy Desktop"
        (desktop / "instance-model-paths").mkdir(parents=True)
        (desktop / "instance-model-paths" / "inst-777.yaml").write_text("x: 1", encoding="utf-8")
        inst_dir = box.tmp / "root" / "ComfyUI-Installs" / "MyInst"
        comfy = inst_dir / "ComfyUI"
        (comfy / ".venv" / "Scripts").mkdir(parents=True)
        (comfy / "main.py").write_text("print(1)", encoding="utf-8")
        (comfy / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
        shared = box.tmp / "root" / "ComfyUI-Shared"
        (shared / "input").mkdir(parents=True)
        (shared / "output").mkdir(parents=True)
        (desktop / "installations.json").write_text(json.dumps([{
            "id": "inst-777", "name": "MyInst", "installPath": str(inst_dir),
            "status": "installed", "launchArgs": "--enable-manager --feature-flag x",
        }]), encoding="utf-8")

        d = B.discover()
        check(len(d["installs"]) == 1, "应找到 1 个安装，实际 %d" % len(d["installs"]))
        it = d["installs"][0]
        check(it["source"] == "desktop", "来源应标 desktop")
        check(it["python"].endswith("python.exe"), "应解析出 venv 解释器")
        check(it["extra_model_paths"].endswith("inst-777.yaml"), "应绑定该实例的模型路径 yaml")
        check(it["input_dir"].endswith("input") and it["output_dir"].endswith("output"),
              "应带上共享 input/output 目录")
        check(it["args"] == ["--enable-manager"], "launchArgs 只保留白名单项，实际 %s" % it["args"])
        check(B.build_argv(it, 8188)[3:5] == ["--port", "8188"], "argv 应可继续拼装")


def test_ensure_attached():
    section("4. 已在线：直接复用，不起进程")
    with Sandbox():
        calls = []
        B.probe = lambda *a, **k: _online()
        B.spawn = lambda *a, **k: calls.append("spawn") or {"ok": True, "pid": 1}
        r = B.ensure("http://127.0.0.1:8188", wait_s=5)
        check(r["ok"] and r["action"] == "attached", "应 attach，实际 %s" % r.get("action"))
        check(not calls, "已在线时不得 spawn")
        check("在线" in r["detail"], "detail 应说明在线")


def test_ensure_remote():
    section("5. 远程地址：只探测，不在本机起进程")
    with Sandbox():
        calls = []
        B.probe = lambda *a, **k: _offline()
        B.spawn = lambda *a, **k: calls.append(1) or {"ok": True, "pid": 1}
        r = B.ensure("http://192.168.1.9:8188")
        check(r["ok"] is False and r["reason"] == "remote", "远程地址必须拒绝，实际 %s" % r.get("reason"))
        check(not calls, "远程地址不得 spawn")
        check(bool(r["next"]), "必须给下一步")


def test_ensure_autostart_off():
    section("6. 关闭自动启动：不再拉起")
    with Sandbox():
        os.environ["SOLODRAMA_COMFY_AUTOSTART"] = "0"
        calls = []
        B.probe = lambda *a, **k: _offline()
        B.spawn = lambda *a, **k: calls.append(1) or {"ok": True, "pid": 1}
        r = B.ensure("http://127.0.0.1:8188")
        check(r["ok"] is False and r["reason"] == "autostart_off", "应报 autostart_off")
        check(not calls, "关掉开关后不得 spawn")
        check(B._autostart_default() is False, "环境变量 0 应判为关闭")
        os.environ["SOLODRAMA_COMFY_AUTOSTART"] = ""
        check(B._autostart_default() is True, "空值等于没设，应回到默认开")


def test_ensure_port_busy():
    section("7. 端口被别的程序占用：报错，不硬起")
    with Sandbox():
        calls = []
        B.probe = lambda *a, **k: _offline()
        B._port_pids = lambda port: [4321]
        B.pid_alive = lambda pid: False
        B.spawn = lambda *a, **k: calls.append(1) or {"ok": True, "pid": 1}
        r = B.ensure("http://127.0.0.1:8188")
        check(r["ok"] is False and r["reason"] == "port_busy", "应报 port_busy，实际 %s" % r.get("reason"))
        check("4321" in r["detail"], "detail 应指出占用者 pid")
        check(not calls, "端口被占时不得 spawn")


def test_ensure_no_install():
    section("8. 没找到安装：说清怎么补")
    with Sandbox():
        B.probe = lambda *a, **k: _offline()
        B._port_pids = lambda port: []
        B.discover = lambda cfg=None: {"installs": [], "desktop": False, "error": ""}
        r = B.ensure("http://127.0.0.1:8188")
        check(r["ok"] is False and r["reason"] == "no_install", "应报 no_install")
        check("连接中心" in (r.get("next") or ""), "next 要指到能补的地方")


def test_ensure_started_backfill():
    section("9. 启动成功：锁里回填真正的监听 pid")
    with Sandbox():
        seq = {"n": 0}

        def fake_probe(*a, **k):
            seq["n"] += 1
            return _online() if seq["n"] >= 3 else _offline()

        B.probe = fake_probe
        state = {"spawned": False}
        # 起之前端口是空的；起之后监听者是 2222（与 spawn 的 1111 不同 —— 实测就是这样）
        B._port_pids = lambda port: [2222] if state["spawned"] else []
        B.pid_alive = lambda pid: True
        B.discover = lambda cfg=None: {"installs": [{
            "id": "i1", "name": "fake", "python": "py.exe", "main_py": "main.py",
            "cwd": ".", "args": [], "extra_model_paths": "", "input_dir": "", "output_dir": "",
        }], "desktop": False, "error": ""}

        def fake_spawn(*a, **k):
            state["spawned"] = True
            return {"ok": True, "pid": 1111}

        B.spawn = fake_spawn
        r = B.ensure("http://127.0.0.1:8188", wait_s=10)
        check(r["ok"] and r["action"] == "started", "应 started，实际 %s/%s" % (r.get("action"), r.get("reason")))
        lk = B.load_lock()
        check(lk.get("pid") == 2222, "锁里的 pid 必须是监听者 2222，实际 %s" % lk.get("pid"))
        check(lk.get("spawn_pid") == 1111, "spawn_pid 要保留 1111")


def test_ensure_exited_classified():
    section("10. 启动即退出：按日志给出人话原因")
    with Sandbox():
        var = Path(os.environ["SOLODRAMA_VAR"])
        var.mkdir(parents=True, exist_ok=True)
        (var / "comfyui.log").write_text(
            "Traceback...\nOSError: [Errno 98] Address already in use\n", encoding="utf-8")
        B.probe = lambda *a, **k: _offline()
        B._port_pids = lambda port: []
        B.pid_alive = lambda pid: False
        B.discover = lambda cfg=None: {"installs": [{
            "id": "i1", "name": "fake", "python": "py.exe", "main_py": "main.py",
            "cwd": ".", "args": [], "extra_model_paths": "", "input_dir": "", "output_dir": "",
        }], "desktop": False, "error": ""}
        B.spawn = lambda *a, **k: {"ok": True, "pid": 3333}
        r = B.ensure("http://127.0.0.1:8188", wait_s=10)
        check(r["ok"] is False, "进程退出必须判失败")
        check(r["reason"] == "port_busy", "应识别 address already in use，实际 %s" % r.get("reason"))
        check(bool(r["next"]), "必须给下一步")


def test_ownership_matrix():
    section("11. 所有权：三种形态都不能判错")
    with Sandbox():
        var = Path(os.environ["SOLODRAMA_VAR"])
        var.mkdir(parents=True, exist_ok=True)
        B.pid_alive = lambda pid: True
        B._port_pids = lambda port: [2222]
        B._save_lock({"pid": 2222, "spawn_pid": 1111, "port": 8188})
        check(B.ownership()["owned"] is True, "监听者等于锁里的 pid → 可以停")
        B._save_lock({"pid": 1111, "spawn_pid": 1111, "port": 8188})
        own = B.ownership()
        check(own["owned"] is False and own["reason"] == "not_listener",
              "锁里的 pid 不是监听者 → 必须拒绝（PID 复用会杀错人），实际 %s" % own["reason"])
        B._port_pids = lambda port: []
        B.pid_alive = lambda pid: False
        B._save_lock({"pid": 2222, "spawn_pid": 1111, "port": 8188})
        check(B.ownership()["reason"] == "dead", "都不在了 → dead")


def test_stop_refuses_foreign():
    section("12. 停止：不是自己启动的就不动")
    with Sandbox():
        var = Path(os.environ["SOLODRAMA_VAR"])
        var.mkdir(parents=True, exist_ok=True)
        B._save_lock({"pid": 1111, "spawn_pid": 1111, "port": 8188})
        B.pid_alive = lambda pid: True
        B._port_pids = lambda port: [9999]
        called = []
        real_run = B.subprocess.run
        B.subprocess.run = lambda *a, **k: called.append(a)       # 不得真的 taskkill
        try:
            r = B.stop()
        finally:
            B.subprocess.run = real_run
        check(r["ok"] is False and r["reason"] == "not_listener", "必须拒绝，实际 %s" % r.get("reason"))
        check(not called, "拒绝时不得执行任何 kill")
        check(B.load_lock() != {}, "拒绝时不能把锁清掉（否则下次以为自己是主人）")


def test_stop_kills_own():
    section("13. 停止：自己启动的能停掉，并清理锁")
    with Sandbox():
        var = Path(os.environ["SOLODRAMA_VAR"])
        var.mkdir(parents=True, exist_ok=True)
        B._save_lock({"pid": 2222, "spawn_pid": 1111, "port": 8188})
        B.pid_alive = lambda pid: True
        seq = {"n": 0}

        def ports(port):
            seq["n"] += 1
            return [2222] if seq["n"] == 1 else []     # 第一次核对所有权，之后视为已释放

        B._port_pids = ports
        killed = []
        real_run = B.subprocess.run
        B.subprocess.run = lambda argv, **k: killed.append(argv) or type("R", (), {"returncode": 0})()
        try:
            r = B.stop()
        finally:
            B.subprocess.run = real_run
        check(r["ok"] is True and r["action"] == "stopped", "应成功停止，实际 %s/%s" % (r.get("ok"), r.get("reason")))
        check(any("1111" in str(x) for x in killed), "应先杀 spawn_pid 的进程树")
        check(any("2222" in str(x) for x in killed), "再杀监听者")
        check(B.load_lock() == {}, "停完必须清锁")


def main() -> int:
    print("=" * 60)
    print("ComfyUI 按需启动测试（离线：不起进程、不联网）")
    print("=" * 60)
    test_parse_url()
    test_build_argv()
    test_discover_desktop()
    test_ensure_attached()
    test_ensure_remote()
    test_ensure_autostart_off()
    test_ensure_port_busy()
    test_ensure_no_install()
    test_ensure_started_backfill()
    test_ensure_exited_classified()
    test_ownership_matrix()
    test_stop_refuses_foreign()
    test_stop_kills_own()
    print("\n" + "-" * 60)
    if FAILS:
        print("[NG] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 按需启动全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
