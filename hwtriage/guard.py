# -*- coding: utf-8 -*-
"""guard.py — 处置层：按 level 分级处置，默认**只出计划不执行**

★ 铁律（血泪教训）：
  1) 默认 dry-run：build_plan() 只算「该处置什么」，绝不杀进程。
     真要执行必须显式 execute_plan(plan, apply=True)，且只处理 WARN 以上。
  2) 保护名单复用 core.is_protected —— 只匹配可执行文件名/完整脚本名，
     严禁放泛词（踩过 "mcp" 和 "gateway" 两个坑，会误保护/误杀一大片）。
  3) 分级处置：
       WARN      → 只报告，不动
       ACT       → 回收工作集（EmptyWorkingSet，温和、可逆）
       CRITICAL  → 才允许 kill 进程（且必须在保护名单之外）
  4) 只碰「失控的内存大户」和「重复副本」，用户正在用的进程一律保护。

teleguard 设计参照：日志/终端不许静默吞错，每个动作都要有回执。

说明：process.py 采集器只给聚合指标（组内存/总数），没有逐 pid 明细，
      所以处置层直接只读扫描 psutil 拿到真实候选，再用 core 阈值判定。
"""
from __future__ import annotations

import ctypes
import re
from typing import List, Dict, Any

from .core import Level, Metric, THRESHOLDS, is_protected

MB = 1024 * 1024
T_MEM = THRESHOLDS["memory"]
HOG_MB = T_MEM["hog_mb"]          # 单进程绝对阈值 3000MB
HOG_SHARE = T_MEM["hog_share"]    # 单进程比例阈值 0.18

# 天然多实例进程（系统/浏览器），不当作泄漏（与 process.py 保持一致口径）
MULTI_INSTANCE_OK = {
    "conhost.exe", "runtimebroker.exe", "svchost.exe", "dllhost.exe",
    "wmiprvse.exe", "taskhostw.exe", "searchprotocolhost.exe",
    "searchfilterhost.exe", "sihost.exe", "ctfmon.exe",
    "msedgewebview2.exe", "chrome.exe", "msedge.exe",
    "powershell.exe", "pwsh.exe", "cmd.exe", "bash.exe",
}


# ---------------------------------------------------------------------------
# 计划构建（只读）
# ---------------------------------------------------------------------------
def _scan() -> List[Dict[str, Any]]:
    """只读扫描进程，返回 [{pid,name,mb,cmd}]。psutil 缺失则空。"""
    rows: List[Dict[str, Any]] = []
    try:
        import psutil
    except Exception:
        return rows
    for p in psutil.process_iter(["pid", "name", "memory_info", "cmdline"]):
        try:
            mi = p.info.get("memory_info")
            if not mi:
                continue
            rows.append({
                "pid": p.info["pid"],
                "name": (p.info.get("name") or "?"),
                "mb": mi.rss / MB,
                "cmd": " ".join(p.info.get("cmdline") or []),
            })
        except Exception:
            continue
    return rows


def build_plan(metrics: List[Metric] = None) -> Dict[str, Any]:
    """算出处置计划（纯函数，不产生副作用）。

    metrics 参数保留兼容（CLI 传入），但真实候选以 psutil 只读扫描为准。
    """
    rows = _scan()
    try:
        import psutil
        total_mb = psutil.virtual_memory().total / MB
    except Exception:
        total_mb = 0.0

    actions: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    notes: List[str] = []

    # ---- 1) 内存大户 / 失控判定 ----
    for r in rows:
        mb = r["mb"]
        pct = (mb / total_mb * 100.0) if total_mb else 0.0
        if mb < HOG_MB and pct < T_MEM["act"]:
            continue
        if is_protected(r["name"], r["cmd"]):
            skipped.append({"pid": r["pid"], "name": r["name"], "why": "保护名单"})
            continue
        if pct >= T_MEM["critical"]:
            kind, level = "kill", Level.CRITICAL.value
        elif pct >= T_MEM["act"] or (mb >= HOG_MB and (mb / total_mb) >= HOG_SHARE
                                     if total_mb else False):
            kind, level = "empty_working_set", Level.ACT.value
        else:
            continue
        actions.append({
            "pid": r["pid"], "name": r["name"], "kind": kind, "level": level,
            "reason": "内存 %.0fMB（占物理 %.1f%%）" % (mb, pct),
        })

    # ---- 2) 重复命令行副本（泄漏候选） ----
    dup: Dict[str, List[int]] = {}
    name_of: Dict[str, str] = {}
    for r in rows:
        if r["name"].lower() in MULTI_INSTANCE_OK:
            continue
        key = re.sub(r"\s+", " ", r["cmd"].strip())
        if len(key) < 20 or key.lower() in ("python.exe", "node.exe", "pythonw.exe"):
            continue
        dup.setdefault(key, []).append(r["pid"])
        name_of[key] = r["name"]
    for key, pids in dup.items():
        if len(pids) < 2:
            continue
        nm = name_of[key]
        if is_protected(nm, key):
            skipped.append({"pid": "多", "name": nm, "why": "重复副本·保护名单"})
            continue
        for pid in pids:
            actions.append({
                "pid": pid, "name": nm, "kind": "empty_working_set",
                "level": Level.ACT.value,
                "reason": "重复命令行 %d 份之一（疑似泄漏，仅温和回收）" % len(pids),
            })

    # ---- 3) 内存整体告警（只提示，不动手） ----
    for m in (metrics or []):
        if m.name.startswith("memory.percent") and m.ok:
            notes.append("内存整体 %.1f%% — 处置层只回收上表大户工作集，不整体杀进程"
                         % m.value)

    return {"actions": actions, "skipped": skipped, "notes": notes,
            "thresholds": {"hog_mb": HOG_MB, "hog_share": HOG_SHARE},
            "scanned": len(rows)}


def render_plan(plan: Dict[str, Any]) -> str:
    """把计划渲染成给人看的文本（dry-run 输出）。"""
    lines = ["=" * 74, "处置计划（dry-run，未执行任何动作）", "=" * 74]
    th = plan.get("thresholds") or {}
    lines.append("已扫描进程 %d 个；阈值 hog≥%sMB、act=%s%%、crit=%s%%"
                 % (plan.get("scanned", 0), th.get("hog_mb", HOG_MB),
                    T_MEM["act"], T_MEM["critical"]))
    acts = plan.get("actions") or []
    if not acts:
        lines.append("")
        lines.append("无需处置。")
    else:
        lines.append("")
        lines.append("建议处置 %d 项：" % len(acts))
        for a in acts:
            lines.append("  [%s] pid=%-7s %-24s %-8s ← %s"
                         % (a["kind"], a["pid"], a["name"], a["level"], a["reason"]))
    skipped = plan.get("skipped") or []
    if skipped:
        lines.append("")
        lines.append("跳过 %d 项（受保护）：" % len(skipped))
        for s in skipped[:12]:
            lines.append("  · pid=%-7s %-24s %s" % (s["pid"], s["name"], s["why"]))
        if len(skipped) > 12:
            lines.append("  … 另有 %d 项" % (len(skipped) - 12))
    for n in plan.get("notes") or []:
        lines.append("")
        lines.append("注：" + n)
    lines.append("=" * 74)
    lines.append("要真正执行：python -m hwtriage.guard --apply（CRITICAL 才会杀，"
                 "保护名单永不碰）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 执行（唯一会改系统状态的地方，默认关闭）
# ---------------------------------------------------------------------------
def _empty_working_set(pid: int) -> bool:
    """温和回收某进程工作集（可逆，不杀进程）。失败返回 False。"""
    try:
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_QUERY_LIMITED = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED,
            False, pid)
        if not handle:
            return False
        try:
            # psapi.EmptyWorkingSet
            ok = ctypes.windll.psapi.EmptyWorkingSet(handle)
            return bool(ok)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return False


def _kill(pid: int) -> bool:
    import os
    import signal
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


def execute_plan(plan: Dict[str, Any], apply: bool = False) -> List[str]:
    """执行计划。apply=False 时只回显，不做任何操作。

    返回每步的回执日志行（绝静默）。
    """
    log: List[str] = []
    if not apply:
        log.append("[dry-run] 未执行。加 --apply 才会回收/杀进程。")
        return log
    for a in plan.get("actions") or []:
        if a["kind"] == "empty_working_set":
            ok = _empty_working_set(a["pid"])
            log.append("回收工作集 pid=%s %s → %s"
                       % (a["pid"], a["name"], "成功" if ok else "失败/无权限"))
        elif a["kind"] == "kill" and a["level"] == Level.CRITICAL.value:
            ok = _kill(a["pid"])
            log.append("终止进程 pid=%s %s → %s"
                       % (a["pid"], a["name"], "成功" if ok else "失败"))
        else:
            log.append("跳过 pid=%s %s（等级 %s 不执行）" % (a["pid"], a["name"], a["level"]))
    return log


def main(argv=None):
    import sys
    argv = argv or sys.argv[1:]
    from .collectors import base as _base
    metrics = _base.run_all(only="memory")   # 内存整体指标（plan 备注用）
    plan = build_plan(metrics)
    print(render_plan(plan))
    if "--apply" in argv:
        print("\n执行：")
        for line in execute_plan(plan, apply=True):
            print("  " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
