# -*- coding: utf-8 -*-
"""advisor.py — 配置顾问：根据硬件档案 + 当前体检，给出「合理方案」并逐条可调

★ 产品逻辑（owner 定的）：
    检测电脑配置 → 推出一份合理方案 → 让用户决定用不用 / 逐条调整
  不是「我帮你改了」，是「我给你建议，你说了算」。

★ 三条设计铁律：
  1) 每条建议必须带「依据」（引用具体指标和阈值），不许空口说"建议升级"。
     无依据的建议 = 算命。
  2) 每条建议必须带「代价」（花钱/费电/有风险），让用户能权衡。
     只说好处不说代价 = 骗人。
  3) 建议分三档：
       safe    纯软件设置/使用习惯，零成本零风险，可随时改回
       cost    要花钱（加内存/换盘）
       risk    系统级改动（改电源计划/BIOS），不可逆或影响续航
     默认只展示，不执行。用户要哪条自己挑。

★ 与 guard.py 的区别：
    guard   = 现在有进程失控，要不要回收（运维动作）
    advisor = 你这台机器该怎么配怎么用（顾问建议）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .core import Metric, Status, THRESHOLDS

# 建议档位
SAFE = "safe"      # 零成本零风险，可逆
COST = "cost"      # 要花钱
RISK = "risk"      # 系统级/不可逆

TIER_TITLE = {
    SAFE: "① 现在就能做（零成本、可随时改回）",
    COST: "② 要花钱（升级硬件，先看值不值）",
    RISK: "③ 系统级改动（有代价，想清楚再动）",
}


# ---------------------------------------------------------------------------
# 从 Metric 里取配置档案
# ---------------------------------------------------------------------------
def _get(metrics: List[Metric], name: str) -> Optional[Metric]:
    for m in metrics:
        if m.name == name:
            return m
    return None


def _num(metrics: List[Metric], name: str) -> Optional[float]:
    m = _get(metrics, name)
    return m.value if (m and m.ok) else None


def _text(metrics: List[Metric], name: str) -> str:
    m = _get(metrics, name)
    if not m or not m.ok:
        return ""
    return m.text or ""


def build_profile(metrics: List[Metric]) -> Dict[str, Any]:
    """把散落的指标收拢成一份「机器画像」。"""
    return {
        "cpu_model": _text(metrics, "hardware.cpu_model"),
        "machine": _text(metrics, "hardware.machine"),
        "os": _text(metrics, "hardware.os"),
        "gpu_model": _text(metrics, "gpu.name"),
        "physical_cores": _num(metrics, "cpu.physical_cores"),
        "logical_cores": _num(metrics, "cpu.logical_cores"),
        "cpu_max_mhz": _num(metrics, "cpu.freq_max_mhz"),
        "mem_total_mb": _num(metrics, "memory.total_mb"),
        "vram_total_mb": _num(metrics, "gpu_mem.total_mb"),
        "cpu_max_state": _num(metrics, "power.cpu_max_state"),
        "scheme": _text(metrics, "power.active_scheme"),
    }


# ---------------------------------------------------------------------------
# 生成建议
# ---------------------------------------------------------------------------
def _advice(tier: str, title: str, why: str, how: str,
            gain: str = "", cost: str = "") -> Dict[str, str]:
    return {"tier": tier, "title": title, "why": why, "how": how,
            "gain": gain, "cost": cost}


def build_advice(metrics: List[Metric]) -> List[Dict[str, str]]:
    """根据实测数据生成建议。每条都有 why（依据）+ cost（代价）。"""
    p = build_profile(metrics)
    adv: List[Dict[str, str]] = []

    # ---------- 1) CPU 限频（这台机器最实在的问题） ----------
    ms = p["cpu_max_state"]
    if ms is not None and ms < 99:
        adv.append(_advice(
            RISK,
            "把 CPU 最大处理器状态从 %.0f%% 改回 100%%" % ms,
            "实测 CPU 最大状态=%.0f%%，当前频率只跑到最大值的 %.0f%% —— 睿频被系统限制住了，"
            "这是「慢」的直接原因，不是硬件不行" % (
                ms, (_num(metrics, "cpu.freq_ratio") or 0)),
            "控制面板 → 电源选项 → 更改计划设置 → 更改高级电源设置 → "
            "处理器电源管理 → 最大处理器状态 → 改成 100%",
            gain="CPU 能跑满睿频，重负载任务（渲染/编译/游戏）明显更快",
            cost="更费电、更热、风扇更响；笔记本续航下降。介意安静就保持现状"))

    # ---------- 2) 内存容量评估 ----------
    mem_total = p["mem_total_mb"]
    mem_pct = _num(metrics, "memory.percent")
    if mem_total and mem_total < 16384:
        adv.append(_advice(
            COST,
            "内存只有 %.0fGB，建议加到 32GB" % (mem_total / 1024),
            "实测物理内存 %.0fGB。当前已用 %.0f%%，可用仅 %.0fMB。"
            "视频渲染/AI 推理/多开浏览器这类活，16GB 是明显瓶颈" % (
                mem_total / 1024, mem_pct or 0,
                _num(metrics, "memory.available_mb") or 0),
            "买同规格 DDR5 SODIMM 内存条（笔记本注意是 SO-DIMM），"
            "本机是 2 插槽，先确认现有是 2×8 还是 1×16",
            gain="多任务不再卡顿、渲染不再爆内存",
            cost="约 300~500 元（32GB 套条）"))
    elif mem_total and mem_total >= 16384 and (mem_pct or 0) >= 85:
        adv.append(_advice(
            SAFE,
            "内存 %.0fGB 够用，但当前占用 %.0f%% 偏高 —— 先关掉不用的程序" % (
                mem_total / 1024, mem_pct or 0),
            "实测内存 %.0f%% 已用，但单进程最大才 %.0fMB，没有失控进程 —— "
            "说明是多任务叠加，不是泄漏" % (
                mem_pct or 0, _num(metrics, "process.max_mb") or 0),
            "跑 `python -m hwtriage --guard` 看哪些是重复副本；"
            "日常关掉不用的浏览器标签/后台应用",
            gain="立刻见效，零成本",
            cost="无"))

    # ---------- 3) 磁盘空间 ----------
    for letter in ("c", "d", "e"):
        pct = _num(metrics, "disk.%s.percent" % letter)
        free = _num(metrics, "disk.%s.free_gb" % letter)
        if pct is not None and pct >= 85:
            adv.append(_advice(
                SAFE,
                "%s 盘占用 %.0f%%，清理一下" % (letter.upper(), pct),
                "实测 %s 盘已用 %.0f%%，剩余 %.1fGB。系统盘超过 90%% 会明显掉速，"
                "SSD 写放大也会加剧" % (letter.upper(), pct, free or 0),
                "清临时文件、旧渲染中间帧、下载目录；"
                "视频项目的中间产物建议放外接盘",
                gain="系统更流畅，SSD 寿命更长",
                cost="无（删的是垃圾）"))

    # ---------- 4) CPU 温度读不到 → 提醒开权限（owner 要的"提醒一下"） ----------
    ct = _get(metrics, "cpu_temp.celsius")
    if ct and ct.status == Status.UNAVAILABLE:
        adv.append(_advice(
            SAFE,
            "开一个可选项：让工具能读到 CPU 温度",
            "当前 CPU 温度读不到。不是工具坏了 —— 读 CPU 温度需要管理员权限跑 "
            "LibreHardwareMonitor，普通权限系统不给",
            "右键「以管理员身份运行」`enable-cpu-temp.bat`，"
            "或在 LHM 里勾 Options → WMI Provider。不开也不影响其他功能",
            gain="能看到 CPU 温度，散热问题早发现",
            cost="需要一次管理员授权（只读传感器，不改任何设置）"))

    # ---------- 5) GPU 显存评估 ----------
    vram = p["vram_total_mb"]
    if vram and vram <= 8192:
        adv.append(_advice(
            SAFE,
            "显存 %.0fGB：跑大模型/高分辨率渲染要控制批次" % (vram / 1024),
            "实测显存总量 %.0fGB。8GB 显存跑 7B 以上模型或 4K 渲染容易爆" % (
                vram / 1024),
            "本地模型优先用量化版（Q4/Q5）；渲染降分辨率或用分块；"
            "`python -m hwtriage --guard` 可看显存实时占用",
            gain="避免爆显存导致的崩溃/重跑",
            cost="无"))

    return adv


def render_advice(metrics: List[Metric]) -> str:
    """渲染成给人看的方案表（按档位分组，每条带依据和代价）。"""
    p = build_profile(metrics)
    adv = build_advice(metrics)
    W = 74
    lines = ["=" * W, "配置顾问 · 这台机器怎么配怎么用", "=" * W]

    # ---- 机器画像 ----
    lines.append("")
    lines.append("── 你的机器 " + "─" * (W - 10))
    def show(label, val, unit=""):
        if val in (None, ""):
            return
        if isinstance(val, float):
            val = ("%.0f" % val)
        lines.append("   %-14s %s%s" % (label, val, unit))
    show("CPU", p["cpu_model"])
    if p["physical_cores"]:
        show("核心", "%d 物理 / %d 逻辑" % (p["physical_cores"], p["logical_cores"] or 0))
    show("显卡", p["gpu_model"])
    if p["vram_total_mb"]:
        show("显存", "%.0f GB" % (p["vram_total_mb"] / 1024))
    if p["mem_total_mb"]:
        show("内存", "%.0f GB" % (p["mem_total_mb"] / 1024))
    show("整机", p["machine"])
    show("系统", p["os"])

    # ---- 建议分档 ----
    if not adv:
        lines.append("")
        lines.append("没发现需要调整的地方，配置和当前用法是匹配的。")
    else:
        for tier in (SAFE, COST, RISK):
            group = [a for a in adv if a["tier"] == tier]
            if not group:
                continue
            lines.append("")
            lines.append("── %s " % TIER_TITLE[tier] + "─" * max(0, W - 6 - len(TIER_TITLE[tier])))
            for i, a in enumerate(group, 1):
                lines.append("")
                lines.append("  [%d] %s" % (i, a["title"]))
                lines.append("      依据：%s" % a["why"])
                if a.get("how"):
                    lines.append("      做法：%s" % a["how"])
                if a.get("gain"):
                    lines.append("      好处：%s" % a["gain"])
                if a.get("cost"):
                    lines.append("      代价：%s" % a["cost"])

    lines.append("")
    lines.append("=" * W)
    lines.append("以上只是建议，本工具不会替你改任何设置。用不用、改哪条，你定。")
    lines.append("要执行某条：照「做法」自己操作；想让我帮你改，明确说改哪条。")
    return "\n".join(lines)


def main(argv=None):
    from .collectors import base as _base
    metrics = _base.run_all()
    print(render_advice(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
