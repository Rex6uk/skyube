# -*- coding: utf-8 -*-
"""process.py — 进程级占用：找出真正的「大胃王」和「泄漏」

这一层是处置的依据，所以要给出「为什么判定它有问题」的证据，
不能只给一个数字。
"""
from __future__ import annotations

import re
import time
from typing import Dict, List

import psutil

from ..core import Metric, Status, is_protected
from .base import Collector, register

MB = 1024 * 1024


def _cmd(p) -> str:
    try:
        return " ".join(p.cmdline())
    except Exception:
        return ""


@register
class ProcessCollector(Collector):
    name = "process"

    def collect(self) -> List[Metric]:
        out: List[Metric] = []

        rows = []
        for p in psutil.process_iter(["pid", "name", "memory_info",
                                      "cpu_times", "create_time"]):
            try:
                rows.append({
                    "pid": p.info["pid"],
                    "name": p.info["name"] or "?",
                    "mb": p.info["memory_info"].rss / MB,
                    "cpu": sum(p.info["cpu_times"][:2]),
                    "age": time.time() - (p.info["create_time"] or time.time()),
                    "cmd": _cmd(p),
                })
            except Exception:
                continue

        out.append(Metric("process.count", "进程总数", len(rows), "个",
                          source="psutil"))

        # 按名字分组 —— 多进程软件（Chromium 系）必须合起来看
        groups: Dict[str, dict] = {}
        for r in rows:
            g = groups.setdefault(r["name"].lower(), {"n": 0, "mb": 0.0})
            g["n"] += 1
            g["mb"] += r["mb"]

        top_groups = sorted(groups.items(), key=lambda x: x[1]["mb"], reverse=True)[:5]
        for i, (nm, g) in enumerate(top_groups, 1):
            out.append(Metric("process.group%d_mb" % i,
                              "第%d大进程组 %s" % (i, nm),
                              round(g["mb"]), "MB", source="psutil/按名合并",
                              note="%d 个进程合计" % g["n"]))

        # 最大单进程
        if rows:
            big = max(rows, key=lambda x: x["mb"])
            out.append(Metric("process.max_mb", "最大单进程内存",
                              round(big["mb"]), "MB", source="psutil",
                              note="%s pid=%d%s" % (
                                  big["name"], big["pid"],
                                  "（受保护）" if is_protected(big["name"], big["cmd"]) else "")))

        # ---------- 泄漏检测：命令行完全相同的多份并发 ----------
        # ★ 必须排除系统自带的"天然多实例"进程，否则全是假阳性。
        # 实测：conhost.exe 23 份、RuntimeBroker.exe 5 份都是正常的，
        # 它们命令行相同是因为由系统统一拉起，不是泄漏。
        MULTI_INSTANCE_OK = {
            "conhost.exe", "runtimebroker.exe", "svchost.exe", "dllhost.exe",
            "wmiprvse.exe", "taskhostw.exe", "searchprotocolhost.exe",
            "searchfilterhost.exe", "sihost.exe", "ctfmon.exe",
            "msedgewebview2.exe", "chrome.exe", "msedge.exe",
            "powershell.exe", "pwsh.exe", "cmd.exe", "bash.exe",
        }
        # ★ node.exe 绝不能排除 —— MCP 泄漏正是 node.exe 同命令行多份，
        #   排除它就等于把唯一要抓的漏掉了（这个坑差点踩到）。
        dup: Dict[str, List[int]] = {}
        for r in rows:
            if r["name"].lower() in MULTI_INSTANCE_OK:
                continue
            key = re.sub(r"\s+", " ", r["cmd"].strip())
            if len(key) < 20:
                continue
            if key.lower() in ("python.exe", "node.exe", "pythonw.exe"):
                continue
            dup.setdefault(key, []).append(r["pid"])

        leaks = [(k, v) for k, v in dup.items() if len(v) >= 2]
        out.append(Metric("process.dup_groups", "重复命令行组数", len(leaks),
                          "组", source="psutil",
                          note=("; ".join("%d份: %s" % (len(v), k[:60])
                                          for k, v in leaks[:3])
                                if leaks else "无重复，正常")))
        if leaks:
            out.append(Metric("process.dup_detail", "重复副本明细", None, "",
                              source="psutil",
                              text=" | ".join("%d份 pid=%s" % (len(v), ",".join(map(str, v)))
                                              for _, v in leaks[:5])))

        # ---------- 失控候选：单进程超绝对+比例双阈值 ----------
        total_mb = psutil.virtual_memory().total / MB
        from ..core import THRESHOLDS
        t = THRESHOLDS["memory"]
        hogs = [r for r in rows
                if r["mb"] >= t["hog_mb"] and r["mb"] / total_mb >= t["hog_share"]]
        out.append(Metric("process.hog_count", "失控进程数", len(hogs), "个",
                          source="psutil",
                          note=("; ".join("%s pid=%d %.0fMB" % (h["name"], h["pid"], h["mb"])
                                          for h in hogs) if hogs
                                else "无（判据: >%dMB 且 >%d%% 物理内存）"
                                     % (t["hog_mb"], int(t["hog_share"] * 100)))))

        return out
