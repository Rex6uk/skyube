# -*- coding: utf-8 -*-
"""cpu.py — CPU 利用率 / 频率 / 负载

注意：利用率必须用「持续采样」，不能用瞬时值。
瞬时 100% 是正常的（编译、解压、渲染都会短暂打满），
只有持续高负载才值得处置。
"""
from __future__ import annotations

import os
import time
from typing import List

import psutil

from ..core import Metric, Status, THRESHOLDS
from .base import Collector, register


@register
class CpuCollector(Collector):
    name = "cpu"

    def collect(self) -> List[Metric]:
        out: List[Metric] = []

        # 瞬时利用率
        pct = psutil.cpu_percent(interval=0.5)
        out.append(Metric("cpu.percent", "CPU 利用率", round(pct, 1),
                          "%", source="psutil"))

        # 持续利用率：采样 2 秒取均值，比瞬时值更能反映真实压力
        samples = []
        for _ in range(4):
            time.sleep(0.5)
            samples.append(psutil.cpu_percent(interval=None))
        sustained = sum(samples) / len(samples)
        out.append(Metric("cpu.sustained_percent", "CPU 持续利用率",
                          round(sustained, 1), "%", source="psutil/2s均值",
                          note="2 秒采样均值，比瞬时值更能反映真实负载"))

        out.append(Metric("cpu.logical_cores", "逻辑核心数",
                          psutil.cpu_count(logical=True), "核", source="psutil"))
        phys = psutil.cpu_count(logical=False)
        if phys:
            out.append(Metric("cpu.physical_cores", "物理核心数", phys, "核",
                              source="psutil"))
        else:
            out.append(Metric("cpu.physical_cores", "物理核心数", None, "核",
                              status=Status.UNAVAILABLE, source="psutil",
                              note="平台未提供物理核数"))

        # 频率 —— 判断是否被降频/锁频
        try:
            f = psutil.cpu_freq()
            if f and f.current:
                out.append(Metric("cpu.freq_mhz", "CPU 当前频率",
                                  round(f.current), "MHz", source="psutil"))
                if f.max:
                    ratio = f.current / f.max * 100
                    out.append(Metric("cpu.freq_ratio", "频率相对最大",
                                      round(ratio, 1), "%", source="psutil",
                                      note="长期偏低说明被限频（电源计划/温度墙）"))
                    if f.max:
                        out.append(Metric("cpu.freq_max_mhz", "CPU 最大频率",
                                          round(f.max), "MHz", source="psutil"))
            else:
                out.append(Metric("cpu.freq_mhz", "CPU 当前频率", None, "MHz",
                                  status=Status.UNAVAILABLE, source="psutil",
                                  note="平台未提供频率"))
        except Exception as e:
            out.append(Metric("cpu.freq_mhz", "CPU 当前频率", None, "MHz",
                              status=Status.ERROR, source="psutil",
                              note=str(e)[:100]))

        # 负载均值（Unix 风格；Windows 上 psutil 用模拟值）
        try:
            la = os.getloadavg()
            out.append(Metric("cpu.load1", "1 分钟负载", round(la[0], 2),
                              "", source="getloadavg"))
        except (AttributeError, OSError):
            pass

        # 每核利用率（找出单核打满的情况，例如单线程任务）
        try:
            per = psutil.cpu_percent(percpu=True, interval=0.2)
            if per:
                out.append(Metric("cpu.max_core_percent", "最忙核心利用率",
                                  round(max(per), 1), "%", source="psutil"))
        except Exception:
            pass

        return out
