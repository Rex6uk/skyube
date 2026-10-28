# -*- coding: utf-8 -*-
"""采集器基类 + 注册表

每个采集器只负责「读」，不做任何处置。处置由 guard 层统一做。
采集器之间互不依赖 —— 这是为了让多个 agent 并行开发时不冲突。
"""
from __future__ import annotations

import traceback
from abc import ABC, abstractmethod
from typing import List

from ..core import Metric, Status


class Collector(ABC):
    """采集器基类。

    约定：
      - 只读，不改系统状态
      - 读不到就返回 status=UNAVAILABLE/ERROR 的 Metric，不抛异常、不返回 0
      - 单个采集器失败不影响其他采集器
    """
    name = "base"
    platforms = ("win32", "linux", "darwin")   # 支持平台；不匹配则整体跳过

    @abstractmethod
    def collect(self) -> List[Metric]:
        ...


_REGISTRY: List[type] = []


def register(cls: type) -> type:
    """装饰器：注册采集器"""
    _REGISTRY.append(cls)
    return cls


def all_collectors() -> List[type]:
    return list(_REGISTRY)


def run_all(only: str = "") -> List[Metric]:
    """跑所有已注册采集器，收集全部 Metric。

    任何一个采集器崩了，都转成一条 ERROR Metric 记下来，
    不影响其他采集器 —— 这很重要：温度采集失败不该让整个面板空掉。
    """
    import sys
    metrics: List[Metric] = []
    for cls in _REGISTRY:
        inst = cls()
        if sys.platform not in cls.platforms:
            metrics.append(Metric(
                name=inst.name + ".platform", label=inst.name + " 采集器",
                value=None, status=Status.UNAVAILABLE,
                source=cls.__name__,
                note="当前平台 %s 不支持" % sys.platform))
            continue
        if only and only not in inst.name:
            continue
        try:
            got = inst.collect()
            metrics.extend(got or [])
        except Exception as e:
            metrics.append(Metric(
                name=inst.name + ".error", label=inst.name + " 采集器",
                value=None, status=Status.ERROR, source=cls.__name__,
                note="%s: %s" % (type(e).__name__, str(e)[:120])))
            if "--traceback" in sys.argv:
                traceback.print_exc()
    return metrics
