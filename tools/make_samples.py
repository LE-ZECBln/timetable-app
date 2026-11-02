"""Generate the files under ``samples/`` and the README preview image."""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from PIL import Image, ImageDraw, ImageFont
from docx import Document
from openpyxl import Workbook

from timetable.export_excel import render_excel
from timetable.export_ics import render_ics
from timetable.layout import build_layout
from timetable.models import Course, default_template
from timetable.render_html import render_print_html
from timetable.render_image import render_pdf, render_png
from timetable.samples import SAMPLE_TABLE_TEXT, SAMPLE_TEXT

SAMPLE_DIR = ROOT / "samples"
ASSET_DIR = ROOT / "assets"
FONT = r"C:\Windows\Fonts\msyh.ttc"


def courses() -> list[Course]:
    return [
        Course("高等数学A", "张三", "教A101", 1, 1, 2, list(range(1, 17)), "all", "1-16周", 4),
        Course("大学英语", "李四", "外语楼201", 2, 3, 4, list(range(1, 17)), "all", "1-16周", 3),
        Course("数据结构", "王五", "计算机楼305", 3, 5, 6, list(range(1, 17)), "all", "1-16周", 3),
        Course("操作系统", "赵六", "教B202", 4, 7, 8, list(range(1, 9)), "all", "1-8周", 3),
        Course("操作系统", "赵六", "教B203", 5, 7, 8, list(range(9, 17)), "all", "9-16周", 3),
        Course("体育（篮球）", "孙七", "体育馆", 5, 9, 10, list(range(1, 17)), "all", "1-16周", 1),
        Course("人工智能导论", "周八", "线上", 1, 9, 10, list(range(1, 9)), "all", "1-8周", 2),
    ]


def make_docx() -> None:
    document = Document()
    document.add_heading("2026 秋季学期课程表", level=1)
    document.add_paragraph("以下为示例课程清单，可直接上传本文件测试解析。")
    table = document.add_table(rows=1, cols=7)
    headers = ["课程名称", "教师", "星期", "节次", "周次", "教室", "学分"]
    for index, header in enumerate(headers):
        table.cell(0, index).text = header
    for course in courses():
        row = table.add_row().cells
        values = [
            course.name,
            course.teacher,
            course.weekday_label,
            course.period_label,
            course.week_label,
            course.classroom,
            str(course.credits or ""),
        ]
        for index, value in enumerate(values):
            row[index].text = value
    document.save(SAMPLE_DIR / "示例课程.docx")


def make_xlsx() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "课程清单"
    sheet.append(["课程名称", "教师", "星期", "节次", "周次", "教室", "学分"])
    for course in courses():
        sheet.append(
            [
                course.name,
                course.teacher,
                course.weekday_label,
                course.period_label,
                course.week_label,
                course.classroom,
                course.credits,
            ]
        )
    workbook.save(SAMPLE_DIR / "示例课程.xlsx")


def make_grid_image() -> None:
    font = ImageFont.truetype(FONT, 30)
    small = ImageFont.truetype(FONT, 24)
    image = Image.new("RGB", (1100, 520), "white")
    draw = ImageDraw.Draw(image)
    for x in (0, 180, 640, 1100):
        draw.line((x, 0, x, 520), fill="black", width=3)
    for y in (0, 100, 300, 500):
        draw.line((0, y, 1100, y), fill="black", width=3)
    draw.text((50, 30), "节次", font=font, fill="black")
    draw.text((300, 30), "周一", font=font, fill="black")
    draw.text((760, 30), "周二", font=font, fill="black")
    draw.text((30, 130), "1-2节", font=small, fill="black")
    draw.text((220, 120), "高等数学", font=small, fill="black")
    draw.text((220, 160), "张三", font=small, fill="black")
    draw.text((220, 200), "教A101", font=small, fill="black")
    draw.text((30, 330), "3-4节", font=small, fill="black")
    draw.text((680, 320), "大学英语", font=small, fill="black")
    draw.text((680, 360), "李四", font=small, fill="black")
    draw.text((680, 400), "外语楼201", font=small, fill="black")
    image.save(SAMPLE_DIR / "示例课表-图片OCR.png")


def main() -> None:
    SAMPLE_DIR.mkdir(exist_ok=True)
    ASSET_DIR.mkdir(exist_ok=True)
    (SAMPLE_DIR / "示例课程.txt").write_text(SAMPLE_TEXT, encoding="utf-8")
    (SAMPLE_DIR / "示例课程.md").write_text(SAMPLE_TABLE_TEXT, encoding="utf-8")
    make_docx()
    make_xlsx()
    make_grid_image()

    template = default_template("standard")
    layout = build_layout(courses(), template, week=1)
    (SAMPLE_DIR / "示例课表.png").write_bytes(render_png(layout))
    (SAMPLE_DIR / "示例课表-扫描版.pdf").write_bytes(render_pdf(layout))
    (SAMPLE_DIR / "示例课表.xlsx").write_bytes(render_excel(layout))
    (SAMPLE_DIR / "示例课表.ics").write_bytes(render_ics(layout))
    (SAMPLE_DIR / "示例课表-打印.html").write_text(
        render_print_html(layout), encoding="utf-8"
    )
    (ASSET_DIR / "demo.png").write_bytes(render_png(layout))
    print("samples and demo image generated")


if __name__ == "__main__":
    main()
