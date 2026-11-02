"""Excel export: a merged weekly grid plus a flat course list."""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .layout import GridLayout
from .models import Course, WEEKDAY_NAMES, format_credits

_HEADER_FILL = PatternFill("solid", fgColor="FF0F172A")
_SUBHEADER_FILL = PatternFill("solid", fgColor="FF1E293B")
_TIME_FILL = PatternFill("solid", fgColor="FFF1F5F9")
_EMPTY_FILL = PatternFill("solid", fgColor="FFFFFFFF")
_WEEKEND_FILL = PatternFill("solid", fgColor="FFFBFCFE")
_WHITE_FONT = Font(name="微软雅黑", size=10, bold=True, color="FFFFFFFF")
_TITLE_FONT = Font(name="微软雅黑", size=18, bold=True, color="FFFFFFFF")
_SUBTITLE_FONT = Font(name="微软雅黑", size=9, color="FF64748B")
_BODY_FONT = Font(name="微软雅黑", size=9, color="FF0F172A")
_TIME_FONT = Font(name="微软雅黑", size=9, bold=True, color="FF334155")
_THIN = Side(style="thin", color="FFE2E8F0")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)


def _argb(hex_color: str) -> str:
    value = (hex_color or "#FFFFFF").lstrip("#")
    if len(value) == 6:
        return "FF" + value.upper()
    return "FFFFFFFF"


def _safe(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _course_cell_text(course: Course) -> str:
    lines = [course.name]
    meta = " · ".join(part for part in (course.teacher, course.classroom) if part)
    if meta:
        lines.append(meta)
    if course.week_label:
        lines.append(course.week_label)
    return "\n".join(lines)


def render_excel(layout: GridLayout) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "课表"
    sheet.sheet_view.showGridLines = False
    days = layout.days
    column_count = 1 + len(days)

    # Title & subtitle
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=column_count)
    title_cell = sheet.cell(row=1, column=1, value=_safe(layout.template.title or "我的课表"))
    title_cell.font = _TITLE_FONT
    title_cell.fill = _HEADER_FILL
    title_cell.alignment = _CENTER
    sheet.row_dimensions[1].height = 38

    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=column_count)
    subtitle_cell = sheet.cell(
        row=2,
        column=1,
        value=f"{layout.week_label} · {layout.days_label} · 共 {layout.template.total_weeks} 周",
    )
    subtitle_cell.font = _SUBTITLE_FONT
    subtitle_cell.alignment = _LEFT
    sheet.row_dimensions[2].height = 22

    # Header
    header_values = ["节次 / 时间"] + [
        f"{WEEKDAY_NAMES.get(day, str(day))}"
        for day in days
    ]
    for column, value in enumerate(header_values, start=1):
        cell = sheet.cell(row=3, column=column, value=_safe(value))
        cell.font = _WHITE_FONT
        cell.fill = _SUBHEADER_FILL
        cell.alignment = _CENTER
        cell.border = _BORDER
    sheet.row_dimensions[3].height = 30

    data_start = 4
    for row_index, row in enumerate(layout.template.rows):
        sheet_row = data_start + row_index
        sheet.row_dimensions[sheet_row].height = 74
        time_cell = sheet.cell(
            row=sheet_row,
            column=1,
            value=f"{row.period_label}\n{row.time_label}",
        )
        time_cell.font = _TIME_FONT
        time_cell.fill = _TIME_FILL
        time_cell.alignment = _CENTER
        time_cell.border = _BORDER

        for column_index, day in enumerate(days, start=2):
            key = (row_index, day)
            cell = sheet.cell(row=sheet_row, column=column_index)
            cell.border = _BORDER
            cell.alignment = _CENTER
            if key in layout.covered:
                continue
            courses = layout.cell_courses(row_index, day)
            if not courses:
                cell.fill = _WEEKEND_FILL if day >= 6 else _EMPTY_FILL
                continue
            span = max(1, layout.rowspans.get(key, 1))
            if span > 1:
                sheet.merge_cells(
                    start_row=sheet_row,
                    start_column=column_index,
                    end_row=min(sheet_row + span - 1, data_start + len(layout.template.rows) - 1),
                    end_column=column_index,
                )
            first = courses[0]
            background, foreground = first.color_pair
            cell.value = _safe("\n\n".join(_course_cell_text(course) for course in courses))
            cell.fill = PatternFill("solid", fgColor=_argb(background))
            cell.font = Font(name="微软雅黑", size=9, color=_argb(foreground))
            cell.alignment = _CENTER

    last_table_row = data_start + len(layout.template.rows) - 1
    last_table_column = column_count
    sheet.column_dimensions["A"].width = 17
    for column_index in range(2, column_count + 1):
        sheet.column_dimensions[get_column_letter(column_index)].width = 28
    sheet.freeze_panes = "B4"
    sheet.print_area = f"A1:{get_column_letter(last_table_column)}{last_table_row}"
    sheet.print_title_rows = "1:3"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = 9  # A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_margins.left = 0.3
    sheet.page_margins.right = 0.3
    sheet.page_margins.top = 0.4
    sheet.page_margins.bottom = 0.4

    # Course list
    list_sheet = workbook.create_sheet("课程清单")
    list_sheet.sheet_view.showGridLines = False
    headers = ["课程名称", "教师", "教室", "星期", "节次", "周次", "学分", "班级", "备注", "来源"]
    for column, header in enumerate(headers, start=1):
        cell = list_sheet.cell(row=1, column=column, value=header)
        cell.font = _WHITE_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER
        cell.border = _BORDER
    for row_index, course in enumerate(layout.all_courses, start=2):
        values = [
            course.name,
            course.teacher,
            course.classroom,
            course.weekday_label,
            course.period_label,
            course.week_label,
            format_credits(course.credits),
            course.class_name,
            course.note,
            course.source,
        ]
        for column, value in enumerate(values, start=1):
            cell = list_sheet.cell(row=row_index, column=column, value=_safe(value))
            cell.font = _BODY_FONT
            cell.alignment = _LEFT if column in (1, 2, 3, 8, 9, 10) else _CENTER
            cell.border = _BORDER
    list_sheet.freeze_panes = "A2"
    list_sheet.auto_filter.ref = f"A1:J{max(1, len(layout.all_courses) + 1)}"
    widths = [26, 12, 16, 9, 11, 14, 8, 18, 22, 22]
    for column, width in enumerate(widths, start=1):
        list_sheet.column_dimensions[get_column_letter(column)].width = width

    # Conflicts / unscheduled
    if layout.conflicts or layout.unscheduled:
        issue_sheet = workbook.create_sheet("冲突与待安排")
        issue_sheet.sheet_view.showGridLines = False
        row = 1
        if layout.conflicts:
            issue_sheet.cell(row=row, column=1, value="时间冲突").font = Font(
                name="微软雅黑", size=12, bold=True, color="FFB91C1C"
            )
            row += 1
            for column, header in enumerate(
                ["课程 A", "课程 B", "星期", "节次", "重叠周次"], start=1
            ):
                cell = issue_sheet.cell(row=row, column=column, value=header)
                cell.font = _WHITE_FONT
                cell.fill = _SUBHEADER_FILL
                cell.border = _BORDER
                cell.alignment = _CENTER
            row += 1
            for conflict in layout.conflicts:
                values = [
                    conflict.a.name,
                    conflict.b.name,
                    WEEKDAY_NAMES.get(conflict.a.weekday or 0, "未设置"),
                    conflict.a.period_label,
                    conflict.week_label,
                ]
                for column, value in enumerate(values, start=1):
                    cell = issue_sheet.cell(row=row, column=column, value=_safe(value))
                    cell.font = _BODY_FONT
                    cell.alignment = _LEFT
                    cell.border = _BORDER
                row += 1
            row += 1
        if layout.unscheduled:
            issue_sheet.cell(row=row, column=1, value="待安排课程").font = Font(
                name="微软雅黑", size=12, bold=True, color="FFB45309"
            )
            row += 1
            for column, header in enumerate(
                ["课程", "教师", "教室", "周次", "原因"], start=1
            ):
                cell = issue_sheet.cell(row=row, column=column, value=header)
                cell.font = _WHITE_FONT
                cell.fill = _SUBHEADER_FILL
                cell.border = _BORDER
                cell.alignment = _CENTER
            row += 1
            for course in layout.unscheduled:
                values = [
                    course.name,
                    course.teacher,
                    course.classroom,
                    course.week_label,
                    "；".join(course.issues) or "缺少星期或节次",
                ]
                for column, value in enumerate(values, start=1):
                    cell = issue_sheet.cell(row=row, column=column, value=_safe(value))
                    cell.font = _BODY_FONT
                    cell.alignment = _LEFT
                    cell.border = _BORDER
                row += 1

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
