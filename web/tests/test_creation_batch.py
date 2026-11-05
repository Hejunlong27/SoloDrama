#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_creation_batch.py —— 分批模板的「续写」语义

为什么单独立一套
----------------
21 份内置模板几乎都按「第N批／共M批」输出。此前的实现是：每次生成**整份覆盖**、
而且**不把已写好的部分给模型**。后果不是报错，而是：
  · 4 批资产库最后只剩最后一批（文件里前 3 批被覆盖，只在 .bak 里）；
  · 点第二次「生成」，模型从第 1 批重写，看不到「已经写到镜 5」。

所以这里钉四条：
1. 从正文读出批次与「下一批从哪开始」（镜号 / 集号）；
2. 追加写入不覆盖、且留备份；
3. 组装输入时把 `prior` 与 `shot_from` 交出去（模型据此续写）；
4. 第一批没有 prior —— 不能因此报「缺变量」。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core import creation, skills  # noqa: E402


def _ws(tmp_path, text_director=""):
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "layout.json").write_text("{}", encoding="utf-8")
    (ws / "project.json").write_text(json.dumps({
        "meta": {"title": "分批测试", "slug": "batch", "style_lock": "2D-cel-webtoon",
                 "total_ep": 30, "ep_seconds": 60}}), encoding="utf-8")
    (ws / "brief.json").write_text(json.dumps({"idea": "嫡女回府", "ep_total": 30}),
                                   encoding="utf-8")
    skills.install(str(ws), "zhaidou-manju")
    # 下游环节的输入：企划案 + 资产库（导演手册要引用资产代号）
    creation.write(str(ws), "plan", "# 立项卡\n\n一句话故事：嫡女回府。")
    creation.write(str(ws), "assets", "# 第1批／共4批｜人物卡\n\n### P01 崔昭\n")
    if text_director:
        d = ws / "00-创作" / "04-导演手册"
        d.mkdir(parents=True)
        (d / "第01集.md").write_text(text_director, encoding="utf-8")
    return ws


def test_batch_of_reads_header():
    assert creation.batch_of("# 第1批／共4批｜人物卡") == (1, 4)
    assert creation.batch_of("# 第03集手册｜第2批/共3批｜镜6–8") == (2, 3)
    assert creation.batch_of("没有批次信息") == (0, 0)


def test_next_segment_counts_shots_and_episodes():
    md = "# 第01集导演手册｜第1批／共3批｜镜1–5\n### 镜 1\nA\n### 镜 3\nB\n"
    seg = creation.next_segment(md, "director")
    assert seg["batch"] == 1 and seg["batch_no"] == 2
    assert seg["shot_from"] == 4, seg

    script = "## 第1集 角门\n...\n## 第2集 归府\n"
    assert creation.next_segment(script, "script")["ep_from"] == 3


def test_write_append_keeps_previous_batches(tmp_path):
    ws = _ws(tmp_path)
    first = "# 第01集导演手册｜第1批／共3批｜镜1–5\n\n### 镜 1\nA\n"
    creation.write(str(ws), "director", first, name="第01集")
    creation.write(str(ws), "director", "# 第01集导演手册｜第2批／共3批｜镜6–8\n\n### 镜 6\nB\n",
                   name="第01集", append=True)

    text = creation.read(str(ws), "director")["text"]
    assert "镜 1" in text and "镜 6" in text, "追加不能覆盖前一批"
    assert creation.batch_of(text) == (2, 3), text[:60]
    # 备份要留（追加也是一次写盘）
    baks = list((ws / "00-创作" / "04-导演手册").glob("*.bak_*"))
    assert baks, "追加写入也必须备份旧版"


def test_write_without_append_replaces(tmp_path):
    ws = _ws(tmp_path)
    creation.write(str(ws), "assets", "# 第1批／共4批｜人物卡\nP01\n")
    creation.write(str(ws), "assets", "# 第1批／共4批｜人物卡\n重写\n")
    text = creation.read(str(ws), "assets")["text"]
    assert "重写" in text and text.count("第1批") == 1


def test_vars_for_passes_prior_and_shot_from(tmp_path):
    ws = _ws(tmp_path, text_director=(
        "# 第01集导演手册｜第1批／共3批｜镜1–5\n\n"
        "### 镜 1\nA\n### 镜 2\nB\n### 镜 5\nC\n"))
    v = creation.vars_for(str(ws), "create.director", {"script_ep": "## 第1集 角门\n崔昭：父亲。"})
    assert v["shot_from"] == 6, v["shot_from"]
    assert v["batch_no"] == 2
    assert "镜 5" in v["prior"], "prior 要带上「已写到哪」，否则模型从头重写"
    assert v["shots_per_batch"] == 5


def test_vars_for_first_batch_has_empty_prior(tmp_path):
    """第一批没有 prior —— 不能因此报「缺变量」。"""
    ws = _ws(tmp_path)
    (ws / "00-创作" / "02-资产库.md").unlink()      # 还没写过 → 第一批
    v = creation.vars_for(str(ws), "create.assets")
    assert v["prior"] == ""
    assert v["batch_no"] == 1
