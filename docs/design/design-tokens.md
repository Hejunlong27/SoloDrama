# 设计 Token 规范 · SoloDrama 2.0

> **真源文件：`web/ui/studio/css/tokens.css`。** 本文是它的说明书，不是它的替代品。
> 冲突时以 `tokens.css` 为准，并回头修本文。

## 1. 三层结构（这是本次重构的核心机制）

```
第 1 层  基色板（raw）      --sd-ink-900 … 只在此定义具体色值
第 2 层  语义 Token（semantic）--sd-bg / --sd-text-2 / --sd-accent … 组件只准用这一层
第 3 层  旧变量别名（legacy）  --bg-app / --txt-2 / --fs-13 … 指向第 2 层，保 22 视图不崩
```

规则：

- 组件 CSS **禁止**直接使用基色板（`--sd-ink-900`）与字面色值。
- 浅色主题**只覆盖第 2 层**，第 1 层不动（基色板是"颜料"，语义层是"用哪支颜料"）。
- 第 3 层只减不增：新代码不写旧名。

## 2. 命名规则

```
--sd-<类别>-<语义>[-<变体>]
```

| 类别 | 例 | 说明 |
|---|---|---|
| `bg` `surface` `elevated` `inset` | `--sd-surface-2` | 底色层次 |
| `line` | `--sd-line-strong` | 描边 |
| `text` | `--sd-text-2` | 文字 |
| `accent` `teal` `ok` `warn` `danger` `info` | `--sd-accent-tint` | 色彩语义 |
| `font` `fs` `lh` | `--sd-fs-h2` | 排版 |
| `space` `radius` `shadow` `dur` `ease` | `--sd-space-4` | 度量与动效 |
| `nav-w` `top-h` `row-h` | `--sd-nav-w` | 布局常量 |

变体后缀固定四个：`-strong`（更强）、`-tint`（半透明底）、`-line`（半透明描边）、`-fill`（装饰填充）。

## 3. 度量 Token（完整表）

### 3.1 间距（4px 基数）

| Token | 值 | 用途 |
|---|---|---|
| `--sd-space-1` | 4px | 图标与文字 |
| `--sd-space-2` | 8px | 紧凑元素间 |
| `--sd-space-3` | 12px | 表单项 / 组件间 |
| `--sd-space-4` | 16px | 卡片内边距 |
| `--sd-space-5` | 24px | 模块间距 |
| `--sd-space-6` | 32px | 区域间距 / 页头与内容 |
| `--sd-space-7` | 48px | 大区块间距 |
| `--sd-space-8` | 64px | 大版面留白 |
| `--sd-space-9` | 80px | 首屏留白（宽屏） |
| `--sd-space-10` | 96px | 极端留白（少用） |

旧 `--sp-1…--sp-10`（2/4/6/8/12/16/20/24/32/40）保留为别名，**不删除**：`app.css` 全篇在用，且它们不是 4 的倍数，直接改值会让现有版面错位。

### 3.2 圆角

| Token | 值 | 用途 |
|---|---|---|
| `--sd-radius-xs` | 3px | 徽标、状态点容器 |
| `--sd-radius-sm` | 6px | 小按钮 |
| `--sd-radius-md` | 8px | 输入框、表格行 |
| `--sd-radius-lg` | 10px | 普通容器、卡片 |
| `--sd-radius-overlay` | 12px | 浮层：抽屉、模态、下拉 |
| `--sd-radius-xl` | 14px | 大型工作区面板 |
| `--sd-radius-pill` | 999px | 标签、计数气泡 |

**上限 14px，且只有「大型工作区面板」用得到。** 短剧素材是矩形画幅，圆角越大越像社交 App；卡片级一律 10px。

### 3.3 阴影（只给浮层）

| Token | 深色 | 浅色 |
|---|---|---|
| `--sd-shadow-1` | `0 2px 8px rgba(0,0,0,.28)` | `0 1px 3px rgba(20,24,32,.08)` |
| `--sd-shadow-2` | `0 6px 20px rgba(0,0,0,.38)` | `0 4px 16px rgba(20,24,32,.10)` |
| `--sd-shadow-3` | `0 18px 48px rgba(0,0,0,.55)` | `0 12px 40px rgba(20,24,32,.14)` |
| `--sd-ring-focus` | `0 0 0 2px var(--sd-accent-line)` | 同 |

卡片**不用阴影**（深色下像脏点，浅色下靠描边）。阴影只出现在抽屉/模态/下拉/toast。

### 3.4 布局常量

| Token | 值 |
|---|---|
| `--sd-nav-w` | 252px |
| `--sd-nav-w-collapsed` | 64px |
| `--sd-top-h` | 60px |
| `--sd-row-h` | 44px |
| `--sd-content-max` | 1440px |

### 3.5 状态色的两档取值

每个状态语义有**两个** Token：图形档与文字档。

| 图形档（描边/圆点/实心块，3:1） | 文字档（淡底上的字，4.5:1） |
|---|---|
| `--sd-ok` `--sd-teal` `--sd-warn` `--sd-danger` `--sd-info` | `--sd-ok-ink` `--sd-teal-ink` `--sd-warn-ink` `--sd-danger-ink` `--sd-info-ink` |

深色主题两档相同；浅色主题文字档压深。**用错档不会报错，只会不可读**，因此：
凡「有背景色的块里写字」，一律 `-ink`。实测对照见 `color-system.md` §5.1。

## 4. 兼容层（第 3 层）映射表

`tokens.css` 里必须存在下列别名，否则 22 个视图与 1255 行 `app.css` 立刻失效：

| 旧变量 | 指向 |
|---|---|
| `--bg-app` | `--sd-bg` |
| `--bg-panel` | `--sd-surface` |
| `--bg-card` | `--sd-surface-2` |
| `--bg-hover` | `--sd-hover` |
| `--bg-active` | `--sd-active` |
| `--bg-inset` | `--sd-inset` |
| `--bg-overlay` | `--sd-overlay` |
| `--line` / `--line-strong` | `--sd-line` / `--sd-line-strong` |
| `--txt` / `--txt-2` / `--txt-3` / `--txt-disabled` | `--sd-text` / `-2` / `-3` / `-disabled` |
| `--accent` / `--accent-strong` / `--accent-tint` / `--accent-line` | `--sd-accent` / `-strong` / `-tint` / `-line` |
| `--live` / `--live-tint` | `--sd-teal` / `--sd-teal-tint` |
| `--ok` / `--danger` / `--info`（+`-tint`） | 同名 `--sd-*` |
| `--create`（蓝紫，创作链） | **废弃**，指向 `--sd-teal`（见下 §4.1） |
| `--font-ui` / `--font-mono` | `--sd-font-ui` / `--sd-font-mono` |
| `--fs-11…--fs-26` | 见 §4.2 |
| `--sp-1…--sp-10` | 保留原值（非 4 倍数，不动） |
| `--r-xs…--r-xl` | `--sd-radius-*` |
| `--sh-2` / `--sh-3` / `--sh-inset` | `--sd-shadow-2` / `-3` / `--sd-inset-line` |
| `--dur-fast` / `--dur-1..3` / `--ease*` | `--sd-dur-*` / `--sd-ease-*` |
| `--nav-w` / `--nav-w-collapsed` / `--top-h` / `--row-h` | `--sd-*` |

### 4.1 为什么 `--create` 蓝紫被废弃

审计发现同屏存在三种彩色（陶土按钮 + 琥珀强调 + 蓝紫创作链），品牌识别被稀释。2.0 只保留金（人做的决定与代价）与蓝绿（数据与进度）两种彩色。

`--create` 保留变量名（`app.css` 有引用）但指向 `--sd-teal`，语义从"创作链专色"改为"数据/进度"。若后续发现创作链仍需要视觉区分，做法是**用版式区分**（编辑式排版、衬线标题），不是再加一个颜色。

### 4.2 字号旧名 → 新名

| 旧名 | 旧值 | 新 Token |
|---|---|---|
| `--fs-11` | 12px | `--sd-fs-caption` |
| `--fs-12` | 13px | `--sd-fs-sm` |
| `--fs-13` | 15px | `--sd-fs-body` |
| `--fs-14` | 16px | `--sd-fs-h3` |
| `--fs-16` | 18px | `--sd-fs-h2` |
| `--fs-20` | 24px | `--sd-fs-h1` |
| `--fs-26` | 32px | `--sd-fs-display` |

注意旧名里的数字**不等于像素值**（历史遗留），映射按上表，不按数字猜。

## 5. 主题切换

```css
:root { /* 深色语义 Token */ }
[data-theme="light"] { /* 只覆盖第 2 层语义 Token */ }
```

- `<html data-theme>` 由 `js/theme.js` 写入；`auto` 时按 `matchMedia('(prefers-color-scheme: light)')` 解析。
- `<head>` 内联 3 行脚本，在 CSS 之前设置 `data-theme`，**防止首帧闪白**。
- `color-scheme: dark|light` 与主题同步声明。

## 6. 变更纪律

1. **改色只改第 1 层，改语义只改第 2 层。** 两者混改是"改了不生效"的头号原因。
2. 新增 Token 必须在本文 §3 登记；未登记的不许合并。
3. 删除 Token 前先全仓 `grep`，并按 §4 保留一个版本的别名。
4. 任何颜色改动后**重跑对比度脚本**，把新数值写回 `color-system.md`。
