# -*- coding: utf-8 -*-
"""paths.py — 跨机器路径发现（唯一允许知道"东西装在哪"的地方）

★ 为什么要有这个模块：
    开源后别人的电脑上，LibreHardwareMonitor 可能装在 C:\\Program Files、
    可能装在 D:\\Tools、可能压根没装；Python 也可能在别处。
    代码里写死 D:\\Tools\\... 就等于"只有我这台能跑"。

★ 设计原则：
    1) 任何模块都不许自己拼绝对路径，一律问这里。
    2) 查找顺序：环境变量 > 常见安装位置 > 全盘轻量搜索 > 找不到返回空。
    3) 找不到不是错误 —— 返回空串，调用方转成 UNAVAILABLE + 给安装提示。
    4) 允许用户用环境变量覆盖：HWTRIAGE_LHM_PATH。

★ 为什么不用注册表/全盘 walk：
    全盘 walk 在机械盘上要几分钟（实测外接 HDD 会卡死），
    所以只查常见位置 + 已装程序的目录，够用且快。
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import List, Optional

LHM_EXE_NAME = "LibreHardwareMonitor.exe"


def _env_path(*names: str) -> str:
    """按顺序取环境变量里的路径，存在则返回。"""
    for n in names:
        v = os.environ.get(n, "").strip().strip('"')
        if v:
            # 允许指向目录或 exe
            if os.path.isdir(v):
                cand = os.path.join(v, LHM_EXE_NAME)
                if os.path.isfile(cand):
                    return cand
            elif os.path.isfile(v):
                return v
    return ""


def find_lhm() -> str:
    """找 LibreHardwareMonitor.exe。找不到返回空串（不抛异常）。

    查找顺序（快 → 慢，找到即停）：
      1) 环境变量 HWTRIAGE_LHM_PATH / LHM_PATH
      2) PATH 里直接有 LibreHardwareMonitor
      3) 各盘常见安装位置（Program Files / Tools / 用户目录 / 便携版）
      4) 已装程序目录（AppData\\Local\\Programs）
    """
    # 1) 环境变量优先（用户可显式指定）
    hit = _env_path("HWTRIAGE_LHM_PATH", "LHM_PATH")
    if hit:
        return hit

    # 2) PATH 查找
    hit = shutil.which("LibreHardwareMonitor")
    if hit:
        return hit

    # 3) 常见安装位置（跨机器通用，不写死盘符）
    candidates: List[str] = []
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    localapp = os.environ.get("LOCALAPPDATA", "")
    home = os.path.expanduser("~")

    bases = [pf, pf86, localapp, home,
             os.path.join(home, "Downloads"),
             os.path.join(home, "Desktop")]
    # 只在这些目录的直接子层找，不递归太深（避免全盘 walk 卡死）
    for b in bases:
        if not b:
            continue
        candidates.append(os.path.join(b, "LibreHardwareMonitor", LHM_EXE_NAME))
        candidates.append(os.path.join(b, "Tools", "LibreHardwareMonitor", LHM_EXE_NAME))
        candidates.append(os.path.join(b, "Programs", "LibreHardwareMonitor", LHM_EXE_NAME))

    # 4) 各固定盘符的 Tools 目录（不 walk，只查一层）
    for drive in ("C:", "D:", "E:", "F:"):
        candidates.append(os.path.join(drive + os.sep, "Tools",
                                       "LibreHardwareMonitor", LHM_EXE_NAME))
        candidates.append(os.path.join(drive + os.sep, "LibreHardwareMonitor",
                                       LHM_EXE_NAME))

    for c in candidates:
        try:
            if os.path.isfile(c):
                return c
        except Exception:
            continue

    # 5) 最后：在几个常见父目录下扫一层子目录（仍不深度递归）
    for b in (os.environ.get("ProgramFiles", ""), localapp,
              os.path.join(home, "AppData", "Local", "Programs")):
        if not b or not os.path.isdir(b):
            continue
        try:
            for name in os.listdir(b):
                if "librehardware" in name.lower():
                    cand = os.path.join(b, name, LHM_EXE_NAME)
                    if os.path.isfile(cand):
                        return cand
        except Exception:
            continue

    return ""


def find_python() -> str:
    """当前解释器路径（脚本里要用同一个 Python 跑子进程时用这个）。"""
    return sys.executable or "python"


def lhm_hint() -> str:
    """没找到 LHM 时给用户看的安装提示（跨平台友好）。"""
    if sys.platform == "win32":
        return ("没找到 LibreHardwareMonitor。它免费开源，下载解压即用，不用安装：\n"
                "  https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases\n"
                "下载后解压到任意目录，然后设置环境变量告诉本工具：\n"
                "  set HWTRIAGE_LHM_PATH=<你解压的目录>\n"
                "（或者放到 C:\\Program Files\\LibreHardwareMonitor\\ 会自动识别）")
    return ("当前系统不通过 LibreHardwareMonitor 读温度（它是 Windows 专用）。\n"
            "Linux 用 lm-sensors，macOS 用 istats —— 本工具会自动尝试 psutil。")


def summary() -> str:
    """诊断用：打印各关键路径的发现结果。"""
    lhm = find_lhm()
    lines = [
        "平台      : %s" % sys.platform,
        "Python    : %s" % find_python(),
        "LHM       : %s" % (lhm or "未找到"),
        "LHM 环境变量: %s" % (os.environ.get("HWTRIAGE_LHM_PATH") or "(未设置)"),
    ]
    return "\n".join(lines)
