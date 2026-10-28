# -*- coding: utf-8 -*-
"""collectors 包 —— 导入即注册

新增采集器只需两步：
  1. 在本目录建 xxx.py，写 @register class XxxCollector(Collector)
  2. 在下面 import 一行
"""
from . import base, memory, cpu, gpu, thermal, disk, process, power, hardware  # noqa: F401

__all__ = ["base", "memory", "cpu", "gpu", "thermal", "disk", "process", "power",
           "hardware"]
