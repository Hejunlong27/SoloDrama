# -*- coding: utf-8 -*-
"""SoloDrama 控制台后端（Web 层）。

子模块：
    paths     —— 路径与运行时常量（唯一真源）
    runner    —— 白名单命令执行器（唯一的「写」通道）
    reader    —— 只读聚合器（整剧一屏）
    jobs      —— 作业队列 / 资源锁 / 事件流 / 审计
    commands  —— 命令目录（W6 完整版，含 Agent 提示词）
"""
