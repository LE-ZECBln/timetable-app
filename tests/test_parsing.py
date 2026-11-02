from __future__ import annotations

import unittest

from timetable.models import Course, Template, default_template
from timetable.parsing import TableData, parse_table, parse_text


class TextParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.template = default_template("standard")

    def test_one_line_records(self) -> None:
        text = """
        高等数学A 张三 周一 第1-2节 1-16周 教A101
        大学英语 李四 周二 第3-4节 1-16周 外语楼201
        """
        outcome = parse_text(text, self.template, "text")
        self.assertEqual(len(outcome.courses), 2)
        first = next(c for c in outcome.courses if "高等数学" in c.name)
        self.assertEqual(first.teacher, "张三")
        self.assertEqual(first.weekday, 1)
        self.assertEqual((first.start_period, first.end_period), (1, 2))
        self.assertEqual(first.classroom, "教A101")
        self.assertEqual(first.weeks, list(range(1, 17)))

    def test_labeled_multiline(self) -> None:
        text = """
        课程名称：高等数学A
        教师：张三
        上课时间：周一 第1-2节
        周次：1-16周
        上课地点：教A101
        """
        outcome = parse_text(text, self.template, "text")
        self.assertEqual(len(outcome.courses), 1)
        course = outcome.courses[0]
        self.assertEqual(course.name, "高等数学A")
        self.assertEqual(course.teacher, "张三")
        self.assertEqual(course.classroom, "教A101")
        self.assertEqual(course.weekday, 1)
        self.assertEqual(course.start_period, 1)
        self.assertEqual(course.end_period, 2)

    def test_multiple_time_slots(self) -> None:
        text = """
        数据结构 王五
        周一 1-2节
        周三 3-4节
        1-16周
        计算机楼305
        """
        outcome = parse_text(text, self.template, "text")
        self.assertEqual(len(outcome.courses), 2)
        days = sorted(c.weekday for c in outcome.courses)
        self.assertEqual(days, [1, 3])
        monday = next(c for c in outcome.courses if c.weekday == 1)
        wednesday = next(c for c in outcome.courses if c.weekday == 3)
        self.assertEqual((monday.start_period, monday.end_period), (1, 2))
        self.assertEqual((wednesday.start_period, wednesday.end_period), (3, 4))

    def test_odd_even_weeks(self) -> None:
        text = """
        操作系统 赵六 周一 1-2节 1-16周(单) 教B202
        数据库 钱七 周二 3-4节 1-16周(双) 教B203
        """
        outcome = parse_text(text, self.template, "text")
        self.assertEqual(len(outcome.courses), 2)
        odd = next(c for c in outcome.courses if "操作系统" in c.name)
        even = next(c for c in outcome.courses if "数据库" in c.name)
        self.assertEqual(odd.week_type, "odd")
        self.assertEqual(odd.weeks, [1, 3, 5, 7, 9, 11, 13, 15])
        self.assertEqual(even.week_type, "even")
        self.assertEqual(even.weeks, [2, 4, 6, 8, 10, 12, 14, 16])

    def test_missing_time_goes_unscheduled(self) -> None:
        text = "人工智能导论 周八 3学分"
        outcome = parse_text(text, self.template, "text")
        self.assertEqual(len(outcome.courses), 1)
        self.assertFalse(outcome.courses[0].scheduled)
        self.assertTrue(outcome.courses[0].issues)

    def test_weekend(self) -> None:
        text = "篮球 孙七 周六 第9-10节 1-8周 体育馆"
        outcome = parse_text(text, self.template, "text")
        self.assertEqual(outcome.courses[0].weekday, 6)
        self.assertEqual(outcome.courses[0].classroom, "体育馆")

    def test_bare_period_line(self) -> None:
        text = "高等数学\n张三\n周一\n1-2\n1-16周\nA101"
        outcome = parse_text(text, self.template, "text")
        self.assertEqual(len(outcome.courses), 1)
        course = outcome.courses[0]
        self.assertEqual(course.weekday, 1)
        self.assertEqual((course.start_period, course.end_period), (1, 2))
        self.assertEqual(course.classroom, "A101")

    def test_time_range_line(self) -> None:
        text = "高等数学\n张三\n周一\n08:00-09:45\n1-16周\nA101"
        outcome = parse_text(text, self.template, "text")
        self.assertEqual(len(outcome.courses), 1)
        course = outcome.courses[0]
        self.assertEqual(course.weekday, 1)
        self.assertEqual((course.start_period, course.end_period), (1, 2))

    def test_time_first_name_last_with_slash_periods(self) -> None:
        text = (
            "星期一   下午5/6节    诚意楼415   自控系统\n"
            "星期一   晚上9/11节  正心楼31    数值分析理论\n"
            "星期二   晚上9/10节  理学楼L520  数值上机\n"
            "星期三   晚上9/11节  正心楼31    数值分析理论\n"
            "星期四   晚上9/10节  诚意楼415   自控系统"
        )
        outcome = parse_text(text, self.template, "text")
        self.assertEqual(len(outcome.courses), 5)
        first = outcome.courses[0]
        self.assertEqual(first.name, "自控系统")
        self.assertEqual(first.classroom, "诚意楼415")
        self.assertEqual(first.weekday, 1)
        self.assertEqual((first.start_period, first.end_period), (5, 6))
        analysis = next(c for c in outcome.courses if c.name == "数值分析理论")
        self.assertEqual(analysis.start_period, 9)
        self.assertEqual(analysis.end_period, 11)
        lab = next(c for c in outcome.courses if c.name == "数值上机")
        self.assertEqual((lab.start_period, lab.end_period), (9, 10))

    def test_two_courses_on_one_line(self) -> None:
        text = (
            "高等数学 张三 周一1-2节 1-16周 教A101;"
            "大学英语 李四 周二3-4节 1-16周 外语楼201"
        )
        outcome = parse_text(text, self.template, "text")
        self.assertEqual(len(outcome.courses), 2)
        math = next(c for c in outcome.courses if "高等数学" in c.name)
        english = next(c for c in outcome.courses if "大学英语" in c.name)
        self.assertEqual(math.teacher, "张三")
        self.assertEqual(english.teacher, "李四")
        self.assertEqual(english.weekday, 2)

    def test_bare_weekday_and_period_cells(self) -> None:
        table = TableData(
            rows=[
                ["课程名称", "教师", "星期", "节次", "周次", "教室"],
                ["高等数学", "张三", "一", "0102", "1-16", "教A101"],
            ],
            source="bare",
        )
        outcome = parse_table(table, self.template)
        self.assertEqual(len(outcome.courses), 1)
        self.assertEqual(outcome.courses[0].weekday, 1)
        self.assertEqual((outcome.courses[0].start_period, outcome.courses[0].end_period), (1, 2))


class TableParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.template = default_template("standard")

    def test_course_list_table(self) -> None:
        table = TableData(
            rows=[
                ["课程名称", "教师", "星期", "节次", "周次", "教室", "学分"],
                ["高等数学A", "张三", "周一", "1-2节", "1-16周", "教A101", "4"],
                ["大学英语", "李四", "周二", "3-4节", "1-16周", "外语楼201", "3"],
            ],
            source="test",
        )
        outcome = parse_table(table, self.template)
        self.assertEqual(len(outcome.courses), 2)
        self.assertEqual(outcome.courses[0].credits, 4.0)
        self.assertEqual(outcome.courses[1].classroom, "外语楼201")

    def test_grid_table(self) -> None:
        table = TableData(
            rows=[
                ["节次", "周一", "周二", "周三"],
                ["1-2节", "高等数学\n张三\n教A101", "", "大学物理\n李四\n教B202"],
                ["3-4节", "", "大学英语\n王五\n外语楼201", ""],
            ],
            source="grid",
        )
        outcome = parse_table(table, self.template)
        self.assertEqual(len(outcome.courses), 3)
        math = next(c for c in outcome.courses if "高等数学" in c.name)
        self.assertEqual(math.weekday, 1)
        self.assertEqual((math.start_period, math.end_period), (1, 2))
        self.assertEqual(math.teacher, "张三")
        self.assertEqual(math.classroom, "教A101")
        english = next(c for c in outcome.courses if "大学英语" in c.name)
        self.assertEqual(english.weekday, 2)
        self.assertEqual((english.start_period, english.end_period), (3, 4))

    def test_grid_with_weeks_in_cell(self) -> None:
        table = TableData(
            rows=[
                ["节次", "周一", "周二"],
                ["1-2节", "高等数学\n1-8周\n张三\nA101", "大学英语\n9-16周\n李四\nB201"],
            ],
            source="grid",
        )
        outcome = parse_table(table, self.template)
        self.assertEqual(len(outcome.courses), 2)
        math = next(c for c in outcome.courses if "高等数学" in c.name)
        self.assertEqual(math.weeks, list(range(1, 9)))
        english = next(c for c in outcome.courses if "大学英语" in c.name)
        self.assertEqual(english.weeks, list(range(9, 17)))


if __name__ == "__main__":
    unittest.main()
