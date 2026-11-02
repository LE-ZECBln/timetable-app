from __future__ import annotations

import io
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from timetable.extractors import (
    extract_bytes,
    extract_csv,
    extract_docx,
    extract_image,
    extract_markdown,
    extract_xlsx,
)
from timetable.parsing import parse_table
from timetable.models import default_template


def _font(size: int = 34):
    for candidate in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


class ExtractorTests(unittest.TestCase):
    def test_txt(self) -> None:
        data = "高等数学 张三 周一 1-2节 1-16周 教A101".encode("utf-8")
        result = extract_bytes("a.txt", data)
        self.assertEqual(result.kind, "txt")
        self.assertIn("高等数学", result.text)

    def test_markdown_table(self) -> None:
        data = (
            "| 课程名称 | 教师 | 星期 | 节次 | 周次 | 教室 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| 高等数学 | 张三 | 周一 | 1-2节 | 1-16周 | 教A101 |\n"
        ).encode("utf-8")
        result = extract_markdown("a.md", data)
        self.assertEqual(len(result.tables), 1)
        self.assertEqual(len(result.tables[0].rows), 2)

    def test_csv(self) -> None:
        data = (
            "课程名称,教师,星期,节次,周次,教室\n"
            "高等数学,张三,周一,1-2节,1-16周,教A101\n"
        ).encode("utf-8-sig")
        result = extract_csv("a.csv", data)
        self.assertEqual(result.kind, "csv")
        self.assertEqual(len(result.tables), 1)

    def test_xlsx(self) -> None:
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "课程"
        sheet.append(["课程名称", "教师", "星期", "节次", "周次", "教室"])
        sheet.append(["高等数学", "张三", "周一", "1-2节", "1-16周", "教A101"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        result = extract_xlsx("a.xlsx", buffer.getvalue())
        self.assertEqual(len(result.tables), 1)
        outcome = parse_table(result.tables[0], default_template())
        self.assertTrue(any("高等数学" in c.name for c in outcome.courses))

    def test_docx(self) -> None:
        from docx import Document

        document = Document()
        document.add_heading("2026 秋季课表", level=1)
        table = document.add_table(rows=2, cols=6)
        headers = ["课程名称", "教师", "星期", "节次", "周次", "教室"]
        values = ["高等数学", "张三", "周一", "1-2节", "1-16周", "教A101"]
        for column, header in enumerate(headers):
            table.cell(0, column).text = header
            table.cell(1, column).text = values[column]
        buffer = io.BytesIO()
        document.save(buffer)
        result = extract_docx("a.docx", buffer.getvalue())
        self.assertEqual(len(result.tables), 1)
        outcome = parse_table(result.tables[0], default_template())
        self.assertEqual(len(outcome.courses), 1)
        self.assertEqual(outcome.courses[0].teacher, "张三")

    def test_docx_merged_grid(self) -> None:
        from docx import Document

        document = Document()
        table = document.add_table(rows=3, cols=3)
        for column, header in enumerate(["节次", "周一", "周二"]):
            table.cell(0, column).text = header
        table.cell(1, 0).text = "1-2节"
        table.cell(1, 1).text = "高等数学\n张三\n教A101"
        table.cell(2, 0).text = "3-4节"
        table.cell(1, 1).merge(table.cell(2, 1))
        buffer = io.BytesIO()
        document.save(buffer)
        result = extract_docx("grid.docx", buffer.getvalue())
        self.assertEqual(len(result.tables), 1)
        outcome = parse_table(result.tables[0], default_template())
        math = next(c for c in outcome.courses if "高等数学" in c.name)
        self.assertEqual(math.weekday, 1)
        self.assertEqual((math.start_period, math.end_period), (1, 4))
        self.assertEqual(math.teacher, "张三")

    def test_xlsx_merged_grid(self) -> None:
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["节次", "周一", "周二"])
        sheet.append(["1-2节", "高等数学\n张三\n教A101", ""])
        sheet.append(["3-4节", "", "大学英语\n李四\n外语楼201"])
        sheet.merge_cells("B2:B3")
        buffer = io.BytesIO()
        workbook.save(buffer)
        result = extract_xlsx("grid.xlsx", buffer.getvalue())
        outcome = parse_table(result.tables[0], default_template())
        math = next(c for c in outcome.courses if "高等数学" in c.name)
        self.assertEqual(math.weekday, 1)
        self.assertEqual((math.start_period, math.end_period), (1, 4))
        english = next(c for c in outcome.courses if "大学英语" in c.name)
        self.assertEqual(english.weekday, 2)
        self.assertEqual((english.start_period, english.end_period), (3, 4))

    def test_gbk_text(self) -> None:
        data = "高等数学 张三 周一 1-2节 1-16周 教A101".encode("gb18030")
        result = extract_bytes("gbk.txt", data)
        self.assertIn("高等数学", result.text)

    def test_image_ocr(self) -> None:
        image = Image.new("RGB", (900, 220), "white")
        draw = ImageDraw.Draw(image)
        font = _font(36)
        draw.text((30, 30), "高等数学 张三", font=font, fill="black")
        draw.text((30, 100), "周一 1-2节 1-16周 教A101", font=font, fill="black")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        result = extract_image("a.png", buffer.getvalue())
        self.assertTrue(result.text)
        self.assertIn("高等数学", result.text.replace(" ", ""))

    def test_image_ocr_grid(self) -> None:
        image = Image.new("RGB", (1100, 520), "white")
        draw = ImageDraw.Draw(image)
        font = _font(30)
        small = _font(24)
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
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        result = extract_image("grid.png", buffer.getvalue())
        self.assertTrue(result.tables)
        outcome = parse_table(result.tables[0], default_template())
        self.assertTrue(any("高等数学" in c.name for c in outcome.courses))
        self.assertTrue(any("大学英语" in c.name for c in outcome.courses))

    def test_scan_pdf_ocr(self) -> None:
        image = Image.new("RGB", (900, 220), "white")
        draw = ImageDraw.Draw(image)
        font = _font(36)
        draw.text((30, 30), "大学英语 李四", font=font, fill="black")
        draw.text((30, 100), "周二 3-4节 1-16周 外语楼201", font=font, fill="black")
        buffer = io.BytesIO()
        image.save(buffer, format="PDF", resolution=150)
        result = extract_bytes("a.pdf", buffer.getvalue())
        self.assertEqual(result.kind, "pdf")
        self.assertTrue(result.text)


if __name__ == "__main__":
    unittest.main()
