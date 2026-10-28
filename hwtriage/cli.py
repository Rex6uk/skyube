#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hwtriage — 硬件状态治理命令行

用法：
    python -m hwtriage              # 完整体检（人读表格）
    python -m hwtriage --advice     # 配置顾问：这台机器该怎么配怎么用
    python -m hwtriage --brief      # 只输出异常 + 读不到（精简巡检）
    python -m hwtriage --cron       # 静默：无异常不输出（挂定时任务）
    python -m hwtriage --json       # 机器读 JSON
    python -m hwtriage --perm       # 权限引导：哪些功能需要额外权限（只提醒）
    python -m hwtriage --guard      # 只出处置计划（dry-run，绝不执行）
    python -m hwtriage --guard --apply   # 真正执行回收（只有 CRITICAL 才会终止进程）
    python -m hwtriage --only gpu   # 只跑某个采集器
    python -m hwtriage --traceback  # 采集器异常时打印堆栈

分层：
    采集层 collectors/*  只读
    报告层 report.py     只渲染
    处置层 guard.py      只出计划/执行回收（默认 dry-run）
    顾问层 advisor.py    配置建议（每条带依据+代价，用户自己决定）
"""
from __future__ import annotations

import io
import json
import sys

from .collectors import base as _base
from .core import level_of


def _fix_stdout():
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv=None):
    argv = argv or sys.argv[1:]
    _fix_stdout()
    as_json = "--json" in argv
    brief = "--brief" in argv
    cron = "--cron" in argv
    want_guard = "--guard" in argv
    want_advice = "--advice" in argv
    want_perm = "--perm" in argv
    only = ""
    if "--only" in argv:
        i = argv.index("--only")
        if i + 1 < len(argv):
            only = argv[i + 1]

    metrics = _base.run_all(only=only)

    # ---------- JSON（机器读，交给上层/看板） ----------
    if as_json:
        payload = {
            "version": __import__("hwtriage").__version__,
            "metrics": [m.to_dict() for m in metrics],
            "levels": {m.name: level_of(m.name, m.value).value
                       for m in metrics if m.ok},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    # ---------- 配置顾问（建议，不执行） ----------
    if want_advice:
        from . import advisor as _advisor
        print(_advisor.render_advice(metrics))
        return 0

    # ---------- 权限引导（只提醒，不强迫） ----------
    if want_perm:
        from . import permguide as _pg
        out = _pg.render_hint(metrics)
        print(out if out else "所有功能都可用，无需额外授权。")
        return 0

    # ---------- 处置：默认 dry-run，--apply 才真执行 ----------
    if want_guard:
        try:
            from . import guard as _guard
        except Exception as e:
            print("guard 模块不可用：%s（处置层尚未就绪）" % e)
            return 2
        plan = _guard.build_plan(metrics)      # 只读：算该处置什么
        if "--apply" in argv:
            print(_guard.render_plan(plan))    # 先回显计划，再执行
            print("\n执行：")
            for line in _guard.execute_plan(plan, apply=True):
                print("  " + line)
            return 0
        print(_guard.render_plan(plan))        # 只打印，不执行
        return 1 if plan.get("actions") else 0

    # ---------- 人读报告：统一走 report 层，不在此重复渲染 ----------
    from . import report as _report
    if cron:
        out = _report.render(metrics, mode="cron")   # 无异常 → 空串
        if out.strip():
            print(out)
        return 0
    if brief:
        print(_report.render(metrics, mode="brief"))
        return 0
    print(_report.render(metrics, mode="full"))
    # 完整体检末尾附一次权限引导（只提醒，不强迫；有阻塞项才出现）
    try:
        from . import permguide as _pg
        _hint = _pg.render_hint(metrics)
        if _hint:
            print()
            print(_hint)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
