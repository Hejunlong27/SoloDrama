# 动效系统 · SoloDrama 2.0

## 1. 立场：动效服务于「状态变化」，不服务于「好看」

这是一个**干活**的工具。用户一天要点几百次。任何超过 200ms 的非必要动效，都是在偷用户的时间。

三类允许的动效：

| 类型 | 目的 | 上限 |
|---|---|---|
| **状态反馈** | 告诉用户「点到了 / 正在跑 / 完成了」 | 120ms |
| **空间关系** | 告诉用户「这个面板从哪来、回到哪去」 | 180–260ms |
| **注意力引导** | 告诉用户「结果在这里」（一次性） | 260ms，只播一次 |

禁止：视差滚动、连续背景动画、文字逐字浮现、加载超过 1s 还只有旋转圈的假进度。

## 2. 时长阶梯

| Token | 值 | 用途 |
|---|---|---|
| `--sd-dur-instant` | 60ms | 按下反馈（`transform: scale(.99)`） |
| `--sd-dur-fast` | 120ms | 悬停、聚焦、颜色过渡 |
| `--sd-dur-base` | 180ms | 抽屉滑入、模态淡入 |
| `--sd-dur-slow` | 260ms | 页面入场、卡片批量出现 |
| `--sd-dur-hold` | 420ms | 进度条完成收尾（从 100% 缩回） |

**为什么悬停压到 120ms**：鼠标划过一排按钮时，180ms 会让"跟手感"变成"拖沓感"。视觉上 120ms 已经能看出渐变。

## 3. 缓动曲线

```css
--sd-ease-standard: cubic-bezier(.2, .8, .2, 1);      /* 通用：快进慢出 */
--sd-ease-out:      cubic-bezier(.16, 1, .3, 1);      /* 入场：冲出来再稳住 */
--sd-ease-in:       cubic-bezier(.4, 0, 1, 1);        /* 退场：加速离开 */
--sd-ease-emphasis: cubic-bezier(.34, 1.56, .64, 1);  /* 仅用于完成勾选，回弹克制 */
```

不用 `ease-in-out`（默认曲线中段太平，观感"肉"）。回弹曲线**只允许**出现在「完成」这一个瞬间，别的地方用回弹会显得廉价。

## 4. 只动这两个属性

```css
/* 唯一允许的动画属性组合 */
transition: transform var(--sd-dur-fast) var(--sd-ease-standard),
            opacity   var(--sd-dur-fast) var(--sd-ease-standard);
```

**禁止 animate `width` / `height` / `top` / `left` / `margin` / `box-shadow`。** 它们触发布局或重绘，在 20+ 卡片的资产墙上会直接掉帧。

需要"高度展开"时：用 `grid-template-rows: 0fr → 1fr`（现代浏览器可动画），或用 `max-height` + `overflow: hidden` 且固定上限。

## 5. 具体规格

| 场景 | 规格 |
|---|---|
| 按钮按下 | `transform: scale(.985)`，60ms |
| 按钮悬停 | 背景色过渡 120ms；主按钮的指针流光 `--mx/--my` 跟随（保留现有实现） |
| 顶部进度条 | **延迟 200ms 才出现**（快请求不闪），完成后 420ms 收回 |
| 抽屉 | `translateX(16px) → 0` + 淡入，180ms；遮罩 120ms |
| 模态 | `scale(.98) → 1` + 淡入，180ms |
| 页面入场 | 内容区 `translateY(6px) → 0` + 淡入，260ms，**只在换模块时播**（同页刷新不重播） |
| Toast | 入场 180ms，停留 3.2s，退场 120ms |
| 骨架屏 | `opacity .45 ↔ .8` 呼吸，1.4s 循环（唯一允许的循环动画） |
| 实时状态点 | `box-shadow` 呼吸 2s 循环 —— 仅「正在执行」一处 |
| 完成勾选 | 路径 `stroke-dashoffset` 绘制，260ms + emphasis 曲线，只播一次 |

## 6. 减少动效（必须实现，不是可选项）

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .01ms !important;
    scroll-behavior: auto !important;
  }
}
```

现有 `app.css` 已有 4 处 `prefers-reduced-motion`，2.0 统一为上面这一条全局规则 + 保留必要的局部覆盖。

## 7. 加载状态的三档（比动效更重要）

| 时长 | 表现 | 理由 |
|---|---|---|
| < 200ms | **什么都不显示** | 闪一下比没有更烦（现有实现已如此，保留） |
| 200ms – 2s | 顶部进度条 + 骨架屏 | 给出「在动」的信号 |
| > 2s | 骨架屏 + 阶段文案（「正在读取分镜…」「正在跑 release_check…」） | 用户要知道卡在哪一步 |
| > 10s | 追加「可离开本页，任务在后台继续」 | 本项目多数操作是子进程，离开不影响 |

## 8. 验收

1. 打开系统「减少动态效果」后，所有动画停止但功能完整（不出现"要等动画结束才能点"）。
2. 切换页面时不出现布局跳动（CLS 目视为 0）。
3. 连续点同一按钮 10 次，不出现动画叠加/抖动。
4. 资产墙滚到 200 张图，滚动帧率不低于 50fps（Chrome Performance 面板抽查）。
