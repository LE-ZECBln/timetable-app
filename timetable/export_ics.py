"""ICS calendar export (local file only)."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone

from .layout import GridLayout
from .models import Course, default_start_date, normalize_hhmm


def _escape(value: str) -> str:
    text = str(value or "")
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    return text


def _fold(line: str) -> str:
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    chunks: list[str] = []
    current = ""
    for character in line:
        if len((current + character).encode("utf-8")) > 73:
            chunks.append(current)
            current = character
        else:
            current += character
    if current:
        chunks.append(current)
    return "\r\n ".join(chunks)


def _event(
    course: Course,
    event_date: date,
    start: str,
    end: str,
    week: int,
) -> list[str]:
    start_time = time.fromisoformat(normalize_hhmm(start))
    end_time = time.fromisoformat(normalize_hhmm(end))
    start_dt = datetime.combine(event_date, start_time)
    end_dt = datetime.combine(event_date, end_time)
    uid = hashlib.md5(
        f"{course.id}-{week}-{event_date.isoformat()}".encode("utf-8")
    ).hexdigest()
    description_parts = [
        f"教师：{course.teacher}" if course.teacher else "",
        f"教室：{course.classroom}" if course.classroom else "",
        f"周次：{course.week_label}",
        f"班级：{course.class_name}" if course.class_name else "",
        f"备注：{course.note}" if course.note else "",
    ]
    description = "；".join(part for part in description_parts if part)
    return [
        "BEGIN:VEVENT",
        f"UID:{uid}@local-timetable",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART;TZID=Asia/Shanghai:{start_dt.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND;TZID=Asia/Shanghai:{end_dt.strftime('%Y%m%dT%H%M%S')}",
        f"SUMMARY:{_escape(course.name)}",
        f"LOCATION:{_escape(course.classroom)}",
        f"DESCRIPTION:{_escape(description)}",
        "CATEGORIES:课程",
        "STATUS:CONFIRMED",
        "TRANSP:OPAQUE",
        "SEQUENCE:0",
        "END:VEVENT",
    ]


def render_ics(layout: GridLayout) -> bytes:
    template = layout.template
    start_date = template.start_date or default_start_date()
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Local Timetable Generator//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(template.title or '我的课表')}",
        "X-WR-TIMEZONE:Asia/Shanghai",
        "BEGIN:VTIMEZONE",
        "TZID:Asia/Shanghai",
        "X-LIC-LOCATION:Asia/Shanghai",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        "TZOFFSETFROM:+0800",
        "TZOFFSETTO:+0800",
        "TZNAME:CST",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]

    event_count = 0
    for course in layout.courses:
        if not course.scheduled:
            continue
        start, end = template.time_range_for(
            course.start_period or 0, course.end_period or 0
        )
        if not start or not end:
            continue
        if layout.week is not None:
            weeks = [layout.week]
        else:
            weeks = course.weeks_for_total(template.total_weeks)
        for week in weeks:
            event_date = start_date + timedelta(
                weeks=week - 1, days=(course.weekday or 1) - 1
            )
            lines.extend(_event(course, event_date, start, end, week))
            event_count += 1
    lines.append("END:VCALENDAR")
    text = "\r\n".join(_fold(line) for line in lines) + "\r\n"
    return text.encode("utf-8")


def render_ics_summary(layout: GridLayout) -> int:
    """Count events without building the file (used for UI hints)."""

    template = layout.template
    count = 0
    for course in layout.courses:
        if not course.scheduled:
            continue
        start, end = template.time_range_for(
            course.start_period or 0, course.end_period or 0
        )
        if not start or not end:
            continue
        if layout.week is not None:
            count += 1
        else:
            count += len(course.weeks_for_total(template.total_weeks))
    return count
