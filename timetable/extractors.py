"""File-to-text/table extractors.

Supported formats (all processed locally):

* ``.txt`` / ``.text``
* ``.md`` / ``.markdown`` (including pipe tables)
* ``.docx`` (paragraphs + tables, including merged cells)
* ``.pdf`` (text layer + tables; scanned pages fall back to OCR)
* ``.xlsx`` (all sheets, merged cells filled)
* ``.csv``
* ``.png`` / ``.jpg`` / ``.webp`` / ``.bmp`` / ``.tif`` (OCR)
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .ocr import ocr_image
from .parsing import TableData, normalize_cell

MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_TEXT_CHARS = 400_000
MAX_PDF_PAGES = 120
MAX_OCR_PAGES = 12
MAX_EXCEL_ROWS = 300
MAX_EXCEL_COLUMNS = 60


@dataclass
class ExtractResult:
    filename: str
    kind: str
    text: str = ""
    tables: list[TableData] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ocr_used: bool = False
    page_count: int = 0
    char_count: int = 0

    def finalize(self) -> "ExtractResult":
        if len(self.text) > MAX_TEXT_CHARS:
            self.text = self.text[:MAX_TEXT_CHARS]
            self.notes.append(f"文本过长，已截断为 {MAX_TEXT_CHARS} 字符。")
        self.char_count = len(self.text)
        return self


def extract_bytes(filename: str, data: bytes) -> ExtractResult:
    safe_name = Path(filename or "未命名").name
    suffix = Path(safe_name).suffix.lower()
    if len(data) > MAX_FILE_BYTES:
        return ExtractResult(
            filename=safe_name,
            kind=suffix.lstrip(".") or "unknown",
            errors=[f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)} MB 限制。"],
        )
    if not data:
        return ExtractResult(
            filename=safe_name,
            kind=suffix.lstrip(".") or "unknown",
            errors=["文件为空。"],
        )

    try:
        if suffix in {".txt", ".text"}:
            return extract_txt(safe_name, data).finalize()
        if suffix in {".md", ".markdown"}:
            return extract_markdown(safe_name, data).finalize()
        if suffix == ".docx":
            return extract_docx(safe_name, data).finalize()
        if suffix == ".pdf":
            return extract_pdf(safe_name, data).finalize()
        if suffix == ".xlsx":
            return extract_xlsx(safe_name, data).finalize()
        if suffix == ".csv":
            return extract_csv(safe_name, data).finalize()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
            return extract_image(safe_name, data).finalize()
        if suffix == ".doc":
            return ExtractResult(
                filename=safe_name,
                kind="doc",
                errors=["暂不支持旧版 .doc，请用 Word 另存为 .docx 后再上传。"],
            )
        if suffix == ".xls":
            return ExtractResult(
                filename=safe_name,
                kind="xls",
                errors=["暂不支持旧版 .xls，请另存为 .xlsx 或 CSV 后再上传。"],
            )
        return ExtractResult(
            filename=safe_name,
            kind=suffix.lstrip(".") or "unknown",
            errors=[f"暂不支持 {suffix or '该'} 格式。"],
        )
    except Exception as exc:  # pragma: no cover - defensive
        return ExtractResult(
            filename=safe_name,
            kind=suffix.lstrip(".") or "unknown",
            errors=[f"读取失败：{type(exc).__name__}: {exc}"],
        ).finalize()


def decode_text(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8 (replace)"


def extract_txt(filename: str, data: bytes) -> ExtractResult:
    text, encoding = decode_text(data)
    return ExtractResult(
        filename=filename,
        kind="txt",
        text=text,
        notes=[f"文本编码：{encoding}"],
    )


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def extract_markdown(filename: str, data: bytes) -> ExtractResult:
    text, encoding = decode_text(data)
    tables, cleaned = _markdown_tables(text, filename)
    return ExtractResult(
        filename=filename,
        kind="markdown",
        text=cleaned,
        tables=tables,
        notes=[f"文本编码：{encoding}"] + ([f"识别到 {len(tables)} 个 Markdown 表格"] if tables else []),
    )


def _markdown_tables(text: str, filename: str = "") -> tuple[list[TableData], str]:
    lines = text.split("\n")
    tables: list[TableData] = []
    cleaned_lines: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if "|" not in line:
            cleaned_lines.append(line)
            index += 1
            continue
        block: list[str] = []
        probe = index
        while probe < len(lines) and "|" in lines[probe]:
            block.append(lines[probe])
            probe += 1
        if len(block) >= 2 and _is_markdown_separator(block[1]):
            rows: list[list[str]] = []
            for block_line in block:
                if _is_markdown_separator(block_line):
                    continue
                rows.append(_split_markdown_row(block_line))
            if rows:
                tables.append(TableData(rows=rows, source=f"{filename} 表格"))
            cleaned_lines.append("")
            index = probe
            continue
        cleaned_lines.extend(block)
        index = probe
    return tables, "\n".join(cleaned_lines)


def _is_markdown_separator(line: str) -> bool:
    value = line.strip().strip("|").strip()
    if not value:
        return False
    return bool(re.fullmatch(r"[:\-\s|]+", value)) and "-" in value


def _split_markdown_row(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [normalize_cell(cell) for cell in value.split("|")]


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def extract_docx(filename: str, data: bytes) -> ExtractResult:
    from docx import Document

    document = Document(io.BytesIO(data))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    tables: list[TableData] = []
    for index, table in enumerate(document.tables):
        matrix = _docx_table_to_matrix(table)
        if matrix:
            tables.append(TableData(rows=matrix, source=f"{filename} 表格{index + 1}"))
    return ExtractResult(
        filename=filename,
        kind="docx",
        text="\n".join(paragraphs),
        tables=tables,
        notes=(
            [f"段落 {len(paragraphs)} 个，表格 {len(tables)} 个"]
            if paragraphs or tables
            else ["文档中没有可读取的段落或表格。"]
        ),
    )


def _docx_table_to_matrix(table: Any) -> list[list[str]]:
    """Convert a python-docx table to a matrix, handling gridSpan/vMerge."""

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    tbl = table._tbl
    rows: list[list[str]] = []
    vmerge_origin: dict[int, str] = {}
    max_width = 0

    for tr in tbl.findall("./w:tr", ns):
        row: list[str] = []
        column = 0
        for tc in tr.findall("./w:tc", ns):
            tc_pr = tc.find("./w:tcPr", ns)
            span = 1
            vmerge: str | None = None
            if tc_pr is not None:
                grid_span = tc_pr.find("./w:gridSpan", ns)
                if grid_span is not None:
                    try:
                        span = max(1, int(grid_span.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "1")))
                    except (TypeError, ValueError):
                        span = 1
                vmerge_element = tc_pr.find("./w:vMerge", ns)
                if vmerge_element is not None:
                    vmerge = vmerge_element.get(
                        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val",
                        "continue",
                    )
            text = _docx_cell_text(tc, ns)
            if vmerge == "restart":
                vmerge_origin[column] = text
            elif vmerge == "continue":
                text = vmerge_origin.get(column, "")
            elif vmerge is None:
                vmerge_origin.pop(column, None)
            row.append(text)
            for _ in range(span - 1):
                row.append("")
            column += span
        max_width = max(max_width, len(row))
        rows.append(row)

    for row in rows:
        row.extend([""] * (max_width - len(row)))
    while rows and all(not cell for cell in rows[-1]):
        rows.pop()
    return rows


def _docx_cell_text(tc: Any, ns: dict[str, str]) -> str:
    paragraphs: list[str] = []
    for paragraph in tc.findall("./w:p", ns):
        pieces: list[str] = []
        for node in paragraph.iter():
            tag = node.tag.split("}")[-1]
            if tag == "t":
                pieces.append(node.text or "")
            elif tag == "tab":
                pieces.append(" ")
            elif tag == "br":
                pieces.append("\n")
        value = "".join(pieces).strip()
        if value:
            paragraphs.append(value)
    return "\n".join(paragraphs)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def extract_pdf(filename: str, data: bytes) -> ExtractResult:
    import pdfplumber

    result = ExtractResult(filename=filename, kind="pdf")
    page_texts: list[str] = []
    ocr_pages: list[int] = []

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        result.page_count = len(pdf.pages)
        if result.page_count > MAX_PDF_PAGES:
            result.notes.append(f"PDF 共 {result.page_count} 页，仅解析前 {MAX_PDF_PAGES} 页。")
        for index, page in enumerate(pdf.pages[:MAX_PDF_PAGES]):
            try:
                text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            except Exception:
                text = ""
            page_texts.append(text)
            try:
                raw_tables = page.extract_tables() or []
            except Exception:
                raw_tables = []
            for table_index, raw_table in enumerate(raw_tables):
                matrix = [[normalize_cell(cell) for cell in row] for row in raw_table]
                if any(any(cell for cell in row) for row in matrix):
                    result.tables.append(
                        TableData(
                            rows=matrix,
                            source=f"{filename} 第{index + 1}页 表格{table_index + 1}",
                        )
                    )
            if len(text.strip()) < 15:
                ocr_pages.append(index)

    if ocr_pages:
        ocr_texts, ocr_tables, ocr_notes = _ocr_pdf_pages(data, ocr_pages, filename)
        result.ocr_used = bool(ocr_texts)
        result.notes.extend(ocr_notes)
        result.tables.extend(ocr_tables)
        for page_index, text in ocr_texts.items():
            if page_index < len(page_texts):
                page_texts[page_index] = (page_texts[page_index] + "\n" + text).strip()
            else:
                page_texts.append(text)

    result.text = "\n\n".join(text for text in page_texts if text.strip())
    if result.page_count:
        result.notes.append(f"PDF 共 {result.page_count} 页")
    if not result.text and not result.tables:
        result.notes.append("PDF 没有可提取的文字或表格；如果是扫描件，请确认 OCR 依赖已安装，或上传页面图片。")
    return result


def _ocr_pdf_pages(
    data: bytes, page_indexes: Sequence[int], filename: str
) -> tuple[dict[int, str], list[TableData], list[str]]:
    notes: list[str] = []
    texts: dict[int, str] = {}
    tables: list[TableData] = []
    try:
        import pypdfium2 as pdfium
    except Exception as exc:  # pragma: no cover
        return {}, [], [f"扫描页 OCR 不可用（pypdfium2 未安装）：{exc}"]

    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:
        return {}, [], [f"扫描页 OCR 失败：{exc}"]

    try:
        for page_index in page_indexes[:MAX_OCR_PAGES]:
            try:
                page = document[page_index]
                bitmap = page.render(scale=2.0)
                image = bitmap.to_pil()
                ocr_result = ocr_image(image, source=f"{filename} 第{page_index + 1}页")
            except Exception as exc:
                notes.append(f"第 {page_index + 1} 页 OCR 失败：{exc}")
                continue
            if ocr_result.error:
                notes.append(f"第 {page_index + 1} 页：{ocr_result.error}")
                continue
            if ocr_result.text.strip():
                texts[page_index] = ocr_result.text
                notes.append(f"第 {page_index + 1} 页使用了本地 OCR")
            if not ocr_result.tables:
                notes.append(f"第 {page_index + 1} 页未还原出可靠表格，建议重点校对")
            for table in ocr_result.tables:
                table.source = f"{filename} 第{page_index + 1}页 OCR 表格"
                tables.append(table)
    finally:
        try:
            document.close()
        except Exception:
            pass
    return texts, tables, notes


# ---------------------------------------------------------------------------
# XLSX / CSV
# ---------------------------------------------------------------------------


def extract_xlsx(filename: str, data: bytes) -> ExtractResult:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), data_only=True, read_only=False)
    result = ExtractResult(filename=filename, kind="xlsx")
    text_parts: list[str] = []
    for sheet in workbook.worksheets:
        max_row = min(sheet.max_row or 0, MAX_EXCEL_ROWS)
        max_column = min(sheet.max_column or 0, MAX_EXCEL_COLUMNS)
        if max_row <= 0 or max_column <= 0:
            continue
        matrix = [
            [
                _excel_cell_text(sheet.cell(row=row_index, column=column_index).value)
                for column_index in range(1, max_column + 1)
            ]
            for row_index in range(1, max_row + 1)
        ]
        for merged_range in sheet.merged_cells.ranges:
            min_col, min_row, max_col, max_row_merged = merged_range.bounds
            if min_row > max_row or min_col > max_column:
                continue
            value = _excel_cell_text(sheet.cell(row=min_row, column=min_col).value)
            for row_index in range(min_row, min(max_row_merged, max_row) + 1):
                for column_index in range(min_col, min(max_col, max_column) + 1):
                    matrix[row_index - 1][column_index - 1] = value
        matrix = [row for row in matrix if any(cell.strip() for cell in row)]
        if not matrix:
            continue
        result.tables.append(
            TableData(rows=matrix, source=f"{filename} / {sheet.title}")
        )
        text_parts.append(f"【{sheet.title}】\n" + "\n".join(" ".join(row) for row in matrix))
    result.text = "\n\n".join(text_parts)
    result.notes.append(f"工作表 {len(result.tables)} 个")
    if not result.tables:
        result.notes.append("工作簿中没有非空工作表。")
    return result


def _excel_cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def extract_csv(filename: str, data: bytes) -> ExtractResult:
    text, encoding = decode_text(data)
    sample = text[:4096]
    dialect: Any = None
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    matrix = [[normalize_cell(cell) for cell in row] for row in rows]
    matrix = [row for row in matrix if any(cell for cell in row)]
    return ExtractResult(
        filename=filename,
        kind="csv",
        text=text,
        tables=[TableData(rows=matrix, source=filename)] if matrix else [],
        notes=[f"文本编码：{encoding}，{len(matrix)} 行"],
    )


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def extract_image(filename: str, data: bytes) -> ExtractResult:
    ocr_result = ocr_image(data, source=filename)
    result = ExtractResult(
        filename=filename,
        kind="image",
        text=ocr_result.text,
        tables=ocr_result.tables,
        notes=list(ocr_result.notes),
        ocr_used=bool(ocr_result.text),
    )
    if ocr_result.error:
        result.errors.append(ocr_result.error)
    if not ocr_result.text and not ocr_result.tables:
        result.notes.append("图片中没有识别到文字。可以换一张更清晰、正对拍摄的图片再试。")
    return result


def summarize_extraction(result: ExtractResult) -> str:
    parts = [
        f"{result.filename}（{result.kind}）",
        f"{result.char_count} 字符",
    ]
    if result.page_count:
        parts.append(f"{result.page_count} 页")
    if result.tables:
        parts.append(f"{len(result.tables)} 个表格")
    if result.ocr_used:
        parts.append("OCR")
    return "，".join(parts)
