"""HTML rendering for the in-app timetable and a standalone print page."""

from __future__ import annotations

from html import escape
from typing import Sequence

from .layout import GridLayout, card_geometry
from .models import WEEKDAY_NAMES, Course, week_date_label

_CSS = r"""
.tt-app, .tt-page {
  --tt-ink: #0f172a;
  --tt-muted: #64748b;
  --tt-line: #e2e8f0;
  --tt-soft: #f8fafc;
  --tt-accent: #2563eb;
  color: var(--tt-ink);
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
  color-scheme: light;
}
.tt-app *, .tt-page * { box-sizing: border-box; }
.tt-scroll { overflow-x: auto; padding-bottom: 4px; }
.tt-head {
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: 16px; margin: 0 0 14px 0;
}
.tt-title { margin: 0; font-size: 26px; line-height: 1.2; letter-spacing: -.02em; }
.tt-subtitle { margin: 6px 0 0 0; color: var(--tt-muted); font-size: 13px; }
.tt-badge {
  flex: none; padding: 8px 13px; border-radius: 999px;
  background: #eff6ff; color: #1d4ed8; font-size: 13px; font-weight: 700;
  border: 1px solid #bfdbfe; white-space: nowrap;
}
.tt-table {
  width: 100%; border-collapse: separate; border-spacing: 0;
  table-layout: fixed; background: #fff; border-radius: 12px; overflow: hidden;
  box-shadow: 0 1px 2px rgba(15,23,42,.05);
}
.tt-table th, .tt-table td {
  border-right: 1px solid var(--tt-line); border-bottom: 1px solid var(--tt-line);
  vertical-align: top;
}
.tt-table th:first-child, .tt-table td:first-child { border-left: 1px solid var(--tt-line); }
.tt-table thead th {
  background: #0f172a; color: #fff; font-size: 13px; font-weight: 700;
  padding: 11px 6px; text-align: center; border-color: #1e293b;
}
.tt-table thead th:first-child { border-top-left-radius: 12px; }
.tt-table thead th:last-child { border-top-right-radius: 12px; }
.tt-table thead .tt-date { display: block; margin-top: 3px; font-size: 10px; font-weight: 400; opacity: .65; }
.tt-corner { width: 112px; }
.tt-time {
  width: 112px; background: var(--tt-soft); text-align: center; padding: 10px 6px;
  font-size: 12px; color: #475569;
}
.tt-time b { display: block; font-size: 13px; color: var(--tt-ink); }
.tt-time span { display: block; margin-top: 3px; font-size: 10px; color: var(--tt-muted); }
.tt-cell { padding: 5px; height: 84px; background: #fff; position: relative; }
.tt-cell.tt-weekend { background: #fcfdff; }
.tt-empty { background:
  linear-gradient(135deg, transparent 0 48%, #f1f5f9 48% 52%, transparent 52% 100%);
  background-size: 14px 14px;
}
.tt-course {
  background: var(--tt-bg, #eff6ff); color: var(--tt-fg, #1d4ed8);
  border-left: 3px solid var(--tt-fg, #1d4ed8);
  border-radius: 8px; padding: 7px 8px 6px 8px; min-height: 52px;
  overflow: hidden; position: relative;
}
.tt-course.tt-course-partial {
  position: absolute; left: 5px; right: 5px;
  top: calc(var(--tt-top, 0%) + 4px);
  height: calc(var(--tt-height, 100%) - 8px);
  min-height: 0;
}
.tt-course.tt-course-partial .tt-name { font-size: 11.5px; }
.tt-course.tt-course-partial .tt-meta { font-size: 9.5px; margin-top: 2px; }
.tt-course.tt-course-partial .tt-weeks { font-size: 9px; margin-top: 1px; }
.tt-course + .tt-course { margin-top: 4px; }
.tt-name { font-size: 12.5px; font-weight: 700; line-height: 1.3; word-break: break-word; }
.tt-meta { margin-top: 3px; font-size: 10.5px; line-height: 1.35; opacity: .9; word-break: break-word; }
.tt-weeks { margin-top: 2px; font-size: 9.5px; opacity: .68; }
.tt-warn {
  position: absolute; top: 4px; right: 5px; font-size: 11px;
  color: #dc2626; background: #fff; border-radius: 999px; padding: 0 3px;
}
.tt-cell-conflict { box-shadow: inset 0 0 0 2px #fecaca; }
.tt-section { margin-top: 18px; }
.tt-section h3 { margin: 0 0 8px 0; font-size: 14px; }
.tt-section ul { margin: 0; padding-left: 18px; font-size: 12px; color: #475569; }
.tt-section li { margin: 4px 0; }
.tt-section .tt-danger { color: #b91c1c; }
.tt-note { margin-top: 12px; color: var(--tt-muted); font-size: 11px; }
.tt-stats { display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0 0 0; }
.tt-stat {
  border: 1px solid var(--tt-line); background: #fff; border-radius: 10px;
  padding: 8px 12px; font-size: 11px; color: var(--tt-muted);
}
.tt-stat b { display: block; font-size: 17px; color: var(--tt-ink); }
.tt-toolbar { margin: 0 0 14px 0; }
.tt-print-btn {
  border: 0; border-radius: 8px; background: #2563eb; color: #fff;
  padding: 9px 16px; font-size: 13px; font-weight: 700; cursor: pointer;
}
.tt-print-btn:hover { background: #1d4ed8; }
.tt-page { background: #fff; max-width: 1240px; margin: 0 auto; padding: 24px; }
.tt-footer { margin-top: 18px; color: var(--tt-muted); font-size: 10px; text-align: right; }
@media print {
  @page { size: A4 landscape; margin: 9mm; }
  body { background: #fff !important; }
  .tt-page { max-width: none; padding: 0; }
  .tt-toolbar { display: none !important; }
  .tt-table { box-shadow: none; border-radius: 0; }
  .tt-table thead th { background: #0f172a !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .tt-course { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .tt-cell { height: 84px; min-height: 84px; }
  tr, td, th { page-break-inside: avoid; }
}
"""


def _e(value: object) -> str:
    return escape(str(value or ""))


def _course_tooltip(course: Course) -> str:
    parts = [
        course.name,
        f"{course.weekday_label} {course.period_label}",
        course.week_label,
    ]
    if course.teacher:
        parts.append(f"教师：{course.teacher}")
    if course.classroom:
        parts.append(f"教室：{course.classroom}")
    if course.class_name:
        parts.append(f"班级：{course.class_name}")
    if course.issues:
        parts.append("提示：" + "；".join(course.issues))
    return "\n".join(part for part in parts if part)


def _course_card(
    course: Course,
    conflict: bool = False,
    geometry: tuple[float, float] | None = None,
) -> str:
    background, foreground = course.color_pair
    warning = ""
    if conflict or course.issues:
        warning = '<span class="tt-warn" title="有冲突或需要核对">⚠</span>'
    meta_parts = [part for part in (course.teacher, course.classroom) if part]
    meta = (
        f'<div class="tt-meta">{_e(" · ".join(meta_parts))}</div>'
        if meta_parts
        else ""
    )
    classes = "tt-course"
    if conflict:
        classes += " tt-course-conflict"
    style = f"--tt-bg:{background};--tt-fg:{foreground}"
    if geometry is not None:
        classes += " tt-course-partial"
        top, height = geometry
        style += f";--tt-top:{top * 100:.2f}%;--tt-height:{height * 100:.2f}%"
    return (
        f'<div class="{classes}" style="{style}" '
        f'title="{_e(_course_tooltip(course))}">'
        f"{warning}"
        f'<div class="tt-name">{_e(course.name)}</div>'
        f"{meta}"
        f'<div class="tt-weeks">{_e(course.week_label)}</div>'
        f"</div>"
    )


def _conflict_section(layout: GridLayout) -> str:
    if not layout.conflicts:
        return ""
    items: list[str] = []
    for conflict in layout.conflicts[:30]:
        items.append(
            "<li>"
            f"{_e(conflict.a.name)} × {_e(conflict.b.name)}"
            f" · {_e(WEEKDAY_NAMES.get(conflict.a.weekday or 0, '未设置'))}"
            f" {_e(conflict.a.period_label)}"
            f" · 重叠周次：{_e(conflict.week_label)}"
            "</li>"
        )
    more = (
        f"<li>另有 {len(layout.conflicts) - 30} 组冲突未展开。</li>"
        if len(layout.conflicts) > 30
        else ""
    )
    return (
        '<div class="tt-section">'
        '<h3 class="tt-danger">⚠ 时间冲突</h3>'
        f'<ul>{"".join(items)}{more}</ul>'
        "</div>"
    )


def _unscheduled_section(layout: GridLayout) -> str:
    if not layout.unscheduled:
        return ""
    items = []
    for course in layout.unscheduled[:40]:
        reason = "；".join(course.issues) if course.issues else "缺少星期或节次"
        items.append(
            f"<li>{_e(course.name)}"
            f"{' · ' + _e(course.teacher) if course.teacher else ''}"
            f" · <span class='tt-danger'>{_e(reason)}</span></li>"
        )
    more = (
        f"<li>另有 {len(layout.unscheduled) - 40} 门课程未展开。</li>"
        if len(layout.unscheduled) > 40
        else ""
    )
    return (
        '<div class="tt-section">'
        "<h3>待安排课程</h3>"
        f"<ul>{''.join(items)}{more}</ul>"
        "</div>"
    )


def _stats(layout: GridLayout) -> str:
    active = layout.courses
    unique_names = len({course.name for course in active if course.name})
    teacher_count = len({course.teacher for course in active if course.teacher})
    classroom_count = len({course.classroom for course in active if course.classroom})
    return (
        '<div class="tt-stats">'
        f'<div class="tt-stat"><b>{unique_names}</b>门课程</div>'
        f'<div class="tt-stat"><b>{len(layout.conflicts)}</b>组冲突</div>'
        f'<div class="tt-stat"><b>{teacher_count}</b>位教师</div>'
        f'<div class="tt-stat"><b>{classroom_count}</b>间教室</div>'
        "</div>"
    )


def render_html(
    layout: GridLayout,
    standalone: bool = False,
    include_sections: bool = True,
) -> str:
    template = layout.template
    title = template.title or "我的课表"
    conflict_ids = {
        course.id
        for conflict in layout.conflicts
        for course in (conflict.a, conflict.b)
    }
    parts: list[str] = []
    parts.append('<div class="tt-app">' if not standalone else '<div class="tt-page">')
    parts.append(
        '<div class="tt-head">'
        f'<div><h1 class="tt-title">{_e(title)}</h1>'
        f'<p class="tt-subtitle">{_e(layout.week_label)} · {_e(layout.days_label)}'
        f" · 共 {template.total_weeks} 周</p></div>"
        f'<div class="tt-badge">{_e(layout.week_label)}</div>'
        "</div>"
    )
    if standalone:
        parts.append(
            '<div class="tt-toolbar">'
            '<button class="tt-print-btn" onclick="window.print()">打印 / 另存为 PDF</button>'
            "</div>"
        )
    parts.append('<div class="tt-scroll"><table class="tt-table">')
    parts.append('<colgroup><col style="width:112px">')
    for _day in layout.days:
        parts.append("<col>")
    parts.append("</colgroup><thead><tr>")
    parts.append('<th class="tt-corner">节次 / 时间</th>')
    for day in layout.days:
        date_label = week_date_label(template, layout.week, day) if layout.week else ""
        parts.append(
            f"<th>{_e(WEEKDAY_NAMES.get(day, str(day)))}"
            f"{f'<span class=\"tt-date\">{_e(date_label)}</span>' if date_label else ''}"
            "</th>"
        )
    parts.append("</tr></thead><tbody>")

    for row_index, row in enumerate(template.rows):
        parts.append("<tr>")
        parts.append(
            f'<th class="tt-time"><b>{_e(row.period_label)}</b>'
            f"<span>{_e(row.time_label)}</span></th>"
        )
        for day in layout.days:
            key = (row_index, day)
            if key in layout.covered:
                continue
            courses = layout.cell_courses(row_index, day)
            span = layout.rowspans.get(key, 1)
            weekend = " tt-weekend" if day >= 6 else ""
            if not courses:
                parts.append(f'<td class="tt-cell tt-empty{weekend}"></td>')
                continue
            conflict = any(course.id in conflict_ids for course in courses)
            cell_classes = "tt-cell" + weekend + (" tt-cell-conflict" if conflict else "")
            rowspan_attr = f' rowspan="{span}"' if span > 1 else ""
            if len(courses) == 1:
                top, height = card_geometry(
                    courses[0], template, row_index, span
                )
                geometry = (
                    (top, height)
                    if top > 0.001 or height < 0.999
                    else None
                )
                cards = _course_card(
                    courses[0],
                    conflict=courses[0].id in conflict_ids,
                    geometry=geometry,
                )
            else:
                cards = "".join(
                    _course_card(course, conflict=course.id in conflict_ids)
                    for course in courses
                )
            parts.append(
                f'<td class="{cell_classes}"{rowspan_attr}>{cards}</td>'
            )
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    if include_sections:
        parts.append(_stats(layout))
        parts.append(_conflict_section(layout))
        parts.append(_unscheduled_section(layout))
    parts.append(
        '<div class="tt-note">提示：点击课程卡片可查看教师、教室与周次；'
        "颜色由课程名称自动分配。所有数据均在本机处理。</div>"
    )
    parts.append("</div>")

    body = "\n".join(parts)
    if not standalone:
        return f"<style>{_CSS}</style>{body}"
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)} · {_e(layout.week_label)}</title>"
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )


def render_print_html(layout: GridLayout) -> str:
    return render_html(layout, standalone=True, include_sections=True)
