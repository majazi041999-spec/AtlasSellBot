"""A tiny, dependency-free .xlsx writer.

Openpyxl would do this too, but it is not currently a dependency and adding one
means every existing installation has to re-run pip before reports work. The
subset of the format we need — one right-to-left sheet, a styled header row,
merged title lines, text and numeric cells — is small enough to emit directly,
so exports work the moment the code is deployed.

Strings are written inline (`t="inlineStr"`) rather than through a shared-string
table: it costs a few bytes and removes a whole class of index bugs. Excel,
LibreOffice, Google Sheets and Numbers all read it.
"""

import zipfile
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence

# Style ids, in the order they are declared in _STYLES below.
STYLE_DEFAULT = 0
STYLE_TITLE = 1
STYLE_HEADER = 2
STYLE_TEXT = 3
STYLE_INT = 4
STYLE_DECIMAL = 5

_TYPE_STYLES = {"text": STYLE_TEXT, "int": STYLE_INT, "float": STYLE_DECIMAL}


def _esc(value: Any) -> str:
    """XML-escape. Also drops control characters, which Excel refuses to open."""
    text = "" if value is None else str(value)
    out = []
    for ch in text:
        if ch in ("\t", "\n"):
            out.append(ch)
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            continue
        elif ch == "&":
            out.append("&amp;")
        elif ch == "<":
            out.append("&lt;")
        elif ch == ">":
            out.append("&gt;")
        elif ch == '"':
            out.append("&quot;")
        else:
            out.append(ch)
    return "".join(out)


def col_letter(index: int) -> str:
    """1 → A, 26 → Z, 27 → AA."""
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

# numFmtId 3 = #,##0 and 2 = 0.00 are built into the format; no custom numFmts needed.
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="3">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="13"/><color rgb="FF1F3864"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
</fonts>
<fills count="3">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF2F5597"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
<border><left/><right/><top/><bottom/><diagonal/></border>
<border><left style="thin"><color rgb="FFBFBFBF"/></left><right style="thin"><color rgb="FFBFBFBF"/></right><top style="thin"><color rgb="FFBFBFBF"/></top><bottom style="thin"><color rgb="FFBFBFBF"/></bottom><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="6">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
<xf numFmtId="0" fontId="2" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
<xf numFmtId="3" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
<xf numFmtId="2" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def _workbook(sheet_name: str) -> str:
    # Excel rejects these characters in a sheet name, and caps it at 31 chars.
    safe = "".join(ch for ch in str(sheet_name or "Sheet1") if ch not in "[]:*?/\\")[:31] or "Sheet1"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="' + _esc(safe) + '" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )


def _cell(ref: str, value: Any, kind: str, style: int) -> str:
    if value is None or value == "":
        return f'<c r="{ref}" s="{style}"/>'
    if kind in ("int", "float"):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return f'<c r="{ref}" s="{STYLE_TEXT}" t="inlineStr"><is><t xml:space="preserve">{_esc(value)}</t></is></c>'
        if kind == "int":
            number = round(number)
            return f'<c r="{ref}" s="{style}"><v>{int(number)}</v></c>'
        return f'<c r="{ref}" s="{style}"><v>{number:.4f}</v></c>'
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{_esc(value)}</t></is></c>'


def build_xlsx(columns: Sequence[Dict[str, Any]], rows: Sequence[Sequence[Any]],
               sheet_name: str = "گزارش", titles: Optional[Sequence[str]] = None,
               rtl: bool = True) -> bytes:
    """Render one sheet to .xlsx bytes.

    `columns`: [{"header": str, "width": int, "type": "text"|"int"|"float"}]
    `rows`:    values in column order; extra values are ignored, missing ones blank.
    `titles`:  lines placed above the header, each merged across the full width.
    """
    columns = list(columns)
    width = max(1, len(columns))
    titles = list(titles or [])

    body: List[str] = []
    merges: List[str] = []
    row_no = 0

    for title in titles:
        row_no += 1
        body.append(
            f'<row r="{row_no}" ht="20" customHeight="1">'
            + _cell(f"A{row_no}", title, "text", STYLE_TITLE)
            + "</row>"
        )
        if width > 1:
            merges.append(f'<mergeCell ref="A{row_no}:{col_letter(width)}{row_no}"/>')
    if titles:
        row_no += 1
        body.append(f'<row r="{row_no}"/>')          # breathing room under the titles

    header_row = row_no + 1
    row_no = header_row
    body.append(
        f'<row r="{row_no}" ht="26" customHeight="1">'
        + "".join(
            _cell(f"{col_letter(i + 1)}{row_no}", col.get("header", ""), "text", STYLE_HEADER)
            for i, col in enumerate(columns)
        )
        + "</row>"
    )

    for values in rows:
        row_no += 1
        cells = []
        for i, col in enumerate(columns):
            kind = str(col.get("type") or "text")
            value = values[i] if i < len(values) else None
            cells.append(_cell(f"{col_letter(i + 1)}{row_no}", value, kind,
                               _TYPE_STYLES.get(kind, STYLE_TEXT)))
        body.append(f'<row r="{row_no}">' + "".join(cells) + "</row>")

    cols_xml = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{float(col.get("width") or 16):.2f}" customWidth="1"/>'
        for i, col in enumerate(columns)
    )
    last_row = max(row_no, header_row)
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{col_letter(width)}{last_row}"/>'
        f'<sheetViews><sheetView {"rightToLeft=\"1\" " if rtl else ""}tabSelected="1" workbookViewId="0">'
        f'<pane ySplit="{header_row}" topLeftCell="A{header_row + 1}" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        '<sheetFormatPr defaultRowHeight="18"/>'
        + (f"<cols>{cols_xml}</cols>" if cols_xml else "")
        + "<sheetData>" + "".join(body) + "</sheetData>"
        + (f'<autoFilter ref="A{header_row}:{col_letter(width)}{last_row}"/>' if row_no > header_row else "")
        + (f'<mergeCells count="{len(merges)}">{"".join(merges)}</mergeCells>' if merges else "")
        + "</worksheet>"
    )

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("xl/workbook.xml", _workbook(sheet_name))
        z.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        z.writestr("xl/styles.xml", _STYLES)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()
