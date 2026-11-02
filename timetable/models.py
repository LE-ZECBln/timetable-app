"""Core data models for the local timetable generator.

The module is deliberately dependency-free so it can be unit-tested without
Streamlit or any parser library.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from math import ceil
from typing import Any, Iterable, Sequence
from uuid import uuid4

WEEKDAY_NAMES: dict[int, str] = {
    1: "周一",
    2: "周二",
    3: "周三",
    4: "周四",
    5: "周五",
    6: "周六",
    7: "周日",
}

WEEKDAY_FULL_NAMES: dict[int, str] = {
    1: "星期一",
    2: "星期二",
    3: "星期三",
    4: "星期四",
    5: "星期五",
    6: "星期六",
    7: "星期日",
}

DEFAULT_TOTAL_WEEKS = 20
MAX_WEEKS = 60
MAX_PERIODS = 20

# A palette that keeps enough contrast on a projector and on paper.
COURSE_PALETTE: list[tuple[str, str]] = [
    ("#E8F1FF", "#1D4ED8"),
    ("#FFF0F3", "#BE123C"),
    ("#EAF8EF", "#15803D"),
    ("#FFF4E5", "#C2410C"),
    ("#F4ECFF", "#6D28D9"),
    ("#E7F8FA", "#0E7490"),
    ("#FFF9DB", "#A16207"),
    ("#F1EFEA", "#57534E"),
    ("#EEF0FF", "#3730A3"),
    ("#FDECEC", "#B91C1C"),
    ("#EAF4FF", "#0369A1"),
    ("#F0F7E8", "#4D7C0F"),
]


def normalize_hhmm(value: str) -> str:
    """Normalise ``8:00`` / ``08：00`` / ``08:00`` to ``08:00``."""

    text = str(value or "").strip().replace("：", ":").replace("．", ".")
    if not text:
        return ""
    parts = text.split(":")
    if len(parts) < 2:
        return text
    try:
        hour = int(parts[0])
        minute = int(parts[1][:2])
    except (TypeError, ValueError):
        return text
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return text
    return f"{hour:02d}:{minute:02d}"


def hhmm_to_minutes(value: str) -> int | None:
    text = normalize_hhmm(value)
    if not text or ":" not in text:
        return None
    try:
        hour, minute = text.split(":", 1)
        return int(hour) * 60 + int(minute)
    except (TypeError, ValueError):
        return None


def compress_weeks(weeks: Iterable[int]) -> str:
    """Compress ``[1,2,3,5,7,8]`` to ``1-3,5,7-8``."""

    numbers = sorted({int(w) for w in weeks if w})
    if not numbers:
        return ""
    ranges: list[tuple[int, int]] = []
    start = prev = numbers[0]
    for number in numbers[1:]:
        if number == prev + 1:
            prev = number
        else:
            ranges.append((start, prev))
            start = prev = number
    ranges.append((start, prev))
    parts: list[str] = []
    for first, last in ranges:
        parts.append(str(first) if first == last else f"{first}-{last}")
    return ",".join(parts)


def default_start_date() -> date:
    """Monday of the current local week."""

    today = date.today()
    return today - timedelta(days=today.weekday())


def _rows_from_standard() -> list["TimeRow"]:
    return [
        TimeRow("1-2节", 1, 2, "08:00", "09:45"),
        TimeRow("3-4节", 3, 4, "10:00", "11:45"),
        TimeRow("5-6节", 5, 6, "13:45", "15:30"),
        TimeRow("7-8节", 7, 8, "15:45", "17:30"),
        TimeRow("9-10节", 9, 10, "18:30", "20:15"),
        TimeRow("11-12节", 11, 12, "20:30", "22:15"),
    ]


@dataclass
class TimeRow:
    """One visible row of the timetable.

    A row normally covers two periods (``1-2节``), but the model also supports
    one-period rows and arbitrary ranges.
    """

    label: str
    period_start: int
    period_end: int
    start: str
    end: str

    def __post_init__(self) -> None:
        self.period_start = int(self.period_start)
        self.period_end = int(self.period_end)
        if self.period_start < 1:
            self.period_start = 1
        if self.period_end < self.period_start:
            self.period_end = self.period_start
        self.start = normalize_hhmm(self.start)
        self.end = normalize_hhmm(self.end)
        if not self.label:
            self.label = (
                f"{self.period_start}节"
                if self.period_start == self.period_end
                else f"{self.period_start}-{self.period_end}节"
            )

    @property
    def period_label(self) -> str:
        if self.period_start == self.period_end:
            return f"第{self.period_start}节"
        return f"{self.period_start}-{self.period_end}节"

    @property
    def time_label(self) -> str:
        if self.start and self.end:
            return f"{self.start}-{self.end}"
        return f"{self.start or '?'}-{self.end or '?'}"

    def covers(self, start: int, end: int) -> bool:
        return not (end < self.period_start or start > self.period_end)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "start": self.start,
            "end": self.end,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TimeRow":
        return cls(
            label=str(data.get("label", "")),
            period_start=int(data.get("period_start", 1)),
            period_end=int(data.get("period_end", 1)),
            start=str(data.get("start", "")),
            end=str(data.get("end", "")),
        )


@dataclass
class Template:
    """Timetable shape and time configuration."""

    mode: str = "standard"  # standard | custom
    total_weeks: int = DEFAULT_TOTAL_WEEKS
    days: list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5])
    rows: list[TimeRow] = field(default_factory=_rows_from_standard)
    start_date: date | None = field(default_factory=default_start_date)
    title: str = "我的课表"

    def __post_init__(self) -> None:
        self.mode = "custom" if self.mode == "custom" else "standard"
        self.total_weeks = max(1, min(MAX_WEEKS, int(self.total_weeks)))
        self.days = sorted({int(d) for d in self.days if 1 <= int(d) <= 7}) or [
            1,
            2,
            3,
            4,
            5,
        ]
        self.rows = sorted(self.rows, key=lambda row: row.period_start)
        if not self.rows:
            self.rows = _rows_from_standard()

    @property
    def max_period(self) -> int:
        return max((row.period_end for row in self.rows), default=0)

    @property
    def min_period(self) -> int:
        return min((row.period_start for row in self.rows), default=1)

    def row_indices_for(self, start_period: int, end_period: int) -> list[int]:
        if start_period < 1 or end_period < start_period:
            return []
        return [
            index
            for index, row in enumerate(self.rows)
            if row.covers(start_period, end_period)
        ]

    def time_range_for(self, start_period: int, end_period: int) -> tuple[str, str]:
        indices = self.row_indices_for(start_period, end_period)
        if not indices:
            return "", ""
        return self.rows[indices[0]].start, self.rows[indices[-1]].end

    def period_range_for_time(self, start: str, end: str = "") -> tuple[int, int] | None:
        """Map a wall-clock range to the closest period range."""

        start_minutes = hhmm_to_minutes(start)
        end_minutes = hhmm_to_minutes(end)
        if start_minutes is None:
            return None

        best: tuple[float, int, int] | None = None
        for row in self.rows:
            row_start = hhmm_to_minutes(row.start)
            row_end = hhmm_to_minutes(row.end)
            if row_start is None or row_end is None:
                continue
            score = abs(row_start - start_minutes)
            if end_minutes is not None:
                score += abs(row_end - end_minutes)
            if best is None or score < best[0]:
                best = (score, row.period_start, row.period_end)
        if best is None:
            return None
        # Reject wildly different times (more than 45 minutes away).
        if best[0] > 90:
            return None
        return best[1], best[2]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "total_weeks": self.total_weeks,
            "days": list(self.days),
            "rows": [row.to_dict() for row in self.rows],
            "start_date": self.start_date.isoformat() if self.start_date else "",
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Template":
        start_date: date | None = None
        raw_date = str(data.get("start_date", "") or "")
        if raw_date:
            try:
                start_date = date.fromisoformat(raw_date)
            except ValueError:
                start_date = None
        rows = [
            TimeRow.from_dict(item)
            for item in (data.get("rows") or [])
            if isinstance(item, dict)
        ]
        raw_days = data.get("days") or [1, 2, 3, 4, 5]
        raw_total = data.get("total_weeks") or DEFAULT_TOTAL_WEEKS
        return cls(
            mode=str(data.get("mode", "standard")),
            total_weeks=int(raw_total),
            days=[int(d) for d in raw_days],
            rows=rows or _rows_from_standard(),
            start_date=start_date,
            title=str(data.get("title", "我的课表")),
        )


_STANDARD_BLOCK_TIMES = [
    ("08:00", "09:45"),
    ("10:00", "11:45"),
    ("13:45", "15:30"),
    ("15:45", "17:30"),
    ("18:30", "20:15"),
    ("20:30", "22:15"),
]

_SINGLE_PERIOD_TIMES = [
    ("08:00", "08:45"),
    ("08:55", "09:40"),
    ("10:00", "10:45"),
    ("10:55", "11:40"),
    ("13:45", "14:30"),
    ("14:40", "15:25"),
    ("15:45", "16:30"),
    ("16:40", "17:25"),
    ("18:30", "19:15"),
    ("19:25", "20:10"),
    ("20:30", "21:15"),
    ("21:25", "22:10"),
]


def make_rows(periods_per_day: int, block_size: int = 2) -> list[TimeRow]:
    """Build editable default rows for the custom template."""

    periods_per_day = max(1, min(MAX_PERIODS, int(periods_per_day)))
    block_size = max(1, min(4, int(block_size)))
    block_count = ceil(periods_per_day / block_size)
    rows: list[TimeRow] = []
    for block_index in range(block_count):
        period_start = block_index * block_size + 1
        period_end = min(periods_per_day, period_start + block_size - 1)
        if block_size == 2 and block_index < len(_STANDARD_BLOCK_TIMES):
            start, end = _STANDARD_BLOCK_TIMES[block_index]
        elif block_size == 1 and period_start <= len(_SINGLE_PERIOD_TIMES):
            start, end = _SINGLE_PERIOD_TIMES[period_start - 1]
        else:
            minutes = 8 * 60 + block_index * (block_size * 45 + (block_size - 1) * 5 + 10)
            start = f"{minutes // 60:02d}:{minutes % 60:02d}"
            end_minutes = minutes + block_size * 45 + (block_size - 1) * 5
            end = f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
        rows.append(
            TimeRow(
                label=(
                    f"{period_start}节"
                    if period_start == period_end
                    else f"{period_start}-{period_end}节"
                ),
                period_start=period_start,
                period_end=period_end,
                start=start,
                end=end,
            )
        )
    return rows


def default_template(mode: str = "standard") -> Template:
    if mode == "custom":
        return Template(
            mode="custom",
            total_weeks=DEFAULT_TOTAL_WEEKS,
            days=[1, 2, 3, 4, 5],
            rows=make_rows(12, 2),
            start_date=default_start_date(),
        )
    return Template(
        mode="standard",
        total_weeks=DEFAULT_TOTAL_WEEKS,
        days=[1, 2, 3, 4, 5],
        rows=_rows_from_standard(),
        start_date=default_start_date(),
    )


@dataclass
class Course:
    """A single course occurrence on one weekday and one time range."""

    name: str
    teacher: str = ""
    classroom: str = ""
    weekday: int | None = None
    start_period: int | None = None
    end_period: int | None = None
    weeks: list[int] = field(default_factory=list)
    week_type: str = "all"  # all | odd | even
    week_expr: str = ""
    credits: float | None = None
    class_name: str = ""
    note: str = ""
    source: str = ""
    raw: str = ""
    issues: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid4().hex[:8])

    def __post_init__(self) -> None:
        self.name = str(self.name or "").strip()
        self.teacher = str(self.teacher or "").strip()
        self.classroom = str(self.classroom or "").strip()
        self.week_type = self.week_type if self.week_type in {"all", "odd", "even"} else "all"
        self.weeks = sorted({int(w) for w in self.weeks if 1 <= int(w) <= MAX_WEEKS})
        if self.weekday is not None:
            try:
                self.weekday = int(self.weekday)
            except (TypeError, ValueError):
                self.weekday = None
        if self.weekday is not None and not 1 <= self.weekday <= 7:
            self.weekday = None
        if self.start_period is not None:
            try:
                self.start_period = int(self.start_period)
            except (TypeError, ValueError):
                self.start_period = None
        if self.end_period is not None:
            try:
                self.end_period = int(self.end_period)
            except (TypeError, ValueError):
                self.end_period = None
        if self.start_period is not None and self.start_period < 1:
            self.start_period = None
        if self.end_period is not None and self.end_period < 1:
            self.end_period = None
        if self.start_period and not self.end_period:
            self.end_period = self.start_period
        if self.end_period and not self.start_period:
            self.start_period = self.end_period
        if self.start_period and self.end_period and self.end_period < self.start_period:
            self.start_period, self.end_period = self.end_period, self.start_period
        if not self.week_expr:
            self.week_expr = self._computed_week_expr()

    def _computed_week_expr(self) -> str:
        if self.weeks:
            return compress_weeks(self.weeks)
        if self.week_type == "odd":
            return "单周"
        if self.week_type == "even":
            return "双周"
        return "全周"

    @property
    def weekday_label(self) -> str:
        return WEEKDAY_NAMES.get(self.weekday or 0, "未设置")

    @property
    def period_label(self) -> str:
        if not self.start_period or not self.end_period:
            return "未排节次"
        if self.start_period == self.end_period:
            return f"第{self.start_period}节"
        return f"{self.start_period}-{self.end_period}节"

    @property
    def week_label(self) -> str:
        return self.week_expr or self._computed_week_expr()

    @property
    def scheduled(self) -> bool:
        return bool(self.weekday and self.start_period and self.end_period)

    @property
    def color_pair(self) -> tuple[str, str]:
        key = (self.name or "课程").encode("utf-8")
        index = int(hashlib.md5(key).hexdigest(), 16) % len(COURSE_PALETTE)
        return COURSE_PALETTE[index]

    def weeks_for_total(self, total_weeks: int) -> list[int]:
        total_weeks = max(1, int(total_weeks))
        if self.weeks:
            return [w for w in self.weeks if w <= total_weeks]
        if self.week_type == "odd":
            return [w for w in range(1, total_weeks + 1) if w % 2 == 1]
        if self.week_type == "even":
            return [w for w in range(1, total_weeks + 1) if w % 2 == 0]
        return list(range(1, total_weeks + 1))

    def is_active(self, week: int | None, total_weeks: int) -> bool:
        if week is None:
            return True
        if week < 1 or week > total_weeks:
            return False
        if self.weeks:
            return week in self.weeks
        if self.week_type == "odd":
            return week % 2 == 1
        if self.week_type == "even":
            return week % 2 == 0
        return True

    def add_issue(self, message: str) -> None:
        if message and message not in self.issues:
            self.issues.append(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "teacher": self.teacher,
            "classroom": self.classroom,
            "weekday": self.weekday or 0,
            "start_period": self.start_period or 0,
            "end_period": self.end_period or 0,
            "weeks": list(self.weeks),
            "week_type": self.week_type,
            "week_expr": self.week_expr,
            "credits": self.credits,
            "class_name": self.class_name,
            "note": self.note,
            "source": self.source,
            "raw": self.raw,
            "issues": list(self.issues),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Course":
        credits = data.get("credits")
        try:
            credits = float(credits) if credits not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            credits = None
        return cls(
            name=str(data.get("name", "")),
            teacher=str(data.get("teacher", "")),
            classroom=str(data.get("classroom", "")),
            weekday=int(data.get("weekday", 0) or 0) or None,
            start_period=int(data.get("start_period", 0) or 0) or None,
            end_period=int(data.get("end_period", 0) or 0) or None,
            weeks=[int(w) for w in data.get("weeks", []) if str(w).strip()],
            week_type=str(data.get("week_type", "all")),
            week_expr=str(data.get("week_expr", "")),
            credits=credits,
            class_name=str(data.get("class_name", "")),
            note=str(data.get("note", "")),
            source=str(data.get("source", "")),
            raw=str(data.get("raw", "")),
            issues=list(data.get("issues", [])),
            id=str(data.get("id", "")) or uuid4().hex[:8],
        )

    def clone(self, **changes: Any) -> "Course":
        data = self.to_dict()
        data.update(changes)
        return Course.from_dict(data)


@dataclass
class Conflict:
    a: Course
    b: Course
    weeks: list[int]

    @property
    def week_label(self) -> str:
        return compress_weeks(self.weeks) or "有重叠周次"


def weeks_intersection(a: Course, b: Course, total_weeks: int) -> list[int]:
    return sorted(set(a.weeks_for_total(total_weeks)) & set(b.weeks_for_total(total_weeks)))


def courses_conflict(a: Course, b: Course, total_weeks: int) -> bool:
    if not a.scheduled or not b.scheduled:
        return False
    if a.weekday != b.weekday:
        return False
    assert a.start_period and a.end_period and b.start_period and b.end_period
    if a.end_period < b.start_period or b.end_period < a.start_period:
        return False
    return bool(weeks_intersection(a, b, total_weeks))


def find_conflicts(courses: Sequence[Course], total_weeks: int) -> list[Conflict]:
    conflicts: list[Conflict] = []
    for index, first in enumerate(courses):
        if not first.scheduled:
            continue
        for second in courses[index + 1 :]:
            if courses_conflict(first, second, total_weeks):
                weeks = weeks_intersection(first, second, total_weeks)
                if weeks:
                    conflicts.append(Conflict(first, second, weeks))
    return conflicts


def course_key(course: Course) -> tuple[Any, ...]:
    return (
        course.name.strip().lower(),
        course.teacher.strip().lower(),
        course.classroom.strip().lower(),
        course.weekday or 0,
        course.start_period or 0,
        course.end_period or 0,
        tuple(course.weeks),
        course.week_type,
    )


def dedupe_courses(courses: Iterable[Course]) -> list[Course]:
    """Remove exact duplicates while keeping the richest record."""

    merged: dict[tuple[Any, ...], Course] = {}
    for course in courses:
        key = course_key(course)
        existing = merged.get(key)
        if existing is None:
            merged[key] = course
            continue
        # Keep the record with more non-empty fields, but merge notes/issues.
        score_existing = sum(
            bool(value)
            for value in (
                existing.teacher,
                existing.classroom,
                existing.weeks,
                existing.credits,
                existing.class_name,
                existing.note,
            )
        )
        score_new = sum(
            bool(value)
            for value in (
                course.teacher,
                course.classroom,
                course.weeks,
                course.credits,
                course.class_name,
                course.note,
            )
        )
        if score_new > score_existing:
            course.issues = list(dict.fromkeys(existing.issues + course.issues))
            merged[key] = course
        else:
            existing.issues = list(dict.fromkeys(existing.issues + course.issues))
    return list(merged.values())


def merge_adjacent_slots(courses: Sequence[Course]) -> list[Course]:
    """Merge duplicated/adjacent rows that describe the same course block."""

    groups: dict[tuple[Any, ...], list[Course]] = {}
    for course in courses:
        if not course.scheduled:
            groups[(course.id,)] = [course]
            continue
        key = (
            course.name.strip().lower(),
            course.teacher.strip().lower(),
            course.classroom.strip().lower(),
            course.weekday,
            tuple(course.weeks),
            course.week_type,
            course.class_name.strip().lower(),
        )
        groups.setdefault(key, []).append(course)

    result: list[Course] = []
    for group in groups.values():
        if len(group) == 1 or not group[0].scheduled:
            result.extend(group)
            continue
        group = sorted(group, key=lambda c: (c.start_period or 0, c.end_period or 0))
        current = group[0]
        for course in group[1:]:
            current_end = current.end_period or 0
            course_start = course.start_period or 0
            if course_start <= current_end + 1:
                current.end_period = max(current_end, course.end_period or 0)
                current.issues = list(dict.fromkeys(current.issues + course.issues))
            else:
                result.append(current)
                current = course
        result.append(current)
    return result


def sort_courses(courses: Iterable[Course]) -> list[Course]:
    return sorted(
        courses,
        key=lambda c: (
            c.weekday or 8,
            c.start_period or 99,
            c.end_period or 99,
            c.name,
        ),
    )


def week_date(template: Template, week: int, weekday: int) -> date | None:
    if not template.start_date:
        return None
    return template.start_date + timedelta(weeks=max(0, week - 1), days=max(0, weekday - 1))


def week_date_label(template: Template, week: int, weekday: int) -> str:
    value = week_date(template, week, weekday)
    if value is None:
        return ""
    return f"{value.month:02d}/{value.day:02d}"


def format_credits(value: float | None) -> str:
    if value is None:
        return ""
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:g}"
