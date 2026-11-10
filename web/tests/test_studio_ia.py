# -*- coding: utf-8 -*-
"""信息架构与阶段矩阵的守卫。

这类问题不会报错，只会「慢慢变得不对」：

1. 新增一个页面 → 加进 `VIEWS` 但忘了放进任何一个工作空间 ⇒ 页面存在、**谁都不进不去**。
2. 引擎新增/改名一个环节 → 前端 `STAGE_ROUTE` 没跟上 ⇒ 「去处理」按钮静默退回总览页。
3. 有人图省事，在 JS 里抄一份节点 id / 中文名 ⇒ 引擎改 id 后 UI 继续显示旧名字。

三个都用静态比对守住，不启动服务、不跑引擎。

```bash
python -m pytest web/tests/test_studio_ia.py -q
```
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
MAIN = ROOT / "web" / "ui" / "studio" / "js" / "main.js"
OVERVIEW = ROOT / "web" / "ui" / "studio" / "js" / "views" / "overview.js"
STORYBOARD = ROOT / "web" / "ui" / "studio" / "js" / "views" / "storyboard.js"
CREATE = ROOT / "web" / "ui" / "studio" / "js" / "views" / "create.js"
ASSETS = ROOT / "web" / "ui" / "studio" / "js" / "views" / "assets.js"
NODES_PY = ROOT / "stages" / "production" / "scripts" / "nodes.py"

# 这些视图不挂在导航上，但都有别的入口（工作台按钮 / 系统中心页签），属正常
ORPHAN_OK = {"projects", "models", "connections", "health", "agent"}


def _main_src() -> str:
    return MAIN.read_text(encoding="utf-8")


def _view_keys() -> set:
    src = _main_src()
    block = src[src.index("const VIEWS = {"):]
    block = block[:block.index("};")]
    return set(re.findall(r"(\w+)\s*:\s*\(\)\s*=>\s*import\(", block))


def _nav_keys() -> set:
    src = _main_src()
    out = set()
    # GLOBAL_NAV 的 key 就是路由
    gnav = src[src.index("const GLOBAL_NAV = "):]
    gnav = gnav[:gnav.index("\n];")]
    out |= set(re.findall(r"key:\s*'([\w.\-]+)'", gnav))
    # WORKSPACES 的 key 是「工作空间 id」（shots / deliver / control），不是路由；
    # 能点进页面的只有 members[].key。混进来会让「导航指向不存在的视图」误报。
    ws = src[src.index("const WORKSPACES = "):]
    ws = ws[:ws.index("\n];")]
    for m in re.finditer(r"members:\s*\[(.*?)\]", ws, re.S):
        out |= set(re.findall(r"key:\s*'([\w.\-]+)'", m.group(1)))
    return out


def _project_routes() -> list:
    src = _main_src()
    block = src[src.index("const PROJECT_ROUTES = ["):]
    return re.findall(r"'([\w.\-]+)'", block[:block.index("];")])


def _stage_ids() -> list:
    src = NODES_PY.read_text(encoding="utf-8")
    block = src[src.index("STAGES = ["):]
    block = block[:block.index("\n]")] if "\n]" in block else block
    return re.findall(r'"id":\s*"([\w.\-]+)"', block)


def test_every_view_has_an_entry():
    missing = sorted(_view_keys() - _nav_keys() - ORPHAN_OK)
    assert not missing, (
        "这些视图在 VIEWS 里注册了，却没有放进任何工作空间或全局导航，用户进不去：%s\n"
        "修法：加进 WORKSPACES 的某个 members，或显式加进本测试的 ORPHAN_OK 并说明入口在哪。"
        % missing)


def test_nav_points_at_real_views():
    bad = sorted(_nav_keys() - _view_keys())
    assert not bad, "导航指向了不存在的视图（点了会 404 到工作台）：%s" % bad


def test_project_routes_are_all_in_nav():
    """需要项目的路由必须能从侧栏点进去，否则「选完项目就找不到那一页」。"""
    bad = sorted(set(_project_routes()) - _nav_keys() - ORPHAN_OK)
    assert not bad, "PROJECT_ROUTES 里有页面没挂导航：%s" % bad


def test_stage_route_covers_engine_stages():
    """引擎的每个环节都要有落点，否则「去处理」会静默退回总览页。"""
    src = OVERVIEW.read_text(encoding="utf-8")
    m = re.search(r"STAGE_ROUTE\s*=\s*\{([^}]*)\}", src)
    assert m, "overview.js 里找不到 STAGE_ROUTE"
    routes = set(re.findall(r"(\w+)\s*:", m.group(1)))
    stages = set(_stage_ids())
    assert stages, "nodes.py 里没解析到 STAGES，正则或结构变了"
    missing = sorted(stages - routes)
    assert not missing, (
        "引擎环节 %s 在 overview.js 的 STAGE_ROUTE 里没有落点。\n"
        "修法：补一条 <stage>: '<route>'，route 必须是真实视图 key。" % missing)


def test_overview_does_not_hardcode_node_ids():
    """节点 id 是引擎契约。前端一旦抄一份，引擎改名后就只剩 UI 在说旧名字。"""
    src = OVERVIEW.read_text(encoding="utf-8")
    ids = re.findall(r'"id":\s*"([\w.\-]+)"', NODES_PY.read_text(encoding="utf-8"))
    leaked = [i for i in set(ids) if "'%s'" % i in src or '"%s"' % i in src]
    assert not leaked, (
        "overview.js 里硬编码了节点 id：%s\n"
        "节点应直接用接口返回的 n.id 渲染，不要在前端写死。" % leaked)


def test_storyboard_is_three_column():
    """分镜页必须是三栏：镜头列表 / 画布 / 属性与提示词。

    为什么守这个：这一页是「逐镜看片 + 改词」的地方，两栏时画布和提示词互相挤。
    三栏的结构标记散在 JS 里，被改回两栏不会有任何报错，只会让人觉得「怎么又难用了」。
    """
    src = STORYBOARD.read_text(encoding="utf-8")
    for cls in ("sd-shot3", "sd-col-list", "sd-col-stage", "sd-col-side"):
        assert cls in src, "storyboard.js 缺少三栏结构标记 %s（被改回两栏了？）" % cls


def test_prompt_editor_stays_single_block():
    """提示词必须**整段**可编辑、可复制。

    2026-11-10 用户明确要求：拆成六个框之后，每次拿去模型里试都要自己拼回去，
    复制粘贴平白多一步，「结构可见」的收益远小于这个成本。
    现在的形态 = 一个 textarea 装完整原文（含段头）+ 一行只读结构 chip。

    这条守卫防的是「以后有人（包括我）觉得分段更整齐，又把它拆开」。
    """
    src = STORYBOARD.read_text(encoding="utf-8")
    assert 'id="rawPrompt"' in src, "找不到整段编辑的 textarea（id=rawPrompt）"
    assert "sd-prompt-sec" not in src, "提示词又被拆成逐段编辑了；用户要求整段可复制"
    assert "parts:" not in src, "提示词改成了按段写回；应走 text 整段写回"


def test_multifile_stage_is_not_editable_as_one_doc():
    """导演手册是目录（几十集），不能当成「一篇文档」编辑。

    这条守的是一个**会静默毁数据**的路径：
    `creation.read('director')` 把所有集用 `---` 拼成一篇（实测 598K 字符）；
    如果允许点它进编辑器，保存时 `creation.write()` 拿不到 name 会回落到「第01集.md」，
    于是第 1 集被整本覆盖 —— 而界面上一切正常，没有任何报错。
    """
    src = CREATE.read_text(encoding="utf-8")
    assert "container:" in src, "多文件阶段缺少 container 标记（会被当成单篇文档编辑）"
    assert "sd-docgroup-h" in src, "容器头没有渲染成不可点的分组标题"


def test_create_stage_list_comes_from_api():
    """阶段清单必须来自 `/api/create/state`，不能在前端写一份常量。

    旧实现对了一份 `const PIPE = [企划案, 资产库, 剧本, 导演手册, ...]`，
    引擎改阶段时前端会继续显示旧名字与旧顺序，而且看起来完全正常。
    """
    src = CREATE.read_text(encoding="utf-8")
    assert "const PIPE" not in src, "阶段清单又变成前端常量了；应以接口返回的 stages 为准"


def test_asset_tabs_are_only_real_material_kinds():
    """资产分类只能是「角色 / 场景 / 道具」三类真实素材。

    这条守的是 2026-11-10 的一次用户裁决：
      · `06-提示词/refs_h3` 是 `prepare_refs.py` 生成的**瘦身副本**
        （长边 ≤2048 / JPEG，只为绕开 H3 的 5760px 上限），原图在 `04-资产/*`。
        把派生文件做成并列分类，等于同一张图出现两次，且改原图不会让副本自动更新。
      · 「散图」是**没归位的图**，它是待办，不是类别。
    两者都降级成「诊断」，仍然能看（否则用户的图在界面上等于不存在），
    但不再出现在主分类里。谁把它们加回 TABS，就会红。
    """
    src = ASSETS.read_text(encoding="utf-8")
    block = src[src.index("const TABS = ["):]
    block = block[:block.index("];")]
    keys = set(re.findall(r"key:\s*'([a-z]+)'", block))
    assert keys == {"characters", "scenes", "props"}, (
        "资产主分类被改动了：%s\n"
        "参考图副本 / 未归位图片属于诊断入口（DIAG），不要放回 TABS。" % sorted(keys))


def test_character_has_single_master():
    """每个角色必须能确定**唯一**一个主形象，且选取规则是显式的。

    主形象是「这个角色长什么样」的基准，各套造型都是它的派生。
    不允许「随便拿一张图当主形象」—— 那会让主形象这个概念失去意义。
    """
    src = (ROOT / "web" / "core" / "characters.py").read_text(encoding="utf-8")
    assert '"master"' in src, "role 输出里没有 master 字段"
    assert '"master_missing"' in src, "没有记录「尚无主形象」的情况"
    # 选取顺序必须写死在代码里，不能依赖文件名排序碰运气
    assert '_first_img("base")' in src and '_first_img("turnaround")' in src, (
        "主形象的层别优先级不见了（应先 base，再 turnaround，最后退到任意有图的变体）")

