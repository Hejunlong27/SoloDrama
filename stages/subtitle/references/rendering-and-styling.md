# 渲染与样式（ASS / 字体 / 位置 / 断行 / 多语言）

> 全部参数都在 `<工作区>/video-pipeline/config.subtitle.json`，**改配置不改代码**。
> 模板：`assets/config.subtitle.example.json`

---

## 一、ASS 文件结构（本项目实测可用）

```
[Script Info]
ScriptType: v4.00+
PlayResX: 1440            ← 必须等于视频宽度
PlayResY: 832             ← 必须等于视频高度
WrapStyle: 2              ← 2 = 不自动换行（由我们自己的断行算法控制，关键）
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,56,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,72,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:02.32,0:00:05.76,Default,,0,0,0,,好啊！好你个陆鸣！
```

**要点**：
- `WrapStyle: 2` —— 让 libass **不要自动折行**，换行完全由我们用 `\N` 控制
- `PlayResX/Y` 必须等于视频分辨率 ⇒ 那么 `Fontsize` 就是**像素值**，`MarginV` 也是像素
- 颜色是 `&HAABBGGRR`（**BGR 顺序**，与 RGB 相反，最容易写错）
- `Alignment: 2` = 底部居中；`BorderStyle: 1` = 描边+阴影
- 多行用 `\N` 连接；文本里的 `{` `}` 必须替换掉（会被当成 ASS 覆写块）

### 1.1 ★ 纵向落点：视觉中心 6:4（V0.7.6 起，移植自 vidpure）

默认不再靠样式的 `MarginV` 定位，而是**逐条**写覆写块：

```
Dialogue: 0,0:00:03.22,0:00:06.36,Default,,0,0,0,,{\an5\pos(540,1152)}Eran las once y veinte.\NLlovía.
```

- `anchor_top = 0.6` ⇒ 文字块**中心**落在 `0.6 × 画布高`，即**距顶 : 距底 = 6:4**；
  1080×1920 上是 `y = 1152`，文字块下沿距底 696px（安全区下限 400px）
- `\an5` = 文字块中心为锚点 ⇒ **一行与两行字幕的中心同线**。用 `Alignment=2`（底对齐）时，
  折行会让整块往下长、上半部分空出来，观感上"字幕在跳" —— 这是换口径的直接原因
- **按比例不按像素**：固定 400px 在 1080×1920 上占 20.8% 高，在 2176×3840 上只占 10.4%，
  同一部剧出 1080P 与 2K 两版字幕位置就不一样了；6:4 在任何画布下视觉重心一致
- 想换位置：`placement.anchor_top` 调 `0.55`（更靠中）/ `0.62–0.66`（更靠下，避开胸口）
- 想回旧口径：`"placement": {"anchor": "pixel"}`，纵向位置改由 `margin_v_pct` 与
  `safe_area.min_bottom_px` 取大者决定（`qa_safe_area` 会按这个模式改判）
- `anchor` 只影响**纵向**；横向仍由 `margin_lr_pct` 与 70% 安全区共同决定

---

## 二、样式参数（改这几个就够）

| 配置键 | 当前值 | 换算（1440×832） | 含义 |
|---|---|---|---|
| `font` | `Microsoft YaHei` | — | 必须是**内核 family name** |
| `font_size_pct` | `6.7` | **56 px** | 按画面高度百分比 |
| `placement.anchor` / `anchor_top` | `ratio` / `0.6` | 中心 y=499 | 视觉中心 6:4（见 §1.1） |
| `margin_v_pct` | `8.7` | **72 px** | 仅 `anchor=pixel` 时生效：距画面底部 |
| `margin_lr_pct` | `4.2` | **60 px** | 左右边距 |
| `outline` / `shadow` | `3` / `1` | — | 黑边 / 阴影像素 |
| `max_line_chars` | `16` | — | 每行上限（中文按**字符**） |
| `line_tolerance_chars` | `3` | — | 标点断行的容差（见第四节） |
| `max_cue_chars` | `32` | — | 一条字幕最多两行 |
| `min_duration_s` / `max_duration_s` | `0.8` / `6.0` | — | 单屏时长 |
| `cps_ok` / `cps_hard_max` | `[2.0, 8.5]` / `12.0` | — | 语速合理区间（**发音字数/秒**） |

**改完直接重跑**：`--stage ass` 可先只出 ASS 不渲染。

---

## 三、字体（实测覆盖表，务必先查）

逐个字体验过字符覆盖（`C:\Windows\Fonts`）：

| 字体 | 西语 `áéíóúüñÑ¿¡ÁÉÍÓÚÜªº` | 中文 |
|---|---|---|
| **`msyh.ttc` 微软雅黑** | ✅ 全覆盖 | ✅ 全覆盖 |
| `msyhbd.ttc` 粗雅黑 | ✅ | ✅ |
| **`simhei.ttf` 黑体** | 🔴 **缺 `ñ Ñ ¿ ¡ Á É Í Ó Ú Ü ª º`** | ✅ |
| `simsun.ttc` / `Deng.ttf` / `msjh.ttc` | ✅ | ✅ |
| arial / segoeui / calibri / times / verdana / tahoma / georgia / consola / cambria | ✅ | 🔴 全缺（纯拉丁字体无 CJK） |

**⇒ 三条结论**：
1. 中文字幕可以用**微软雅黑一个字体通吃中西**（默认选项）
2. **西语绝不能用 `simhei`** ⇒ 会出豆腐块
3. 西语观感更好的是另配拉丁字体（Inter/Roboto 类）；但 libass **不支持字体 fallback 列表**，
   双语同屏必须用**两个 Style + 两个 Dialogue 事件**，不要指望自动回退

---

## 四、断行规则（中/西是两套算法）

| 语言 | `wrap` | 算法 | 禁止 |
|---|---|---|---|
| **中文** | `char` | 按**字符数**断；**优先在标点处断**（`，。！？；：…—、`）；`\N` 连接 | 行首标点；把词切开 |
| **西语** | `word` | 按**单词边界**断；≤42 字符/行 | **切断单词**（哪怕只差 1 个字符） |

### 中文断行的关键：容差

中文没有空格，**任何按字符硬切都可能切开词**。实测踩到：
```
❌ 老娘就说你活蹦乱跳的怎么可能得癌 / 症！把我那两万块吐出来！
✅ 老娘就说你活蹦乱跳的怎么可能得癌症！ / 把我那两万块吐出来！
```

**做法**：找离中点最近、且**断点两侧都不超过 `max_line_chars + line_tolerance_chars`** 的标点。
宁可行长多一点（+3 字），也不要把词切开。

### 整句过长

超过 `max_cue_chars`（中文 32 字）时**按标点拆成多条字幕**，时间按**字数比例**分配。

---

## 五、多语言（中文 / 西班牙语）

**关键认知：西语是"原生立项"，不是"把中文翻过去"** —— 所以要做的是**语言无关**，不是"支持翻译"。

| 环节 | 中文剧 | 西语剧 | 改代码吗 |
|---|---|---|---|
| 台词真源 | `<d>[中文] …</d>` | `<d>[Español] …</d>` | ❌ 只换语言标签 |
| **解析器** | 匹配 `[语言]` 标签 | 同上 | ❌ **但不得硬编码 `[中文]`** |
| **时间轴推导** | 镜头切点 + 段首 | **完全同一套逻辑** | ❌ **语言无关** ✅ |
| 断行 | 按字符 + 标点优先 | 按**单词边界** | ✅ 配置分派 |
| 字体 | 微软雅黑 | 拉丁字体（禁用 simhei） | ✅ 配置 |
| 预算校验 | ≤16 字/行、CPS ≤9 | ≤42 字符/行、CPS ≤17 | ✅ 配置 |
| 对齐器语言码 | `cmn` | `spa` | ✅ 配置 `aligner_language_code` |

**字符预算（Netflix 口径，`推断`）**：中文 16 字/行、CPS ≤9；西语 42 字符/行、CPS ≤17。
两行字符预算比 = 84 ÷ 32 = **2.625 倍** —— 这条只在"把同一部剧译成多语言"时才有意义（本期不做）。

**RTL 预留**：本机 ffmpeg 已 `--enable-libfribidi`，将来加阿拉伯语无需换工具链，只需加一份语言配置。

---

## 六、软字幕 vs 硬烧录

| 方式 | 命令要点 | 优点 | 缺点 |
|---|---|---|---|
| **硬烧录**（默认，交付用） | `-vf "subtitles=filename='…'"` + `-c:v libx264 -crf 18 -preset medium` | 任何播放器都能看 | **必须重编**（每集 30–60 秒） |
| **软字幕**（`--soft`） | `-c copy -c:s mov_text` | **零重编**、可开关、可后改 | 部分播放器/短剧平台不认 |

---

## 七、路径转义（所有 ffmpeg 滤镜通用，最容易卡住的一步）

```python
def esc_filter_path(p):
    s = str(p).replace("\\", "/")
    s = re.sub(r"^([A-Za-z]):", r"\1\\:", s)   # 转义冒号
    return "filename='%s'" % s                  # 整值加单引号
```

实测四种写法的结果：

```
[FAIL] subtitles=C:/.../t.ass                裸绝对路径 → Unable to parse "original_size"
[OK]   subtitles=filename='C\:/.../t.ass'    转义冒号+单引号 ← 唯一可行
[FAIL] subtitles=C\:/.../t.ass               只转义冒号 → 同样报 original_size
[FAIL] subtitles=../asstest/t.ass            相对路径 → 按进程 cwd 解析，找不到
```

**注意**：`ass=` 滤镜更糟，会把路径当成 `original_size`。用 `subtitles=filename='…'`。
