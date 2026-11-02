from __future__ import annotations

import io
import unittest

from timetable.export_excel import render_excel
from timetable.export_ics import render_ics
from timetable.layout import build_layout, card_geometry
from timetable.models import Course, default_template
from timetable.render_html import render_html, render_print_html
from timetable.render_image import render_pdf, render_png


def sample_courses() -> list[Course]:
    return [
        Course(
            name="高等数学A",
            teacher="张三",
            classroom="教A101",
            weekday=1,
            start_period=1,
            end_period=2,
            weeks=list(range(1, 17)),
            week_expr="1-16周",
            credits=4,
        ),
        Course(
            name="大学英语",
            teacher="李四",
            classroom="外语楼201",
            weekday=2,
            start_period=3,
            end_period=4,
            weeks=list(range(1, 17)),
            week_expr="1-16周",
            credits=3,
        ),
        Course(
            name="操作系统",
            teacher="赵六",
            classroom="教B202",
            weekday=1,
            start_period=7,
            end_period=8,
            weeks=list(range(1, 9)),
            week_expr="1-8周",
        ),
        Course(
            name="体育（篮球）",
            teacher="孙七",
            classroom="体育馆",
            weekday=5,
            start_period=9,
            end_period=10,
            weeks=list(range(1, 17)),
            week_expr="1-16周",
        ),
        Course(
            name="人工智能导论",
            teacher="周八",
            weekday=3,
            start_period=3,
            end_period=4,
            weeks=[1, 2, 3],
            week_expr="1-3周",
        ),
    ]


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.template = default_template("standard")
        self.template.start_date = self.template.start_date
        self.courses = sample_courses()
        self.layout = build_layout(self.courses, self.template, week=1)

    def test_layout(self) -> None:
        self.assertEqual(len(self.layout.courses), 5)
        self.assertTrue(self.layout.has_courses)
        self.assertEqual(self.layout.cell_courses(0, 1)[0].name, "高等数学A")

    def test_partial_block_geometry(self) -> None:
        course = Course(
            name="数值分析",
            teacher="王五",
            classroom="正心楼31",
            weekday=1,
            start_period=9,
            end_period=11,
            weeks=[1, 2],
            week_expr="1-2周",
        )
        layout = build_layout([course], self.template, week=1)
        self.assertEqual(layout.rowspans.get((4, 1)), 2)
        top, height = card_geometry(course, self.template, 4, 2)
        self.assertAlmostEqual(top, 0.0)
        self.assertAlmostEqual(height, 0.75)
        html = render_html(layout)
        self.assertIn("tt-course-partial", html)
        self.assertIn("--tt-height:75.00%", html)

    def test_html(self) -> None:
        html = render_html(self.layout)
        self.assertIn("高等数学A", html)
        self.assertIn("tt-table", html)
        self.assertIn("教A101", html)

    def test_print_html(self) -> None:
        html = render_print_html(self.layout)
        self.assertIn("<!doctype html>", html)
        self.assertIn("window.print()", html)

    def test_excel(self) -> None:
        data = render_excel(self.layout)
        self.assertGreater(len(data), 3000)
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(data))
        self.assertIn("课表", workbook.sheetnames)
        self.assertIn("课程清单", workbook.sheetnames)
        self.assertEqual(workbook["课程清单"].max_row, 6)

    def test_png_and_pdf(self) -> None:
        png = render_png(self.layout)
        self.assertTrue(png.startswith(b"\x89PNG"))
        pdf = render_pdf(self.layout)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_ics(self) -> None:
        data = render_ics(self.layout)
        text = data.decode("utf-8")
        self.assertIn("BEGIN:VCALENDAR", text)
        self.assertIn("SUMMARY:高等数学A", text)
        self.assertIn("DTSTART;TZID=Asia/Shanghai:", text)
        self.assertGreaterEqual(text.count("BEGIN:VEVENT"), 5)


if __name__ == "__main__":
    unittest.main()
