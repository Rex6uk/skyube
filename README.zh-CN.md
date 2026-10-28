# Skyube

**硬件体检 + 配置顾问**

自动检测你的硬件配置，如实报告真实状态，并给出一份由你自己决定的建议方案。
全程**只读** —— 不会改动你的任何系统设置。

[English](README.md)

---

## 为什么还要一个硬件工具？

大多数工具要么甩一堆看不懂的数字，要么把读不到的项悄悄填成 0。
两种都危险：前者把问题藏起来，后者凭空造出一台"健康"的机器。

Skyube 建立在三条铁律上：

| 铁律 | 落到实处的意思 |
|---|---|
| **绝不伪造读数** | 读不到就写 `UNAVAILABLE` 并说明原因，**绝不返回 0** |
| **绝不伪造告警** | 读得到就如实报——包括非数值项（显卡型号、磁盘健康、电源计划） |
| **绝不擅自动手** | 处置层默认 dry-run，不经你明确要求不杀进程、不改设置 |

这三条不是口号，每一条都有自动化测试守着。

---

## 三步上手

```bash
git clone https://github.com/Rex6uk/skyube.git
cd skyube
pip install -r requirements.txt

python -m hwtriage --advice    # 1. 这台机器该怎么配？
python -m hwtriage             # 2. 现在状态怎么样？
python -m hwtriage --perm      # 3. 哪些功能需要额外授权？（可选）
```

放在任何目录都能跑——无需配置，没有写死的路径。Python 和 LibreHardwareMonitor
都是运行时自动发现。

---

## 命令一览

| 命令 | 用途 |
|---|---|
| `python -m hwtriage` | 完整体检——全部指标，按域分组 |
| `python -m hwtriage --advice` | **配置顾问**——机器画像 + 分档建议 |
| `python -m hwtriage --brief` | 只看该关心的 |
| `python -m hwtriage --cron` | **静默巡检**——全正常时一个字都不输出 |
| `python -m hwtriage --json` | 机器可读输出 |
| `python -m hwtriage --perm` | 哪些功能需要授权、具体怎么开 |
| `python -m hwtriage --guard` | 出处置**计划**（默认 dry-run） |
| `python -m hwtriage --guard --apply` | 真正执行：只回收工作集；只有 `CRITICAL` 才可能被终止 |
| `python -m hwtriage --only gpu` | 只跑单个采集器 |
| `python -m hwtriage.test_selftest` | 跑 **32 项**质量自检 |

`--only` 可用采集器：`memory` `cpu` `gpu` `thermal` `disk` `process` `power` `hardware`

### 退出码

| 码 | 含义 |
|---|---|
| `0` | 正常跑完；对 `--guard` 还表示「没有该处置的东西」 |
| `1` | 仅 `--guard`：处置计划里有动作（dry-run 依旧一行都没执行） |
| `2` | 请求需要的模块不可用 |

所以 `python -m hwtriage --cron` 可以直接挂定时任务，
`python -m hwtriage --guard` 只有在真发现该处置的东西时才返回非 0。

---

## 配置顾问（`--advice`）

先读机器档案（CPU 型号、核心数、显卡、显存、内存、整机型号、系统），
再结合实时测量，给出**分三档**的建议：

| 档位 | 含义 | 例子 |
|---|---|---|
| ① 现在就能做 | 零成本、可随时改回 | 清理快满的磁盘；控制显存批次 |
| ② 要花钱 | 升级硬件 | 16G 内存 → 32G |
| ③ 系统级改动 | 有代价、可能不可逆 | CPU 最大状态 85% → 100%（更费电、更热） |

每条建议必须带四样东西：**依据**（具体实测值）、**做法**（点哪里）、**好处**、**代价**。

没有依据的建议是算命；不说代价的建议是推销。这两类都会被测试判为不合格。

顾问模块**没有 `execute` 函数**——有测试专门断言这一点。它在结构上就不可能改动你的机器。

---

## 读 CPU / 主板温度（可选）

很多笔记本的 ACPI 层不暴露 CPU 温度。Skyube 会退到
[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)
（免费开源，解压即用，无需安装）。

读 CPU 温度需要**管理员权限**。Skyube **绝不会**自行提权，只告诉你该怎么做。

- **Windows**：双击 `enable-cpu-temp.bat` —— 它会请求提权、启动 LHM、验证 WMI 命名空间，
  然后重新测量。若提示命名空间不存在，在 LHM 里勾选 `Options → WMI Provider` 再跑一次。
- 或者告诉 Skyube 你的位置：`set HWTRIAGE_LHM_PATH=<目录>`；
  把 LHM 放在 `C:\Program Files\LibreHardwareMonitor\` 下也会被自动找到。

**不开也完全没问题**——其他所有功能照常工作，温度会如实显示 `UNAVAILABLE` 并附原因。

### 权限设计原则

由 `permguide.py` 里的测试守着：

1. **绝不自行提权**——不弹 UAC、不写计划任务、不改注册表
2. **没权限不是错误**——用 `UNAVAILABLE` 表达，绝不报 `ERROR` 吓人
3. **说清具体点哪里**——"请以管理员运行"这种提示等于没说
4. **必须写明"不开也能用"**——不拿权限绑架用户

---

## 定时巡检（`--cron`）

静默模式：没有需要报告的事情时，进程一个字都不输出。

```bash
python -m hwtriage --cron          # 试一下

# Windows——一键安装（自动探测路径）
install-scheduled-check.bat

# Linux / macOS
0 12 * * * cd ~/skyube && python3 -m hwtriage --cron >> _cron.log 2>&1
```

---

## 读不到的项——以及为什么这叫诚实

| 项 | 为什么读不到 |
|---|---|
| CPU / 主板温度 | 需管理员 + LHM WMI Provider（见上节） |
| GPU 风扇转速 / 功耗上限 | 笔记本硬件返回 `N/A` |
| SMART 故障预测 | 需要管理员权限 |

这些一律 `status=UNAVAILABLE` + 具体原因 + `value=None`。**绝不用 0 冒充。**

> 只有这几项读不到。显卡型号、P8 电源状态、磁盘健康度、电源计划名、外接电源状态
> 都是**能读到的**，会正常显示——它们是存放在 `Metric.text` 里的非数值读数。
>
> 这点很重要：当初这 5 项被错标成"读不到"时，6 个假警报把真问题淹没了。
> 假红和假绿一样有害。

---

## 处置层（`guard`）

- **默认 dry-run**——`--guard` 只打印计划，一行都不执行。
- 必须加 `--apply` 才动手；即便如此，也只有 `CRITICAL` 才可能被终止，
  其余只做可逆的工作集回收。
- 保护名单复用 `core.is_protected`：`explorer`、`clawchat`、`msedge`、`ffmpeg`
  等一律不碰。
- 命令行重复的进程只回收、绝不杀——那可能是你有意的多开。

---

## 质量自检

```bash
python -m hwtriage.test_selftest     # 31 项，纯标准库
```

守的是真正重要的性质，不是行覆盖率：

- 数据模型拒绝"没值却标 OK"（**防假绿**）
- 非数值读数必须标 `OK`，不能算读不到（**防假红**）
- 阈值方向正确（`cpu_max_state` 越高越好；MB/GB/MHz 这类绝对量不参与百分比阈值）
- 保护名单不许出现 `mcp`、`gateway` 这类泛词
- 静默模式真的静默
- 顾问模块不可能长出 `execute` 函数
- 源码里不许出现任何本机专用路径

改完任何东西，跑一遍全绿再交。

---

## 目录结构

```
hwtriage/
  core.py            # Metric 模型、阈值、保护名单
  cli.py             # 命令行入口
  report.py          # 渲染：完整 / 精简 / 静默
  guard.py           # 处置层（默认 dry-run）
  advisor.py         # 配置建议
  permguide.py       # 权限引导（绝不自行提权）
  paths.py           # 运行时发现 Python / LibreHardwareMonitor
  test_selftest.py   # 32 项质量自检
  collectors/
    base.py          # 采集器基类 + 注册表
    memory.py cpu.py gpu.py thermal.py
    disk.py process.py power.py hardware.py
```

**铁律**：采集器只「读」并返回 `Metric`。读不到就是 `UNAVAILABLE` + `note` + `value=None`，
永远不编造数字。

---

## 许可证

MIT —— 见 [LICENSE](LICENSE)。
