#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 industry-dispatch-task 的 create.json，并按固定四列表渲染 requirement。

仅使用 Python 3.11 标准库。退出码 0=通过，1=失败。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Iterable

ALLOWED_TOP_KEYS = {
    "name",
    "taskType",
    "requirement",
    "publish",
    "needAudit",
    "deadlineDate",
    "enterpriseNames",
    "unmatchedCount",
    "items",
}
ALLOWED_ITEM_KEYS = {"enterpriseId", "problems", "requirement", "attachments"}
ALLOWED_KINDS = {"VEHICLE", "DRIVER", "ENTERPRISE"}
TASK_TYPES = {"通知", "工作部署", "问题处置", "材料报送"}
FORBIDDEN_ITEM_KEYS = {
    "issues",
    "summary",
    "name",
    "fatigue",
    "speed",
    "track_issue",
    "enterpriseName",
}
FORBIDDEN_ROOT_KEYS = {"fatigue", "speed", "track_issue", "issues"}
MULTI_OBJECT_MARKERS = ("、", ",", "/", ";", "；", "及", "和", "等")
SUMMARY_FACT_RE = re.compile(
    r"(超速|疲劳驾驶|轨迹异常|轨迹完整率)\s*\d+|完整率低于|未处理\)\s*$"
)
PLATE_SPLIT_RE = re.compile(r"[、,，/；;]")
NAME_SPLIT_RE = re.compile(r"[、,，/；;]")

VEHICLE_HEADERS = ("发生时间", "车牌号", "问题类型", "事实")
DRIVER_HEADERS = ("发生时间", "姓名", "问题类型", "事实")
ENTERPRISE_HEADERS = ("发生时间", "问题类别", "问题事项", "事实")
SECTION_ORDER = (
    ("ENTERPRISE", "企业问题", ENTERPRISE_HEADERS),
    ("VEHICLE", "车辆问题", VEHICLE_HEADERS),
    ("DRIVER", "驾驶员问题", DRIVER_HEADERS),
)


def _fail(errors: list[str]) -> int:
    sys.stderr.write("校验失败：\n")
    for item in errors:
        sys.stderr.write("- {0}\n".format(item))
    return 1


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _cell(value: Any) -> str:
    return _as_text(value).replace("|", "｜")


def _has_multi_object(value: str) -> bool:
    return any(marker in value for marker in MULTI_OBJECT_MARKERS)


def _looks_like_summary_fact(fact: str, has_object: bool) -> bool:
    if has_object:
        return False
    return bool(SUMMARY_FACT_RE.search(fact.replace(" ", "")))


def _render_table(title: str, headers: tuple[str, ...], rows: list[list[str]]) -> str:
    lines = [
        "## {0}".format(title),
        "",
        "| {0} |".format(" | ".join(headers)),
        "| {0} |".format(" | ".join("---" for _ in headers)),
    ]
    for row in rows:
        lines.append("| {0} |".format(" | ".join(_cell(col) for col in row)))
    return "\n".join(lines)


def render_requirement(problems: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for kind, title, headers in SECTION_ORDER:
        rows: list[list[str]] = []
        for problem in problems:
            if problem.get("kind") != kind:
                continue
            occurred = _cell(problem.get("occurredAt") or "—")
            fact = _cell(problem.get("fact"))
            ptype = _cell(problem.get("problemType"))
            if kind == "VEHICLE":
                rows.append([occurred, _cell(problem.get("vehiclePlate")), ptype, fact])
            elif kind == "DRIVER":
                rows.append([occurred, _cell(problem.get("driverName")), ptype, fact])
            else:
                rows.append(
                    [occurred, _cell(problem.get("problemCategory")), ptype, fact]
                )
        if rows:
            blocks.append(_render_table(title, headers, rows))
    return "\n\n".join(blocks)


def _check_problem(
    problem: Any,
    index: int,
    item_index: int,
    *,
    has_vehicle_or_driver: bool,
) -> list[str]:
    prefix = "items[{0}].problems[{1}]".format(item_index, index)
    errors: list[str] = []
    if not isinstance(problem, dict):
        return ["{0} 必须是对象".format(prefix)]
    kind = _as_text(problem.get("kind"))
    if kind not in ALLOWED_KINDS:
        errors.append("{0}.kind 只能是 VEHICLE / DRIVER / ENTERPRISE".format(prefix))
        return errors
    fact = _as_text(problem.get("fact"))
    ptype = _as_text(problem.get("problemType"))
    occurred = problem.get("occurredAt")
    if occurred is None or _as_text(occurred) == "":
        errors.append("{0}.occurredAt 必填，无则填 —".format(prefix))
    if not ptype:
        errors.append("{0}.problemType 必填".format(prefix))
    if not fact:
        errors.append("{0}.fact 必填".format(prefix))

    if kind == "VEHICLE":
        plate = _as_text(problem.get("vehiclePlate"))
        if not plate:
            errors.append("{0} VEHICLE 必须有且只有一个 vehiclePlate".format(prefix))
        elif _has_multi_object(plate) or PLATE_SPLIT_RE.search(plate):
            errors.append("{0}.vehiclePlate 只能有一个车牌，禁止多人/多车写进同一条".format(prefix))
        if _as_text(problem.get("driverName")):
            errors.append("{0} VEHICLE 不要填 driverName".format(prefix))
    elif kind == "DRIVER":
        name = _as_text(problem.get("driverName"))
        if not name:
            errors.append("{0} DRIVER 必须有且只有一个 driverName".format(prefix))
        elif _has_multi_object(name) or NAME_SPLIT_RE.search(name):
            errors.append("{0}.driverName 只能有一个姓名，禁止多人写进同一条".format(prefix))
        if _as_text(problem.get("vehiclePlate")):
            errors.append("{0} DRIVER 不要填 vehiclePlate".format(prefix))
    else:
        if not _as_text(problem.get("problemCategory")):
            errors.append("{0} ENTERPRISE 必须有 problemCategory".format(prefix))
        if has_vehicle_or_driver and _looks_like_summary_fact(fact, False):
            errors.append("{0} 已有分车/分人时禁止把企业合计写入 ENTERPRISE".format(prefix))

    if kind in {"VEHICLE", "DRIVER"} and _looks_like_summary_fact(
        fact, True
    ) and not (
        _as_text(problem.get("vehiclePlate")) or _as_text(problem.get("driverName"))
    ):
        errors.append("{0} 禁止无对象合计，例如「超速17次」".format(prefix))
    return errors


def parse_allowed_ids(payload: Any) -> list[str]:
    """从 ID 数组或 enterprise_resolve/list 返回值抽出可下发企业 ID。"""
    ids: list[str] = []
    if isinstance(payload, list):
        if payload and all(isinstance(item, str) for item in payload):
            return [item.strip() for item in payload if str(item).strip()]
        records = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("ids"), list) and payload.get("ids") and all(
            isinstance(item, str) for item in payload.get("ids") or []
        ):
            return [item.strip() for item in payload["ids"] if str(item).strip()]
        records = None
        for key in ("records", "list", "data", "items"):
            if isinstance(payload.get(key), list):
                records = payload.get(key)
                break
        if records is None:
            return []
    else:
        return []
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("found") is False:
            continue
        if record.get("enabled") is False:
            continue
        match_count = record.get("matchCount")
        if match_count not in (None, 1):
            continue
        enterprise_id = record.get("enterpriseId")
        if isinstance(enterprise_id, str) and enterprise_id.strip():
            ids.append(enterprise_id.strip())
        elif isinstance(enterprise_id, (int, float)):
            ids.append(str(int(enterprise_id)))
    return ids


def _load_allowed_ids(path: str | None) -> tuple[set[str] | None, list[str]]:
    if not path:
        return None, []
    try:
        payload = _load_json(path)
    except FileNotFoundError:
        return None, ["找不到 allowed-ids 文件: {0}".format(path)]
    except json.JSONDecodeError as exc:
        return None, ["allowed-ids JSON 解析失败: {0}".format(exc)]
    ids = parse_allowed_ids(payload)
    if not ids:
        return None, ["allowed-ids 为空，必须写入 resolve/list 返回的可下发企业 ID"]
    return set(ids), []


def check_create(payload: Any, allowed_ids: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    if isinstance(payload, list):
        return [
            "根节点不能是数组。这是企业合计概况，必须写成 create.json 对象，"
            "且 items[].problems 为一车/一人一条。"
        ]
    if not isinstance(payload, dict):
        return ["create.json 必须是 JSON 对象"]

    extra_root = set(payload.keys()) - ALLOWED_TOP_KEYS
    if extra_root:
        errors.append("顶层多余字段: {0}".format(", ".join(sorted(extra_root))))
    for key in FORBIDDEN_ROOT_KEYS:
        if key in payload:
            errors.append("禁止顶层字段 {0}".format(key))

    name = _as_text(payload.get("name"))
    if not name:
        errors.append("name 必填")
    task_type = _as_text(payload.get("taskType"))
    if task_type not in TASK_TYPES:
        errors.append("taskType 必须是通知 / 工作部署 / 问题处置 / 材料报送")
    if payload.get("publish") is not True:
        errors.append("publish 必须为 true")
    if not _as_text(payload.get("requirement")):
        errors.append("任务级 requirement 必填")

    names = payload.get("enterpriseNames")
    if not isinstance(names, list) or not names or any(not _as_text(item) for item in names):
        errors.append("enterpriseNames 必须是非空字符串数组")
        names = []
    unmatched = payload.get("unmatchedCount", 0)
    if not isinstance(unmatched, int) or unmatched < 0:
        errors.append("unmatchedCount 必须是 >= 0 的整数")

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        errors.append("items 必须是非空数组")
        return errors
    if names and len(items) != len(names):
        errors.append(
            "items.length({0}) 必须等于 enterpriseNames.length({1})".format(
                len(items), len(names)
            )
        )

    is_problem_task = task_type == "问题处置"
    if is_problem_task and payload.get("needAudit") is not True:
        errors.append("问题处置 needAudit 必须为 true")

    for item_index, item in enumerate(items):
        prefix = "items[{0}]".format(item_index)
        if not isinstance(item, dict):
            errors.append("{0} 必须是对象".format(prefix))
            continue
        forbidden = FORBIDDEN_ITEM_KEYS.intersection(item.keys())
        if forbidden:
            errors.append("{0} 禁止字段: {1}".format(prefix, ", ".join(sorted(forbidden))))
        extra = set(item.keys()) - ALLOWED_ITEM_KEYS
        if extra:
            errors.append("{0} 多余字段: {1}".format(prefix, ", ".join(sorted(extra))))
        enterprise_id = item.get("enterpriseId")
        if not isinstance(enterprise_id, str) or not enterprise_id.strip():
            errors.append("{0}.enterpriseId 必须是非空字符串，禁止数字 5 或无引号 ID".format(prefix))
        elif allowed_ids is not None and enterprise_id.strip() not in allowed_ids:
            errors.append(
                "{0}.enterpriseId `{1}` 不在 resolve/list 可下发 ID 中".format(
                    prefix, enterprise_id.strip()
                )
            )

        if is_problem_task:
            if "requirement" in item:
                errors.append("{0} 冻结阶段不要写 requirement，交给脚本渲染".format(prefix))
            problems = item.get("problems")
            if not isinstance(problems, list) or not problems:
                errors.append("{0}.problems 必须是至少 1 条的对象数组".format(prefix))
                continue
            has_object_row = any(
                isinstance(row, dict)
                and row.get("kind") in {"VEHICLE", "DRIVER"}
                for row in problems
            )
            for problem_index, problem in enumerate(problems):
                errors.extend(
                    _check_problem(
                        problem,
                        problem_index,
                        item_index,
                        has_vehicle_or_driver=has_object_row,
                    )
                )
        else:
            requirement = _as_text(item.get("requirement"))
            if not requirement:
                errors.append("{0}.requirement 非问题处置时必填短 Markdown".format(prefix))
            if item.get("problems"):
                errors.append("{0} 非问题处置不要写 problems".format(prefix))
    return errors


def _requirement_has_table(text: str, headers: tuple[str, ...]) -> bool:
    header_line = "| {0} |".format(" | ".join(headers))
    sep = "| {0} |".format(" | ".join("---" for _ in headers))
    return header_line in text and sep in text


def check_submit(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["submit.json 必须是 JSON 对象"]
    if payload.get("enterpriseIds"):
        errors.append("禁止传 enterpriseIds")
    if payload.get("enterpriseNames") is not None or payload.get("unmatchedCount") is not None:
        errors.append("提交前必须删除 enterpriseNames / unmatchedCount")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return ["items 必须是非空数组"]
    task_type = _as_text(payload.get("taskType"))
    for item_index, item in enumerate(items):
        prefix = "items[{0}]".format(item_index)
        if not isinstance(item, dict):
            errors.append("{0} 必须是对象".format(prefix))
            continue
        if item.get("problems") is not None:
            errors.append("{0} 提交时必须删除 problems".format(prefix))
        if not isinstance(item.get("enterpriseId"), str) or not item.get("enterpriseId"):
            errors.append("{0}.enterpriseId 必须是字符串".format(prefix))
        requirement = _as_text(item.get("requirement"))
        if not requirement:
            errors.append("{0}.requirement 必填".format(prefix))
            continue
        if task_type != "问题处置":
            continue
        if not requirement.startswith("## "):
            errors.append("{0}.requirement 必须以 ## 节标题开头".format(prefix))
        if "- " in requirement and "|" not in requirement:
            errors.append("{0}.requirement 禁止用列表代替表格".format(prefix))
        has_any_table = False
        if "## 车辆问题" in requirement:
            has_any_table = True
            if not _requirement_has_table(requirement, VEHICLE_HEADERS):
                errors.append("{0} 车辆问题必须是「发生时间|车牌号|问题类型|事实」四列表".format(prefix))
        if "## 驾驶员问题" in requirement:
            has_any_table = True
            if not _requirement_has_table(requirement, DRIVER_HEADERS):
                errors.append("{0} 驾驶员问题必须是「发生时间|姓名|问题类型|事实」四列表".format(prefix))
        if "## 企业问题" in requirement:
            has_any_table = True
            if not _requirement_has_table(requirement, ENTERPRISE_HEADERS):
                errors.append("{0} 企业问题必须是「发生时间|问题类别|问题事项|事实」四列表".format(prefix))
        if not has_any_table:
            errors.append("{0}.requirement 缺少 ## 车辆/驾驶员/企业问题表".format(prefix))
    return errors


def render_submit(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.pop("enterpriseNames", None)
    result.pop("unmatchedCount", None)
    items: list[dict[str, Any]] = []
    for item in payload.get("items") or []:
        row = dict(item)
        problems = row.pop("problems", None)
        if isinstance(problems, list) and problems:
            row["requirement"] = render_requirement(problems)
        items.append(row)
    result["items"] = items
    return result


def _print_ok(message: str) -> int:
    sys.stdout.write(message + "\n")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验并渲染任务下发 JSON")
    sub = parser.add_subparsers(dest="cmd", required=True)
    check_p = sub.add_parser("check", help="校验 pending_write/create.json")
    check_p.add_argument("path")
    check_p.add_argument("--allowed-ids", dest="allowed_ids", default="")
    render_p = sub.add_parser("render", help="校验后渲染 pending_write/submit.json")
    render_p.add_argument("src")
    render_p.add_argument("dst")
    render_p.add_argument("--allowed-ids", dest="allowed_ids", default="")
    submit_p = sub.add_parser("check-submit", help="校验提交前 JSON")
    submit_p.add_argument("path")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        allowed_ids = None
        allowed_path = str(getattr(args, "allowed_ids", "") or "").strip()
        if allowed_path:
            allowed_ids, allowed_errors = _load_allowed_ids(allowed_path)
            if allowed_errors:
                return _fail(allowed_errors)
        if args.cmd == "check":
            errors = check_create(_load_json(args.path), allowed_ids=allowed_ids)
            if errors:
                return _fail(errors)
            return _print_ok("create.json 校验通过")
        if args.cmd == "render":
            payload = _load_json(args.src)
            errors = check_create(payload, allowed_ids=allowed_ids)
            if errors:
                return _fail(errors)
            submit = render_submit(payload)
            submit_errors = check_submit(submit)
            if submit_errors:
                return _fail(submit_errors)
            with open(args.dst, "w", encoding="utf-8") as handle:
                json.dump(submit, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            return _print_ok("已写入 {0}".format(args.dst))
        payload = _load_json(args.path)
        errors = check_submit(payload)
        if errors:
            return _fail(errors)
        return _print_ok("submit.json 校验通过")
    except FileNotFoundError as exc:
        return _fail(["找不到文件: {0}".format(exc.filename or "")])
    except json.JSONDecodeError as exc:
        return _fail(["JSON 解析失败: {0}".format(exc)])
    except OSError as exc:
        return _fail(["读写失败: {0}".format(exc)])


if __name__ == "__main__":
    sys.exit(main())
