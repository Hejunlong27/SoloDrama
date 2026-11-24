# 流水线出片模式

这是基于当前 SoloDrama 项目素材的轻量流水线：

1. `inspect` 扫描工作区中的视频素材。
2. 准备逐镜配音路径或已有的 `solodrama-voice-rough-cut` 粗剪清单。
3. `renderRoughCut` 读取清单并合成。
4. 或直接用 `render` 指定有序镜头列表。

合成时会统一分辨率、帧率和像素格式；每个镜头先等比缩放并补黑边，再按顺序拼接。项目画幅、帧率和 BGM 默认继承 `.solodrama/project.json`。

音频模式支持镜头原声（`clip`）、旁白替换（`narration`）、原声与旁白混合（`mix`）和静音（`none`）。还可以加入封面片头、BGM，并把 SRT/ASS 字幕烧录进成片。输出 MP4 到工作区，源视频不会被修改。
