"""cloud/ —— 云端 ComfyUI 镜像的编排层（建实例 / 等就绪 / 收产物 / 停计费 / 记成本）

为什么单独一个包，而不是塞进 stages/
------------------------------------
`stages/` 是**生产流水线**：剧本 → 资产 → 分镜 → 出片 → 剪辑 → 发行，每一步都是
「对工作区里的文件做确定性转换」。而云端实例是**资源**：它会自己消失（欠费/回收）、
会按分钟烧钱、要先建后停。两类东西的生命周期完全不同，混在一起会让每个环节都
背上「实例还开着吗」的包袱。

所以这里的定位是「引擎外挂的控制面」：

    python -m cloud up       建实例 → 等 ComfyUI 就绪 → 打印可直接用的 COMFYUI_URL
    python -m cloud status   查状态（含「有没有在烧钱」）
    python -m cloud down     停实例（停止 GPU 计费）
    python -m cloud probe    就绪三查（版本 / 节点 / 模型）
    python -m cloud cost     当日与累计成本台账
    python -m cloud reap     回收空闲实例（忘停的兜底）

出片侧不需要记这些命令：`drama video run --engine cloud` 默认
`--cloud-lifecycle auto` —— 任务要跑才开机、跑完就关（`cloud/session.py`）。

四条硬约束（文档 §5.3）
------------------------
1. **幂等**：同名实例在跑就复用，不重复创建 —— 脚本重跑不该多烧一份钱。
2. **失败必停**：建成功但等不到就绪，必须自动 stop，不能留一台空转的机器。
3. **凭据不落盘**：Token / SSH 密码只从环境变量读（`XGY_TOKEN` / `XGY_SSH_PASSWORD`），
   不进 settings.json、不进台账、不进日志（打印一律 `mask_key`）。
4. **成本护栏**：建实例前查当日累计 GPU 时长，超过上限直接拒绝。

⚠ 上游端点未核对
----------------
仙宫云开放 API 的**具体端点名与参数**尚未核对（文档附录 C 已标注待确认）。
本包因此分成两层：

  · `XgyApi`（`provisioner.py`）—— 真正的 HTTP 适配器，端点与字段映射**全部来自配置**
    （`settings.json` 的 `cloud.endpoints` / `cloud.field_map`）。没配就明确报
    「待配置 + 该填哪几个键」，而不是猜一个路径去 404。
  · `Provisioner` —— 生命周期语义（幂等 / 失败必停 / 护栏），与上游无关，可被任何
    provider 复用；测试用一个本地假 API 驱动它。

换句话说：**语义现在就能测、能用；端点填上才算真正打通**。
"""

from .config import effective, hydrate_env, settings_path          # noqa: F401
from .ledger import record, day_hours, read_all                    # noqa: F401
from .health import probe, MIN_COMFY_VERSION                       # noqa: F401
from .provisioner import Instance, Provisioner, CloudNotConfigured, CostGuard  # noqa: F401
from .session import CloudNotReady, Lease, lease_for                     # noqa: F401

__all__ = [
    "effective", "hydrate_env", "settings_path",
    "record", "day_hours", "read_all",
    "probe", "MIN_COMFY_VERSION",
    "Instance", "Provisioner", "CloudNotConfigured", "CostGuard",
    "Lease", "lease_for", "CloudNotReady",
]

__version__ = "0.1.0"
