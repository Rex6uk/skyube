# -*- coding: utf-8 -*-
"""memory.py — 内存 + 交换采集

跨平台（psutil）。这一层只读，不做处置。
"""
from __future__ import annotations

from typing import List

import psutil

from ..core import Metric, Status
from .base import Collector, register

MB = 1024 * 1024


@register
class MemoryCollector(Collector):
    name = "memory"

    def collect(self) -> List[Metric]:
        out: List[Metric] = []

        v = psutil.virtual_memory()
        total_mb = v.total / MB
        used_mb = (v.total - v.available) / MB
        avail_mb = v.available / MB

        out.append(Metric("memory.percent", "内存占用", round(v.percent, 1),
                          "%", source="psutil"))
        out.append(Metric("memory.total_mb", "物理内存总量", round(total_mb),
                          "MB", source="psutil"))
        out.append(Metric("memory.used_mb", "内存已用", round(used_mb),
                          "MB", source="psutil"))
        out.append(Metric("memory.available_mb", "内存可用", round(avail_mb),
                          "MB", source="psutil"))

        # 交换/页面文件 —— 内存不够时它会涨，是"已经在扛"的信号
        try:
            s = psutil.swap_memory()
            if s.total > 0:
                out.append(Metric("swap.percent", "交换区占用", round(s.percent, 1),
                                  "%", source="psutil"))
                out.append(Metric("swap.used_mb", "交换区已用", round(s.used / MB),
                                  "MB", source="psutil"))
            else:
                out.append(Metric("swap.percent", "交换区占用", None, "%",
                                  status=Status.UNAVAILABLE, source="psutil",
                                  note="系统未配置交换区/页面文件"))
        except Exception as e:
            out.append(Metric("swap.percent", "交换区占用", None, "%",
                              status=Status.ERROR, source="psutil",
                              note=str(e)[:100]))

        # 提交内存（Commit）—— Windows 特有，能看出"承诺了多少"
        if hasattr(v, "total") and hasattr(psutil, "swap_memory"):
            try:
                s = psutil.swap_memory()
                commit_total = (v.total + s.total) / MB
                commit_used = (v.used + s.used) / MB
                if commit_total > 0:
                    out.append(Metric("memory.commit_percent", "提交内存占用",
                                      round(commit_used / commit_total * 100, 1),
                                      "%", source="psutil+swap"))
            except Exception:
                pass

        return out
