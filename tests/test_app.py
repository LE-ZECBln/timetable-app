"""UI smoke tests using Streamlit's AppTest (no browser required)."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

# Streamlit/AppTest creates temp dirs with mode 0o700; some Windows sandbox
# tokens cannot reopen them.  Ignoring the mode on Windows keeps the tests
# runnable in both normal and restricted shells.
if os.name == "nt":
    _real_mkdir = os.mkdir

    def _mkdir(path, mode=0o777, *args, **kwargs):
        return _real_mkdir(path, *args, **kwargs)

    os.mkdir = _mkdir

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parent.parent / "app.py"


def _button(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def _text_input(app: AppTest, label: str):
    return next(widget for widget in app.text_input if widget.label == label)


def _selectbox(app: AppTest, label: str):
    return next(widget for widget in app.selectbox if widget.label == label)


def _goto_page(app: AppTest, page: str) -> None:
    if app.sidebar.radio[0].value != page:
        app.sidebar.radio[0].set_value(page).run()


def _add_course(
    app: AppTest,
    *,
    name: str = "高等数学",
    classroom: str = "正心楼415",
    weekday: str = "周一",
    periods: str = "5/6节",
) -> None:
    _goto_page(app, "① 导入课程")
    _text_input(app, "课程名称 *").set_value(name)
    _text_input(app, "教室（可选）").set_value(classroom)
    _selectbox(app, "星期（可选）").set_value(weekday)
    _text_input(app, "节次（可选）").set_value(periods)
    app.run()
    _button(app, "添加到课程").click().run()


class AppTests(unittest.TestCase):
    def test_boot(self) -> None:
        app = AppTest.from_file(str(APP), default_timeout=120)
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(app.radio)
        self.assertEqual(app.session_state.page, "🏠 首页")

    def test_cover_and_mode_one(self) -> None:
        app = AppTest.from_file(str(APP), default_timeout=120)
        app.run()
        _button(app, "开始课表编辑 →").click().run()
        self.assertEqual(app.session_state.page, "🧭 开始")
        _button(app, "使用模式一（默认时间）").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state.page, "① 导入课程")
        self.assertEqual(app.session_state.template.mode, "standard")

    def test_mode_two_goes_to_settings_then_import(self) -> None:
        app = AppTest.from_file(str(APP), default_timeout=120)
        app.run()
        _button(app, "开始课表编辑 →").click().run()
        _button(app, "使用模式二（自定义时间）").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state.page, "⑤ 模板设置")
        self.assertEqual(app.session_state.template.mode, "custom")
        _button(app, "保存模板设置").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state.page, "① 导入课程")
        self.assertFalse(app.session_state.template_onboarding)

    def test_suggestions_fill_editable_fields(self) -> None:
        app = AppTest.from_file(str(APP), default_timeout=120)
        app.run()
        _goto_page(app, "① 导入课程")

        _button(app, "高等数学").click().run()
        _button(app, "正心楼").click().run()
        _button(app, "周一 5-6节").click().run()

        self.assertFalse(app.exception)
        self.assertEqual(_text_input(app, "课程名称 *").value, "高等数学")
        self.assertEqual(_text_input(app, "教室（可选）").value, "正心楼")
        self.assertEqual(_selectbox(app, "星期（可选）").value, "周一")
        self.assertEqual(_text_input(app, "节次（可选）").value, "5-6节")

    def test_building_suggestion_keeps_room_number(self) -> None:
        app = AppTest.from_file(str(APP), default_timeout=120)
        app.run()
        _goto_page(app, "① 导入课程")
        _text_input(app, "教室（可选）").set_value("正心楼415")
        app.run()
        _button(app, "诚意楼").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(_text_input(app, "教室（可选）").value, "诚意楼415")

    def test_structured_add_and_pages(self) -> None:
        app = AppTest.from_file(str(APP), default_timeout=120)
        app.run()
        _add_course(app)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state.courses), 1)
        course = app.session_state.courses[0]
        self.assertEqual(course.name, "高等数学")
        self.assertEqual(course.classroom, "正心楼415")
        self.assertEqual((course.start_period, course.end_period), (5, 6))

        for page in ["② 校对课程", "③ 课表视图", "④ 导出文件", "⑤ 模板设置", "⑥ 使用帮助"]:
            _goto_page(app, page)
            self.assertFalse(app.exception, msg=page)

    def test_minimal_course_without_time(self) -> None:
        app = AppTest.from_file(str(APP), default_timeout=120)
        app.run()
        _goto_page(app, "① 导入课程")
        _text_input(app, "课程名称 *").set_value("大学英语")
        app.run()
        _button(app, "添加到课程").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state.courses), 1)
        self.assertFalse(app.session_state.courses[0].scheduled)

    def test_multiple_periods_in_one_add(self) -> None:
        app = AppTest.from_file(str(APP), default_timeout=120)
        app.run()
        _add_course(app, name="数值分析", periods="5/6节,9/11节")
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state.courses), 2)
        periods = {(course.start_period, course.end_period) for course in app.session_state.courses}
        self.assertEqual(periods, {(5, 6), (9, 11)})

    def test_export_png(self) -> None:
        app = AppTest.from_file(str(APP), default_timeout=120)
        app.run()
        _add_course(app)
        _goto_page(app, "④ 导出文件")
        _button(app, "生成 PNG").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.session_state.export_cache)

    def test_go_to_review(self) -> None:
        app = AppTest.from_file(str(APP), default_timeout=120)
        app.run()
        _add_course(app)
        _button(app, "去校对课程 →").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.sidebar.radio[0].value, "② 校对课程")

    def test_review_to_timetable(self) -> None:
        app = AppTest.from_file(str(APP), default_timeout=120)
        app.run()
        _add_course(app)
        _button(app, "去校对课程 →").click().run()
        _button(app, "去课表视图 →").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.sidebar.radio[0].value, "③ 课表视图")


if __name__ == "__main__":
    unittest.main()
