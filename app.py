"""本地智能课表生成器 · Streamlit 入口。

运行方式::

    streamlit run app.py

所有解析、OCR、渲染均在本机完成，不调用任何外部 API。
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

# Windows restricted tokens (including the DSH sandbox) cannot reopen a
# directory that Python creates with mode 0o700.  tempfile.mkdtemp uses that
# mode, which can break Streamlit's upload/config temp files.  On Windows the
# mode argument is not a real POSIX permission, so creating with the default
# inherited ACL is the safe equivalent.
if os.name == "nt":
    _real_mkdir = os.mkdir

    def _mkdir(path, mode=0o777, *args, **kwargs):
        return _real_mkdir(path, *args, **kwargs)

    os.mkdir = _mkdir

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor"
if VENDOR.is_dir() and str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from timetable.export_ics import render_ics_summary
from timetable.exports import export_bytes
from timetable.extractors import ExtractResult, extract_bytes
from timetable.layout import build_layout
from timetable.models import (
    WEEKDAY_NAMES,
    Course,
    Template,
    TimeRow,
    default_start_date,
    default_template,
    dedupe_courses,
    make_rows,
    merge_adjacent_slots,
    normalize_hhmm,
)
from timetable.ocr import ocr_available
from timetable.parsing import (
    ParseOutcome,
    TableData,
    parse_period_slots,
    parse_tables,
    parse_text,
    parse_time_slots,
    parse_weeks,
)
from timetable.render_html import render_html
from timetable.samples import SAMPLE_TABLE_TEXT, SAMPLE_TEXT
from timetable.suggestions import (
    CLASSROOM_BUILDINGS,
    COURSE_NAME_SUGGESTIONS,
    PERIOD_SUGGESTIONS,
    TIME_SLOT_SUGGESTIONS,
    TOP_COURSE_SUGGESTIONS,
    WEEK_SUGGESTIONS,
    WEEKDAY_SUGGESTIONS,
)

APP_TITLE = "智能课表生成器"
APP_VERSION = "1.2.0"
PAGES = [
    "🏠 首页",
    "🧭 开始",
    "① 导入课程",
    "② 校对课程",
    "③ 课表视图",
    "④ 导出文件",
    "⑤ 模板设置",
    "⑥ 使用帮助",
]
WEEKDAY_OPTIONS = ["未设置"] + [WEEKDAY_NAMES[day] for day in range(1, 8)]
TYPE_LABELS = {"all": "每周", "odd": "单周", "even": "双周"}
LABEL_TYPES = {"每周": "all", "单周": "odd", "双周": "even"}
STRUCTURAL_PREFIXES = (
    "未识别",
    "尚未排入",
    "节次超出",
    "节次不在",
    "缺少课程名称",
    "未设置",
    "上课日不在",
)

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)

_CSS = r"""
<style>
html, body, [class*="css"] {
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
}
.stApp {
  background:
    radial-gradient(1100px 420px at 12% -8%, #e8f1ff 0%, rgba(232,241,255,0) 62%),
    radial-gradient(900px 380px at 92% 0%, #f3ecff 0%, rgba(243,236,255,0) 58%),
    #f6f8fc;
}
.block-container { max-width: 1320px; padding-top: 1.6rem; padding-bottom: 3rem; }
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #0f172a 0%, #111c33 58%, #0b1220 100%);
  border-right: 0;
}
[data-testid="stSidebar"] * { color: #e2e8f0; }
[data-testid="stSidebar"] .stRadio label { color: #e2e8f0 !important; }
[data-testid="stSidebar"] [data-testid="stMetricValue"] { color: #fff; }
[data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] small { color: #94a3b8 !important; }
[data-testid="stSidebar"] hr { border-color: #1e293b; }
.hero {
  border: 1px solid #dbe6f5;
  background: linear-gradient(135deg, #ffffff 0%, #f7fbff 60%, #f3f0ff 100%);
  border-radius: 18px;
  padding: 22px 24px;
  margin-bottom: 18px;
  box-shadow: 0 10px 30px rgba(15, 23, 42, .05);
}
.hero h1 { margin: 0; font-size: 30px; letter-spacing: -.02em; color: #0f172a; }
.hero p { margin: 8px 0 0 0; color: #64748b; font-size: 14px; line-height: 1.6; }
.hero .pill {
  display: inline-block; margin-top: 12px; padding: 5px 10px; border-radius: 999px;
  background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe;
  font-size: 12px; font-weight: 700;
}
.empty-card {
  border: 1px dashed #cbd5e1; background: #fff; border-radius: 16px;
  padding: 30px; text-align: center; color: #64748b; margin: 12px 0 18px 0;
}
.empty-card h3 { margin: 0 0 8px 0; color: #0f172a; }
.empty-card p { margin: 0 auto; max-width: 620px; line-height: 1.7; font-size: 13px; }
.home-feature {
  height: 170px;
  background: #eaf1ff;
  border: 1px solid #d8e4fb;
  border-radius: 14px;
  padding: 18px 20px;
  box-sizing: border-box;
}
.home-feature h4 {
  margin: 0 0 10px 0; color: #1d4ed8; font-size: 15px; font-weight: 800;
}
.home-feature p {
  margin: 0; color: #334155; font-size: 13px; line-height: 1.7;
}
.brand { padding: 8px 2px 2px 2px; }
.brand .logo { font-size: 30px; line-height: 1; }
.brand .name { margin-top: 8px; font-size: 17px; font-weight: 800; color: #fff; letter-spacing: .01em; }
.brand .sub { margin-top: 5px; font-size: 11px; color: #94a3b8; line-height: 1.5; }
.side-card {
  border: 1px solid #1e293b; background: rgba(30, 41, 59, .55);
  border-radius: 12px; padding: 12px 13px; margin: 10px 0 12px 0;
}
.side-card .row { display: flex; justify-content: space-between; font-size: 12px; color: #cbd5e1; margin: 5px 0; }
.side-card .row b { color: #fff; }
div[data-testid="stMetric"] {
  background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
  padding: 10px 14px; box-shadow: 0 1px 2px rgba(15,23,42,.03);
}
div[data-testid="stMetric"] label { color: #64748b !important; }
div[data-testid="stMetricValue"] { color: #0f172a; }
.stButton > button, .stDownloadButton > button {
  border-radius: 9px; font-weight: 700; border-color: #cbd5e1;
}
.stButton > button[kind="primary"] {
  background: #2563eb; border-color: #2563eb;
}
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] {
  border-radius: 9px 9px 0 0; padding: 8px 16px; font-weight: 700;
}
.stTabs [aria-selected="true"] { background: #eff6ff; color: #1d4ed8; }
.small-note { color: #64748b; font-size: 12px; line-height: 1.6; }
.file-row {
  border: 1px solid #e2e8f0; background: #fff; border-radius: 10px;
  padding: 9px 12px; margin: 5px 0; font-size: 12px; color: #475569;
}
.file-row b { color: #0f172a; }
</style>
"""

st.markdown(_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def init_state() -> None:
    defaults = {
        "template": default_template("standard"),
        "courses": [],
        "raw_text": "",
        "parse_log": [],
        "unparsed": [],
        "import_summary": None,
        "page": PAGES[0],
        "pending_page": None,
        "week_choice": "全部周次",
        "data_version": 0,
        "text_version": 0,
        "uploader_version": 0,
        "rows_version": 0,
        "settings_version": 0,
        "custom_rows": None,
        "clear_structured_on_next_run": False,
        "template_onboarding": False,
        "export_cache": {},
        "flash": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def bump_version() -> None:
    st.session_state.data_version += 1
    st.session_state.export_cache = {}


def set_flash(message: str, kind: str = "success") -> None:
    st.session_state.flash = (kind, message)


def show_flash() -> None:
    flash = st.session_state.get("flash")
    if flash:
        kind, message = flash
        st.session_state.flash = None
        getattr(st, kind, st.success)(message)


def goto(page: str) -> None:
    # The navigation radio uses key="page"; it is already instantiated when a
    # button click is processed, so assigning st.session_state.page directly
    # raises StreamlitWidgetAlreadyInstantiatedError.  Queue the target and let
    # main() apply it at the start of the next run, before the radio exists.
    st.session_state.pending_page = page
    st.rerun()


def reset_all_data() -> None:
    st.session_state.courses = []
    st.session_state.raw_text = ""
    st.session_state.parse_log = []
    st.session_state.unparsed = []
    st.session_state.import_summary = None
    st.session_state.week_choice = "全部周次"
    st.session_state.text_version += 1
    st.session_state.uploader_version += 1
    st.session_state.clear_structured_on_next_run = True
    bump_version()


def hero(title: str, subtitle: str, pill: str = "") -> None:
    pill_html = f'<div class="pill">{html.escape(pill)}</div>' if pill else ""
    st.markdown(
        f'<div class="hero"><h1>{html.escape(title)}</h1>'
        f"<p>{html.escape(subtitle)}</p>{pill_html}</div>",
        unsafe_allow_html=True,
    )


def empty_state(
    title: str,
    message: str,
    button_label: str | None = None,
    page: str | None = None,
) -> None:
    st.markdown(
        f'<div class="empty-card"><h3>{html.escape(title)}</h3>'
        f"<p>{html.escape(message)}</p></div>",
        unsafe_allow_html=True,
    )
    if button_label and page and st.button(button_label, type="primary"):
        goto(page)


def _to_int(value, default: int = 0) -> int:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        text = str(value).strip()
        if not text:
            return default
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _to_float(value) -> float | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _weekday_from_label(label: str) -> int | None:
    for day, name in WEEKDAY_NAMES.items():
        if label == name:
            return day
    return None


def _validate_course(course: Course, template: Template) -> None:
    course.issues = [
        issue for issue in course.issues if not issue.startswith(STRUCTURAL_PREFIXES)
    ]
    if not course.name:
        course.add_issue("缺少课程名称")
    if not course.weekday:
        course.add_issue("未设置上课星期")
    if not course.start_period or not course.end_period:
        course.add_issue("未设置节次")
    else:
        if course.end_period > template.max_period:
            course.add_issue(f"节次超出模板范围（最多 {template.max_period} 节）")
        if course.weekday and course.weekday not in template.days:
            course.add_issue("上课日不在当前模板中")
        elif not template.row_indices_for(course.start_period, course.end_period):
            course.add_issue("节次不在模板时间格中")
    if not course.scheduled:
        course.add_issue("尚未排入课表")


def _courses_df(courses: list[Course]) -> pd.DataFrame:
    rows = []
    for course in courses:
        rows.append(
            {
                "id": course.id,
                "课程名称": course.name,
                "教师": course.teacher,
                "教室": course.classroom,
                "星期": course.weekday_label if course.weekday else "未设置",
                "开始节": course.start_period or 0,
                "结束节": course.end_period or 0,
                "周次": course.week_expr or course.week_label,
                "类型": TYPE_LABELS.get(course.week_type, "每周"),
                "学分": course.credits if course.credits is not None else None,
                "班级": course.class_name,
                "备注": course.note,
                "状态": "；".join(course.issues) if course.issues else "正常",
                "来源": course.source,
            }
        )
    columns = [
        "id",
        "课程名称",
        "教师",
        "教室",
        "星期",
        "开始节",
        "结束节",
        "周次",
        "类型",
        "学分",
        "班级",
        "备注",
        "状态",
        "来源",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def _df_to_courses(df: pd.DataFrame, template: Template) -> list[Course]:
    existing_issues = {course.id: list(course.issues) for course in st.session_state.courses}
    courses: list[Course] = []
    for row in df.to_dict("records"):
        name = str(row.get("课程名称", "") or "").strip()
        if not name:
            continue
        row_id = row.get("id")
        course_id = (
            ""
            if row_id is None or (isinstance(row_id, float) and pd.isna(row_id))
            else str(row_id).strip()
        )
        if not course_id or course_id == "nan":
            course_id = uuid4().hex[:8]
        weekday = _weekday_from_label(str(row.get("星期", "未设置") or "未设置"))
        start = _to_int(row.get("开始节"), 0) or None
        end = _to_int(row.get("结束节"), 0) or None
        if start and not end:
            end = start
        if end and not start:
            start = end
        if start and end and end < start:
            start, end = end, start
        weeks_text = str(row.get("周次", "") or "").strip()
        weeks, week_type, week_expr = parse_weeks(weeks_text, assume_weeks=True)
        type_label = str(row.get("类型", "每周") or "每周")
        if type_label in {"单周", "双周"}:
            week_type = LABEL_TYPES[type_label]
            if weeks:
                weeks = [
                    week
                    for week in weeks
                    if (week % 2 == 1 if week_type == "odd" else week % 2 == 0)
                ]
        elif week_type == "all" and not weeks:
            week_expr = week_expr or "全周"
        course = Course(
            name=name,
            teacher=str(row.get("教师", "") or "").strip(),
            classroom=str(row.get("教室", "") or "").strip(),
            weekday=weekday,
            start_period=start,
            end_period=end,
            weeks=weeks,
            week_type=week_type,
            week_expr=week_expr,
            credits=_to_float(row.get("学分")),
            class_name=str(row.get("班级", "") or "").strip(),
            note=str(row.get("备注", "") or "").strip(),
            source=str(row.get("来源", "") or "手动编辑"),
            issues=existing_issues.get(course_id, []),
            id=course_id,
        )
        _validate_course(course, template)
        courses.append(course)
    return dedupe_courses(merge_adjacent_slots(courses))


def _combine_outcome(outcome: ParseOutcome) -> list[Course]:
    return dedupe_courses(merge_adjacent_slots(outcome.courses))


def _parse_extract(result: ExtractResult, template: Template) -> ParseOutcome:
    outcome = ParseOutcome()
    table_outcome = ParseOutcome()
    if result.tables:
        table_outcome = parse_tables(result.tables, template, result.filename)
        outcome.extend(table_outcome)
    skip_text = result.kind in {"xlsx", "csv"}
    if result.ocr_used and result.tables and table_outcome.courses:
        # OCR grid reconstruction is much more reliable than the flat OCR
        # text; do not parse both and create duplicate/bogus records.
        skip_text = True
    if result.text.strip() and not skip_text:
        text_outcome = parse_text(result.text, template, result.filename)
        outcome.extend(text_outcome)
        if table_outcome.courses:
            outcome.issues = [
                issue
                for issue in outcome.issues
                if issue != "未识别到课程。请尝试表格格式、检查时间/星期写法，或手动添加。"
            ]
    outcome.courses = _combine_outcome(outcome)
    return outcome


def _add_parse_log(
    name: str,
    kind: str,
    char_count: int,
    course_count: int,
    notes: str,
) -> None:
    st.session_state.parse_log.append(
        {
            "文件": name,
            "类型": kind,
            "字符数": char_count,
            "识别课程": course_count,
            "提示": notes,
        }
    )


def _parse_text_and_store(text: str, source: str = "粘贴文本", append: bool = False) -> None:
    template = st.session_state.template
    outcome = parse_text(text, template, source)
    new_courses = _combine_outcome(outcome)
    existing = st.session_state.courses if append else []
    st.session_state.courses = dedupe_courses(merge_adjacent_slots(existing + new_courses))
    previous_raw = st.session_state.raw_text if append and st.session_state.raw_text else ""
    st.session_state.raw_text = (
        (previous_raw + "\n\n" + text) if previous_raw else text
    )
    st.session_state.unparsed = outcome.unparsed
    st.session_state.parse_log = []
    _add_parse_log(
        source,
        "文本",
        len(text),
        len(new_courses),
        "；".join(outcome.issues[:6]),
    )
    st.session_state.import_summary = {
        "source": source,
        "files": 1,
        "new_courses": len(new_courses),
        "total_courses": len(st.session_state.courses),
        "issues": len(outcome.issues),
        "unparsed": len(outcome.unparsed),
    }
    bump_version()
    if new_courses:
        set_flash(f"解析完成：识别到 {len(new_courses)} 条课程安排。")
    else:
        set_flash("没有识别到课程，请检查格式或查看下方提示。", "warning")


def _parse_files_and_store(files: list, append: bool = False) -> None:
    template = st.session_state.template
    all_new: list[Course] = []
    raw_chunks: list[str] = []
    unparsed: list[str] = []
    logs: list[dict] = []
    total_issues = 0

    for uploaded in files:
        data = uploaded.getvalue()
        result = extract_bytes(uploaded.name, data)
        outcome = _parse_extract(result, template)
        all_new.extend(outcome.courses)
        unparsed.extend(outcome.unparsed)
        total_issues += len(outcome.issues)
        if result.text:
            raw_chunks.append(f"===== {result.filename} =====\n{result.text}")
        notes = list(result.notes) + list(result.errors) + list(outcome.issues[:5])
        logs.append(
            {
                "文件": result.filename,
                "类型": result.kind,
                "字符数": result.char_count,
                "识别课程": len(outcome.courses),
                "提示": "；".join(part for part in notes if part)[:500],
            }
        )

    all_new = dedupe_courses(merge_adjacent_slots(all_new))
    existing = st.session_state.courses if append else []
    st.session_state.courses = dedupe_courses(merge_adjacent_slots(existing + all_new))
    previous_raw = st.session_state.raw_text if append and st.session_state.raw_text else ""
    new_raw = "\n\n".join(raw_chunks)
    st.session_state.raw_text = (
        (previous_raw + "\n\n" + new_raw) if previous_raw else new_raw
    )
    st.session_state.parse_log = logs
    st.session_state.unparsed = list(dict.fromkeys(unparsed))[:100]
    st.session_state.text_version += 1
    st.session_state.import_summary = {
        "source": f"{len(files)} 个文件",
        "files": len(files),
        "new_courses": len(all_new),
        "total_courses": len(st.session_state.courses),
        "issues": total_issues,
        "unparsed": len(st.session_state.unparsed),
    }
    bump_version()
    if all_new:
        set_flash(f"文件解析完成：识别到 {len(all_new)} 条课程安排。")
    else:
        set_flash("文件已读取，但没有识别到课程。请查看解析日志或手动添加。", "warning")


# ---------------------------------------------------------------------------
# Import page
# ---------------------------------------------------------------------------
# Legacy free-text / file-upload UI.  It is intentionally not called by main()
# while the product is in structured-text-only mode; the extractors, OCR and
# parser modules remain available for a future re-enable.
# ---------------------------------------------------------------------------


def _render_import_summary() -> None:
    summary = st.session_state.get("import_summary")
    if not summary:
        return
    st.markdown("---")
    st.subheader("本次导入结果")
    columns = st.columns(4)
    columns[0].metric("文件 / 来源", summary.get("files", 1))
    columns[1].metric("新识别课程", summary.get("new_courses", 0))
    columns[2].metric("当前课程总数", summary.get("total_courses", 0))
    columns[3].metric("解析提示", summary.get("issues", 0))
    if summary.get("unparsed"):
        st.caption(f"有 {summary['unparsed']} 行文本未匹配，可在“校对课程 → 原始文本”中查看。")

    if st.session_state.parse_log:
        st.dataframe(
            pd.DataFrame(st.session_state.parse_log),
            width="stretch",
            hide_index=True,
        )

    if st.session_state.unparsed:
        with st.expander("查看未识别的文本行", expanded=False):
            for line in st.session_state.unparsed[:80]:
                st.code(line, language=None)

    col_a, col_b = st.columns([1, 1])
    if col_a.button("去校对课程 →", type="primary", width="stretch"):
        goto("② 校对课程")
    if col_b.button("继续导入", width="stretch"):
        st.session_state.import_summary = None
        st.rerun()


def page_home() -> None:
    hero(
        "智能课表生成器",
        "从结构化录入到周课表，再到 Excel / PNG / PDF / ICS 导出。所有数据都在本机处理，不需要 API Key。",
        "本地运行 · 无需 API · 支持导出",
    )
    cols = st.columns(3)
    features = [
        (
            "① 结构化录入",
            "课程名、教室、星期等关键信息分字段填写；常用信息于备选库中列出，支持点击填入。",
        ),
        (
            "② 校对与课表",
            "录入结果可逐条修改；自动检测时间冲突，按周查看课表。",
        ),
        (
            "③ 五种导出",
            "Excel 课表、PNG 图片、PDF、ICS 日历、可打印 HTML。",
        ),
    ]
    for column, (title, description) in zip(cols, features):
        column.markdown(
            f'<div class="home-feature"><h4>{title}</h4>'
            f"<p>{description}</p></div>",
            unsafe_allow_html=True,
        )
    st.markdown("---")
    col_start, col_help = st.columns([1.6, 1])
    if col_start.button("开始课表编辑 →", type="primary", width="stretch"):
        goto("🧭 开始")
    if col_help.button("查看使用帮助", width="stretch"):
        goto("⑥ 使用帮助")
    courses = st.session_state.courses
    if courses:
        st.caption(f"当前会话已有 {len(courses)} 条课程安排，继续编辑不会丢失。")
    st.caption("提示：左侧导航栏可以随时在首页、录入、校对、课表、导出和模板设置之间切换。")


def _choose_template_mode(mode: str) -> None:
    courses = st.session_state.courses
    if mode == "standard":
        new_template = default_template("standard")
        st.session_state.template = new_template
        st.session_state.custom_rows = [row.to_dict() for row in new_template.rows]
        st.session_state.settings_version += 1
        st.session_state.rows_version += 1
        st.session_state.template_onboarding = False
        for course in courses:
            _validate_course(course, new_template)
        bump_version()
        set_flash("已选择模式一：默认 6 时段 / 12 节时间。")
        goto("① 导入课程")

    if st.session_state.template.mode != "custom":
        new_template = default_template("custom")
        st.session_state.template = new_template
        st.session_state.custom_rows = [row.to_dict() for row in new_template.rows]
    st.session_state.settings_version += 1
    st.session_state.rows_version += 1
    st.session_state.template_onboarding = True
    for course in courses:
        _validate_course(course, st.session_state.template)
    bump_version()
    set_flash("请先在模式二中设置时间格，保存后将自动进入录入课程。")
    goto("⑤ 模板设置")


def page_mode_select() -> None:
    hero(
        "选择课表时间模式",
        "模式一使用内置的标准 6 时段 / 12 节时间；模式二先进入模板设置，自定义总周数、上课日、节次和上下课时间。",
        "第二步 · 先选时间模板",
    )
    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True, height=430):
            st.markdown("### 模式一 · 默认时间")
            st.markdown(
                "固定 6 个时段，适合大多数课程表：\n\n"
                "- 1-2 节 08:00–09:45\n"
                "- 3-4 节 10:00–11:45\n"
                "- 5-6 节 13:45–15:30\n"
                "- 7-8 节 15:45–17:30\n"
                "- 9-10 节 18:30–20:15\n"
                "- 11-12 节 20:30–22:15"
            )
            if st.button(
                "使用模式一（默认时间）",
                type="primary",
                width="stretch",
            ):
                _choose_template_mode("standard")
    with col2:
        with st.container(border=True, height=430):
            st.markdown("### 模式二 · 自定义时间")
            st.markdown(
                "先完成模板设置，再开始录入：\n\n"
                "- 设置学期总周数、上课日；\n"
                "- 设置第 1 周周一（用于日期与 ICS）；\n"
                "- 设置每天节数、每格包含节数；\n"
                "- 逐行修改每个时间格的开始/结束时间；\n"
                "- 设置是否包含周末；\n"
                "- 保存后自动进入“录入课程”，之后仍可回来修改。"
            )
            if st.button("使用模式二（自定义时间）", width="stretch"):
                _choose_template_mode("custom")
    st.caption("选择后仍可通过左侧导航栏自由切换页面；之后也可以在“模板设置”里修改。")


def _legacy_page_import() -> None:

    hero(
        "导入课程",
        "粘贴课程文本，或上传 Word / PDF / Excel / Markdown / 图片。规则解析器会识别课程、教师、教室、星期、节次与周次；全程本地运行。",
        "第一步 · 支持 8 种输入格式",
    )
    cols = st.columns(3)
    cols[0].info("**Word / PDF**\n\n支持段落、课程列表表格与星期×节次网格；扫描 PDF 自动走本地 OCR。")
    cols[1].info("**文本 / Markdown / Excel / CSV**\n\n自动识别表头、制表符、竖线表格和一行一条课程记录。")
    cols[2].info("**图片 OCR**\n\nPNG / JPG / WEBP 等图片可用本地中文 OCR；不需要联网或 API Key。")

    tab_text, tab_files, tab_manual, tab_sample = st.tabs(
        ["粘贴文本", "上传文件", "手动添加", "示例"]
    )

    with tab_text:
        text_value = st.text_area(
            "课程文本",
            value=st.session_state.raw_text,
            height=300,
            key=f"raw_input_{st.session_state.text_version}",
            placeholder=(
                "例如：\n"
                "高等数学A 张三 周一 第1-2节 1-16周 教A101\n"
                "大学英语 李四 周二 3-4节 1-16周 外语楼201\n\n"
                "也支持表格、教务系统导出的多行格式。"
            ),
        )
        col_parse, col_sample, col_clear = st.columns([1.2, 1, 1])
        if col_parse.button("解析文本", type="primary", width="stretch"):
            if not text_value.strip():
                st.warning("请先粘贴课程文本。")
            else:
                _parse_text_and_store(text_value, "粘贴文本")
        if col_sample.button("填入示例", width="stretch"):
            st.session_state.raw_text = SAMPLE_TEXT
            st.session_state.text_version += 1
            st.rerun()
        if col_clear.button("清空文本", width="stretch"):
            st.session_state.raw_text = ""
            st.session_state.text_version += 1
            st.rerun()
        st.caption("提示：一行一条课程、或“课程名 / 教师 / 时间 / 周次 / 教室”分行的格式识别率最高。")

    with tab_files:
        uploaded_files = st.file_uploader(
            "上传课程文件（可多选）",
            type=[
                "txt",
                "text",
                "md",
                "markdown",
                "docx",
                "pdf",
                "xlsx",
                "csv",
                "png",
                "jpg",
                "jpeg",
                "webp",
                "bmp",
                "tif",
                "tiff",
            ],
            accept_multiple_files=True,
            key=f"uploader_{st.session_state.uploader_version}",
            help="单个文件不超过 30 MB。旧版 .doc / .xls 请先另存为 .docx / .xlsx。",
        )
        if uploaded_files:
            for uploaded in uploaded_files:
                st.markdown(
                    f'<div class="file-row"><b>{html.escape(uploaded.name)}</b>'
                    f" · {uploaded.size / 1024:.0f} KB · {html.escape(uploaded.type or '未知类型')}</div>",
                    unsafe_allow_html=True,
                )
        col_parse_files, col_append, col_clear_files = st.columns([1.2, 1, 1])
        append_files = col_append.checkbox("追加到现有课程", value=False)
        if col_parse_files.button("解析上传文件", type="primary", width="stretch"):
            if not uploaded_files:
                st.warning("请先选择文件。")
            else:
                _parse_files_and_store(list(uploaded_files), append=append_files)
        if col_clear_files.button("清空文件列表", width="stretch"):
            st.session_state.uploader_version += 1
            st.rerun()
        if not ocr_available():
            st.warning("本地 OCR 暂不可用；Word / PDF / Excel / 文本仍可正常解析。可把图片文字粘贴到“粘贴文本”。")
        st.caption("扫描版 PDF 与图片会使用本机 OCR，复杂表格建议同时核对识别结果。")

    with tab_manual:
        with st.form("manual_add_form"):
            st.markdown("**添加一条课程安排**")
            col1, col2, col3 = st.columns(3)
            name = col1.text_input("课程名称 *", placeholder="例如：高等数学A")
            teacher = col2.text_input("教师", placeholder="张三")
            classroom = col3.text_input("教室", placeholder="教A101")
            col4, col5, col6 = st.columns(3)
            weekday_label = col4.selectbox("星期", WEEKDAY_OPTIONS[1:])
            start = col5.number_input("开始节", min_value=1, max_value=20, value=1, step=1)
            end = col6.number_input("结束节", min_value=1, max_value=20, value=2, step=1)
            col7, col8, col9 = st.columns(3)
            weeks_text = col7.text_input("周次", value="1-16周", help="如 1-16周、1-8,10-16周、1-16周(单)、全周")
            week_type_label = col8.selectbox("类型", ["每周", "单周", "双周"])
            credits = col9.number_input("学分", min_value=0.0, max_value=20.0, value=0.0, step=0.5)
            class_name = st.text_input("班级（可选）")
            note = st.text_input("备注（可选）")
            submitted = st.form_submit_button("添加到课程", type="primary")
        if submitted:
            if not name.strip():
                st.error("课程名称不能为空。")
            else:
                weeks, week_type, week_expr = parse_weeks(weeks_text, assume_weeks=True)
                if week_type_label in {"单周", "双周"}:
                    week_type = LABEL_TYPES[week_type_label]
                    if weeks:
                        weeks = [
                            week
                            for week in weeks
                            if (week % 2 == 1 if week_type == "odd" else week % 2 == 0)
                        ]
                course = Course(
                    name=name.strip(),
                    teacher=teacher.strip(),
                    classroom=classroom.strip(),
                    weekday=_weekday_from_label(weekday_label),
                    start_period=int(start),
                    end_period=max(int(start), int(end)),
                    weeks=weeks,
                    week_type=week_type,
                    week_expr=week_expr or "全周",
                    credits=credits or None,
                    class_name=class_name.strip(),
                    note=note.strip(),
                    source="手动添加",
                )
                _validate_course(course, st.session_state.template)
                st.session_state.courses = dedupe_courses(
                    merge_adjacent_slots(st.session_state.courses + [course])
                )
                bump_version()
                set_flash(f"已添加《{course.name}》。")
                st.rerun()

    with tab_sample:
        st.markdown("**示例 1：自由文本（含多种写法）**")
        st.code(SAMPLE_TEXT, language=None)
        st.markdown("**示例 2：Markdown 表格**")
        st.code(SAMPLE_TABLE_TEXT, language="markdown")
        col_a, col_b = st.columns(2)
        if col_a.button("加载示例文本并解析", type="primary", width="stretch"):
            st.session_state.raw_text = SAMPLE_TEXT
            st.session_state.text_version += 1
            _parse_text_and_store(SAMPLE_TEXT, "示例文本")
            st.rerun()
        if col_b.button("加载示例表格并解析", width="stretch"):
            result = ExtractResult(
                filename="示例表格.md",
                kind="markdown",
                text="",
                tables=[
                    TableData(
                        rows=[
                            ["课程名称", "教师", "星期", "节次", "周次", "教室", "学分"],
                            ["高等数学A", "张三", "周一", "1-2节", "1-16周", "教A101", "4"],
                            ["大学英语", "李四", "周二", "3-4节", "1-16周", "外语楼201", "3"],
                            ["数据结构", "王五", "周三", "5-6节", "1-16周", "计算机楼305", "3"],
                            ["操作系统", "赵六", "周四", "7-8节", "1-8周", "教B202", "3"],
                            ["体育（篮球）", "孙七", "周五", "9-10节", "1-16周", "体育馆", "1"],
                        ]
                    )
                ],
                notes=["示例表格"],
            )
            outcome = _parse_extract(result, st.session_state.template)
            st.session_state.courses = _combine_outcome(outcome)
            st.session_state.raw_text = SAMPLE_TABLE_TEXT
            st.session_state.parse_log = [
                {
                    "文件": "示例表格.md",
                    "类型": "markdown",
                    "字符数": len(SAMPLE_TABLE_TEXT),
                    "识别课程": len(outcome.courses),
                    "提示": "示例表格",
                }
            ]
            st.session_state.import_summary = {
                "source": "示例表格",
                "files": 1,
                "new_courses": len(outcome.courses),
                "total_courses": len(outcome.courses),
                "issues": len(outcome.issues),
                "unparsed": 0,
            }
            bump_version()
            set_flash(f"已加载示例表格：{len(outcome.courses)} 条课程安排。")
            st.rerun()

    _render_import_summary()


# ---------------------------------------------------------------------------
# Review page
# ---------------------------------------------------------------------------


def _set_suggestion_value(key: str, value: str) -> None:
    st.session_state[key] = value


def _set_building_suggestion(key: str, building: str) -> None:
    """Fill a building name while keeping a room number already typed."""

    current = str(st.session_state.get(key, "") or "")
    match = re.search(r"([A-Za-z]?\d+[A-Za-z]?)\s*$", current)
    suffix = match.group(1) if match else ""
    st.session_state[key] = building + suffix


def _set_time_slot_suggestion(
    weekday_key: str, periods_key: str, weekday: str, periods: str
) -> None:
    st.session_state[weekday_key] = weekday
    st.session_state[periods_key] = periods


def _render_suggestion_buttons(
    options: list[str],
    target_key: str,
    prefix: str,
    columns: int = 3,
    on_click=None,
) -> None:
    cols = st.columns(columns)
    callback = on_click or _set_suggestion_value
    for index, option in enumerate(options):
        with cols[index % columns]:
            st.button(
                option,
                key=f"{prefix}_{index}",
                on_click=callback,
                args=(target_key, option),
                width="stretch",
            )


def _render_time_slot_buttons(
    weekday_key: str, periods_key: str, prefix: str, columns: int = 4
) -> None:
    cols = st.columns(columns)
    for index, (weekday, periods) in enumerate(TIME_SLOT_SUGGESTIONS):
        with cols[index % columns]:
            st.button(
                f"{weekday} {periods}",
                key=f"{prefix}_{index}",
                on_click=_set_time_slot_suggestion,
                args=(weekday_key, periods_key, weekday, periods),
                width="stretch",
            )


def _add_structured_course(
    *,
    name: str,
    teacher: str,
    classroom: str,
    weekday_label: str,
    periods_text: str,
    weeks_text: str,
    week_type_label: str,
    credits: float,
    class_name: str,
    note: str,
    template: Template,
) -> None:
    weekday = _weekday_from_label(weekday_label)
    slots = parse_period_slots(periods_text) or parse_time_slots(periods_text, template)
    if not slots:
        slots = [(None, None)]

    weeks, week_type, week_expr = parse_weeks(weeks_text, assume_weeks=True)
    if week_type_label == "单周":
        week_type = "odd"
        weeks = [week for week in weeks if week % 2 == 1]
        if week_expr == "全周":
            week_expr = "单周"
        elif week_expr and "单" not in week_expr:
            week_expr += "(单)"
        elif not week_expr:
            week_expr = "单周"
    elif week_type_label == "双周":
        week_type = "even"
        weeks = [week for week in weeks if week % 2 == 0]
        if week_expr == "全周":
            week_expr = "双周"
        elif week_expr and "双" not in week_expr:
            week_expr += "(双)"
        elif not week_expr:
            week_expr = "双周"

    new_courses: list[Course] = []
    for start_period, end_period in slots:
        course = Course(
            name=name,
            teacher=teacher,
            classroom=classroom,
            weekday=weekday,
            start_period=start_period,
            end_period=end_period,
            weeks=weeks,
            week_type=week_type,
            week_expr=week_expr,
            credits=credits or None,
            class_name=class_name,
            note=note,
            source="结构化录入",
            raw=f"{name} | {weekday_label} | {periods_text} | {classroom}",
        )
        _validate_course(course, template)
        new_courses.append(course)

    st.session_state.courses = dedupe_courses(
        merge_adjacent_slots(st.session_state.courses + new_courses)
    )
    bump_version()
    message = f"已添加《{name}》"
    if len(new_courses) > 1:
        message += f"，共 {len(new_courses)} 个时间段"
    set_flash(message + "。")


_STRUCTURED_DEFAULTS = {
    "structured_name": "",
    "structured_teacher": "",
    "structured_classroom": "",
    "structured_weekday": "未设置",
    "structured_periods": "",
    "structured_weeks": "",
    "structured_type": "每周",
    "structured_credits": 0.0,
    "structured_class": "",
    "structured_note": "",
}


def _clear_structured_form() -> None:
    for key, value in _STRUCTURED_DEFAULTS.items():
        st.session_state[key] = value


def _handle_structured_add() -> None:
    template = st.session_state.template
    name = str(st.session_state.get("structured_name", "") or "").strip()
    if not name:
        st.session_state.structured_error = "课程名称不能为空；其他字段可以留空。"
        return
    _add_structured_course(
        name=name,
        teacher=str(st.session_state.get("structured_teacher", "") or "").strip(),
        classroom=str(st.session_state.get("structured_classroom", "") or "").strip(),
        weekday_label=str(
            st.session_state.get("structured_weekday", "未设置") or "未设置"
        ),
        periods_text=str(st.session_state.get("structured_periods", "") or "").strip(),
        weeks_text=str(st.session_state.get("structured_weeks", "") or "").strip(),
        week_type_label=str(
            st.session_state.get("structured_type", "每周") or "每周"
        ),
        credits=float(st.session_state.get("structured_credits", 0.0) or 0.0),
        class_name=str(st.session_state.get("structured_class", "") or "").strip(),
        note=str(st.session_state.get("structured_note", "") or "").strip(),
        template=template,
    )
    st.session_state.structured_error = ""
    _clear_structured_form()


def page_import() -> None:
    hero(
        "结构化录入课程",
        "当前仅开放文本结构化录入：每个框只填写对应内容，避免自由文本格式差异导致误识别。Word / PDF / Excel / 图片上传入口暂时关闭，相关解析代码保留。",
        "仅文本模式 · 点击常用备选快速填入",
    )
    st.info(
        "除了“课程名称”以外，其他框都可以留空。只填课程名称也能添加；"
        "缺少星期或节次的课程会进入“待安排”，之后可在校对页补全。"
    )
    if st.session_state.get("structured_error"):
        st.error(st.session_state.pop("structured_error"))
    if st.session_state.get("clear_structured_on_next_run"):
        _clear_structured_form()
        st.session_state.clear_structured_on_next_run = False

    courses: list[Course] = st.session_state.courses
    template: Template = st.session_state.template
    layout = build_layout(courses, template, None) if courses else None
    unscheduled_count = len(layout.unscheduled) if layout else 0
    conflict_count = len(layout.conflicts) if layout else 0
    metric_cols = st.columns(4)
    metric_cols[0].metric("当前课程", len(courses))
    metric_cols[1].metric("待安排", unscheduled_count)
    metric_cols[2].metric("时间冲突", conflict_count)
    metric_cols[3].metric("学期总周数", template.total_weeks)
    if courses:
        col_go, col_hint = st.columns([1, 2])
        if col_go.button("去校对课程 →", type="primary", width="stretch"):
            goto("② 校对课程")
        col_hint.caption("已录入课程可在“校对课程”批量修改、删除或补全时间。")

    name_key = "structured_name"
    teacher_key = "structured_teacher"
    classroom_key = "structured_classroom"
    weekday_key = "structured_weekday"
    periods_key = "structured_periods"
    weeks_key = "structured_weeks"
    type_key = "structured_type"
    credits_key = "structured_credits"
    class_key = "structured_class"
    note_key = "structured_note"

    with st.container(border=True):
        st.markdown("#### 1. 课程基本信息")
        col1, col2, col3 = st.columns([1.5, 1, 1])
        col1.text_input(
            "课程名称 *",
            key=name_key,
            placeholder="例如：高等数学",
        )
        col2.text_input(
            "教师（可选）",
            key=teacher_key,
            placeholder="例如：张三",
        )
        col3.number_input(
            "学分（可选）",
            min_value=0.0,
            max_value=20.0,
            value=0.0,
            step=0.5,
            key=credits_key,
        )
        col4, col5 = st.columns([1, 2])
        col4.text_input(
            "班级（可选）",
            key=class_key,
            placeholder="例如：自动化2301",
        )
        col5.text_input(
            "备注（可选）",
            key=note_key,
            placeholder="例如：实验课、线上、单双周说明",
        )
        st.caption("常用课程名（点击填入，填入后仍可修改）：")
        _render_suggestion_buttons(
            TOP_COURSE_SUGGESTIONS,
            name_key,
            "suggest_name_top",
            columns=3,
        )
        with st.expander("更多常用课程名", expanded=False):
            _render_suggestion_buttons(
                [
                    course
                    for course in COURSE_NAME_SUGGESTIONS
                    if course not in TOP_COURSE_SUGGESTIONS
                ],
                name_key,
                "suggest_name",
                columns=3,
            )

    with st.container(border=True):
        st.markdown("#### 2. 上课地点")
        st.text_input(
            "教室（可选）",
            key=classroom_key,
            placeholder="例如：正心楼415",
        )
        st.caption("点击教学楼快速填入，再补全教室号；例如“正心楼” → “正心楼415”。")
        _render_suggestion_buttons(
            CLASSROOM_BUILDINGS,
            classroom_key,
            "suggest_room",
            columns=3,
            on_click=_set_building_suggestion,
        )

    with st.container(border=True):
        st.markdown("#### 3. 上课时间")
        col1, col2, col3, col4 = st.columns([1, 1.2, 1, 1])
        col1.selectbox(
            "星期（可选）",
            ["未设置"] + WEEKDAY_SUGGESTIONS,
            key=weekday_key,
        )
        col2.text_input(
            "节次（可选）",
            key=periods_key,
            placeholder="例如：5/6节、9-11节",
        )
        col3.text_input(
            "周次（可选）",
            key=weeks_key,
            placeholder="例如：1-16周",
        )
        col4.selectbox(
            "周类型（可选）",
            ["每周", "单周", "双周"],
            key=type_key,
        )
        st.caption("点击常用时间/节次/周次快速填入；未填星期或节次也可添加，之后进入“待安排”。")
        with st.expander("常用整段时间（点击同时填入星期 + 节次）", expanded=False):
            _render_time_slot_buttons(
                weekday_key,
                periods_key,
                "suggest_slot",
                columns=4,
            )
        col_period, col_week = st.columns(2)
        with col_period:
            st.markdown("**常用节次**")
            _render_suggestion_buttons(
                PERIOD_SUGGESTIONS,
                periods_key,
                "suggest_period",
                columns=2,
            )
        with col_week:
            st.markdown("**常用周次**")
            _render_suggestion_buttons(
                WEEK_SUGGESTIONS,
                weeks_key,
                "suggest_week",
                columns=2,
            )

    st.markdown("---")
    col_add, col_clear, col_review = st.columns([1.4, 1, 1])
    col_add.button(
        "添加到课程",
        type="primary",
        width="stretch",
        on_click=_handle_structured_add,
    )
    col_clear.button(
        "清空当前表单",
        width="stretch",
        on_click=_clear_structured_form,
    )
    if col_review.button(
        "去校对课程 →", width="stretch", disabled=not courses
    ):
        goto("② 校对课程")


def page_review() -> None:
    hero(
        "校对课程",
        "检查录入结果，修正星期、节次、周次、教师和教室。修改后点击“应用修改”，再进入课表视图。",
        "第二步 · 支持直接编辑表格",
    )
    courses: list[Course] = st.session_state.courses
    if not courses:
        empty_state(
            "还没有课程",
            "先到“导入课程”用结构化表单添加课程；课程名称必填，其他字段可以留空。",
            "去录入课程",
            "① 导入课程",
        )
        return

    template = st.session_state.template
    layout_all = build_layout(courses, template, None)
    conflict_count = len(layout_all.conflicts)
    unscheduled_count = len(layout_all.unscheduled)
    scheduled_count = len(courses) - unscheduled_count
    metric_cols = st.columns(4)
    metric_cols[0].metric("课程安排", len(courses))
    metric_cols[1].metric("已排入课表", scheduled_count)
    metric_cols[2].metric("待安排", unscheduled_count)
    metric_cols[3].metric("时间冲突", conflict_count)

    tab_list, tab_issues, tab_unscheduled, tab_raw = st.tabs(
        ["课程列表", "问题与冲突", "待安排", "旧版原文"]
    )

    with tab_list:
        df = _courses_df(courses)
        st.caption("直接双击单元格编辑；新增行会自动生成 ID。编辑完成后必须点击“应用修改”。")
        edited = st.data_editor(
            df,
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            key=f"course_editor_{st.session_state.data_version}",
            column_order=[
                "课程名称",
                "教师",
                "教室",
                "星期",
                "开始节",
                "结束节",
                "周次",
                "类型",
                "学分",
                "班级",
                "备注",
                "状态",
                "来源",
            ],
            column_config={
                "课程名称": st.column_config.TextColumn("课程名称", required=True, width="medium"),
                "教师": st.column_config.TextColumn("教师", width="small"),
                "教室": st.column_config.TextColumn("教室", width="small"),
                "星期": st.column_config.SelectboxColumn("星期", options=WEEKDAY_OPTIONS, width="small"),
                "开始节": st.column_config.NumberColumn("开始节", min_value=0, max_value=template.max_period, step=1),
                "结束节": st.column_config.NumberColumn("结束节", min_value=0, max_value=template.max_period, step=1),
                "周次": st.column_config.TextColumn(
                    "周次",
                    help="如 1-16周、1-8,10-16周、1-16周(单)、全周；留空按全周处理",
                    width="small",
                ),
                "类型": st.column_config.SelectboxColumn("类型", options=["每周", "单周", "双周"], width="small"),
                "学分": st.column_config.NumberColumn("学分", min_value=0.0, max_value=20.0, step=0.5, width="small"),
                "班级": st.column_config.TextColumn("班级", width="small"),
                "备注": st.column_config.TextColumn("备注", width="medium"),
                "状态": st.column_config.TextColumn("状态", disabled=True, width="medium"),
                "来源": st.column_config.TextColumn("来源", disabled=True, width="small"),
            },
        )
        col_save, col_reset, col_reparse = st.columns([1.2, 1, 1])
        if col_save.button("应用修改", type="primary", width="stretch"):
            new_courses = _df_to_courses(edited, template)
            if not new_courses:
                st.error("课程列表为空，修改未保存。")
            else:
                st.session_state.courses = new_courses
                bump_version()
                set_flash(f"已保存 {len(new_courses)} 条课程安排。")
                st.rerun()
        if col_reset.button("撤销未保存修改", width="stretch"):
            bump_version()
            st.rerun()
        if col_reparse.button("重新解析旧版原文", width="stretch", disabled=not st.session_state.raw_text):
            outcome = parse_text(st.session_state.raw_text, template, "重新解析")
            st.session_state.courses = _combine_outcome(outcome)
            st.session_state.unparsed = outcome.unparsed
            bump_version()
            set_flash(f"重新解析完成：{len(st.session_state.courses)} 条课程安排。")
            st.rerun()

    with tab_issues:
        issue_courses = [course for course in courses if course.issues]
        if issue_courses:
            issue_rows = [
                {
                    "课程": course.name,
                    "星期": course.weekday_label,
                    "节次": course.period_label,
                    "问题": "；".join(course.issues),
                }
                for course in issue_courses
            ]
            st.dataframe(pd.DataFrame(issue_rows), width="stretch", hide_index=True)
        else:
            st.success("没有发现字段缺失或格式问题。")

        st.markdown("#### 时间冲突")
        if layout_all.conflicts:
            conflict_rows = [
                {
                    "课程 A": conflict.a.name,
                    "课程 B": conflict.b.name,
                    "星期": WEEKDAY_NAMES.get(conflict.a.weekday or 0, "未设置"),
                    "节次": conflict.a.period_label,
                    "重叠周次": conflict.week_label,
                }
                for conflict in layout_all.conflicts
            ]
            st.dataframe(pd.DataFrame(conflict_rows), width="stretch", hide_index=True)
            st.warning("冲突课程仍会渲染，但会在课表中标红。请调整其中一门的时间，或确认是否为不同周次。")
        else:
            st.success("没有时间冲突。")

        if st.session_state.unparsed:
            st.markdown("#### 未识别的文本行")
            with st.expander("展开查看", expanded=False):
                for line in st.session_state.unparsed[:100]:
                    st.code(line, language=None)

    with tab_unscheduled:
        if layout_all.unscheduled:
            st.warning("以下课程缺少有效星期/节次，或上课日不在当前模板中。可逐条安排，也可回到课程列表直接编辑。")
            rows = [
                {
                    "课程": course.name,
                    "教师": course.teacher,
                    "教室": course.classroom,
                    "周次": course.week_label,
                    "原因": "；".join(course.issues) or "缺少星期或节次",
                }
                for course in layout_all.unscheduled
            ]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

            options = {
                f"{course.name}（{course.teacher or '无教师'}） · {course.week_label} · {index + 1}": course.id
                for index, course in enumerate(layout_all.unscheduled)
            }
            selected_label = st.selectbox("选择要安排的课程", list(options), key="quick_assign_course")
            selected_id = options[selected_label]
            col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
            template_day_labels = [WEEKDAY_NAMES[day] for day in template.days]
            weekday_label = col1.selectbox(
                "星期", template_day_labels, key="quick_weekday"
            )
            start = col2.number_input(
                "开始节",
                min_value=1,
                max_value=template.max_period,
                value=1,
                step=1,
                key="quick_start",
            )
            end = col3.number_input(
                "结束节",
                min_value=1,
                max_value=template.max_period,
                value=2,
                step=1,
                key="quick_end",
            )
            if col4.button("安排到课表", type="primary", width="stretch"):
                target = next((course for course in courses if course.id == selected_id), None)
                if target:
                    target.weekday = _weekday_from_label(weekday_label)
                    target.start_period = int(start)
                    target.end_period = max(int(start), int(end))
                    _validate_course(target, template)
                    st.session_state.courses = dedupe_courses(merge_adjacent_slots(courses))
                    bump_version()
                    set_flash(f"已安排《{target.name}》。")
                    st.rerun()
        else:
            st.success("所有课程都已排入课表。")

    with tab_raw:
        st.caption("当前结构化录入没有“原文”；这里保留旧版文本/文件导入的原文与解析日志。")
        st.text_area(
            "解析原文",
            value=st.session_state.raw_text or "（暂无原文）",
            height=320,
            disabled=True,
        )
        if st.session_state.raw_text:
            st.download_button(
                "下载原始文本",
                data=st.session_state.raw_text.encode("utf-8"),
                file_name="课程原文.txt",
                mime="text/plain",
            )
        if st.session_state.parse_log:
            st.markdown("#### 解析日志")
            st.dataframe(
                pd.DataFrame(st.session_state.parse_log),
                width="stretch",
                hide_index=True,
            )

    st.markdown("---")
    col_back, col_next = st.columns(2)
    if col_back.button("返回录入课程", width="stretch"):
        goto("① 导入课程")
    if col_next.button("去课表视图 →", type="primary", width="stretch"):
        goto("③ 课表视图")


# ---------------------------------------------------------------------------
# Timetable page
# ---------------------------------------------------------------------------


def page_timetable() -> None:
    hero(
        "课表视图",
        "按周查看课程。颜色按课程名称自动分配；冲突课程会标红，待安排课程单独列出。",
        "第三步 · 周课表",
    )
    courses: list[Course] = st.session_state.courses
    if not courses:
        empty_state(
            "课表还是空的",
            "先导入或手动添加课程，再回到这里生成周课表。",
            "去导入课程",
            "① 导入课程",
        )
        return

    template = st.session_state.template
    week_options = ["全部周次"] + [f"第{week}周" for week in range(1, template.total_weeks + 1)]
    if st.session_state.week_choice not in week_options:
        st.session_state.week_choice = "全部周次"
    if st.session_state.get("week_selector") not in week_options:
        st.session_state.week_selector = st.session_state.week_choice
    col_week, col_details, _col_spacer = st.columns([1.1, 1.6, 1.4])
    week_choice = col_week.selectbox(
        "查看周次",
        week_options,
        index=week_options.index(st.session_state.week_choice),
        key="week_selector",
    )
    st.session_state.week_choice = week_choice
    week = None if week_choice == "全部周次" else int(week_choice.replace("第", "").replace("周", ""))
    show_details = col_details.toggle("显示冲突与待安排明细", value=True)

    layout = build_layout(courses, template, week)
    teacher_count = len({course.teacher for course in layout.courses if course.teacher})
    metric_cols = st.columns(4)
    metric_cols[0].metric("本周课程", len(layout.courses))
    metric_cols[1].metric("时间冲突", len(layout.conflicts))
    metric_cols[2].metric("待安排", len(layout.unscheduled))
    metric_cols[3].metric("任课教师", teacher_count)
    if layout.conflicts:
        st.warning(f"检测到 {len(layout.conflicts)} 组时间冲突，已在课表中用红框和 ⚠ 标出。")
    if not layout.courses:
        st.info("当前查看范围内没有已排入课表的课程。可以切换到“全部周次”，或到“待安排”中处理。")

    st.markdown(render_html(layout, include_sections=show_details), unsafe_allow_html=True)
    st.markdown("---")
    col_a, col_b = st.columns(2)
    if col_a.button("去导出文件 →", type="primary", width="stretch", disabled=not layout.courses):
        goto("④ 导出文件")
    if col_b.button("返回校对课程", width="stretch"):
        goto("② 校对课程")


# ---------------------------------------------------------------------------
# Export page
# ---------------------------------------------------------------------------


def _safe_filename(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\r\n]+', "_", value).strip(" ._")
    return value or "我的课表"


def _file_name(base: str, week: int | None, extension: str) -> str:
    suffix = "全部周次" if week is None else f"第{week}周"
    return f"{_safe_filename(base)}_{suffix}.{extension}"


def _export_tab(
    layout,
    fmt: str,
    label: str,
    extension: str,
    mime: str,
    description: str,
    base_name: str,
    scope_key: str,
    preview: str = "",
) -> None:
    st.markdown(description)
    cache_key = f"{fmt}:{scope_key}:{st.session_state.data_version}"
    cache = st.session_state.export_cache
    if st.button(f"生成 {label}", type="primary", key=f"generate_{cache_key}"):
        try:
            with st.spinner(f"正在生成 {label}…"):
                cache[cache_key] = export_bytes(layout, fmt)
            st.success(f"{label} 已生成。")
        except Exception as exc:
            st.error(f"生成 {label} 失败：{type(exc).__name__}: {exc}")
    data = cache.get(cache_key)
    if not data:
        st.caption("点击上方按钮生成文件；生成后可下载或预览。")
        return
    st.caption(f"文件大小：{len(data) / 1024:.1f} KB")
    st.download_button(
        f"下载 {label}",
        data=data,
        file_name=_file_name(base_name, layout.week, extension),
        mime=mime,
        key=f"download_{cache_key}",
        width="stretch",
    )
    if preview == "png":
        st.image(data, width="stretch")
    elif preview == "html":
        with st.expander("打印预览", expanded=False):
            components.html(data.decode("utf-8"), height=760, scrolling=True)
    elif fmt == "ics":
        st.caption(f"共 {render_ics_summary(layout)} 个日程事件。导入手机/电脑日历后，可按周查看。")


def page_export() -> None:
    hero(
        "导出文件",
        "把当前课表导出为 Excel、PNG、PDF、ICS 日历或可打印 HTML。所有文件都在本机生成。",
        "第四步 · 5 种导出格式",
    )
    courses: list[Course] = st.session_state.courses
    if not courses:
        empty_state(
            "还没有可导出的课程",
            "先导入课程并校对，再生成课表文件。",
            "去导入课程",
            "① 导入课程",
        )
        return
    template = st.session_state.template
    scope_options = ["当前查看的周次", "全部周次", "指定周次"]
    scope = st.radio("导出范围", scope_options, horizontal=True, index=0)
    week = None
    if scope == "当前查看的周次":
        current = st.session_state.week_choice
        week = None if current == "全部周次" else int(current.replace("第", "").replace("周", ""))
    elif scope == "指定周次":
        week = st.selectbox("选择周次", list(range(1, template.total_weeks + 1)), index=0)
    if week is not None and not 1 <= week <= template.total_weeks:
        week = template.total_weeks
    layout = build_layout(courses, template, week)
    st.caption(
        f"当前范围：{layout.week_label} · {layout.days_label} · "
        f"{len(layout.courses)} 条课程安排 · {len(layout.conflicts)} 组冲突"
    )
    if not layout.courses:
        st.warning("当前范围没有已排入课表的课程，导出的课表会是空的。可以切换到“全部周次”。")

    col_base, col_clear = st.columns([2, 1])
    base_name = col_base.text_input("文件名前缀", value=template.title or "我的课表")
    if col_clear.button("清空导出缓存", width="stretch"):
        st.session_state.export_cache = {}
        st.rerun()

    tab_excel, tab_png, tab_pdf, tab_ics, tab_html = st.tabs(
        ["Excel 课表", "PNG 图片", "PDF 打印", "日历 ICS", "打印 HTML"]
    )
    scope_key = f"{scope}:{week}"
    with tab_excel:
        _export_tab(
            layout,
            "xlsx",
            "Excel",
            "xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "生成带合并单元格、颜色和课程清单的 `.xlsx`。适合打印、存档和继续编辑。",
            base_name,
            scope_key,
        )
    with tab_png:
        _export_tab(
            layout,
            "png",
            "PNG",
            "png",
            "image/png",
            "生成 A4 横向、200 DPI 的课表图片，适合发群、保存到手机或插入文档。",
            base_name,
            scope_key,
            preview="png",
        )
    with tab_pdf:
        _export_tab(
            layout,
            "pdf",
            "PDF",
            "pdf",
            "application/pdf",
            "生成 A4 横向 PDF（图片型），可直接打印或提交。",
            base_name,
            scope_key,
        )
    with tab_ics:
        _export_tab(
            layout,
            "ics",
            "ICS 日历",
            "ics",
            "text/calendar",
            "生成标准 `.ics` 日历文件；导入后每个课程会按周出现在手机/电脑日历中。",
            base_name,
            scope_key,
        )
    with tab_html:
        _export_tab(
            layout,
            "html",
            "打印 HTML",
            "html",
            "text/html",
            "生成独立的打印页面；用浏览器打开后按 Ctrl+P 即可打印或另存为 PDF。",
            base_name,
            scope_key,
            preview="html",
        )


# ---------------------------------------------------------------------------
# Settings page
# ---------------------------------------------------------------------------


def _rows_df_from_template(rows: list[TimeRow]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "开始节": row.period_start,
                "结束节": row.period_end,
                "开始时间": row.start,
                "结束时间": row.end,
            }
            for row in rows
        ]
    )


def _rows_from_editor(df: pd.DataFrame) -> list[TimeRow]:
    rows: list[TimeRow] = []
    for row in df.to_dict("records"):
        start_period = _to_int(row.get("开始节"), 0)
        end_period = _to_int(row.get("结束节"), 0)
        start = normalize_hhmm(str(row.get("开始时间", "") or ""))
        end = normalize_hhmm(str(row.get("结束时间", "") or ""))
        if start_period < 1 or end_period < start_period:
            continue
        if not start or not end:
            continue
        rows.append(
            TimeRow(
                label=f"{start_period}-{end_period}节",
                period_start=start_period,
                period_end=end_period,
                start=start,
                end=end,
            )
        )
    return sorted(rows, key=lambda row: row.period_start)


def page_settings() -> None:
    hero(
        "模板设置",
        "标准模板固定为 12 节 / 6 个时段；自定义模板可以修改总周数、上课日、每天节数与上下课时间。",
        "第五步 · 课表形状",
    )
    template: Template = st.session_state.template
    if st.session_state.get("template_onboarding"):
        st.info(
            "当前是模式二：请先调整时间格，点击“保存模板设置”后将自动进入录入课程。"
        )
    mode_options = ["标准模板（6 时段 / 12 节）", "自定义模板"]
    mode = st.radio(
        "模板模式",
        mode_options,
        index=0 if template.mode == "standard" else 1,
        horizontal=True,
        key=f"settings_mode_{st.session_state.settings_version}",
    )
    is_custom = mode == mode_options[1]

    col1, col2, col3 = st.columns(3)
    settings_version = st.session_state.settings_version
    total_weeks = col1.number_input(
        "学期总周数",
        min_value=1,
        max_value=30,
        value=int(template.total_weeks),
        step=1,
        key=f"settings_weeks_{settings_version}",
    )
    start_date_value = col2.date_input(
        "第 1 周周一",
        value=template.start_date or default_start_date(),
        key=f"settings_start_{settings_version}",
    )
    title = col3.text_input(
        "课表标题",
        value=template.title or "我的课表",
        key=f"settings_title_{settings_version}",
    )
    days = st.multiselect(
        "每周上课日",
        options=list(WEEKDAY_NAMES.keys()),
        default=list(template.days),
        format_func=lambda day: WEEKDAY_NAMES[day],
        key=f"settings_days_{settings_version}",
    )
    if not days:
        st.warning("至少选择一个上课日。")

    edited_rows: pd.DataFrame | None = None
    if is_custom:
        st.markdown("#### 自定义时间格")
        st.caption("每一行是课表中的一个可见时段。可以合并 1-4 节，也可以一节课一行。修改后点击页面底部“保存模板设置”。")
        if st.session_state.custom_rows is None:
            st.session_state.custom_rows = [row.to_dict() for row in template.rows]
        col_p, col_b, col_generate, col_standard = st.columns([1, 1, 1, 1])
        default_periods = template.max_period if template.mode == "custom" else 12
        periods_per_day = col_p.number_input(
            "每天节数",
            min_value=1,
            max_value=20,
            value=max(1, default_periods),
            step=1,
            key=f"settings_periods_{settings_version}",
        )
        block_size = col_b.selectbox(
            "每格包含节数",
            [1, 2, 3, 4],
            index=1,
            key=f"settings_block_{settings_version}",
        )
        if col_generate.button("生成时间格", width="stretch"):
            st.session_state.custom_rows = [
                row.to_dict() for row in make_rows(int(periods_per_day), int(block_size))
            ]
            st.session_state.rows_version += 1
            st.rerun()
        if col_standard.button("按标准时段填充", width="stretch"):
            st.session_state.custom_rows = [
                row.to_dict() for row in default_template("standard").rows
            ]
            st.session_state.rows_version += 1
            st.rerun()

        current_rows = [
            TimeRow.from_dict(item)
            for item in (st.session_state.custom_rows or [])
            if isinstance(item, dict)
        ]
        edited_rows = st.data_editor(
            _rows_df_from_template(current_rows),
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            key=f"rows_editor_{st.session_state.rows_version}",
            column_config={
                "开始节": st.column_config.NumberColumn("开始节", min_value=1, max_value=20, step=1),
                "结束节": st.column_config.NumberColumn("结束节", min_value=1, max_value=20, step=1),
                "开始时间": st.column_config.TextColumn("开始时间", help="HH:MM，例如 08:00"),
                "结束时间": st.column_config.TextColumn("结束时间", help="HH:MM，例如 09:45"),
            },
        )
        if edited_rows is not None and len(edited_rows) == 0:
            st.warning("时间格为空，保存时会回退到标准模板。")
    else:
        st.markdown("#### 标准时段")
        standard = default_template("standard")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "时段": row.period_label,
                        "开始": row.start,
                        "结束": row.end,
                    }
                    for row in standard.rows
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        st.caption("标准模板时间固定；如需调整时间，请切换到“自定义模板”。")

    st.markdown("---")
    col_save, col_reset = st.columns([1.4, 1])
    if col_save.button("保存模板设置", type="primary", width="stretch"):
        if not days:
            st.error("请至少选择一个上课日。")
            return
        if is_custom:
            rows = _rows_from_editor(edited_rows) if edited_rows is not None else []
            if not rows:
                st.error("自定义时间格为空，无法保存。")
                return
            sorted_rows = sorted(rows, key=lambda row: row.period_start)
            for previous, current in zip(sorted_rows, sorted_rows[1:]):
                if current.period_start <= previous.period_end:
                    st.error(
                        f"时间格节次重叠：{previous.period_label} 与 {current.period_label}。"
                    )
                    return
        else:
            rows = default_template("standard").rows
        for row in rows:
            if row.start and row.end and row.start >= row.end:
                st.error(f"时段 {row.period_label} 的结束时间必须晚于开始时间。")
                return
        new_template = Template(
            mode="custom" if is_custom else "standard",
            total_weeks=int(total_weeks),
            days=[int(day) for day in days],
            rows=rows,
            start_date=start_date_value,
            title=title.strip() or "我的课表",
        )
        st.session_state.template = new_template
        st.session_state.custom_rows = [row.to_dict() for row in rows]
        st.session_state.rows_version += 1
        st.session_state.settings_version += 1
        for course in st.session_state.courses:
            _validate_course(course, new_template)
        bump_version()
        if st.session_state.get("template_onboarding"):
            st.session_state.template_onboarding = False
            st.session_state.pending_page = "① 导入课程"
            set_flash("模板设置已保存，开始录入课程。")
        else:
            set_flash("模板设置已保存。")
        st.rerun()

    if col_reset.button("恢复默认模板", width="stretch"):
        new_template = default_template("standard")
        st.session_state.template = new_template
        st.session_state.custom_rows = [row.to_dict() for row in new_template.rows]
        st.session_state.rows_version += 1
        st.session_state.settings_version += 1
        for course in st.session_state.courses:
            _validate_course(course, new_template)
        bump_version()
        set_flash("已恢复标准模板。")
        st.rerun()

    st.markdown("---")
    st.markdown("#### 数据管理")
    st.caption("课程数据只保存在当前 Streamlit 会话中；刷新页面或关闭进程后会丢失。需要保留时请导出 Excel 或下载 JSON。")
    col_json, col_clear = st.columns([1, 1])
    payload = {
        "version": APP_VERSION,
        "template": st.session_state.template.to_dict(),
        "courses": [course.to_dict() for course in st.session_state.courses],
    }
    col_json.download_button(
        "下载课程数据（JSON）",
        data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="timetable_data.json",
        mime="application/json",
        width="stretch",
    )
    with col_clear:
        confirm = st.checkbox("确认清空所有课程", key="confirm_clear")
        if st.button("清空所有课程", disabled=not confirm, width="stretch"):
            reset_all_data()
            set_flash("已清空所有课程数据。")
            st.rerun()


# ---------------------------------------------------------------------------
# Help page
# ---------------------------------------------------------------------------


def page_help() -> None:
    hero(
        "使用帮助",
        "从结构化录入、时间格式到模板与导出说明，这里汇总了最常见的问题。",
        "完全本地 · 不联网 · 不需要 API Key",
    )
    st.markdown(
        """
> **首次进入流程**：首页封面 → “开始课表编辑” → 选择模式一（默认时间）或模式二（自定义时间）→ 录入课程。左侧导航栏可随时切换页面。

### 1. 当前输入方式

当前页面只开放**结构化文本录入**：

| 字段 | 说明 |
| --- | --- |
| 课程名称 * | 必填；其他字段都可以留空 |
| 教师 | 可选，例如“张三” |
| 教室 | 可选；可点击“正心楼 / 致知楼 / 诚意楼 / 格物楼 / 电机楼 / 理学楼”快速填入，再补教室号 |
| 星期 | 可选；下拉选择周一至周日 |
| 节次 | 可选；例如 `5/6节`、`9-11节`、`1-2节` |
| 周次 | 可选；例如 `1-16周`、`单周`、`双周`、`全周` |
| 学分 / 班级 / 备注 | 可选 |

> Word / PDF / Excel / CSV / Markdown / 图片上传入口当前已隐藏，但相关解析代码保留，后续可重新开启。

### 2. 常用备选库

- 课程名：展开“常用课程名”，点击“高等数学”“大学英语”“线性代数”等即可填入；
- 教学楼：点击“正心楼”等按钮填入，再手动补全为“正心楼415”；
- 节次 / 周次：点击“5/6节”“1-16周”等按钮填入；
- 整段时间：展开“常用整段时间”，点击“周一 5-6节”会同时填入星期和节次。

填入后所有字段仍然可以直接修改；多个节次可写成 `5/6节,9/11节`。

### 3. 能识别哪些时间写法

- 星期：`周一`、`星期一`、`礼拜一`、`周一至周三`、`Mon`；
- 节次：`第1-2节`、`1-2节`、`第3节`、`1、2节`、`5/6节`、`9/11节`、`08:00-09:45`；
- 周次：`1-16周`、`1-8,10-16周`、`第1-16周`、`单周`、`双周`、`1-16周(单)`；
- 多个节次：在“节次”框写 `5/6节,9/11节`，会生成多条课程安排；多个星期请分多次添加。

### 4. 模板与周次

- **标准模板**：每天 6 个时段，分别对应第 1-2、3-4、5-6、7-8、9-10、11-12 节；
  默认时间为 08:00-09:45、10:00-11:45、13:45-15:30、15:45-17:30、18:30-20:15、20:30-22:15。
- **自定义模板**：可修改总周数、上课日、每天节数、每格包含节数和每格起止时间。
- 课表视图支持“全部周次”和单周查看；单双周会按周次过滤。
- 非常规端点（如 `9-11节`）：网页课表和 PNG/PDF 会按 1.5 个时间格显示，占 11-12 格的一半；Excel 受行高限制仍按合并格显示。

### 5. 导出

- **Excel**：合并单元格的周课表 + 课程清单 + 冲突/待安排；
- **PNG**：A4 横向 200 DPI，适合发群；
- **PDF**：A4 横向，适合打印；
- **ICS**：标准日历文件，导入手机/电脑日历；
- **打印 HTML**：独立网页，浏览器打开后 `Ctrl+P`。

### 6. 隐私说明

所有录入的数据都只在本机内存中处理。程序不包含任何外部 API 调用，不会上传课程内容，也不需要 DeepSeek/OpenAI 等 API Key。关闭 Streamlit 进程后会话数据会消失；需要保留请下载 Excel 或 JSON。

### 7. 常见问题

**Q：模式二设置完怎么开始录入？**
A：点击“保存模板设置”，保存成功后会自动进入“录入课程”；也可以随时点左侧导航栏的“① 导入课程”。

**Q：为什么现在看不到上传文件的入口？**
A：当前版本优先解决自由文本/文件格式差异导致的误识别，暂时只开放结构化文本录入；文件解析和 OCR 代码仍保留。

**Q：没有填星期或节次可以保存吗？**
A：可以。课程会进入“待安排”，之后可在“校对课程 → 待安排”快速安排，或直接编辑课程列表。

**Q：为什么某门课进了“待安排”？**
A：缺少星期/节次，或上课日不在当前模板的上课日里。到“校对课程 → 待安排”快速安排，或直接编辑课程列表。

**Q：为什么有冲突？**
A：同一星期、节次重叠且周次有交集。课表会用红框和 ⚠ 标出；可以在课程列表修改时间/周次。

**Q：数据会保存吗？**
A：当前版本只保存在会话中，刷新后丢失。可使用“模板设置 → 下载课程数据（JSON）”留档。

**Q：需要安装什么？**
A：项目内已带 `vendor/` 依赖；直接运行 `streamlit run app.py` 即可。若使用干净环境，先执行 `pip install -r requirements.txt`。
"""
    )


# ---------------------------------------------------------------------------
# Sidebar & routing
# ---------------------------------------------------------------------------


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown(
            '<div class="brand"><div class="logo">📅</div>'
            '<div class="name">智能课表生成器</div>'
            '<div class="sub">结构化录入 · 本地渲染 · 无 API</div></div>',
            unsafe_allow_html=True,
        )
        st.markdown("---")
        page = st.radio("导航", PAGES, key="page", label_visibility="collapsed")
        st.markdown("---")
        courses: list[Course] = st.session_state.courses
        template: Template = st.session_state.template
        layout = build_layout(courses, template, None) if courses else None
        conflict_count = len(layout.conflicts) if layout else 0
        unscheduled_count = len(layout.unscheduled) if layout else 0
        st.markdown(
            '<div class="side-card">'
            f'<div class="row"><span>课程安排</span><b>{len(courses)}</b></div>'
            f'<div class="row"><span>时间冲突</span><b>{conflict_count}</b></div>'
            f'<div class="row"><span>待安排</span><b>{unscheduled_count}</b></div>'
            f'<div class="row"><span>总周数</span><b>{template.total_weeks}</b></div>'
            f'<div class="row"><span>模板</span><b>{"自定义" if template.mode == "custom" else "标准"}</b></div>'
            "</div>",
            unsafe_allow_html=True,
        )
        st.caption("所有数据仅在本机处理，不会上传。")
        st.caption(f"v{APP_VERSION} · 结构化录入 · 无网络请求")
        st.markdown("---")
        with st.expander("清空数据", expanded=False):
            confirm = st.checkbox("确认清空", key="sidebar_confirm_clear")
            if st.button("清空所有课程", disabled=not confirm, width="stretch"):
                reset_all_data()
                set_flash("已清空所有课程数据。")
                st.rerun()
    return page


def main() -> None:
    init_state()
    pending_page = st.session_state.pop("pending_page", None)
    if pending_page:
        # Safe here: the navigation radio has not been instantiated yet in this
        # script run.
        st.session_state.page = pending_page
    page = render_sidebar()
    show_flash()
    if page == "🏠 首页":
        page_home()
    elif page == "🧭 开始":
        page_mode_select()
    elif page == "① 导入课程":
        page_import()
    elif page == "② 校对课程":
        page_review()
    elif page == "③ 课表视图":
        page_timetable()
    elif page == "④ 导出文件":
        page_export()
    elif page == "⑤ 模板设置":
        page_settings()
    else:
        page_help()


if __name__ == "__main__":
    main()
