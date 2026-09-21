#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""短脚本：把 create.json 的 problems 渲成四列表。文件须小于工具结果上限，可整份 Write 后再跑。"""
from __future__ import annotations

import json
import sys

ORDER = (
    ("ENTERPRISE", "企业问题", ("发生时间", "问题类别", "问题事项", "事实")),
    ("VEHICLE", "车辆问题", ("发生时间", "车牌号", "问题类型", "事实")),
    ("DRIVER", "驾驶员问题", ("发生时间", "姓名", "问题类型", "事实")),
)


def cell(v: object) -> str:
    return str(v or "").strip().replace("|", "｜")


def mid(kind: str, p: dict) -> str:
    if kind == "VEHICLE":
        return cell(p.get("vehiclePlate"))
    if kind == "DRIVER":
        return cell(p.get("driverName"))
    return cell(p.get("problemCategory"))


def render(problems: list) -> str:
    blocks: list[str] = []
    for kind, title, headers in ORDER:
        rows = []
        for p in problems or []:
            if isinstance(p, dict) and p.get("kind") == kind:
                rows.append(
                    [cell(p.get("occurredAt") or "—"), mid(kind, p), cell(p.get("problemType")), cell(p.get("fact"))]
                )
        if not rows:
            continue
        lines = [
            "## {0}".format(title),
            "",
            "| {0} |".format(" | ".join(headers)),
            "| {0} |".format(" | ".join("---" for _ in headers)),
        ]
        lines.extend("| {0} |".format(" | ".join(row)) for row in rows)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] != "render":
        sys.stderr.write("用法: render.py render create.json submit.json\n")
        return 1
    data = json.load(open(argv[2], "r", encoding="utf-8"))
    if not isinstance(data, dict) or data.get("taskType") != "问题处置":
        sys.stderr.write("只渲染问题处置 create.json 对象\n")
        return 1
    data.pop("enterpriseNames", None)
    data.pop("unmatchedCount", None)
    items = []
    for item in data.get("items") or []:
        row = dict(item)
        problems = row.pop("problems", None)
        if not isinstance(problems, list) or not problems:
            sys.stderr.write("每个 item 必须有非空 problems\n")
            return 1
        text = render(problems)
        if "## " not in text or "| --- |" not in text:
            sys.stderr.write("渲染结果缺少四列表\n")
            return 1
        row["requirement"] = text
        items.append(row)
    data["items"] = items
    with open(argv[3], "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    sys.stdout.write("已写入 {0}\n".format(argv[3]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
