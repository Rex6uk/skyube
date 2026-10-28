# -*- coding: utf-8 -*-
"""thermal.py — CPU / 主板 / 硬盘温度

★ 这是整个项目最难的一块，实测结论（本机 HP 暗影精灵 9, R9 8945HX）：
    - psutil.sensors_temperatures()      → AttributeError（Windows 不支持）
    - WMI MSAcpi_ThermalZoneTemperature  → 无输出（该机型 ACPI 未暴露）
    - LibreHardwareMonitor               → 已装在 D:\\Tools\\LibreHardwareMonitor，未运行
    - nvidia-smi temperature.gpu         → 有（GPU 温度，见 gpu.py）

所以 CPU 温度有两条路：
  1) LibreHardwareMonitor 的 WMI 命名空间 root/LibreHardwareMonitor
     （需 LHM 进程在运行；WMI Provider 由 LHM 启动时注册，部分传感器需管理员）
  2) 装 LHM 的 .NET 库直接用（LibreHardwareMonitorLib.dll）

本模块先试 1，失败则明确报 UNAVAILABLE 并给出启用步骤 —— 绝不返回 0 假装正常。
"""
from __future__ import annotations

import subprocess
import sys
from typing import List, Optional

from ..core import Metric, Status
from .base import Collector, register

LHM_EXE = ""      # 运行时由 paths.find_lhm() 动态发现（跨机器可运行）
LHM_NS = "root/LibreHardwareMonitor"
NO_WIN = 0x08000000


def _lhm_exe() -> str:
    """每次现查，避免模块导入时就固化成本机路径。"""
    from ..paths import find_lhm
    return find_lhm()


def _ps(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace",
                           creationflags=NO_WIN)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _lhm_state() -> dict:
    """探测 LHM 三层状态：进程 / 命名空间 / 传感器。一次探测，多处复用。"""
    running = "LibreHardwareMonitor" in _ps(
        "(Get-Process -Name LibreHardwareMonitor -ErrorAction SilentlyContinue) -ne $null")
    ns_rows = _ps(
        "Get-CimInstance -Namespace %s -ClassName Sensor -ErrorAction SilentlyContinue | "
        "Where-Object { $_.SensorType -eq 'Temperature' } | "
        "ForEach-Object { $_.Name + '|' + $_.Identifier + '|' + $_.Value }" % LHM_NS)
    return {"running": running, "rows": ns_rows}


def _parse_lhm(rows: str) -> List[Metric]:
    out: List[Metric] = []
    for line in rows.splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        nm, ident, val = parts[0].strip(), parts[1].strip(), parts[2].strip()
        try:
            v = float(val)
        except ValueError:
            continue
        if not (-40 <= v <= 130):
            continue  # 物理上不合理 → 视为无数据，宁缺毋假
        low = (nm + ident).lower()
        if "cpu" in low or "package" in low or "core" in low or "tctl" in low or "tdie" in low:
            out.append(Metric("cpu_temp." + nm.replace(" ", "_"),
                              "CPU " + nm, round(v, 1), "C", source="LibreHardwareMonitor"))
        elif "gpu" in low:
            out.append(Metric("gpu_temp." + nm.replace(" ", "_"),
                              "GPU " + nm, round(v, 1), "C", source="LibreHardwareMonitor"))
        elif "ssd" in low or "hdd" in low or "disk" in low or "nvme" in low or "m.2" in low:
            out.append(Metric("disk_temp." + nm.replace(" ", "_"),
                              "硬盘 " + nm, round(v, 1), "C", source="LibreHardwareMonitor"))
        elif "mem" in low or "ram" in low:
            out.append(Metric("mem_temp." + nm.replace(" ", "_"),
                              "内存 " + nm, round(v, 1), "C", source="LibreHardwareMonitor"))
        else:
            out.append(Metric("board_temp." + nm.replace(" ", "_"),
                              nm, round(v, 1), "C", source="LibreHardwareMonitor"))
    return out


def _acpi_temps() -> List[Metric]:
    """ACPI 热区（多数消费级笔记本无数据，作兜底）。"""
    acpi = _ps(
        "Get-CimInstance -Namespace root/WMI -ClassName MSAcpi_ThermalZoneTemperature "
        "-ErrorAction SilentlyContinue | ForEach-Object { "
        "$_.InstanceName + '|' + [math]::Round(($_.CurrentTemperature/10-273.15),1) }")
    out: List[Metric] = []
    for line in acpi.splitlines():
        parts = line.split("|")
        if len(parts) < 2:
            continue
        try:
            v = float(parts[1])
        except ValueError:
            continue
        if -20 < v < 150:
            out.append(Metric("board_temp.acpi_" + parts[0].split("\\")[-1][:20],
                              "ACPI 热区", round(v, 1), "C", source="WMI/ACPI"))
    return out


def _diag_note(state: dict) -> str:
    """按探测结果给出精确的失败原因 + 修复步骤，不再一刀切。"""
    from ..paths import find_lhm, lhm_hint
    exe = find_lhm()
    lines = ["CPU 温度读不到（该机型 psutil/ACPI 均不暴露）"]
    if not exe:
        # 跨机器：这台机器压根没装 LHM，给安装指引而不是本机路径
        lines.append("· " + lhm_hint().replace("\n", " "))
    elif not state["running"]:
        lines.append("· LHM 未运行 → 需以管理员身份启动它一次（%s）" % exe)
    elif not state["rows"]:
        lines.append("· LHM 在跑但未注册 WMI 命名空间 → 它可能不是管理员启动；"
                     "请以管理员身份重启 LHM 并在 Options 勾选 WMI Provider")
    else:
        lines.append("· LHM 有 WMI 但无温度传感器 → 需管理员权限读 CPU 温度")
    if exe:
        lines.append("· 修复方式：右键 '%s' 以管理员运行一次，"
                     "Options → 勾 WMI Provider；之后本采集器自动接管" % exe)
    return " | ".join(lines)


@register
class ThermalCollector(Collector):
    name = "thermal"

    def collect(self) -> List[Metric]:
        out: List[Metric] = []

        # ---------- 非 Windows：psutil 通常可用 ----------
        if sys.platform != "win32":
            try:
                import psutil
                temps = psutil.sensors_temperatures()
                if temps:
                    for chip, entries in temps.items():
                        for i, e in enumerate(entries):
                            key = "%s.%s" % (chip, e.label or ("sensor%d" % i))
                            out.append(Metric("cpu_temp." + key.replace(" ", "_"),
                                              "%s %s" % (chip, e.label or ""),
                                              round(e.current, 1), "C",
                                              source="psutil"))
                    return out
            except Exception as e:
                out.append(Metric("cpu_temp.celsius", "CPU 温度", None, "C",
                                  status=Status.ERROR, source="psutil",
                                  note=str(e)[:100]))
                return out
            out.append(Metric("cpu_temp.celsius", "CPU 温度", None, "C",
                              status=Status.UNAVAILABLE, source="psutil",
                              note="psutil 未返回温度传感器"))
            return out

        # ---------- Windows：先试 LibreHardwareMonitor WMI（只读探测） ----------
        state = _lhm_state()
        if state["rows"]:
            parsed = _parse_lhm(state["rows"])
            if parsed:
                out.extend(parsed)
                if any(m.name.startswith("board_temp.") for m in out):
                    return out
                # 有 CPU 温度但缺主板温度：补一个明确说明
                out.append(Metric("board_temp.celsius", "主板温度", None, "C",
                                  status=Status.UNAVAILABLE, source="LibreHardwareMonitor",
                                  note="LHM 未暴露主板温度传感器（只读到 CPU/GPU/盘），非故障"))
                return out

        # ---------- 退而试 ACPI（多数消费级笔记本无数据） ----------
        acpi_out = _acpi_temps()
        if acpi_out:
            out.extend(acpi_out)
            return out

        # ---------- 全部失败：按探测结果给精确诊断 ----------
        note = _diag_note(state)
        out.append(Metric("cpu_temp.celsius", "CPU 温度", None, "C",
                         status=Status.UNAVAILABLE, source="none", note=note))
        out.append(Metric("board_temp.celsius", "主板温度", None, "C",
                         status=Status.UNAVAILABLE, source="none", note=note))
        return out
