# -*- coding: utf-8 -*-
"""test_selftest.py — 无需 pytest 的自检套件（标准库 unittest）

跑法：  python -m hwtriage.test_selftest
       python hwtriage/test_selftest.py

守的是「质量底线」，不是覆盖率：
  1) 数据模型铁律：读不到必须 UNAVAILABLE+note，绝不能用 0 冒充
  2) 文本型读数（text）与数值型（value）不能互相污染
  3) 阈值判定方向正确（cpu_max_state 越高越好；绝对量不参与百分比阈值）
  4) 保护名单不许误伤（explorer/clawchat 必须被保护）
  5) 三个渲染模式都能跑且静默模式真静默
"""
import unittest

from .core import Level, Metric, Status, level_of, is_protected, THRESHOLDS
from . import report


class TestMetricModel(unittest.TestCase):
    """数据模型：防假绿、防假红"""

    def test_ok_requires_value_or_text(self):
        """status=OK 但 value/text 都空 → 必须抛错（防假绿）"""
        with self.assertRaises(ValueError):
            Metric("x.y", "标签", None)

    def test_unavailable_requires_note(self):
        """UNAVAILABLE 没写原因 → 必须抛错（防'不知道为什么读不到'）"""
        with self.assertRaises(ValueError):
            Metric("x.y", "标签", None, status=Status.UNAVAILABLE)

    def test_numeric_ok(self):
        m = Metric("memory.percent", "内存占用", 50.0, "%")
        self.assertTrue(m.ok)
        self.assertIsNone(m.text or None)

    def test_text_ok(self):
        """文本型读数（显卡型号等）必须是 OK，不能标成读不到"""
        m = Metric("gpu.name", "显卡型号", None, text="RTX 5060")
        self.assertTrue(m.ok, "文本型读数必须算读到了")
        self.assertEqual(m.text, "RTX 5060")

    def test_text_and_value_independent(self):
        """value=None 但有 text → OK；两者都空才报错"""
        m = Metric("power.active_scheme", "电源计划", None, text="平衡")
        self.assertTrue(m.ok)
        self.assertIsNone(m.value)


class TestLevelOf(unittest.TestCase):
    """阈值判定方向"""

    def test_absolute_quantities_ignored(self):
        """绝对量（_mb/_gb/_mhz）不参与百分比阈值，否则面板全假红"""
        for name, v in [("memory.total_mb", 15414), ("disk.c.free_gb", 97),
                        ("cpu.freq_mhz", 2139), ("gpu_power.watts", 24)]:
            self.assertEqual(level_of(name, v), Level.OK, "%s 不该判等级" % name)

    def test_memory_percent_levels(self):
        t = THRESHOLDS["memory"]
        self.assertEqual(level_of("memory.percent", t["warn"] - 1), Level.OK)
        self.assertEqual(level_of("memory.percent", t["warn"]), Level.WARN)
        self.assertEqual(level_of("memory.percent", t["critical"]), Level.CRITICAL)

    def test_cpu_max_state_inverted(self):
        """cpu_max_state 是越高越好：100 正常，85 报警"""
        self.assertEqual(level_of("power.cpu_max_state", 100), Level.OK)
        self.assertEqual(level_of("power.cpu_max_state", 85), Level.WARN)

    def test_none_is_ok(self):
        """读不到不参与阈值（不产生假红）"""
        self.assertEqual(level_of("memory.percent", None), Level.OK)


class TestProtection(unittest.TestCase):
    """保护名单：宁可少杀，不可错杀"""

    def test_critical_apps_protected(self):
        for n in ["explorer.exe", "clawchat.exe", "msedge.exe", "ffmpeg.exe",
                  "svchost.exe", "lsass.exe"]:
            self.assertTrue(is_protected(n), "%s 必须被保护" % n)

    def test_generic_words_not_protected(self):
        """泛词不许进保护名单（踩过 mcp / gateway 两个坑）"""
        self.assertFalse(is_protected("mcp"), "泛词 mcp 不该被保护")
        self.assertFalse(is_protected("gateway"), "泛词 gateway 不该被保护")
        self.assertFalse(is_protected("some_random.exe"))


class TestRender(unittest.TestCase):
    """三个渲染模式"""

    def _fake(self):
        return [
            Metric("memory.percent", "内存占用", 50.0, "%"),
            Metric("gpu.name", "显卡型号", None, text="RTX 5060"),
            Metric("cpu_temp.celsius", "CPU 温度", None, "C",
                   status=Status.UNAVAILABLE, note="需管理员"),
        ]

    def test_full_contains_all(self):
        out = report.render(self._fake(), "full")
        self.assertIn("内存占用", out)
        self.assertIn("RTX 5060", out)          # 文本型要显示
        self.assertIn("读不到", out)

    def test_brief_runs(self):
        self.assertIn("硬件状态体检", report.render(self._fake(), "brief"))

    def test_cron_silent_when_clean(self):
        """静默模式：全正常 → 一个字都不输出"""
        clean = [Metric("memory.percent", "内存占用", 10.0, "%")]
        self.assertEqual(report.render(clean, "cron").strip(), "")

    def test_cron_speaks_when_anomaly(self):
        bad = [Metric("memory.percent", "内存占用", 99.0, "%")]
        out = report.render(bad, "cron")
        self.assertIn("需要关注", out)


class TestGuardPlan(unittest.TestCase):
    """处置层：默认绝不动手"""

    def test_dry_run_does_nothing(self):
        from . import guard
        log = guard.execute_plan({"actions": [
            {"pid": 999999, "name": "x.exe", "kind": "empty_working_set",
             "level": "act", "reason": "test"}]}, apply=False)
        self.assertTrue(any("dry-run" in l for l in log))

    def test_plan_shape(self):
        from . import guard
        plan = guard.build_plan([])
        for k in ("actions", "skipped", "notes", "thresholds", "scanned"):
            self.assertIn(k, plan)


class TestAdvisor(unittest.TestCase):
    """顾问层：建议必须有依据、有代价，且绝不自作主张"""

    def _metrics(self, **over):
        """造一组可控指标，方便断言建议触发条件。"""
        base = [
            Metric("hardware.cpu_model", "CPU 型号", None, text="Test CPU"),
            Metric("memory.total_mb", "物理内存总量", 16384, "MB"),
            Metric("memory.percent", "内存占用", 50.0, "%"),
            Metric("memory.available_mb", "内存可用", 8000, "MB"),
            Metric("cpu.physical_cores", "物理核心数", 8, "核"),
            Metric("cpu.logical_cores", "逻辑核心数", 16, "核"),
            Metric("cpu.freq_max_mhz", "CPU 最大频率", 3000, "MHz"),
            Metric("cpu.freq_ratio", "频率相对最大", 99.0, "%"),
            Metric("gpu.name", "显卡型号", None, text="Test GPU"),
            Metric("gpu_mem.total_mb", "显存总量", 16384, "MB"),
            Metric("power.cpu_max_state", "CPU 最大状态", 100.0, "%"),
            Metric("process.max_mb", "最大单进程内存", 800, "MB"),
        ]
        base.extend(over.get("extra", []))
        return base

    def test_healthy_machine_no_advice(self):
        """全正常 → 不该乱提建议（不乱吓人）"""
        from . import advisor
        self.assertEqual(advisor.build_advice(self._metrics()), [])

    def test_cpu_throttle_detected(self):
        """CPU 限频 → 必须出建议，且标 RISK（改电源计划有代价）"""
        from . import advisor
        m = self._metrics()
        for x in m:
            if x.name == "power.cpu_max_state":
                x.value = 85.0
        adv = advisor.build_advice(m)
        risk = [a for a in adv if a["tier"] == advisor.RISK]
        self.assertTrue(risk, "CPU 限频必须提 RISK 级建议")
        self.assertIn("85", risk[0]["title"])

    def test_low_memory_suggests_upgrade(self):
        """内存 <16G → 建议加内存（COST 级）"""
        from . import advisor
        m = self._metrics()
        for x in m:
            if x.name == "memory.total_mb":
                x.value = 8192
        adv = advisor.build_advice(m)
        self.assertTrue([a for a in adv if a["tier"] == advisor.COST])

    def test_every_advice_has_why_and_cost(self):
        """铁律：每条建议必须有依据(why)，且必须有代价(cost)字段"""
        from . import advisor
        m = self._metrics()
        for x in m:
            if x.name == "power.cpu_max_state":
                x.value = 85.0
        for a in advisor.build_advice(m):
            self.assertTrue(a["why"], "建议缺依据: %s" % a["title"])
            self.assertIn("cost", a, "建议缺代价字段: %s" % a["title"])

    def test_advice_never_auto_executes(self):
        """顾问层只能建议，绝不能有执行函数"""
        from . import advisor
        self.assertFalse(hasattr(advisor, "execute"),
                         "advisor 不许有 execute —— 它只能建议")
        self.assertFalse(hasattr(advisor, "apply"),
                         "advisor 不许有 apply —— 它只能建议")

    def test_render_shows_profile(self):
        """渲染必须给出机器画像 + 免责声明"""
        from . import advisor
        out = advisor.render_advice(self._metrics())
        self.assertIn("Test CPU", out)
        self.assertIn("Test GPU", out)
        self.assertIn("你定", out)      # 明确用户决定权


class TestPermGuide(unittest.TestCase):
    """权限引导：只提醒，不强迫，绝不自动提权"""

    def test_no_blocked_returns_empty(self):
        from . import permguide
        ok = [Metric("cpu_temp.celsius", "CPU 温度", 55.0, "C")]
        self.assertEqual(permguide.render_hint(ok), "")

    def test_hint_mentions_optional(self):
        """提示必须写明「不开也能用」——不能吓用户"""
        from . import permguide
        m = [Metric("cpu_temp.celsius", "CPU 温度", None, "C",
                    status=Status.UNAVAILABLE, note="需管理员")]
        out = permguide.render_hint(m)
        self.assertIn("也完全能用", out)

    def test_hint_gives_concrete_steps(self):
        """提示要具体到点哪里，不能只说'请用管理员'"""
        from . import permguide
        m = [Metric("cpu_temp.celsius", "CPU 温度", None, "C",
                    status=Status.UNAVAILABLE, note="需管理员")]
        out = permguide.render_hint(m)
        self.assertTrue("WMI Provider" in out or "管理员身份运行" in out,
                        "必须给出具体操作步骤")

    def test_never_auto_elevates(self):
        """铁律：不许有提权函数（不弹 UAC、不写计划任务）"""
        from . import permguide
        for forbidden in ("elevate", "runas", "uac_prompt", "ShellExecute"):
            self.assertFalse(hasattr(permguide, forbidden),
                             "permguide 不许有 %s —— 绝不能自动提权" % forbidden)


class TestPaths(unittest.TestCase):
    """跨机器路径发现：任何电脑都能跑，不许写死本机路径"""

    def test_no_hardcoded_path_in_source(self):
        """源码里不许出现本机绝对路径（D:\\Tools / Users\\hp）"""
        import os
        pkg = os.path.dirname(os.path.abspath(__file__))
        bad = []
        for root, dirs, files in os.walk(pkg):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if not f.endswith(".py"):
                    continue
                if f == "test_selftest.py":   # 测试自己含检查词，跳过自指
                    continue
                path = os.path.join(root, f)
                try:
                    t = open(path, encoding="utf-8", errors="ignore").read()
                except Exception:
                    continue
                for token in ("D:\\Tools", "Users\\hp", "Python313"):
                    if token in t:
                        bad.append("%s 含 %s" % (f, token))
        self.assertEqual(bad, [], "发现硬编码本机路径: %s" % bad)

    def test_find_lhm_returns_str(self):
        """find_lhm 找不到必须返回空串，不能抛异常"""
        from . import paths
        r = paths.find_lhm()
        self.assertIsInstance(r, str)

    def test_env_override_respected(self):
        """环境变量 HWTRIAGE_LHM_PATH 必须能覆盖自动发现"""
        import os
        from . import paths
        old = os.environ.get("HWTRIAGE_LHM_PATH")
        try:
            os.environ["HWTRIAGE_LHM_PATH"] = r"C:\nonexistent\dir"
            # 指向不存在的目录 → 不该返回它
            r = paths.find_lhm()
            self.assertNotEqual(r, r"C:\nonexistent\dir")
        finally:
            if old is None:
                os.environ.pop("HWTRIAGE_LHM_PATH", None)
            else:
                os.environ["HWTRIAGE_LHM_PATH"] = old

    def test_lhm_hint_is_actionable(self):
        """没找到 LHM 时，提示必须给出下载地址或安装方法"""
        from . import paths
        h = paths.lhm_hint()
        self.assertTrue("github.com" in h or "lm-sensors" in h,
                        "提示必须告诉用户去哪装")


if __name__ == "__main__":
    unittest.main(verbosity=2)
