#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify a release zip *before* it is published.

A green packaging step proves nothing about the download. The v1.0.0 artifact
shipped without ``.gitignore``/``.gitattributes``/``.github`` because the
exclusion pattern ``-x "*.git*"`` matched them, and CI stayed green: the zip
was produced, it just was not what we promised. So the artifact is now checked
in CI, not assumed.

Usage:  python scripts/verify_artifact.py dist/skyube-v1.0.0.zip
Exit 0 = safe to publish, non-zero = reason printed on stderr.
"""
from __future__ import annotations

import sys
import zipfile

REQUIRED = (
    ".gitignore",                      # users re-init git from the source pack
    ".gitattributes",                  # keeps CRLF out of every later diff
    ".github/workflows/release.yml",   # the release pipeline ships with the code
    "README.md",
    "README.zh-CN.md",
    "LICENSE",
    "pyproject.toml",
    "requirements.txt",
    "hwtriage/cli.py",
    "hwtriage/test_selftest.py",
)

# 构建污染：出现即失败，不许"能解压就行"
FORBIDDEN_SUBSTRINGS = ("__pycache__", ".pyc", "egg-info", "/build/")


def verify(path: str) -> int:
    try:
        zf = zipfile.ZipFile(path)
    except Exception as e:
        print("cannot open %s: %s" % (path, e), file=sys.stderr)
        return 2

    with zf:
        bad = zf.testzip()
        if bad is not None:
            print("corrupt member in zip: %s" % bad, file=sys.stderr)
            return 3
        names = set(zf.namelist())

    missing = [r for r in REQUIRED if r not in names]
    if missing:
        print("missing from the artifact: %s" % ", ".join(missing), file=sys.stderr)
        return 4

    junk = sorted(n for n in names if any(s in n for s in FORBIDDEN_SUBSTRINGS))
    if junk:
        print("build junk inside the artifact: %s" % ", ".join(junk[:5]), file=sys.stderr)
        return 5

    print("artifact ok: %d entries, all %d required files present" % (len(names), len(REQUIRED)))
    return 0


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print("usage: python scripts/verify_artifact.py <release-zip>", file=sys.stderr)
        return 1
    return verify(argv[0])


if __name__ == "__main__":
    raise SystemExit(main())
