import re
import uuid

import pytest

from app.utils import fs_access
from fastapi import HTTPException

from app.utils.fs_access import (
    build_upload_storage_name,
    open_upload_storage_file,
    reject_invalid_office_upload,
)

pytestmark = pytest.mark.no_infrastructure


def test_build_upload_storage_name_keeps_chinese_and_uses_short_suffix():
    name = build_upload_storage_name("销售日报 2025.xlsx", suffix="a1B2")

    assert name == "销售日报 2025_a1B2.xlsx"


def test_build_upload_storage_name_removes_path_separators_without_losing_name():
    name = build_upload_storage_name("../报表\\月度.xlsx", suffix="c3D4")

    assert name == ".._报表_月度_c3D4.xlsx"
    assert "/" not in name
    assert "\\" not in name


def test_build_upload_storage_name_generates_four_hex_characters_by_default():
    name = build_upload_storage_name("report.csv")

    assert re.fullmatch(r"report_[0-9a-f]{4}\.csv", name)


def test_open_upload_storage_file_retries_after_a_name_collision(tmp_path, monkeypatch):
    suffixes = iter(
        (
            uuid.UUID("a1b20000-0000-0000-0000-000000000000"),
            uuid.UUID("a1b20000-0000-0000-0000-000000000000"),
            uuid.UUID("c3d40000-0000-0000-0000-000000000000"),
        )
    )
    monkeypatch.setattr(fs_access.uuid, "uuid4", lambda: next(suffixes))

    first_path, first_handle = open_upload_storage_file(str(tmp_path), "report.csv")
    with first_handle:
        first_handle.write(b"first")

    second_path, second_handle = open_upload_storage_file(str(tmp_path), "report.csv")
    with second_handle:
        second_handle.write(b"second")

    assert first_path != second_path
    assert (tmp_path / "report.csv").read_bytes() == b"first"
    assert (tmp_path / "report_c3d4.csv").read_bytes() == b"second"


def test_open_upload_storage_file_keeps_original_name_when_available(tmp_path):
    path, handle = open_upload_storage_file(str(tmp_path), "9.12日企业疲劳驾驶表.xlsx")
    with handle:
        handle.write(b"ok")

    assert path.endswith("9.12日企业疲劳驾驶表.xlsx")
    assert (tmp_path / "9.12日企业疲劳驾驶表.xlsx").read_bytes() == b"ok"


def test_reject_invalid_office_upload_blocks_html_masquerading_as_xlsx():
    with pytest.raises(HTTPException) as exc:
        reject_invalid_office_upload("9.12日企业疲劳驾驶表.xlsx", b"<!doctype html><html></html>")
    assert exc.value.status_code == 400
    assert "不是有效的 Office 文档" in str(exc.value.detail)


def test_reject_invalid_office_upload_allows_zip_xlsx():
    reject_invalid_office_upload("report.xlsx", b"PK\x03\x04" + b"\x00" * 8)
