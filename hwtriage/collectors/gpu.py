# -*- coding: utf-8 -*-
"""gpu.py — 显存 / GPU 利用率 / 温度 / 功耗

实测本机（RTX 5060 Laptop, driver 610.62）nvidia-smi 能拿到：
  显存 total/used/free、utilization、temperature.gpu、power.draw、clocks、pstate
拿不到：
  fan.speed = [N/A]、power.limit = [N/A]（笔记本锁了，读不到上限）
  temperature.memory = N/A（部分笔记本机型不暴露显存温度）

★ 关键坑：nvidia-smi 输出里 [N/A] 必须识别成"读不到"，不能当 0。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import List, Optional

from ..core import Metric, Status
from .base import Collector, register

MB = 1024 * 1024

# Windows 上 nvidia-smi 不一定在 PATH 里，实测本机就在 System32
CANDIDATES = [
    r"C:\Windows\System32\nvidia-smi.exe",
    r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
]


def _find_smi() -> Optional[str]:
    for p in CANDIDATES:
        if os.path.exists(p):
            return p
    return shutil.which("nvidia-smi")


def _run(smi: str, query: str) -> List[str]:
    """返回每个 GPU 一行的字段列表；失败返回空"""
    try:
        r = subprocess.run([smi, "--query-gpu=" + query, "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return []
        return [ln.strip() for ln in (r.stdout or "").strip().splitlines() if ln.strip()]
    except Exception:
        return []


def _num(s: str) -> Optional[float]:
    """把 nvidia-smi 字段转成数字；[N/A] 和空值返回 None（关键！）"""
    if s is None:
        return None
    t = str(s).strip().strip("[]")
    if not t or t.upper() in ("N/A", "NA", "[N/A]", "NOT SUPPORTED"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


@register
class GpuCollector(Collector):
    name = "gpu"

    def collect(self) -> List[Metric]:
        out: List[Metric] = []

        smi = _find_smi()
        if not smi:
            out.append(Metric("gpu.present", "GPU 采集", None, "",
                              status=Status.UNAVAILABLE, source="nvidia-smi",
                              note="未找到 nvidia-smi（非 NVIDIA 显卡或未装驱动）"))
            return out

        # 基础 + 利用率 + 温度
        rows = _run(smi, "name,memory.total,memory.used,memory.free,"
                         "utilization.gpu,temperature.gpu,power.draw,power.limit,"
                         "clocks.current.graphics,pstate")
        if not rows:
            out.append(Metric("gpu.present", "GPU 采集", None, "",
                              status=Status.ERROR, source="nvidia-smi",
                              note="nvidia-smi 执行失败或无输出"))
            return out

        # 多卡：只取第一张（笔记本/单卡场景），但把卡数报出来
        out.append(Metric("gpu.count", "GPU 数量", len(rows), "张",
                          source="nvidia-smi"))

        f = [x.strip() for x in rows[0].split(",")]
        while len(f) < 10:
            f.append("")

        name = f[0]
        mem_total = _num(f[1])
        mem_used = _num(f[2])
        mem_free = _num(f[3])
        util = _num(f[4])
        temp = _num(f[5])
        power = _num(f[6])
        power_limit = _num(f[7])
        clk = _num(f[8])
        pstate = f[9]

        out.append(Metric("gpu.name", "显卡型号", None, "",
                          source="nvidia-smi", text=name))   # 文本型读数：真读到了

        if mem_total:
            out.append(Metric("gpu_mem.total_mb", "显存总量", round(mem_total),
                              "MB", source="nvidia-smi"))
        if mem_used is not None:
            out.append(Metric("gpu_mem.used_mb", "显存已用", round(mem_used),
                              "MB", source="nvidia-smi"))
            if mem_total:
                pct = mem_used / mem_total * 100
                out.append(Metric("gpu_mem.percent", "显存占用", round(pct, 1),
                                  "%", source="nvidia-smi"))
        if mem_free is not None:
            out.append(Metric("gpu_mem.free_mb", "显存可用", round(mem_free),
                              "MB", source="nvidia-smi"))

        if util is not None:
            out.append(Metric("gpu.util_percent", "GPU 利用率", round(util, 1),
                              "%", source="nvidia-smi"))

        if temp is not None:
            out.append(Metric("gpu_temp.celsius", "GPU 温度", round(temp, 1),
                              "C", source="nvidia-smi"))
        else:
            out.append(Metric("gpu_temp.celsius", "GPU 温度", None, "C",
                              status=Status.UNAVAILABLE, source="nvidia-smi",
                              note="该机型不暴露 GPU 温度（返回 N/A）"))

        if power is not None:
            out.append(Metric("gpu_power.watts", "GPU 功耗", round(power, 1),
                              "W", source="nvidia-smi"))
            if power_limit:
                out.append(Metric("gpu_power.percent", "功耗相对上限",
                                  round(power / power_limit * 100, 1), "%",
                                  source="nvidia-smi",
                                  note="上限 %.0fW" % power_limit))
        else:
            out.append(Metric("gpu_power.watts", "GPU 功耗", None, "W",
                              status=Status.UNAVAILABLE, source="nvidia-smi",
                              note="读不到功耗"))

        if power_limit is None:
            out.append(Metric("gpu_power.limit_w", "功耗上限", None, "W",
                              status=Status.UNAVAILABLE, source="nvidia-smi",
                              note="笔记本机型通常锁了上限，返回 N/A"))

        if clk is not None:
            out.append(Metric("gpu.clock_mhz", "GPU 核心频率", round(clk),
                              "MHz", source="nvidia-smi"))
        if pstate:
            out.append(Metric("gpu.pstate", "电源状态", None, "",
                              source="nvidia-smi",
                              text=pstate, note="P0=满载 P8=空闲"))

        # 风扇
        fan = _run(smi, "fan.speed")
        if fan:
            fv = _num(fan[0].split(",")[0])
            if fv is None:
                out.append(Metric("gpu.fan_percent", "GPU 风扇", None, "%",
                                  status=Status.UNAVAILABLE, source="nvidia-smi",
                                  note="该机型不暴露风扇转速（返回 N/A）"))
            else:
                out.append(Metric("gpu.fan_percent", "GPU 风扇", round(fv, 1),
                                  "%", source="nvidia-smi"))

        # 显存温度（多数笔记本不暴露）
        mt = _run(smi, "temperature.memory")
        if mt:
            mv = _num(mt[0].split(",")[0])
            if mv is not None:
                out.append(Metric("gpu_temp.memory_celsius", "显存温度",
                                  round(mv, 1), "C", source="nvidia-smi"))

        return out
