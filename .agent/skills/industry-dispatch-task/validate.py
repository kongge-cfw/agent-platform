#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定位并执行 scripts/validate_create_json.py。只许 Bash 跑本文件，禁止把校验脚本读进上下文。"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

NAME = "validate_create_json.py"


def _add(paths: list[Path], seen: set[str], path: Path) -> None:
    key = str(path)
    if key not in seen:
        seen.add(key)
        paths.append(path)


def candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    cwd = Path.cwd()
    seen: set[str] = set()
    paths: list[Path] = []
    for path in (
        here / "scripts" / NAME,
        cwd / "skills/.seed/industry-dispatch-task/scripts" / NAME,
        cwd / "skills/industry-dispatch-task/scripts" / NAME,
        Path("/workspace/skills/.seed/industry-dispatch-task/scripts") / NAME,
        Path("/workspace/skills/industry-dispatch-task/scripts") / NAME,
    ):
        _add(paths, seen, path)
    for root in (here, cwd / "skills", Path("/workspace/skills")):
        if not root.exists():
            continue
        try:
            for found in root.rglob(NAME):
                if found.is_file():
                    _add(paths, seen, found)
        except OSError:
            continue
    return paths


def main() -> int:
    for path in candidates():
        if not path.is_file():
            continue
        sys.argv[0] = str(path)
        try:
            runpy.run_path(str(path), run_name="__main__")
        except SystemExit as exc:
            code = exc.code
            if code is None:
                return 0
            return int(code) if isinstance(code, int) else 1
        return 0
    sys.stderr.write(
        "找不到 {0}。请在 skills/.seed 或 skills/industry-dispatch-task/scripts 下查找。\n".format(
            NAME
        )
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
