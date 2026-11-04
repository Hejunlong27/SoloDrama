# -*- coding: utf-8 -*-
"""站点真源（configs/channels.json）回归测试 —— 零依赖、零网络、零计费。

跑法：
    python stages/video/workflow/scripts/engine/tests/test_channels.py

要证明的事（每条都对应一次真实误判）：

  1. **过期快照不再改变行为**：进程里 `RUNNINGHUB_BASE_URL=.ai`、配置里 `cn`，
     引擎必须用 `cn`。这是本次整改的起因：用户改了用户级变量，已开着的终端仍是旧值，
     而症状是上传报 `code=1 API Key不存在` —— 看起来像 Key 错，实际是变量过期。
  2. **显式覆盖仍然有效**：`SOLODRAMA_RH_SITE` 优先级高于配置，单次跑批能临时切站。
  3. **别名可读**：`cn` / `zh` / `ai` / `intl` / 完整 URL 都能落到同一个值。
  4. **没有配置时回退**：删掉 channels.json 这套机制不能把引擎带崩，仍按旧变量走。
  5. **被忽略的值必须留痕**：`RH_SITE_IGNORED` 要能报出「你设的 .ai 被忽略了」，
     否则「改了没生效」永远查不到。
  6. **能力卡与运行时是同一个数**：卡里写 .cn、引擎跑 .ai 这种三方不一致不允许再出现。
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
ROOT = ENGINE.parents[4]                      # engine → scripts → workflow → video → stages → 仓库根
assert (ROOT / "configs" / "channels.json").is_file(), "仓库根定位失败：%s" % ROOT
sys.path.insert(0, str(ENGINE))

import config as C                                               # noqa: E402

_ENV_NAMES = ("RUNNINGHUB_BASE_URL", "RH_BASE_URL", "SOLODRAMA_RH_SITE")
CN = "https://www.runninghub.cn"
AI = "https://www.runninghub.ai"


class Base(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in _ENV_NAMES}
        for k in _ENV_NAMES:
            os.environ.pop(k, None)
        self._saved_root = C._find_repo_root

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        C._find_repo_root = self._saved_root


class TestResolve(Base):
    def test_config_wins_over_stale_env(self):
        """过期快照（.ai）不能改变行为：配置说 cn 就是 cn。"""
        os.environ["RUNNINGHUB_BASE_URL"] = AI
        url, src, ignored = C.resolve_rh_site()
        self.assertEqual(url, CN, "配置应压过过期的环境变量")
        self.assertIn("channels.json", src)
        self.assertEqual(ignored, AI, "被忽略的旧值要留痕，否则「改了没生效」查不到")

    def test_env_override(self):
        os.environ["SOLODRAMA_RH_SITE"] = "ai"
        os.environ["RUNNINGHUB_BASE_URL"] = CN
        url, src, ignored = C.resolve_rh_site()
        self.assertEqual(url, AI)
        self.assertIn("SOLODRAMA_RH_SITE", src)
        self.assertEqual(ignored, "", "显式覆盖时不该报旧变量冲突")

    def test_explicit_beats_env(self):
        os.environ["SOLODRAMA_RH_SITE"] = "ai"
        url, src, _ = C.resolve_rh_site("cn")
        self.assertEqual(url, CN)
        self.assertIn("显式", src)

    def test_aliases(self):
        for raw, want in (("cn", CN), ("zh", CN), ("ai", AI), ("intl", AI),
                          (CN + "/", CN), (AI, AI), ("runninghub.cn", CN)):
            self.assertEqual(C.normalize_site(raw), want, "别名 %r 解析错" % raw)
        self.assertEqual(C.normalize_site(""), "")
        self.assertEqual(C.normalize_site("自建站"), "自建站", "认不出的别名原样返回，交给上层报错")

    def test_no_env_fallback_any_more(self):
        """旧环境变量**不再参与解析**：没有配置时也不能被它带偏。"""
        C._find_repo_root = lambda: None
        os.environ["RUNNINGHUB_BASE_URL"] = AI
        url, src, ignored = C.resolve_rh_site()
        self.assertEqual(url, CN, "旧环境变量已废弃，不能回退到它")
        self.assertIn("默认", src)
        self.assertEqual(ignored, AI, "被忽略的值仍要留痕，好让体检提示去删掉它")

    def test_stale_env_without_config(self):
        """没有配置 + 旧变量与默认一致 → 不报「被忽略」，避免无意义告警。"""
        C._find_repo_root = lambda: None
        os.environ["RUNNINGHUB_BASE_URL"] = CN
        url, _src, ignored = C.resolve_rh_site()
        self.assertEqual(url, CN)
        self.assertEqual(ignored, "", "同值不算冲突，不该提示")

    def test_default_when_nothing(self):
        C._find_repo_root = lambda: None
        url, src, _ = C.resolve_rh_site()
        self.assertEqual(url, CN, "什么都没有时必须落到国内站默认值")
        self.assertIn("默认", src)

    def test_module_value_matches_resolver(self):
        """模块级 RH_BASE_URL 也要来自同一套解析，不能是另一条路径。"""
        self.assertEqual(C.RH_BASE_URL, C.resolve_rh_site()[0])


class TestCardAgrees(Base):
    def test_capabilities_uses_runtime_site(self):
        """能力卡比对用的必须是「运行时站点」，不是裸环境变量。"""
        sys.path.insert(0, str(ROOT / "stages" / "production" / "scripts"))
        import capabilities as CAP
        os.environ["RUNNINGHUB_BASE_URL"] = AI          # 制造过期快照
        site, src, _ignored = CAP._rh_runtime_site()
        self.assertEqual(site, C.RH_BASE_URL, "体检与引擎必须是同一个数")
        self.assertNotEqual(site, AI, "过期快照不该被当成运行时站点")


class TestSetSiteCmd(unittest.TestCase):
    def test_dry_run_does_not_touch_file(self):
        """`set-site --dry-run` 只能打印，不能改仓库配置。"""
        cfg = ROOT / "configs" / "channels.json"
        before = cfg.read_bytes()
        r = subprocess.run([sys.executable, str(ROOT / "stages" / "video" / "workflow"
                                                / "scripts" / "configure.py"),
                            "set-site", "ai", "--dry-run"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        self.assertIn("DRY-RUN", r.stdout)
        self.assertEqual(cfg.read_bytes(), before, "dry-run 改动了文件")


if __name__ == "__main__":
    unittest.main(verbosity=2)
