# -*- coding: utf-8 -*-
"""disk.py — 磁盘空间 / IO / SMART 健康

实测本机：
  C 345/444GB (77.6%)、D 408/508GB (80.4%)、E 431/699GB (61.7%)
  Get-PhysicalDisk 能拿到 MediaType / HealthStatus / OperationalStatus
  SMART 预测失败需管理员，普通权限读不到 → 标 UNAVAILABLE 不报错
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from typing import List

import psutil

from ..core import Metric, Status
from .base import Collector, register

MB = 1024 * 1024
NO_WIN = 0x08000000


def _ps(cmd: str, timeout: int = 30):
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace",
                           creationflags=NO_WIN)
        return (r.stdout or "").strip()
    except Exception:
        return ""


@register
class DiskCollector(Collector):
    name = "disk"

    def collect(self) -> List[Metric]:
        out: List[Metric] = []

        # ---------- 各分区占用 ----------
        seen = set()
        for p in psutil.disk_partitions(all=False):
            mp = p.mountpoint
            if mp in seen:
                continue
            seen.add(mp)
            try:
                u = psutil.disk_usage(mp)
            except (PermissionError, OSError):
                out.append(Metric("disk.%s.percent" % _safe(mp), "分区 %s" % mp,
                                  None, "%", status=Status.UNAVAILABLE,
                                  source="psutil",
                                  note="无权限或设备未就绪（外接盘拔了？）"))
                continue
            if u.total == 0:
                continue
            tag = _safe(mp)
            out.append(Metric("disk.%s.percent" % tag, "分区 %s 占用" % mp,
                              round(u.percent, 1), "%", source="psutil",
                              note="%.0fGB / %.0fGB" % (u.used / 2**30, u.total / 2**30)))
            out.append(Metric("disk.%s.free_gb" % tag, "分区 %s 可用" % mp,
                              round(u.free / 2**30, 1), "GB", source="psutil"))

        # ---------- IO 吞吐 ----------
        try:
            io = psutil.disk_io_counters()
            if io:
                out.append(Metric("disk_io.read_gb", "磁盘累计读取",
                                  round(io.read_bytes / 2**30, 1), "GB",
                                  source="psutil"))
                out.append(Metric("disk_io.write_gb", "磁盘累计写入",
                                  round(io.write_bytes / 2**30, 1), "GB",
                                  source="psutil"))
        except Exception:
            pass

        # ---------- SMART 健康（Windows） ----------
        if sys.platform == "win32":
            raw = _ps("Get-PhysicalDisk -ErrorAction SilentlyContinue | "
                      "ForEach-Object { $_.DeviceId + '|' + $_.FriendlyName + '|' + "
                      "$_.MediaType + '|' + $_.HealthStatus + '|' + $_.OperationalStatus }")
            if raw:
                for line in raw.splitlines():
                    parts = line.split("|")
                    if len(parts) < 5:
                        continue
                    dev, nm, media, health, op = [x.strip() for x in parts[:5]]
                    tag = "disk%s" % dev
                    good = (health.lower() == "healthy" and op.lower() == "ok")
                    out.append(Metric("disk_health." + tag, "磁盘 %s" % nm,
                                      None, "",
                                      status=Status.OK if good else Status.ERROR,
                                      source="Get-PhysicalDisk",
                                      text="%s / %s / %s" % (
                                          media or "?", health or "?", op or "?"),
                                      note="" if good else "← 需要关注"))
            else:
                out.append(Metric("disk_health.status", "磁盘健康", None, "",
                                  status=Status.UNAVAILABLE, source="Get-PhysicalDisk",
                                  note="读不到（需管理员或该平台无此接口）"))

            # SMART 预测失败：普通权限读不到，明确标注
            sm = _ps("Get-CimInstance -Namespace root/WMI "
                     "-ClassName MSStorageDriver_FailurePredictStatus "
                     "-ErrorAction SilentlyContinue | ForEach-Object { "
                     "$_.InstanceName + '|' + $_.PredictFailure }")
            if sm:
                for line in sm.splitlines():
                    parts = line.split("|")
                    if len(parts) < 2:
                        continue
                    fail = parts[1].strip().lower() in ("true", "1")
                    out.append(Metric("disk_health.smart_predict", "SMART 故障预测",
                                      None, "",
                                      status=Status.ERROR if fail else Status.OK,
                                      source="WMI/MSStorageDriver",
                                      text="预测将故障" if fail else "未预测到故障",
                                      note="← 立刻备份！" if fail else ""))
            else:
                out.append(Metric("disk_health.smart_predict", "SMART 故障预测",
                                  None, "", status=Status.UNAVAILABLE,
                                  source="WMI/MSStorageDriver",
                                  note="需管理员权限才能读 SMART 预测"))

        return out


def _safe(mountpoint: str) -> str:
    """把 C:\\ 变成 c，/home 变成 home —— 用作指标名的合法片段"""
    s = mountpoint.replace(":\\", "").replace(":/", "").replace("\\", "").replace("/", "")
    return (s or "root").lower()[:12]
