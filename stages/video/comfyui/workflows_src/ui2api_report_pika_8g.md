# 工作流转换报告

- 源文件：`D:\编程\SoloDrama\stages\video\comfyui\workflows_src\h3_pika_8g_raw.json`
- 界面节点：66 → API 节点：27
- 悬空引用：0

## 节点类型分布

| class_type | 数量 |
|---|---|
| `LoraLoaderModelOnly` | 2 |
| `VAELoader` | 2 |
| `LoadImage` | 2 |
| `LayerUtility: ImageScaleByAspectRatio V2` | 2 |
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
| `CLIPLoader` | 1 |
| `VHS_VideoCombine` | 1 |
| `PrimitiveFloat` | 1 |
| `ResolutionSelector` | 1 |
| `BasicGuider` | 1 |
| `ManualSigmas` | 1 |
| `PrimitiveStringMultiline` | 1 |
| `MiniMaxH3SigmaShift` | 1 |

## 未进入 API 的节点

| 节点 | 类型 | 原因 |
|---|---|---|
| 189 | `LoadImage` | bypass |
| 190 | `LoadImage` | bypass |
| 191 | `LoadImage` | bypass |
| 192 | `LoadImage` | bypass |
| 263 | `LayerUtility: ImageScaleByAspectRatio V2` | bypass |
| 264 | `LayerUtility: ImageScaleByAspectRatio V2` | bypass |
| 265 | `LayerUtility: ImageScaleByAspectRatio V2` | bypass |
| 267 | `LayerUtility: ImageScaleByAspectRatio V2` | bypass |
