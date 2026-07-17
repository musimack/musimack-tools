"""Deterministic one-sheet BS-01 XLSX serialization using bounded OOXML."""

# ruff: noqa: ANN401, E501, PLR2004 - OOXML literals and heterogeneous cells are intentional.

from __future__ import annotations

import html
import io
import re
import zipfile
from typing import Any

SHEET_NAME = "Blog Strategy"
EXPORT_COLUMNS = (
    "Client",
    "Website",
    "Page URL",
    "Page Title",
    "Canonical URL",
    "Inclusion Status",
    "Primary Topic",
    "Secondary Topics",
    "Search Intent",
    "Audience Question",
    "Content Role",
    "Topic Family",
    "Supported Service or Commercial Page",
    "Geographic Intent",
    "Claim Risk",
    "Overlap Concern",
    "Related Pages",
    "Overlap Review State",
    "Preferred Page",
    "Recommended Action",
    "Priority",
    "Destination or Parent Page",
    "Rationale",
    "Human Approved",
    "Notes",
    "Evidence Source",
    "Last Reviewed",
)
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def safe_spreadsheet_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return f"'{text}" if text.startswith(_FORMULA_PREFIXES) else text


def build_xlsx(rows: list[list[Any]]) -> bytes:
    """Create a minimal standards-compliant XLSX with no formulas or hidden sheets."""
    all_rows = [list(EXPORT_COLUMNS), *rows]
    hyperlinks: list[tuple[str, str, str]] = []
    sheet_rows = []
    for row_number, row in enumerate(all_rows, start=1):
        cells = []
        for column_number, raw in enumerate(row, start=1):
            reference = f"{_column(column_number)}{row_number}"
            value = safe_spreadsheet_text(raw)
            style = 1 if row_number == 1 else (2 if column_number == 27 else 3)
            cells.append(
                f'<c r="{reference}" t="inlineStr" s="{style}"><is><t xml:space="preserve">'
                f"{html.escape(value)}</t></is></c>"
            )
            if row_number > 1 and column_number in {2, 3, 5, 13, 19, 22} and _safe_url(value):
                relationship_id = f"rId{len(hyperlinks) + 1}"
                hyperlinks.append((reference, relationship_id, value))
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    last_row = len(all_rows)
    last_column = _column(len(EXPORT_COLUMNS))
    links_xml = ""
    relationships_xml = ""
    if hyperlinks:
        links_xml = (
            "<hyperlinks>"
            + "".join(
                f'<hyperlink ref="{cell}" r:id="{relationship_id}"/>'
                for cell, relationship_id, _url in hyperlinks
            )
            + "</hyperlinks>"
        )
        relationships_xml = _relationships(hyperlinks)
    worksheet = _worksheet("".join(sheet_rows), last_column, last_row, links_xml)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        _write(archive, "[Content_Types].xml", _content_types())
        _write(archive, "_rels/.rels", _root_relationships())
        _write(archive, "docProps/app.xml", _app_properties())
        _write(archive, "docProps/core.xml", _core_properties())
        _write(archive, "xl/workbook.xml", _workbook())
        _write(archive, "xl/_rels/workbook.xml.rels", _workbook_relationships())
        _write(archive, "xl/styles.xml", _styles())
        _write(archive, "xl/worksheets/sheet1.xml", worksheet)
        if relationships_xml:
            _write(archive, "xl/worksheets/_rels/sheet1.xml.rels", relationships_xml)
    return stream.getvalue()


def validate_xlsx(payload: bytes, expected_rows: int) -> dict[str, Any]:
    """Reopen and structurally validate the generated package without executing formulas."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        workbook = archive.read("xl/workbook.xml").decode()
        sheet = archive.read("xl/worksheets/sheet1.xml").decode()
        hidden = 'state="hidden"' in workbook or 'state="veryHidden"' in workbook
        formulas = bool(re.search(r"<f(?:\s|>)", sheet))
        rows = len(re.findall(r"<row\b", sheet)) - 1
        relationship_path = "xl/worksheets/_rels/sheet1.xml.rels"
        relationships = (
            archive.read(relationship_path).decode() if relationship_path in names else ""
        )
        targets = re.findall(r'Target="([^"]+)" TargetMode="External"', relationships)
        valid = {
            "worksheet_count": len(re.findall(r"<sheet\b", workbook)),
            "worksheet_name": SHEET_NAME if f'name="{SHEET_NAME}"' in workbook else None,
            "row_count": rows,
            "frozen_header": 'ySplit="1"' in sheet and 'state="frozen"' in sheet,
            "filters_enabled": "<autoFilter" in sheet,
            "hidden_sheets": hidden,
            "formula_count": 1 if formulas else 0,
            "has_styles": "xl/styles.xml" in names,
            "hyperlink_count": len(targets),
            "safe_hyperlinks": all(_safe_url(html.unescape(target)) for target in targets),
        }
        if valid["worksheet_count"] != 1 or valid["worksheet_name"] != SHEET_NAME:
            raise ValueError("blog_strategy_export_invalid")
        if rows != expected_rows or hidden or formulas or not valid["safe_hyperlinks"]:
            raise ValueError("blog_strategy_export_invalid")
        return valid


def _write(archive: zipfile.ZipFile, name: str, content: str) -> None:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, content.encode())


def _column(value: int) -> str:
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _safe_url(value: str) -> bool:
    return re.fullmatch(r"https?://[^\s<>'\"]+", value) is not None


def _content_types() -> str:
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>'


def _root_relationships() -> str:
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>'


def _app_properties() -> str:
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Musimack SEO Toolkit</Application></Properties>'


def _core_properties() -> str:
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Blog Strategy</dc:title><dc:creator>Musimack SEO Toolkit</dc:creator></cp:coreProperties>'


def _workbook() -> str:
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{SHEET_NAME}" sheetId="1" r:id="rId1"/></sheets></workbook>'


def _workbook_relationships() -> str:
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'


def _styles() -> str:
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="3"><font><sz val="10"/><name val="Aptos"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="10"/><name val="Aptos"/></font><font><color rgb="FF0563C1"/><u/><sz val="10"/><name val="Aptos"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF0F4C5C"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="center"/></xf><xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf></cellXfs></styleSheet>'


def _worksheet(rows: str, last_column: str, last_row: int, hyperlinks: str) -> str:
    widths = [
        22,
        28,
        42,
        32,
        42,
        16,
        24,
        28,
        22,
        36,
        22,
        24,
        38,
        24,
        18,
        32,
        38,
        20,
        38,
        22,
        16,
        38,
        40,
        16,
        40,
        30,
        20,
    ]
    columns = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(widths, 1)
    )
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>{columns}</cols><sheetData>{rows}</sheetData><autoFilter ref="A1:{last_column}{last_row}"/>{hyperlinks}</worksheet>'


def _relationships(hyperlinks: list[tuple[str, str, str]]) -> str:
    values = "".join(
        f'<Relationship Id="{relationship_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="{html.escape(url)}" TargetMode="External"/>'
        for _cell, relationship_id, url in hyperlinks
    )
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{values}</Relationships>'
