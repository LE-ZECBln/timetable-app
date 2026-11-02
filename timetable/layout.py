"""Turn parsed courses into a renderable weekly grid."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .models import (
    Conflict,
    Course,
    Template,
    WEEKDAY_NAMES,
    find_conflicts,
    sort_courses,
)


@dataclass
class GridLayout:
    template: Template
    week: int | None
    days: list[int]
    courses: list[Course]
    all_courses: list[Course] = field(default_factory=list)
    cells: dict[tuple[int, int], list[Course]] = field(default_factory=dict)
    rowspans: dict[tuple[int, int], int] = field(default_factory=dict)
    covered: set[tuple[int, int]] = field(default_factory=set)
    conflicts: list[Conflict] = field(default_factory=list)
    unscheduled: list[Course] = field(default_factory=list)

    @property
    def week_label(self) -> str:
        if self.week is None:
            return "全部周次"
        return f"第 {self.week} 周"

    @property
    def days_label(self) -> str:
        if self.days == [1, 2, 3, 4, 5]:
            return "周一至周五"
        if self.days == [1, 2, 3, 4, 5, 6, 7]:
            return "周一至周日"
        return "、".join(WEEKDAY_NAMES.get(day, str(day)) for day in self.days)

    @property
    def has_courses(self) -> bool:
        return any(self.cells.values())

    def cell_courses(self, row: int, day: int) -> list[Course]:
        return self.cells.get((row, day), [])


def build_layout(
    courses: Sequence[Course],
    template: Template,
    week: int | None = None,
) -> GridLayout:
    layout = GridLayout(
        template=template,
        week=week,
        days=list(template.days),
        courses=[],
        all_courses=sort_courses(courses),
    )
    active: list[Course] = []
    for course in courses:
        if not course.scheduled:
            layout.unscheduled.append(course)
            continue
        if week is not None and not course.is_active(week, template.total_weeks):
            continue
        row_indices = template.row_indices_for(
            course.start_period or 0, course.end_period or 0
        )
        if not row_indices:
            layout.unscheduled.append(course)
            continue
        if course.weekday not in template.days:
            # A course on a day hidden by the template is still "unscheduled"
            # for this view, but keep it visible in the warning list.
            layout.unscheduled.append(course)
            continue
        active.append(course)
        for row_index in row_indices:
            layout.cells.setdefault((row_index, course.weekday), []).append(course)

    layout.courses = active
    layout.conflicts = find_conflicts(active, template.total_weeks)
    layout.unscheduled = sort_courses(_dedupe_by_id(layout.unscheduled))
    _compute_spans(layout)
    return layout


def _dedupe_by_id(courses: Iterable[Course]) -> list[Course]:
    seen: set[str] = set()
    result: list[Course] = []
    for course in courses:
        if course.id in seen:
            continue
        seen.add(course.id)
        result.append(course)
    return result


def _compute_spans(layout: GridLayout) -> None:
    """Merge a course cell vertically when it exclusively occupies the rows."""

    for day in layout.days:
        for row_index in range(len(layout.template.rows)):
            key = (row_index, day)
            if key in layout.covered:
                continue
            cell = layout.cells.get(key, [])
            if len(cell) != 1:
                continue
            course = cell[0]
            rows = [
                index
                for index, row in enumerate(layout.template.rows)
                if row.covers(course.start_period or 0, course.end_period or 0)
            ]
            if not rows or rows[0] != row_index:
                continue
            rows = list(range(rows[0], rows[-1] + 1))
            if any(
                layout.cells.get((index, day), []) != [course] for index in rows
            ):
                continue
            layout.rowspans[key] = len(rows)
            for index in rows[1:]:
                layout.covered.add((index, day))


def card_geometry(
    course: Course, template: Template, row_index: int, span: int
) -> tuple[float, float]:
    """Return ``(top_fraction, height_fraction)`` inside a spanned cell.

    Standard-template rows cover two periods.  A course such as 9-11节 fills
    the 9-10 block and only half of the 11-12 block, so the card should be
    1.5 rows tall rather than a full two-row span.
    """

    rows = template.rows[row_index : row_index + max(1, span)]
    if not rows:
        return 0.0, 1.0
    total_periods = sum(
        max(0, row.period_end - row.period_start + 1) for row in rows
    )
    if total_periods <= 0:
        return 0.0, 1.0
    start = course.start_period or rows[0].period_start
    end = course.end_period or rows[-1].period_end
    start = max(start, rows[0].period_start)
    end = min(end, rows[-1].period_end)
    covered = 0
    for row in rows:
        covered += max(
            0, min(row.period_end, end) - max(row.period_start, start) + 1
        )
    top = max(0.0, min(1.0, (start - rows[0].period_start) / total_periods))
    height = max(0.0, min(1.0 - top, covered / total_periods))
    return top, height
