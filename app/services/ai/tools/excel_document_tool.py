"""Controlled Excel document tools for configured agents."""
from __future__ import annotations

from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import range_boundaries

from app.core.context import get_current_agent_context
from app.services.ai.tools.document_paths import (
    DocumentPathError,
    resolve_document_input_path,
    resolve_document_output_path,
)
from app.services.ai.tools.generated_file_service import register_artifact
from app.services.ai.tools.tool_compat import tool

_EXTENSIONS = {".xlsx"}
_MAX_PREVIEW_ROWS = 20
_MAX_PREVIEW_COLUMNS = 20
_MAX_RANGE_ROWS = 200
_MAX_RANGE_COLUMNS = 50
_EXCEL_READ_ACTION_ALIASES = {
    "read": "inspect",
    "open": "inspect",
    "load": "inspect",
    "preview": "inspect",
    "view": "inspect",
    "get": "inspect",
}


def _context():
    context = get_current_agent_context()
    if not context:
        raise DocumentPathError("无法获取当前执行上下文")
    return context


def _context_user_name(context) -> str | None:
    dims = context.user_dimensions or {}
    raw_name = dims.get("user_name") or dims.get("username")
    if not raw_name:
        return None
    name = str(raw_name).strip()
    return name or None


async def _input_path(path: str):
    context = _context()
    return await resolve_document_input_path(
        path,
        allowed_attachment_paths=context.authorized_attachment_paths,
        user_id=context.user_id,
        conversation_id=context.conversation_id,
        allowed_extensions=_EXTENSIONS,
        user_name=_context_user_name(context),
    )


async def _output_path(filename: str):
    context = _context()
    return await resolve_document_output_path(
        filename,
        user_id=context.user_id,
        conversation_id=context.conversation_id,
        allowed_extensions=_EXTENSIONS,
        user_name=_context_user_name(context),
    )


async def _artifact_result(output_path, *, summary: str, changes: dict[str, Any]) -> dict[str, Any]:
    context = _context()
    artifact = await register_artifact(
        source_path=output_path,
        filename=output_path.name,
        owner_user_id=context.user_id,
        artifact_type="excel",
        conversation_id=context.conversation_id,
        trace_id=context.trace_id,
    )
    return {
        "status": "ok",
        "summary": summary,
        "changes": changes,
        "artifact": artifact.to_tool_payload(),
    }


def _normalize_excel_read_action(
    action: str | None,
    sheet_name: str | None,
    cell_range: str | None,
) -> str:
    normalized = str(action or "").strip().lower()
    if normalized in {"inspect", "read_range"}:
        return normalized
    if sheet_name and cell_range:
        return "read_range"
    if not normalized or normalized in _EXCEL_READ_ACTION_ALIASES:
        return "inspect"
    raise DocumentPathError("excel_document_read 仅支持 inspect 或 read_range")


def _format_sheet_names(sheetnames: list[str]) -> str:
    names = [str(name) for name in sheetnames if str(name).strip()]
    if not names:
        return "（无）"
    return "、".join(names)


def _resolve_sheet_name(requested: str | None, sheetnames: list[str]) -> str:
    """Exact match, then unique prefix/contains. Ambiguous or missing names list all sheets."""
    wanted = str(requested or "").strip()
    if not wanted:
        raise DocumentPathError(
            f"需要工作表名称。当前工作簿的工作表：{_format_sheet_names(sheetnames)}"
        )
    names = [str(name) for name in sheetnames]
    if wanted in names:
        return wanted

    folded = wanted.casefold()
    case_hits = [name for name in names if name.casefold() == folded]
    if len(case_hits) == 1:
        return case_hits[0]
    if len(case_hits) > 1:
        raise DocumentPathError(
            f"工作表「{wanted}」匹配到多个同名表：{_format_sheet_names(case_hits)}"
        )

    prefix_hits = [name for name in names if name.startswith(wanted)]
    if len(prefix_hits) == 1:
        return prefix_hits[0]

    contains_hits = [name for name in names if wanted in name]
    if len(contains_hits) == 1:
        return contains_hits[0]

    if prefix_hits or contains_hits:
        candidates = prefix_hits or contains_hits
        raise DocumentPathError(
            f"工作表「{wanted}」不唯一，候选：{_format_sheet_names(candidates)}。"
            f"请用 inspect 返回的完整表名。当前工作簿的工作表：{_format_sheet_names(names)}"
        )
    raise DocumentPathError(
        f"工作表「{wanted}」不存在。当前工作簿的工作表：{_format_sheet_names(names)}"
    )


@tool
async def excel_document_read(
    path: str,
    action: str = "inspect",
    sheet_name: str | None = None,
    cell_range: str | None = None,
) -> dict[str, Any]:
    """Inspect an Excel workbook or read a bounded range from an uploaded workbook.

    action:
    - inspect: list sheets and a small preview. Use this first. Do not pass action=read.
    - read_range: requires sheet_name and cell_range such as A1:G50.
      Prefer the exact title from inspect. A unique prefix or substring of
      an existing sheet name is also accepted. Each call is capped at 200
      rows and 50 columns; oversized ranges are truncated and return next_range.
    """
    action = _normalize_excel_read_action(action, sheet_name, cell_range)
    input_path = await _input_path(path)
    workbook = load_workbook(input_path, read_only=True, data_only=False)
    try:
        if action == "inspect":
            sheets = []
            for worksheet in workbook.worksheets:
                preview = [
                    list(row)
                    for row in worksheet.iter_rows(
                        max_row=min(worksheet.max_row, _MAX_PREVIEW_ROWS),
                        max_col=min(worksheet.max_column, _MAX_PREVIEW_COLUMNS),
                        values_only=True,
                    )
                ]
                sheets.append({"name": worksheet.title, "rows": worksheet.max_row, "columns": worksheet.max_column, "preview": preview})
            return {"status": "ok", "summary": f"工作簿包含 {len(sheets)} 个工作表", "data": {"sheets": sheets}, "truncated": False}
        if not sheet_name or not cell_range:
            raise DocumentPathError("read_range 需要 sheet_name 和 cell_range")
        sheet_name = _resolve_sheet_name(sheet_name, list(workbook.sheetnames))
        min_col, min_row, max_col, max_row = range_boundaries(cell_range)
        requested_rows = max_row - min_row + 1
        requested_cols = max_col - min_col + 1
        end_row = max_row
        end_col = max_col
        truncated = False
        if requested_rows > _MAX_RANGE_ROWS:
            end_row = min_row + _MAX_RANGE_ROWS - 1
            truncated = True
        if requested_cols > _MAX_RANGE_COLUMNS:
            end_col = min_col + _MAX_RANGE_COLUMNS - 1
            truncated = True
        worksheet = workbook[sheet_name]
        values = [
            list(row)
            for row in worksheet.iter_rows(
                min_row=min_row,
                max_row=end_row,
                min_col=min_col,
                max_col=end_col,
                values_only=True,
            )
        ]
        read_range = (
            f"{get_column_letter(min_col)}{min_row}:"
            f"{get_column_letter(end_col)}{end_row}"
        )
        payload: dict[str, Any] = {
            "values": values,
            "requested_range": cell_range,
            "read_range": read_range,
        }
        summary = f"已读取 {sheet_name}!{read_range}"
        if truncated:
            next_row = end_row + 1
            if next_row <= max_row:
                next_end = min(max_row, next_row + _MAX_RANGE_ROWS - 1)
                payload["next_range"] = (
                    f"{get_column_letter(min_col)}{next_row}:"
                    f"{get_column_letter(end_col)}{next_end}"
                )
            payload["limit"] = {
                "max_rows": _MAX_RANGE_ROWS,
                "max_columns": _MAX_RANGE_COLUMNS,
            }
            summary += (
                f"（已截取，原范围 {cell_range} 超过 {_MAX_RANGE_ROWS} 行或 "
                f"{_MAX_RANGE_COLUMNS} 列；下一段用 read_range "
                f"{payload.get('next_range') or '继续分页'}）"
            )
        return {
            "status": "ok",
            "summary": summary,
            "data": payload,
            "truncated": truncated,
        }
    finally:
        workbook.close()


@tool
async def excel_document_write(
    action: str,
    output_filename: str,
    path: str | None = None,
    sheet_name: str | None = None,
    cells: list[dict[str, Any]] | None = None,
    rows: list[list[Any]] | None = None,
) -> dict[str, Any]:
    """Create or modify an Excel workbook copy and return a download link.

    For ``action="create"``, pass ``rows`` and/or ``cells`` to populate the
    new workbook's active sheet in the same call. A create call without either
    parameter intentionally produces a blank workbook.

    Copy artifact.download_url verbatim in the final response; do not alter its
    protocol, host, path, or token.
    """
    if action not in {"create", "write_cells", "append_rows", "create_sheet"}:
        raise DocumentPathError("excel_document_write 不支持该操作")
    if action == "create":
        workbook = Workbook()
        worksheet = workbook.active
        if sheet_name:
            worksheet.title = sheet_name
    else:
        if not path:
            raise DocumentPathError("修改工作簿需要 path")
        workbook = load_workbook(await _input_path(path), data_only=False)
        if not sheet_name:
            raise DocumentPathError("修改工作簿需要 sheet_name")
        if action != "create_sheet":
            sheet_name = _resolve_sheet_name(sheet_name, list(workbook.sheetnames))
    changes: dict[str, Any] = {}
    if action == "create":
        if cells:
            for cell in cells:
                address = str(cell.get("address") or "")
                if not address:
                    raise DocumentPathError("单元格地址不能为空")
                worksheet[address] = cell.get("value")
            changes["written_cells"] = len(cells)
        if rows:
            for row in rows:
                worksheet.append(list(row))
            changes["appended_rows"] = len(rows)
        changes["created_workbook"] = True
    elif action == "write_cells":
        worksheet = workbook[sheet_name]
        if not cells:
            raise DocumentPathError("write_cells 需要 cells")
        for cell in cells:
            address = str(cell.get("address") or "")
            if not address:
                raise DocumentPathError("单元格地址不能为空")
            worksheet[address] = cell.get("value")
        changes["written_cells"] = len(cells)
    elif action == "append_rows":
        worksheet = workbook[sheet_name]
        if not rows:
            raise DocumentPathError("append_rows 需要 rows")
        for row in rows:
            worksheet.append(list(row))
        changes["appended_rows"] = len(rows)
    elif action == "create_sheet":
        if sheet_name in workbook.sheetnames:
            raise DocumentPathError("工作表已存在")
        workbook.create_sheet(sheet_name)
        changes["created_sheet"] = sheet_name
    output_path = await _output_path(output_filename)
    workbook.save(output_path)
    workbook.close()
    return await _artifact_result(output_path, summary="已生成 Excel 文件", changes=changes)
