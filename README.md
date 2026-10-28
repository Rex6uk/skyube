# Skyube

**Hardware health check + configuration advisor for your PC.**

Detects what hardware you actually have, reports its real condition, and suggests a
plan you decide on. Read-only by design — it never changes your system settings.

[中文说明](README.zh-CN.md)

---

## Why another hardware monitor?

Most tools either dump raw numbers nobody can read, or quietly fill in missing
readings with zeros. Both are dangerous: the first hides the problem, the second
invents a healthy machine that doesn't exist.

Skyube is built around three rules:

| Rule | What it means in practice |
|---|---|
| **Never fake a reading** | If a sensor can't be read, it says `UNAVAILABLE` and explains why. It never returns `0`. |
| **Never fake an alarm** | If a value *is* readable it's reported as readable — including non-numeric ones (GPU model, disk health, power plan). |
| **Never act without you** | The disposal layer is dry-run by default. Nothing is killed, throttled, or changed unless you explicitly ask. |

Each rule is enforced by an automated test, not by good intentions.

---

## Quick start

```bash
git clone https://github.com/Rex6uk/skyube.git
cd skyube
pip install -r requirements.txt

python -m hwtriage --advice    # 1. What should I change about this machine?
python -m hwtriage             # 2. How is it doing right now?
python -m hwtriage --perm      # 3. Which features need extra permission? (optional)
```

Works from any directory — nothing to configure, no hard-coded paths. Python and
LibreHardwareMonitor are discovered at runtime.

---

## Commands

| Command | Purpose |
|---|---|
| `python -m hwtriage` | Full check-up — every metric, grouped by domain |
| `python -m hwtriage --advice` | **Configuration advisor** — machine profile + tiered recommendations |
| `python -m hwtriage --brief` | Only what needs attention |
| `python -m hwtriage --cron` | Silent monitoring — prints **nothing** when everything is fine |
| `python -m hwtriage --json` | Machine-readable output |
| `python -m hwtriage --perm` | Which features need extra permission, and how to enable them |
| `python -m hwtriage --guard` | Disposal **plan only** (dry-run by default) |
| `python -m hwtriage --guard --apply` | Act: reclaim working sets; only `CRITICAL` may be terminated |
| `python -m hwtriage --only gpu` | Run a single collector |
| `python -m hwtriage.test_selftest` | Run the 31-test quality suite |

Collectors for `--only`: `memory` `cpu` `gpu` `thermal` `disk` `process` `power` `hardware`

---

## The advisor (`--advice`)

Reads the machine profile (CPU, cores, GPU, VRAM, RAM, chassis, OS), then combines it
with live measurements to produce recommendations in **three tiers**:

| Tier | Meaning | Example |
|---|---|---|
| ① Do it now | Free, reversible | Clear a nearly-full disk; cap VRAM batch size |
| ② Costs money | Hardware upgrade | 16 GB RAM → 32 GB |
| ③ System-level | Has a cost, may be irreversible | CPU max state 85% → 100% (more power, more heat) |

Every recommendation carries four things: **evidence** (the measured value behind it),
**how** (exactly where to click), **benefit**, and **cost**.

A recommendation without evidence is fortune-telling. One without a stated cost is a
sales pitch. The test suite rejects both.

The advisor module has **no `execute` function** — a test asserts this. It is
structurally incapable of changing anything on your machine.

---

## Reading CPU / motherboard temperature (optional)

On many laptops the ACPI layer doesn't expose CPU temperature. Skyube falls back to
[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)
(free, open source, no install needed — just unzip).

Reading CPU temperature requires **administrator rights**. Skyube will **never**
elevate itself; it only tells you what to do.

- **Windows:** double-click `enable-cpu-temp.bat` — it requests elevation, starts LHM,
  verifies the WMI namespace, then re-measures. If the namespace is missing, tick
  `Options → WMI Provider` inside LHM and run it once more.
- Or point Skyube at your copy: `set HWTRIAGE_LHM_PATH=<folder>` — or place LHM under
  `C:\Program Files\LibreHardwareMonitor\` and it is found automatically.

Not enabling it is perfectly fine — every other feature still works, and temperature
is honestly reported as `UNAVAILABLE` with the reason attached.

### Permission design principles

Enforced by tests in `permguide.py`:

1. **Never self-elevate** — no UAC prompt, no scheduled task, no registry write
2. **Missing permission is not an error** — reported as `UNAVAILABLE`, never `ERROR`
3. **Say exactly where to click** — "please run as administrator" is not a helpful hint
4. **Always state "it works without this"** — permission is never held hostage

---

## Scheduled monitoring (`--cron`)

Silent by design: the process prints nothing at all when there is nothing to report.

```bash
python -m hwtriage --cron          # try it

# Windows — one-click installer (auto-detects paths)
install-scheduled-check.bat

# Linux / macOS
0 12 * * * cd ~/skyube && python3 -m hwtriage --cron >> _cron.log 2>&1
```

---

## Unavailable readings — and why that's honest

| Reading | Why it isn't available |
|---|---|
| CPU / motherboard temperature | Needs admin + LHM WMI Provider (see above) |
| GPU fan speed / power limit | Notebook hardware returns `N/A` |
| SMART failure prediction | Requires administrator |

These are always reported as `status=UNAVAILABLE` with a specific reason and
`value=None`. **Never `0`.**

> Only those readings are unavailable. GPU model, P-state, disk health, power-plan
> name and AC status are all **readable** and displayed normally — they are
> non-numeric values carried in `Metric.text`.
>
> This matters: when those five were wrongly marked "unreadable", six false alarms
> buried the real problems. A false alarm is as harmful as a false green light.

---

## The disposal layer (`guard`)

- **Dry-run by default** — `--guard` prints a plan and executes nothing.
- `--apply` is required to act; even then only `CRITICAL` items may be terminated.
  Everything else receives a reversible working-set reclaim.
- The protection list reuses `core.is_protected`: `explorer`, `clawchat`, `msedge`,
  `ffmpeg` and friends are never touched.
- Duplicate-command-line processes are only reclaimed, never killed — they might be
  intentional multi-instance apps.

---

## Quality suite

```bash
python -m hwtriage.test_selftest     # 31 tests, standard library only
```

The suite guards properties that matter, not line coverage:

- the data model refuses `OK` without a real value (**anti fake-green**)
- non-numeric readings must be `OK`, not "unavailable" (**anti fake-red**)
- thresholds point the right way (`cpu_max_state` is better when high; absolute
  quantities such as MB/GB/MHz never participate in percentage thresholds)
- the protection list must never contain generic words like `mcp` or `gateway`
- silent mode is genuinely silent
- the advisor never gains an `execute` function
- no hard-coded machine-specific paths anywhere in the source

Run it before shipping any change.

---

## Project layout

```
hwtriage/
  core.py            # Metric model, thresholds, protection list
  cli.py             # command-line entry point
  report.py          # rendering: full / brief / silent
  guard.py           # disposal layer (dry-run default)
  advisor.py         # configuration recommendations
  permguide.py       # permission guidance (never self-elevates)
  paths.py           # runtime discovery of Python / LibreHardwareMonitor
  test_selftest.py   # 31-test quality suite
  collectors/
    base.py          # collector base class + registry
    memory.py cpu.py gpu.py thermal.py
    disk.py process.py power.py hardware.py
```

**Rule:** collectors only *read* and return `Metric` objects. An unreadable value is
`UNAVAILABLE` + `note` + `value=None` — never a fabricated number.

---

## License

MIT — see [LICENSE](LICENSE).
