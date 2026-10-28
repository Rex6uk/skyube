# -*- coding: utf-8 -*-
"""report.py — 报告层：把 Metric 列表渲染成给人看的体检表

★ 与采集层(collectors)、处置层(guard)严格分离。本层只「读」Metric、只「渲染」，
  不采集、不判定阈值（阈值判定复用 core.level_of）、不处置进程。

设计要点：
  1) 异常项（WARN/ACT/CRITICAL）用 level_of 判定，带等级图标(!!/XX)一眼能看出。
  2) 读不到的项（status=UNAVAILABLE/ERROR，value=None）单独归档到「读不到」区，
     绝不和故障混在一起 —— 读不到 ≠ 坏了，可能是平台/硬件不暴露（如 CPU 温度）。
  3) 三种模式：
       full  完整体检表（人读，正常+异常+读不到全列）
       brief 只列异常+读不到（每日巡检/手测）
       cron  静默模式，挂定时任务用 —— 没异常就一个字都不输出，有异常才打印精简报告。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from .core import Level, Metric, Status, level_of

# 等级图标（与 cli.py 保持一致的 ASCII 安全字符，避免 Windows 控制台编码问题）
ICON = {Level.OK: "  ", Level.WARN: "! ", Level.ACT: "!!", Level.CRITICAL: "XX"}
BADGE = {Status.OK: "", Status.UNAVAILABLE: "[不可读]",
         Status.ERROR: "[错误]", Status.STALE: "[过期]"}

# 分组顺序 / 中文标题（与 cli.py 保持一致）
DOMAIN_ORDER = [
    "memory", "swap", "cpu", "gpu_mem", "gpu", "gpu_temp", "gpu_power",
    "cpu_temp", "board_temp", "disk", "disk_io", "disk_health",
    "disk_temp", "battery", "power", "process",
]
DOMAIN_TITLE = {
    "memory": "内存", "swap": "交换区", "cpu": "CPU",
    "gpu_mem": "显存", "gpu": "GPU", "gpu_temp": "GPU 温度",
    "gpu_power": "GPU 功耗", "cpu_temp": "CPU 温度",
    "board_temp": "主板温度", "disk": "磁盘空间",
    "disk_io": "磁盘 IO", "disk_health": "磁盘健康",
    "disk_temp": "硬盘温度", "battery": "电池",
    "power": "电源", "process": "进程",
}

WIDTH = 74
_LV_ORDER = {Level.CRITICAL: 0, Level.ACT: 1, Level.WARN: 2}


def format_value(m: Metric) -> str:
    """把 Metric 格式化成可读字符串（文本型读 text，None → 破折号）。"""
    if m.text:                       # 文本型读数优先
        return m.text
    if m.value is None:
        return "—"
    v = m.value
    if m.unit == "%":
        return "%.1f%%" % v
    if isinstance(v, float) and v == int(v):
        s = "%d" % int(v)
    elif isinstance(v, float):
        s = "%.1f" % v
    else:
        s = str(v)
    if m.unit and m.unit != "%":
        s += " " + m.unit
    return s


def _domain(name: str) -> str:
    return name.split(".")[0]


def categorize(metrics: List[Metric]) -> Tuple[List[Tuple[Level, Metric]],
                                               List[Metric], List[Metric]]:
    """把 Metric 分成三类：异常(含等级) / 读不到 / 正常。"""
    anomalies: List[Tuple[Level, Metric]] = []
    unread: List[Metric] = []
    normal: List[Metric] = []
    for m in metrics:
        if not m.ok:                       # UNAVAILABLE / ERROR / STALE → 读不到
            unread.append(m)
            continue
        lv = level_of(m.name, m.value)
        if lv != Level.OK:
            anomalies.append((lv, m))
        else:
            normal.append(m)
    anomalies.sort(key=lambda x: _LV_ORDER.get(x[0], 9))
    return anomalies, unread, normal


def _section_header(title: str) -> str:
    return "── %s " % title + "─" * max(0, WIDTH - 4 - len(title))


def _emit_metric(lines: List[str], m: Metric, lv: Level = Level.OK) -> None:
    icon = ICON.get(lv, "  ")
    line = "  %s %-22s %12s %s" % (icon, m.label, format_value(m), BADGE.get(m.status, ""))
    lines.append(line.rstrip())
    if m.note:
        lines.append("       └ %s" % m.note[:110])


def render_full(metrics: List[Metric], now: Optional[datetime] = None) -> List[str]:
    """完整体检表：正常 + 异常分组展示，读不到单独归档，末尾给汇总。"""
    now = now or datetime.now()
    lines: List[str] = []
    lines.append("=" * WIDTH)
    lines.append("硬件状态体检   " + now.strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("=" * WIDTH)

    anomalies, unread, normal = categorize(metrics)

    grouped = {}
    for m in normal + [a[1] for a in anomalies]:
        grouped.setdefault(_domain(m.name), []).append(m)
    domains = [d for d in DOMAIN_ORDER if d in grouped] + \
              [d for d in grouped if d not in DOMAIN_ORDER]

    for d in domains:
        items = grouped[d]
        lines.append("")
        lines.append(_section_header(DOMAIN_TITLE.get(d, d)))
        for m in items:
            lv = level_of(m.name, m.value) if m.ok else Level.OK
            _emit_metric(lines, m, lv)

    # ---------- 读不到：单独归类，绝不混进故障 ----------
    if unread:
        lines.append("")
        lines.append(_section_header("读不到（非故障）"))
        for m in unread:
            _emit_metric(lines, m)

    # ---------- 汇总 ----------
    lines.append("")
    lines.append("=" * WIDTH)
    if anomalies:
        lines.append("需要关注 %d 项：" % len(anomalies))
        for lv, m in anomalies:
            _emit_metric(lines, m, lv)
    else:
        lines.append("全部正常，无需处置。")
    if unread:
        names = "、".join(m.label for m in unread[:12])
        if len(unread) > 12:
            names += " 等 %d 项" % len(unread)
        lines.append("")
        lines.append("读不到 %d 项（平台/硬件不暴露，非故障）：%s" % (len(unread), names))
    lines.append("=" * WIDTH)
    return lines


def render_brief(metrics: List[Metric], now: Optional[datetime] = None) -> List[str]:
    """精简模式：只列异常 + 读不到（每日巡检/手测用，不含正常项）。"""
    now = now or datetime.now()
    lines: List[str] = []
    lines.append("=" * WIDTH)
    lines.append("硬件状态体检（精简）   " + now.strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("=" * WIDTH)

    anomalies, unread, _ = categorize(metrics)
    if anomalies:
        lines.append("需要关注 %d 项：" % len(anomalies))
        for lv, m in anomalies:
            _emit_metric(lines, m, lv)
    else:
        lines.append("无异常。")

    if unread:
        lines.append("")
        lines.append("读不到 %d 项（非故障）：" % len(unread))
        for m in unread:
            _emit_metric(lines, m)

    lines.append("=" * WIDTH)
    return lines


def render_cron(metrics: List[Metric], now: Optional[datetime] = None) -> List[str]:
    """静默模式（挂 cron 用）。

    ★ 没异常就返回空列表 —— 一个字都不输出，cron 邮件/日志保持干净。
    ★ 一旦有异常，才打印一行摘要 + 异常项，读不到项只给计数不刷屏。
    """
    anomalies, unread, _ = categorize(metrics)
    if not anomalies:
        return []

    now = now or datetime.now()
    lines: List[str] = []
    lines.append("[HWTriage %s] 需要关注 %d 项："
                 % (now.strftime("%Y-%m-%d %H:%M"), len(anomalies)))
    for lv, m in anomalies:
        _emit_metric(lines, m, lv)
    if unread:
        names = "、".join(m.label for m in unread[:10])
        if len(unread) > 10:
            names += " 等"
        lines.append("  读不到 %d 项（非故障）：%s" % (len(unread), names))
    return lines


def render(metrics: List[Metric], mode: str = "full",
           now: Optional[datetime] = None) -> str:
    """统一入口：mode ∈ {full, brief, cron}，返回拼接好的字符串。"""
    if mode == "brief":
        ls = render_brief(metrics, now)
    elif mode == "cron":
        ls = render_cron(metrics, now)
    else:
        ls = render_full(metrics, now)
    return "\n".join(ls)


def _demo() -> None:
    """python -m hwtriage.report 自测：跑全部采集器 + 三种渲染。"""
    from .collectors import base as _base
    metrics = _base.run_all()
    for mode in ("full", "brief", "cron"):
        print("########## mode=%s ##########" % mode)
        print(render(metrics, mode))
        print()


if __name__ == "__main__":
    _demo()
