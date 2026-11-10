# 设计系统总览 · SoloDrama 2.0

> 索引文件。细则在六份子文档，代码真源在 `web/ui/studio/css/tokens.css`。
> **冲突时以代码为准，并回头修文档。**

## 1. 文件分工

| 文件 | 管什么 |
|---|---|
| `brand-guidelines.md` | 品牌定位、视觉母题、语气与文案、评审清单 |
| `design-tokens.md` | Token 三层结构与命名规则、度量表、旧名映射、变更纪律 |
| `color-system.md` | 深浅两套色值 + 实测对比度、强调色纪律、状态色语义、迁移表 |
| `typography.md` | 字体栈、字阶、中文排版细则 |
| `motion-system.md` | 时长阶梯、缓动、只动 transform/opacity、三档加载态 |
| `component-guidelines.md` | 按钮/输入/卡片/表格/浮层/三态 + 三个新组件 |
| `ui-redesign-plan.md` | 逐页重设计方案（Phase 3–4 的执行蓝本） |

代码：

| 文件 | 内容 |
|---|---|
| `css/tokens.css` | 基色板 + 语义 Token（深/浅）+ 旧变量别名 |
| `css/app.css` | 既有组件（1255 行，结构不动） |
| `css/components-2.css` | 2.0 新组件，只新增类名 |
| `js/theme.js` | 三态主题解析与切换 |
| `design.html` | 视觉样板（真实组件，可切换主题） |
| `design-probe.html` | 对比度探针：打印每个组件在两种主题下的**真实计算色与对比度**，底部给 `LOW(<4.5)` 清单。改 Token 后必跑 |

## 2. Token 速查（最终值）

| 类别 | Token 与值 |
|---|---|
| 底色（深/浅） | `bg` `#101216`/`#F4F2ED`；`surface` `#171B22`/`#FFFFFF`；`surface-2` `#202630`/`#EFECE5`；`elevated` `#282F3A`/`#FFFFFF` |
| 描边 | `line` `#303844`/`#E2DED5`；`line-strong` `#3D4754`/`#CFC9BD` |
| 文字 | `text` `#F2F0EA`/`#20242B`；`text-2` `#A1A8B2`/`#5A6169`；`text-3` `#737D89`/`#6B727A`；`text-3-strong` `#8B949E`/`#5F666E` |
| 强调 | `accent` `#D6A76C`/`#9B7145`；`accent-strong` `#E8BE85`/`#8A6439`；`on-accent` `#14171C`/`#FFFFFF` |
| 辅助 | `teal` `#78A9A4`/`#3F7F79` |
| 媒体浮层（**不随主题变**） | `on-media` `#F2F0EA`；`media-veil` `rgba(8,10,13,.62)`；`media-scrim` 三段渐变 |
| 状态 | `ok` `#72B89A`/`#2F7A50`；`warn` `#E0A45D`/`#8A6320`；`danger` `#D87979`/`#A63D33`；`info` `#8FA3BF`/`#4A5C77` |
| 间距 | 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 80 / 96 |
| 圆角 | 3 / 6 / 8 / 10 / 12（浮层）/ 14（大工作区）/ pill |
| 动效 | 60 / 120 / 180 / 260 / 420ms；4 条缓动曲线 |

## 3. 组件注册表

| 组件 | 类名 | 来源 | 状态 |
|---|---|---|---|
| 按钮 | `.btn` `.primary` `.quiet` `.ghost.icon` | app.css | 在用 |
| 危险按钮 | `.btn.danger` | components-2 | **新增** |
| 输入 | `.input` `.search` | app.css | 在用 |
| 状态点 | `.dot.done/.doing/.todo` | app.css | 在用 |
| 徽标 | `.badge` `.warn` `.outline` | app.css | 在用 |
| 告警 | `.alert.info/.warn/.bad` | app.css | 在用 |
| 卡片 | `.card` `.card-b` | app.css | 在用 |
| 抽屉/模态/Toast | `.drawer` `.modal` `.toasts` | app.css | 在用 |
| 空/错/载 | `.empty` / `errorCard()` / `skeleton()` | app.css + ui.js | 在用 |
| 项目海报卡 | `.sd-poster*` | components-2 | **新增** |
| 阶段条 | `.sd-stages` `.sd-stage[data-state]` | components-2 | **新增** |
| 六段式提示词 | `.sd-prompt*` | components-2 | **新增** |
| 成本行 | `.sd-cost-row*` | components-2 | **新增** |
| 侧栏二级项 | `.nav-sub` `.nav-subitem` | components-2 | **新增** |
| 工作空间页签 | `.wsbar` `.ws-tab` `.ws-link` | components-2 | **新增** |
| 阶段矩阵 | `.sd-nodegrid` `.sd-nstage` `.sd-node[data-state]` | components-2 | **新增** |
| 下一步卡 | `.sd-next*` | components-2 | **新增** |
| 三栏工作台 | `.sd-shot3` `.sd-col` `.sd-col-{list,stage,side}` | components-2 | **新增** |
| 镜头行 | `.sd-row` `.sd-row-id` `.sd-row-mark` | components-2 | **新增** |
| 画布 | `.sd-stage` `.sd-video` `.sd-blank` `.sd-stage-meta` `.sd-kv-*` | components-2 | **新增** |
| 提示词整段编辑 | `.sd-p-text` `.sd-p-meta` `.sd-p-secs` `.sd-pchip` | components-2 | **新增** |
| 校验摘要 | `.sd-lintbar[.bad/.warn]` `.sd-lintbody` | components-2 | **新增** |
| 分段结构展示（**仅样板**） | `.sd-prompt-sec` `.sd-prompt-head` `.sd-prompt-edit` | components-2 | 产品页不用，见 CSS 注释 |
| 创作三栏 | `.sd-cw3` `.sd-col-{docs,ed,ctx}` | components-2 | **新增** |
| 文档树 | `.sd-docitem[.on/.child]` `.sd-docgroup` `.sd-docgroup-h` | components-2 | **新增** |
| 文档编辑器 | `.sd-edhead` `.sd-edtools` `.sd-edtext` `.sd-edempty` `.sd-edpath` | components-2 | **新增** |
| 视图切换 | `.sd-seg` `.sd-segbtn[.on]` | components-2 | **新增** |
| Markdown 预览 | `.sd-md` `.sd-md-tw` `.sd-md-code` | components-2 | **新增**（受限子集） |
| 上下文卡 | `.sd-cwcard` `.sd-fld` `.sd-note` `.sd-kvrow` `.sd-ideafields` | components-2 | **新增** |
| 角色档案 | `.sd-roster` `.sd-char` `.sd-char-h/-name/-role/-anchor` | components-2 | **新增** |
| 变体分组 | `.sd-cv-group` `.sd-cv-gh` `.sd-cv-row` `.sd-cv` `.sd-cv-img` | components-2 | **新增** |
| 变体操作条 | `.sd-cstage-bar`（含「看提示词 / 重出这一张」） | components-2 | **新增** |
| 版本对照 | `.modal-wide` `.sd-vd-*` | components-2 | **新增** |

## 4. 主题机制

```html
<html data-theme="dark" data-theme-mode="auto">
```

- 三态：`auto`（跟随系统）/ `dark` / `light`，存 `localStorage.sd-theme`。
- 首帧由 `<head>` 内联脚本写入 `data-theme`（防闪白），`js/theme.js` 接管后续切换。
- 浅色只覆盖第 2 层语义 Token，第 1 层基色板与第 3 层别名不动。

## 5. 加一个新 Token 的三步

1. 在 `tokens.css` 第 1 层加颜色（如果需要），第 2 层加语义 Token（深浅各一处）。
2. 在 `design-tokens.md` §3 登记一行，注明用途。
3. 若涉及颜色，重跑对比度脚本，把实测值写回 `color-system.md`。

**禁止**：在组件里写字面色值；跳过登记直接加变量；为每个透明度单独开 Token（用 `color-mix`）。

## 6. 当前视觉债务（下一步）

| # | 项 | 影响 |
|---|---|---|
| V1 | ~~`app.css` 72 处硬编码色值~~ | **已清零**（生效中仅剩 1 处视频黑边，故意保留） |
| V2 | 顶栏/侧栏视觉仍是旧观感 | 首页改版时一并处理 |
| V3 | 图标仅 16/20 两档，缺 24 | 首页大区块需要 |
| V4 | 移动端断点未在改版后重测 | 需 Playwright 复核 |

## 7. 验收（每次交付自检）

1. 深浅两套单独看都成立，不是「也能看」。
2. 正文/次要/必读元信息对比度 ≥ 4.5:1（脚本实测）。
3. 同屏金色元素 ≤ 3 处。
4. 切换主题不闪白、不重排。
5. 所有可交互元素有可见焦点。
