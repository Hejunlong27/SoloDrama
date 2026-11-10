# -*- coding: utf-8 -*-
"""创作版本（`.bak_<时间戳>.md`）的读取与隔离。

这里守的不是「功能能不能跑」，而是三件容易错得很安静的事：

1. **备份归属**：导演手册一个目录下躺着 30 份产物的备份。
   如果只按「目录里的 .md」列，第 02 集会看到第 01 集的备份，
   用户点开「第 02 集的历史」结果读的是第 01 集 —— 而界面一切正常。
2. **路径穿越**：`file` 是查询参数，`../` 必须被吃掉，否则能读工作区外的文件。
3. **不建版本库**：`write()` 已经在磁盘上留了备份，这里只负责列出来。
   如果有人又写了索引，就会出现「索引三个、磁盘五个」的分叉。

```bash
python -m pytest web/tests/test_create_versions.py -q
```
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from core import creation  # noqa: E402


def _mk(tmp_path, name="剧"):
    ws = tmp_path / name
    (ws / "00-创作").mkdir(parents=True)
    return ws


def test_lists_only_own_backups(tmp_path):
    ws = _mk(tmp_path)
    d = ws / "00-创作"
    (d / "01-企划案.md").write_text("当前", encoding="utf-8")
    (d / "01-企划案.bak_1700000000.md").write_text("旧一", encoding="utf-8")
    (d / "01-企划案.bak_1700000100.md").write_text("旧二", encoding="utf-8")
    # 同目录下另一个产物的备份，不能混进来
    (d / "02-资产库.bak_1700000200.md").write_text("别人的", encoding="utf-8")
    # 用户手工建的副本，不是本项目的版本
    (d / "01-企划案-副本.md").write_text("手工", encoding="utf-8")

    v = creation.versions(ws, "plan")
    files = [x["file"] for x in v["items"]]
    assert files == ["01-企划案.md", "01-企划案.bak_1700000100.md", "01-企划案.bak_1700000000.md"], files
    assert [x["current"] for x in v["items"]] == [True, False, False]
    assert v["name"] == "01-企划案.md"


def test_multifile_stage_isolates_by_stem(tmp_path):
    """第 02 集的历史里不能出现第 01 集的备份。"""
    ws = _mk(tmp_path)
    d = ws / "00-创作" / "04-导演手册"
    d.mkdir(parents=True)
    (d / "第01集.md").write_text("ep1 当前", encoding="utf-8")
    (d / "第01集.bak_1700000000.md").write_text("ep1 旧", encoding="utf-8")
    (d / "第02集.md").write_text("ep2 当前", encoding="utf-8")
    (d / "第02集.bak_1700000500.md").write_text("ep2 旧", encoding="utf-8")

    v1 = creation.versions(ws, "director", "第01集.md")
    assert [x["file"] for x in v1["items"]] == ["第01集.md", "第01集.bak_1700000000.md"]

    v2 = creation.versions(ws, "director", "第02集.md")
    assert [x["file"] for x in v2["items"]] == ["第02集.md", "第02集.bak_1700000500.md"]


def test_read_backup_and_current(tmp_path):
    ws = _mk(tmp_path)
    d = ws / "00-创作"
    (d / "01-企划案.md").write_text("当前版", encoding="utf-8")
    (d / "01-企划案.bak_1700000000.md").write_text("旧版", encoding="utf-8")

    cur = creation.read_version(ws, "plan")
    assert cur["text"] == "当前版" and cur["ts"] == 0

    old = creation.read_version(ws, "plan", "", "01-企划案.bak_1700000000.md")
    assert old["text"] == "旧版"
    assert old["ts"] == 1700000000
    assert old["when"], "备份必须带可读时间，否则界面只有一串数字"


def test_rejects_foreign_and_traversal(tmp_path):
    ws = _mk(tmp_path)
    d = ws / "00-创作"
    (d / "01-企划案.md").write_text("当前", encoding="utf-8")
    (d / "02-资产库.bak_1700000200.md").write_text("别人的", encoding="utf-8")
    (tmp_path / "outside.md").write_text("外面", encoding="utf-8")

    with pytest.raises(ValueError):
        creation.read_version(ws, "plan", "", "02-资产库.bak_1700000200.md")
    with pytest.raises(ValueError):
        creation.read_version(ws, "plan", "", "../outside.md")
    with pytest.raises(ValueError):
        creation.read_version(ws, "plan", "", "01-企划案.md.bak_1700000000")   # 不以 .md 结尾
    with pytest.raises(ValueError):
        creation.read_version(ws, "plan", "", "01-企划案.bak_1700000000.md")   # 不存在


def test_no_backup_yet(tmp_path):
    """只有当前文件时也要能列出来（界面靠 items 长度判断「还没有历史版本」）。"""
    ws = _mk(tmp_path)
    (ws / "00-创作" / "01-企划案.md").write_text("只有当前", encoding="utf-8")
    v = creation.versions(ws, "plan")
    assert [x["file"] for x in v["items"]] == ["01-企划案.md"]
    assert v["exists"] is True


def test_bad_stage_raises_keyerror(tmp_path):
    ws = _mk(tmp_path)
    with pytest.raises(KeyError):
        creation.versions(ws, "worldview")
