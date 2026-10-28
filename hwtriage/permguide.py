# -*- coding: utf-8 -*-
"""permguide.py — 权限引导：把「需要管理员」变成「友好提示」，绝不硬要

★ owner 定的产品原则（原话）：
    "如果发布到 GitHub 上，其他人也用了这个。那只是提醒他一下要不要开一下这个功能，
     到时候可以让其他人给你开一下权限。"
  → 核心：**只提醒，不强迫**。没权限照样能用，只是少了温度这项。

★ 三条铁律：
  1) 绝不自动提权。不弹 UAC、不写计划任务、不改注册表。
  2) 没权限不是错误，是"这个功能需要你点一下"。用 UNAVAILABLE 表达，不用 ERROR。
  3) 提示要具体到"点哪里"，不能只说"请以管理员运行"——用户不知道点哪。

★ 为什么单独一层：
    开源后用户环境千奇百怪（无 LHM、公司电脑禁管理员、Linux/Mac）。
    提示逻辑集中在这里，以后加平台只要改这一个文件。
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List

from .core import Metric, Status
from .paths import find_lhm, lhm_hint


def is_admin() -> bool:
    """当前是否管理员。非 Windows 返回 True（不需要这个判断）。"""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def find_lhm_exe() -> str:
    """兼容旧名：实际委托给 paths.find_lhm（跨机器自动发现）。"""
    return find_lhm()


def diagnose(metrics: List[Metric]) -> Dict[str, object]:
    """看当前有哪些功能因为权限/缺软件而不可用，给出针对性引导。

    返回 {blocked: [...], hint: "给人看的提示", optional: True}
    """
    blocked = []
    for m in metrics:
        if m.status != Status.UNAVAILABLE:
            continue
        if m.name in ("cpu_temp.celsius", "board_temp.celsius"):
            blocked.append("cpu_temp")
        elif m.name == "disk_health.smart_predict":
            blocked.append("smart")

    if not blocked:
        return {"blocked": [], "hint": "", "optional": True}

    admin = is_admin()
    lhm = find_lhm()
    lines = []

    if "cpu_temp" in blocked:
        if sys.platform != "win32":
            # 非 Windows：LibreHardwareMonitor 完全不适用，绝不该提 WMI / 提权
            lines.append("· CPU 温度：" + lhm_hint().replace("\n", "\n  "))
        elif not lhm:
            # Windows 但没装 LHM
            lines.append("· CPU 温度：" + lhm_hint().replace("\n", "\n  "))
        elif not admin:
            lines.append("· CPU 温度：LibreHardwareMonitor 已找到（%s）" % lhm)
            lines.append("  但读 CPU 温度需要管理员权限。想开的话：")
            lines.append("    右键它以「以管理员身份运行」→ 菜单 Options → 勾选 WMI Provider")
            lines.append("    （只读传感器数据，不改任何系统设置，随时可关）")
        else:
            lines.append("· CPU 温度：已是管理员且找到 LHM，但命名空间还没注册。")
            lines.append("  请确认 LHM 正在运行，且 Options → WMI Provider 已勾选。")

    if "smart" in blocked:
        if sys.platform == "win32" and not admin:
            lines.append("· SMART 硬盘故障预测：需要管理员权限读（不读也不影响磁盘空间/健康度显示）")
        elif sys.platform != "win32":
            lines.append("· SMART 硬盘故障预测：需要 root 读（不读也不影响磁盘空间/健康度显示）")

    if not lines:
        return {"blocked": blocked, "hint": "", "optional": True}

    hint = ("以下 %d 项需要额外授权，**不开也完全能用**，只是少了这几项数据：\n%s"
            % (len(blocked), "\n".join(lines)))
    return {"blocked": blocked, "hint": hint, "optional": True}


def render_hint(metrics: List[Metric]) -> str:
    """渲染成一段友好提示（不刷屏，只在有阻塞项时出现）。"""
    d = diagnose(metrics)
    if not d["hint"]:
        return ""
    return d["hint"]


def main(argv=None):
    from .collectors import base as _base
    metrics = _base.run_all()
    out = render_hint(metrics)
    print(out if out else "所有功能都可用，无需额外授权。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
