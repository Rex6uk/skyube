# -*- coding: utf-8 -*-
"""hardware.py — 硬件配置档案（给"推荐方案"用，不是体检）

★ 和体检的区别：
    体检 = 此刻状态（CPU 利用率、内存占用、温度）→ 关心"现在累不累"
    档案 = 机器身份（CPU 型号、内存容量、显卡、硬盘）→ 关心"你有多大本事"

★ 为什么要单独一层：
    推荐方案必须先知道"你是什么机器"。体检指标每秒都变，档案基本不变。
    混在一起会导致：换个瞬间跑一次，推荐方案就变了 —— 那叫不靠谱。

★ 读不到的处理：型号这类信息，读不到就写 UNAVAILABLE + 原因，
  绝不用 "Unknown" 冒充（下游会拿它做推荐，假型号会推出错方案）。
"""
from __future__ import annotations

import subprocess
import sys
from typing import List

from ..core import Metric, Status
from .base import Collector, register

NO_WIN = 0x08000000


def _ps(cmd: str, timeout: int = 25) -> str:
    """跑 PowerShell 取文本。

    ★ 编码坑：Windows 上 PowerShell 默认按系统代码页（中文机=GBK/936）输出，
      直接用 encoding="utf-8" 解会得到乱码（实测系统名变成 "Microsoft Windows 11 ��ͥ��"）。
      解法：先让 PowerShell 自己输出 UTF-8（$OutputEncoding + chcp），再按 utf-8 解；
      解不出再回退 GBK。
    """
    wrapped = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
               "$OutputEncoding=[Text.Encoding]::UTF8;" + cmd)
    for enc in ("utf-8", "gbk"):
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", wrapped],
                               capture_output=True, text=True, timeout=timeout,
                               encoding=enc, errors="replace",
                               creationflags=NO_WIN)
            out = (r.stdout or "").strip()
            if out and "\ufffd" not in out:
                return out
            if out:
                return out        # 有内容但含替换符，交给调用方判断
        except Exception:
            continue
    return ""


def _kv(raw: str) -> dict:
    """解析 PowerShell Format-List 的 'Key : Value' 输出。"""
    out = {}
    for line in raw.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


@register
class HardwareCollector(Collector):
    """整机配置档案（静态身份，非运行状态）"""
    name = "hardware"

    def collect(self) -> List[Metric]:
        out: List[Metric] = []
        if sys.platform != "win32":
            out.append(Metric("hardware.platform", "平台", None,
                              status=Status.UNAVAILABLE,
                              note="仅 Windows 实现"))
            return out

        # ---------- CPU 型号 ----------
        cpu = _kv(_ps("Get-CimInstance Win32_Processor | "
                      "Select-Object -First 1 Name,NumberOfCores,"
                      "NumberOfLogicalProcessors,MaxClockSpeed | Format-List"))
        cname = cpu.get("name", "")
        if cname:
            out.append(Metric("hardware.cpu_model", "CPU 型号", None,
                              source="WMI/Win32_Processor", text=cname))
        else:
            out.append(Metric("hardware.cpu_model", "CPU 型号", None,
                              status=Status.UNAVAILABLE, source="WMI",
                              note="WMI Win32_Processor 无输出"))

        # ---------- 整机 / 主板 ----------
        cs = _kv(_ps("Get-CimInstance Win32_ComputerSystem | "
                     "Select-Object Manufacturer,Model | Format-List"))
        maker, model = cs.get("manufacturer", ""), cs.get("model", "")
        if maker or model:
            out.append(Metric("hardware.machine", "整机型号", None,
                              source="WMI/Win32_ComputerSystem",
                              text=("%s %s" % (maker, model)).strip()))
        else:
            out.append(Metric("hardware.machine", "整机型号", None,
                              status=Status.UNAVAILABLE, source="WMI",
                              note="Win32_ComputerSystem 无输出"))

        # ---------- 系统版本（判断能否用某些功能） ----------
        os_name = _ps("(Get-CimInstance Win32_OperatingSystem).Caption")
        if os_name:
            out.append(Metric("hardware.os", "操作系统", None,
                              source="WMI/Win32_OperatingSystem", text=os_name))

        return out
