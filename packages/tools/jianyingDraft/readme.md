# 剪映草稿

将分镜视频、配音、字幕、封面和 BGM 整理为剪映草稿目录：

- `mode: episode`：每一集生成一份独立草稿。
- `mode: season`：整季所有镜头按顺序放进一份草稿。
- `createDraftFromRoughCut`：读取 `solodrama-voice-rough-cut` 粗剪清单，按镜头和逐镜配音生成一份草稿。
- 项目画布尺寸、帧率、封面、字幕和 BGM 默认继承 `.solodrama/project.json`。
- `clip.subtitlePath` 支持 SRT 字幕轨；`clip.coverPath` 生成首帧封面图轨；可添加旁白和 BGM 音轨。

草稿写入工作区 `.solodrama/jianyingDrafts`，包含 `draft_content.json`、`draft_meta_info.json` 和导入说明。剪映版本较多，最终兼容性需要在你的剪映版本中实际导入验证。
