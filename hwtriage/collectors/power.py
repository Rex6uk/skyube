# -*- coding: utf-8 -*-
"""power.py — 电源计划 / 电池 / 温度墙线索

笔记本"越用越慢"最常见的原因不是硬件老化，而是：
  - 电源计划被设成"节能" → CPU 锁基准频率（AMD 上表现为禁睿频）
  - 电池模式 → 系统主动降频
  - 温度墙 → 撞到 95℃ 就降频

本采集器把这些线索找出来，但不改任何设置。
★ 铁律：绝不自动改电源计划里的 PROCTHROTTLEMAX。
  设 <100% 在 AMD 上 = 全机锁基准频率，用户会回来问「CPU 怎么这么慢」。
"""
from __future__ import annotations

import subprocess
import sys
from typing import List

from ..core import Metric, Status
from .base import Collector, register

NO_WIN = 0x08000000


def _ps(cmd: str, timeout: int = 25):
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace",
                           creationflags=NO_WIN)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _cmd(cmd: List[str], timeout: int = 20, encoding: str = "utf-8"):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding=encoding, errors="replace",
                           creationflags=NO_WIN)
        return (r.stdout or "").strip()
    except Exception:
        return ""


@register
class PowerCollector(Collector):
    name = "power"

    def collect(self) -> List[Metric]:
        out: List[Metric] = []

        # ---------- 电池 ----------
        try:
            import psutil
            b = psutil.sensors_battery()
            if b:
                out.append(Metric("battery.percent", "电池电量", round(b.percent, 0),
                                  "%", source="psutil"))
                out.append(Metric("battery.plugged", "外接电源",
                                  None, "",
                                  source="psutil",
                                  text="已接通" if b.power_plugged else "未接通",
                                  note="" if b.power_plugged else "电池供电，会降频"))
            else:
                out.append(Metric("battery.percent", "电池电量", None, "%",
                                  status=Status.UNAVAILABLE, source="psutil",
                                  note="台机或无电池"))
        except Exception as e:
            out.append(Metric("battery.percent", "电池电量", None, "%",
                              status=Status.ERROR, source="psutil",
                              note=str(e)[:100]))

        if sys.platform != "win32":
            return out

        # ---------- 电源计划 ----------
        # powercfg 输出是 GBK 编码，用 utf-8 解会炸（实测 UnicodeDecodeError）
        act = _cmd(["powercfg", "/getactivescheme"], encoding="gbk")
        if act:
            # 提取方案名：形如 "电源方案 GUID: xxx  (平衡)" → 取括号里的名字
            import re as _re
            mm = _re.search(r"\(([^)]+)\)\s*$", act)
            scheme = mm.group(1) if mm else act[:60]
            out.append(Metric("power.active_scheme", "当前电源计划", None, "",
                              source="powercfg", text=scheme,
                              note=act[:160]))
        else:
            out.append(Metric("power.active_scheme", "当前电源计划", None, "",
                              status=Status.UNAVAILABLE, source="powercfg",
                              note="读不到（powercfg 无输出）"))

        # ---------- CPU 最大处理器状态 ----------
        # 这是"锁频"的直接证据：<100% 说明被限了
        # 实测输出（GBK）：
        #   最小可能的设置: 0x00000000
        #   最大可能的设置: 0x00000064      ← 0x64 = 100
        #   当前交流电源设置索引: 0x00000055  ← 0x55 = 85%
        #   当前直流电源设置索引: 0x00000055
        # ★ 坑：单位就是「%」，十六进制直读。不要除以 1000（曾算成 0.085%）。
        q = _cmd(["powercfg", "/q", "SCHEME_CURRENT", "SUB_PROCESSOR",
                  "PROCTHROTTLEMAX"], encoding="gbk")
        if q:
            import re
            ac = re.search(r"当前交流电源设置索引[:：]\s*0x([0-9a-fA-F]+)", q)
            dc = re.search(r"当前直流电源设置索引[:：]\s*0x([0-9a-fA-F]+)", q)
            vals = []
            if ac:
                vals.append(int(ac.group(1), 16))
            if dc:
                vals.append(int(dc.group(1), 16))
            if vals:
                mn = min(vals)
                out.append(Metric("power.cpu_max_state", "CPU 最大状态",
                                  float(mn), "%", source="powercfg",
                                  note=("★ 被限制在 %d%%！CPU 无法跑满，睿频被压死。"
                                        "改回 100%% 才恢复满速（本工具不自动改，见文档）" % mn
                                        if mn < 99 else "100%，可正常睿频")))
            else:
                out.append(Metric("power.cpu_max_state", "CPU 最大状态", None, "%",
                                  status=Status.UNAVAILABLE, source="powercfg",
                                  note="未读到 PROCTHROTTLEMAX 数值"))

        # ---------- 温度墙线索：近 24h 的 Kernel-Processor-Power 事件 ----------
        ev = _ps("Get-WinEvent -FilterHashtable @{LogName='System'; "
                 "StartTime=(Get-Date).AddHours(-24)} -ErrorAction SilentlyContinue | "
                 "Where-Object { $_.ProviderName -match 'Processor-Power|Thermal' } | "
                 "Measure-Object | Select-Object -ExpandProperty Count")
        if ev and ev.isdigit():
            out.append(Metric("power.thermal_events_24h", "24h 降频/温度事件",
                              int(ev), "次", source="事件日志",
                              note=("有降频记录，检查散热" if int(ev) > 0
                                    else "无降频记录")))

        return out
