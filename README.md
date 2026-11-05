<p align="center">
  <img src="web/ui/studio/img/logo.svg" width="84" height="84" alt="SoloDrama">
</p>

# SoloDrama

**把一句话点子做成可发布竖屏短剧的流水线。**

创作交给可插拔的题材模板，执行交给本机或云端的 ComfyUI，两者之间只隔一份文件契约 ——
所以换一套题材模板，引擎一行不用改。

---

## 四层结构

```mermaid
flowchart TB
    subgraph L1["① 创作层 · 人 × LLM"]
        A1["Skill 模板<br/>skills.json + skills/&lt;id&gt;.md"]
        A2["企划案<br/>00-创作/01-企划案.md"]
        A3["资产库<br/>00-创作/02-资产库.md"]
        A4["分集剧本<br/>00-创作/03-分集剧本.md"]
        A5["导演手册<br/>00-创作/04-导演手册/第NN集.md"]
    end

    subgraph L2["② 契约层 · 机械转换"]
        B1["md2pack<br/>（convert.apply）"]
        B2["pack/<br/>assets/*.json + episodes/*.json"]
    end

    subgraph L3["③ 引擎层 · 只认契约"]
        C1["pack_import<br/>校验 + 落盘"]
        C2["06-提示词/&lt;ep&gt;/<br/>五文件"]
        C3["资产出图"]
        C4["分镜图"]
        C5["分镜出片"]
        C6["后期与发行"]
    end

    subgraph L4["④ 控制面 · Studio"]
        D1["画布 / 流水线"]
        D2["通道与预检"]
        D3["作业与台账"]
    end

    A1 --> A2 --> A3 --> A4 --> A5
    A3 --> B1
    A5 --> B1
    B1 --> B2 --> C1 --> C2
    C2 --> C3 --> C4 --> C5 --> C6
    D1 -.读取磁盘状态.-> C2
    D2 -.读模型确认单.-> C3
    D3 -.启动子进程.-> C5
```

创作只写 markdown，引擎只读 JSON。层与层之间传文件，不传内存状态。

## 全景

```mermaid
flowchart LR
    subgraph C["创作"]
        N1["1 创作模板"]
        N2["2 灵感"]
        N3["3 企划案"]
        N4["4 资产库"]
        N5["5 剧本"]
        N6["6 导演手册"]
    end
    subgraph E["契约与引擎"]
        N7["7 转换"]
        N8["8 制作包"]
        N9["9 导入"]
        N10["10 绑定参考图"]
        N11["11 生成端门禁"]
        N12["12 资产出图"]
        N13["13 分镜图"]
        N14["14 出片解析"]
        N15["15 批量出片"]
        N16["16 出片审计"]
    end
    subgraph P["后期"]
        N17["17 母版"]
        N18["18 放大"]
        N19["19 字幕"]
        N20["20 合规"]
        N21["21 发行导出"]
    end

    N1 --> N3
    N2 --> N3
    N3 --> N4 --> N6
    N3 --> N5 --> N6
    N4 --> N7
    N6 --> N7
    N7 --> N8 --> N9 --> N10 --> N11
    N10 --> N12 --> N13
    N13 --> N14 --> N15 --> N16
    N16 --> N17 --> N18 --> N19 --> N20 --> N21
```

## 生成通道

```mermaid
flowchart TD
    S["要出图 / 出片"] --> Q1{"模型确认单<br/>model-plan.json<br/>有 choice 吗"}
    Q1 -- 无 --> Q2["拒绝执行<br/>先跑 models set（G0）"]
    Q1 -- 有 --> Q3{"choice 是什么"}
    Q3 -- local_comfyui --> L1{"预检：地址 + 节点 + 模型 + 必需输入"}
    Q3 -- cloud_comfyui --> C0{"地址是 loopback 吗"}
    Q3 -- runninghub --> R1{"Key + 工作流 ID 齐吗"}
    C0 -- 是 --> CX["直接退出<br/>（云端通道不许打本机）"]
    C0 -- 否 --> C1{"守卫：域名在受信名单？"}
    C1 -- 否 --> CX2["拒绝<br/>不因上云就放宽 ALLOW_REMOTE"]
    C1 -- 是 --> L1
    L1 -- 不通过 --> F["点名缺哪个文件 / 哪个节点<br/>并给可替代工作流"]
    L1 -- 通过 --> GO["提交"]
    R1 -- 不齐 --> F
    R1 -- 齐 --> GO
    GO --> B{"billing 是 PAID 吗"}
    B -- 是 --> B1{"界面带 confirm=true"}
    B1 -- 否 --> B2["428 → 必须先看报价"]
    B1 -- 是 --> RUN["真跑"]
    B -- 否 --> RUN
```

三条路，同一个执行器、同一套预检。通道只从「模型确认单」读一次，界面与命令行不会各有各的答案。

---

## 效果

![资产卡：4 个角色各 4 视图 + 场景](docs/showcase/01-assets.jpg)

*4 个角色各 4 视图。四视图是后续所有镜头的共同锚点 —— 换集不换脸靠它。*

![同批分镜的 3 段原帧](docs/showcase/02-shots.jpg)

*同批分镜的 3 段原帧（672×1216）：同一件大衣、同一场雨、同一张脸。*

![Studio 工作台](docs/showcase/03-studio.png)

*Studio：项目、待办、通道状态一屏可见。每个数字都来自引擎的真实产物。*

---

## License

[Apache-2.0](LICENSE)
