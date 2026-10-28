# -*- coding: utf-8 -*-
"""core.py — 统一数据模型 + 阈值配置 + 状态判定

所有采集器都必须返回 Metric 对象，不许直接 print 或返回裸数字。
这样做的原因：**读不到的数据必须显式标记为 unavailable，而不是返回 0 冒充**。
曾经踩过：某个采集器读不到温度就返回 0，面板上显示「CPU 0℃」，看着很健康，
实际是传感器没接通。这类"假绿"比报警更危险。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class Status(str, Enum):
    OK = "ok"                # 读到有效数据
    UNAVAILABLE = "unavailable"   # 该平台/该硬件不支持，不是错误
    ERROR = "error"          # 本该能读但读失败（权限、驱动、超时）
    STALE = "stale"          # 上次读到了，本次超时未更新


class Level(str, Enum):
    OK = "ok"          # 正常
    WARN = "warn"      # 偏高，仅提示
    ACT = "act"        # 达到处置线
    CRITICAL = "critical"  # 危险，必须立刻处理


@dataclass
class Metric:
    """单个指标的标准化载体。

    两种读数形态，二选一：
      1) 数值型：value=<float>，status=OK
      2) 文本型：text="<字符串>"，status=OK（如显卡型号、电源方案名、P8 状态、磁盘健康）
      读不到：value=None 且 text="" 且 status=UNAVAILABLE/ERROR，必须带 note 说明原因。

    ★ 历史坑：以前只有 value(float)，文本型读数（显卡型号/P8/健康度/电源方案）
      无处安放，只能塞进 note 并标 UNAVAILABLE —— 结果"读到了却报读不到"，
      6 项假红把真问题淹掉。假红和假绿一样有害。text 字段就是为此加的。
    """
    name: str                 # 机器可读键，如 "memory.percent"
    label: str                # 人可读名，如 "内存占用"
    value: Optional[float]    # 数值；不可用时为 None
    unit: str = ""            # "%", "MB", "C", "MHz", "W"
    status: Status = Status.OK
    source: str = ""          # 数据来源，如 "psutil" / "nvidia-smi"
    note: str = ""            # 不可用的原因 / 补充说明
    text: str = ""            # 文本型读数（显卡型号/P8/健康度/电源方案名）
    ts: float = field(default_factory=time.time)

    def __post_init__(self):
        has_value = self.value is not None
        has_text = bool(self.text)
        if self.status == Status.OK and not has_value and not has_text:
            raise ValueError(
                "Metric(%s): status=OK 但 value 和 text 都空 —— "
                "读不到数据必须标 UNAVAILABLE/ERROR" % self.name)
        if self.status in (Status.UNAVAILABLE, Status.ERROR) and not self.note:
            raise ValueError(
                "Metric(%s): status=%s 但没有 note 说明原因" % (self.name, self.status))

    @property
    def ok(self) -> bool:
        return self.status == Status.OK

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# ---------------------------------------------------------------------------
# 阈值配置
# ---------------------------------------------------------------------------
# 原则：比例阈值必须设在「比绝对阈值低」的位置，否则绝对阈值形同虚设。
# 实测踩坑：失控判据写成「>3GB 且 >25%」，16GB 机器上 25%=3853MB 比 3GB 高，
# 3~3.8GB 的进程全部漏判，而且不报错、只是什么都不做。
#
# 本机基线：15.1GB 内存 / RTX 5060 8GB 显存 / 16 物理核 / 32 逻辑核
# 8GB 机器请整体下调 memory.warn 到 80，gpu 阈值不变
THRESHOLDS = {
    "memory": {
        "warn": 85, "act": 90, "critical": 95,
        "hog_mb": 3000,        # 单进程失控的绝对阈值
        "hog_share": 0.18,     # 单进程失控的比例阈值（必须 < hog_mb/物理内存）
    },
    "swap": {
        "warn": 50, "act": 70, "critical": 85,
    },
    "cpu": {
        "warn": 85, "act": 95, "critical": 99,
        "sustained_sec": 60,   # 持续多久才算"高负载"，瞬时飙高不算
    },
    "cpu_temp": {
        "warn": 85, "act": 95, "critical": 100,   # 笔记本 CPU 常见上限 100℃
    },
    "gpu_mem": {
        "warn": 85, "act": 92, "critical": 96,
    },
    "gpu_temp": {
        "warn": 80, "act": 88, "critical": 92,    # 笔记本 GPU 常见上限 87~95℃
    },
    "gpu_power": {
        "warn": 90, "act": 100, "critical": 110,  # 相对 power.limit 的百分比
    },
    "power": {
        "warn": 90, "act": 100, "critical": 110,   # cpu_max_state: 100 正常
    },
    "disk": {
        "warn": 85, "act": 92, "critical": 96,
    },
    "disk_temp": {
        "warn": 50, "act": 60, "critical": 70,
    },
    "process": {
        "warn": 999999, "act": 999999, "critical": 999999,  # 进程数不设阈值
    },
}


def level_of(metric_name: str, value: Optional[float]) -> Level:
    """按指标名找对应阈值段，返回等级。

    ★ 关键：只有「占用率」类指标才参与阈值判定。
      指标名以 _mb / _gb / _mhz / _w / count / cores / total 等结尾的，
      是绝对量或容量，不能拿去跟百分比阈值比 ——
      否则 15414MB 内存总量会因为 >95 被判成「危险」，面板全是假红。

    阈值域映射：指标名 <domain>.<field> 取 domain；
    但 gpu_mem / gpu_temp / gpu_power / disk_temp / disk_health 这类双段域要特判。
    """
    if value is None:
        return Level.OK

    parts = metric_name.split(".")
    domain = parts[0]
    field = parts[1] if len(parts) > 1 else ""

    # 只有这些字段才是「占用率」，才有阈值可言
    RATE_FIELDS = {
        "percent", "sustained_percent", "max_core_percent", "commit_percent",
        "util_percent", "fan_percent", "celsius", "watts", "ratio",
        "freq_ratio", "cpu_max_state", "thermal_events_24h",
    }
    if field not in RATE_FIELDS:
        return Level.OK

    # cpu_max_state 是「越高越好」，方向相反，单独处理
    if field == "cpu_max_state":
        return Level.OK if value >= 99 else Level.WARN

    # 温度/功耗这类按实际值比，不是百分比
    t = THRESHOLDS.get(domain)
    if not t:
        return Level.OK

    if "critical" in t and value >= t["critical"]:
        return Level.CRITICAL
    if "act" in t and value >= t["act"]:
        return Level.ACT
    if "warn" in t and value >= t["warn"]:
        return Level.WARN
    return Level.OK


# ---------------------------------------------------------------------------
# 保护名单
# ---------------------------------------------------------------------------
# ★ 铁律：不许放泛词。
# 踩过两次：
#   1) 放了 "mcp" → 所有 MCP 泄漏副本都被保护，永远清不掉
#   2) 放了 "gateway" → 路径里含 gateway 字样的无关进程也被保护
# 规则必须匹配「可执行文件名」或「完整脚本名」，不能匹配可能在路径中出现的单词。
PROTECT_NAMES = {
    # 系统核心
    "system", "system idle process", "registry", "memory compression",
    "csrss.exe", "wininit.exe", "services.exe", "lsass.exe", "smss.exe",
    "winlogon.exe", "fontdrvhost.exe", "svchost.exe", "dwm.exe",
    "explorer.exe", "sihost.exe", "ctfmon.exe", "taskhostw.exe",
    "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "textinputhost.exe", "applicationframehost.exe",
    # 安全
    "securityhealthsystray.exe", "msmpeng.exe", "nissrv.exe",
    # 输入法（杀了打不出中文）
    "handy.exe", "chime.exe", "sogouinput.exe",
    # 通信（用户可能正在聊）
    "clawchat.exe", "wechat.exe", "wxwork.exe", "qq.exe", "telegram.exe",
    # 浏览器/编辑器（用户可能正在用）
    "msedge.exe", "chrome.exe", "firefox.exe", "code.exe", "notepad++.exe",
    # 渲染链（正在合成的视频会废）
    "ffmpeg.exe", "ffprobe.exe",
}

# 命令行子串 —— 只允许精确到可执行文件或脚本名
PROTECT_CMDLINE = [
    "hermes_cli.main gateway",
    "hermes-agent/venv", "hermes-agent\\venv",
    "openclaw/dist/index.js", "openclaw\\dist\\index.js",
    "agnes-proxy", "liveware-sample",
    "mcp-server-filesystem", "chrome-devtools-mcp", "playwright-mcp",
]


def is_protected(name: str, cmdline: str = "") -> bool:
    n = (name or "").lower()
    if n in PROTECT_NAMES:
        return True
    c = (cmdline or "").lower()
    return any(k in c for k in PROTECT_CMDLINE)
