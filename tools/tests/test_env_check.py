#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_env_check.py —— 环境自检工具离线测试

只测**不依赖真实机器状态**的部分：
  结构   collect() 的字段完整、必需项判定自洽
  渲染   render / render_fix 不抛异常且含关键判定字样
  输出   --json 可被解析、--quiet 只列未通过
  探测   _lib_state 与 _probe_alt 对同一解释器结论一致
  清单   _manifest_state 在仓库根返回 (N, 0, True)；项目内返回 exists=False

用法：python tools/tests/test_env_check.py
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # tools/

import env_check as E  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def test_collect_shape():
    rep = E.collect()
    check("collect 返回必需键", {"python", "executable", "items", "ok"} <= set(rep), str(list(rep)))
    check("items 非空且有分组", len(rep["items"]) >= 10
          and all({"group", "name", "ok", "required", "detail"} <= set(i) for i in rep["items"]))
    groups = {i["group"] for i in rep["items"]}
    check("覆盖五层检查", {"运行时", "依赖", "外部程序", "配置", "完整性"} <= groups, str(groups))
    req = [i for i in rep["items"] if i["required"]]
    check("必需项集合正确",
          {"Python", "Pillow", "ffmpeg", "ffprobe"} <= {i["name"] for i in req},
          str([i["name"] for i in req]))
    check("ok 与必需项一致",
          rep["ok"] == all(i["ok"] for i in rep["items"] if i["required"]))
    check("解释器路径是绝对路径", pathlib.Path(rep["executable"]).is_absolute())


def test_render():
    rep = E.collect()
    out = E.render(rep)
    check("render 含标题", "SoloDrama 环境自检" in out)
    check("render 含解释器", rep["executable"] in out)
    check("render 有结论行", "[OK]" in out or "[NG]" in out)
    q = E.render(rep, only_failed=True)
    check("quiet 模式不含通过项", "[OK  ] ffmpeg" not in q)
    fx = E.render_fix(rep)
    check("fix 报告只打印不执行", "只打印，不执行" in fx, fx[:60])
    check("fix 报告有内容", len(fx.strip().splitlines()) >= 3)


def test_probe_consistency():
    ok_lib, _ver = E._lib_state("PIL")
    ok_alt, _v2 = E._probe_alt(sys.executable, "PIL")
    check("当前解释器 _lib_state 与 _probe_alt 结论一致", ok_lib == ok_alt,
          "%s vs %s" % (ok_lib, ok_alt))
    ok_none, _ = E._probe_alt(sys.executable, "definitely_not_a_module_xyz")
    check("不存在的模块判为没有", ok_none is False)
    ok_bad, _ = E._probe_alt(str(pathlib.Path(sys.executable).parent / "no_such_python.exe"), "PIL")
    check("解释器不存在时不抛异常", ok_bad is False)


def test_manifest():
    total, bad, exists = E._manifest_state()
    if (E.ROOT / "manifest.sha256").is_file():
        check("仓库根：清单存在且条数 > 0", exists is True and total > 0,
              "%s/%s/%s" % (total, bad, exists))
        # 不断言 bad==0：开发过程中改完文件还没重建清单时，这一项本来就该是「不符」
        check("不符条数在合理区间", 0 <= bad <= total, "bad=%s total=%s" % (bad, total))
    else:
        check("无清单时 exists=False（项目内运行属正常）", exists is False)


def test_port():
    check("关闭的端口判为不可达", E._port_open("127.0.0.1", 1, timeout=0.3) is False)


def test_cli():
    def run(argv):
        buf, old = io.StringIO(), sys.argv
        sys.argv = ["env_check.py"] + argv
        try:
            with contextlib.redirect_stdout(buf):
                rc = E.main()
        finally:
            sys.argv = old
        return rc, buf.getvalue()

    rc, out = run(["--json"])
    try:
        obj = json.loads(out)
        parsed = isinstance(obj, dict) and "items" in obj
    except json.JSONDecodeError:
        parsed = False
    check("--json 输出可解析", parsed, out[:80])
    check("--json 退出码与 ok 一致", (rc == 0) == json.loads(out)["ok"], "rc=%d" % rc)

    rc2, out2 = run(["--quiet"])
    check("--quiet 不打印通过项", "[OK  ] Pillow" not in out2)
    check("退出码 0/2 二选一", rc2 in (0, 2), "rc=%d" % rc2)


def main() -> int:
    for fn in (test_collect_shape, test_render, test_probe_consistency,
               test_manifest, test_port, test_cli):
        try:
            fn()
        except Exception as e:                                     # noqa: BLE001
            check("%s 抛异常" % fn.__name__, False, repr(e))
    ok = sum(1 for _, c, _ in RESULTS if c)
    for name, cond, detail in RESULTS:
        if not cond:
            print("[FAIL] %s%s" % (name, ("｜" + detail) if detail else ""))
    print("\n%s  %d/%d 通过" % ("[OK]" if ok == len(RESULTS) else "[NG]", ok, len(RESULTS)))
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
