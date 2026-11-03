# 内置题材模板（创作 Skill）

这里放的是**随仓库分发的项目模板**：新建项目时可以直接选一个或多个，装进
`<工作区>/skills/`，之后「创作」页生成企划案 / 资产库 / 剧本 / 导演手册时按它的叙事结构走。

- 来源：用户提供的 `ai-manju-skills-main`（21 个题材，2026-11-02 版），原样复制，**未改一字**。
- 类型：**纯数据**（Markdown 提示词）。装载 = 复制 + 登记；不 import、不执行、不联网。
- 画风：这些模板正文里通常写死了「现代精致国漫」一类的风格词。
  按项目纪律，**画风由 `<工作区>/project.json` 的 style_lock 决定，模板只管叙事套路**；
  `web/core/skills.py::compose_prompt()` 会把 style_lock 插在指令最前面并要求模型忽略冲突描述。

## 目录约定

```
stages/creation/skills/<id>/SKILL.md
```

`<id>` 就是模板 id（`tianchong-manju` 等）。frontmatter 里的 `name` / `description` 会被
「Skill 中心」读出来展示；正文是给模型看的完整工作说明。

## 调用范围（为什么它进不了出片链路）

Skill 只能**写创作层的 Markdown**（`00-创作/`、`03-剧本/`、`05-分镜/`）。
引擎的输入契约是 `06-提示词/<ep>/` 下五个 JSON，**只能由 `stages/import/pack_import.py`
从制作包生成**。这条边界是有意为之：出片稳定性靠的是「提示词逐字搬运 + 契约校验」，
让模型直接改 `06-提示词/` 等于把随机性塞进计费链路。

详见 `docs/CREATION.md` 与 `web/core/skills.py` 顶部的「画风归属」。
