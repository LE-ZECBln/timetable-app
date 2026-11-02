"""Small facade used by the Streamlit UI and the tests."""

from __future__ import annotations

from .export_excel import render_excel
from .export_ics import render_ics
from .layout import GridLayout
from .render_html import render_html, render_print_html
from .render_image import render_pdf, render_png


def export_bytes(layout: GridLayout, fmt: str) -> bytes:
    fmt = fmt.lower()
    if fmt in {"xlsx", "excel"}:
        return render_excel(layout)
    if fmt in {"png", "image"}:
        return render_png(layout)
    if fmt in {"pdf"}:
        return render_pdf(layout)
    if fmt in {"ics", "ical"}:
        return render_ics(layout)
    if fmt in {"html", "print"}:
        return render_print_html(layout).encode("utf-8")
    raise ValueError(f"不支持的导出格式：{fmt}")
