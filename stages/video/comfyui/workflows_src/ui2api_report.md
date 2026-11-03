# 工作流转换报告

- 源文件：`D:\文件备份\谷歌下载文件\【Minimax+H3】无损融合单采【满血API画布级工作流】 (1).json`
- 界面节点：64 → API 节点：30
- 悬空引用：0

## 节点类型分布

| class_type | 数量 |
|---|---|
| `LoadImage` | 6 |
| `LoraLoaderModelOnly` | 2 |
| `VAELoader` | 2 |
| `SamplerCustomAdvanced` | 1 |
| `KSamplerSelect` | 1 |
| `RandomNoise` | 1 |
| `忽略多组孤海` | 1 |
| `ComfyMathExpression` | 1 |
| `VAEDecodeAudio` | 1 |
| `VAEDecode` | 1 |
| `ModelAttentionBackend` | 1 |
| `BlockSparseAttention` | 1 |
| `MiniMaxH3ReferenceToVideo` | 1 |
| `UNETLoader` | 1 |
| `ModelPreviewOverrideKJ` | 1 |
| `CLIPLoader` | 1 |
| `VHS_VideoCombine` | 1 |
| `PrimitiveFloat` | 1 |
| `ResolutionSelector` | 1 |
| `BasicScheduler` | 1 |
| `BasicGuider` | 1 |
| `ManualSigmas` | 1 |
| `PrimitiveStringMultiline` | 1 |

## 未进入 API 的节点

| 节点 | 类型 | 原因 |
|---|---|---|
| 166 | `LoraLoaderModelOnly` | bypass |

## 转换备注

- SetNode(时长) 没有输入，引用 357 视为缺失
- #136.length 连线解析失败，已回落到 widget 值 1008
- SetNode(时长) 没有输入，引用 368 视为缺失
- #150.preview_frames 连线解析失败，已回落到 widget 值 48
