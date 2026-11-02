"""Rule-based course parsers.

Everything in this module is local and deterministic: no network calls, no
model calls, no vendor SDKs.  The parser supports three common shapes:

* free text / one-line records / multi-line blocks;
* course-list tables with a header row;
* grid timetables whose columns are weekdays and rows are periods.

The public entry points are :func:`parse_text`, :func:`parse_table` and
:func:`parse_tables`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .models import (
    MAX_PERIODS,
    MAX_WEEKS,
    Course,
    Template,
    dedupe_courses,
    merge_adjacent_slots,
)

# ---------------------------------------------------------------------------
# Public data containers
# ---------------------------------------------------------------------------


@dataclass
class TableData:
    rows: list[list[str]]
    source: str = ""


@dataclass
class ParseOutcome:
    courses: list[Course] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)

    def extend(self, other: "ParseOutcome") -> None:
        self.courses.extend(other.courses)
        self.issues.extend(other.issues)
        self.unparsed.extend(other.unparsed)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_DASHES = str.maketrans(
    {
        "—": "-",
        "–": "-",
        "－": "-",
        "﹣": "-",
        "～": "-",
        "〜": "-",
        "至": "至",  # keep the Chinese separator, regex accepts it
    }
)

_NOISE_LINE_RE = re.compile(
    r"^(?:第?\s*\d+\s*页(?:\s*[/／共]\s*\d+\s*页)?|共\s*\d+\s*页|"
    r"打印(?:时间|日期)?\s*[:：]?.*|制表(?:人|日期)?\s*[:：]?.*|"
    r"导出(?:时间|日期)\s*[:：]?.*|生成(?:时间|日期)\s*[:：]?.*)$"
)

_SPACE_RE = re.compile(r"[ \t\u3000]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Normalise line endings, full-width characters and noise lines."""

    if not text:
        return ""
    value = unicodedata.normalize("NFKC", str(text))
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    value = value.translate(_DASHES)
    lines: list[str] = []
    for raw_line in value.split("\n"):
        line = _SPACE_RE.sub(" ", raw_line).strip()
        if not line:
            lines.append("")
            continue
        if _NOISE_LINE_RE.match(line):
            continue
        lines.append(line)
    return _MULTI_NEWLINE_RE.sub("\n\n", "\n".join(lines)).strip()


def normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    value = value.translate(_DASHES)
    lines = [_SPACE_RE.sub(" ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _clean_lines(text: str) -> list[str]:
    return [line.strip() for line in normalize_text(text).split("\n")]


# ---------------------------------------------------------------------------
# Weekdays
# ---------------------------------------------------------------------------

_WEEKDAY_MAP = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "日": 7,
    "天": 7,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
}

_WEEKDAY_RANGE_RE = re.compile(
    r"(?:星期|周|礼拜)\s*([一二三四五六日天1-7])\s*(?:至|到|~|-)\s*"
    r"(?:星期|周|礼拜)?\s*([一二三四五六日天1-7])"
)
_WEEKDAY_RE = re.compile(r"(?:星期|周|礼拜)\s*([一二三四五六日天1-7])")
_EN_WEEKDAY_RE = re.compile(
    r"\b(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|sday|nesday|rsday|urday)?\b",
    re.IGNORECASE,
)
_EN_WEEKDAY_MAP = {
    "mon": 1,
    "tue": 2,
    "tues": 2,
    "wed": 3,
    "thu": 4,
    "thur": 4,
    "thurs": 4,
    "fri": 5,
    "sat": 6,
    "sun": 7,
}


def _weekday_spans(text: str) -> list[tuple[int, int, list[int]]]:
    """Return sorted, non-overlapping weekday spans.

    A span is ``(start, end, [weekday numbers])``.  Chinese weekday ranges
    such as ``周一至周三`` are treated as one span.
    """

    spans: list[tuple[int, int, list[int]]] = []
    occupied: list[tuple[int, int]] = []
    for match in _WEEKDAY_RANGE_RE.finditer(text):
        first = _WEEKDAY_MAP.get(match.group(1))
        last = _WEEKDAY_MAP.get(match.group(2))
        if not first or not last:
            continue
        if first <= last:
            days = list(range(first, last + 1))
        else:
            days = list(range(first, 8)) + list(range(1, last + 1))
        spans.append((match.start(), match.end(), days))
        occupied.append((match.start(), match.end()))
    for match in _WEEKDAY_RE.finditer(text):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        day = _WEEKDAY_MAP.get(match.group(1))
        if day:
            spans.append((match.start(), match.end(), [day]))
    for match in _EN_WEEKDAY_RE.finditer(text):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        day = _EN_WEEKDAY_MAP.get(match.group(1).lower())
        if day:
            spans.append((match.start(), match.end(), [day]))
    spans.sort(key=lambda item: item[0])
    # Drop overlapping singles in case two regexes matched the same area.
    result: list[tuple[int, int, list[int]]] = []
    for span in spans:
        if result and span[0] < result[-1][1]:
            continue
        result.append(span)
    return result


def parse_weekdays(text: str) -> list[int]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    # A table column may contain just "一" or "1".
    bare = re.fullmatch(r"\s*([一二三四五六日天1-7])\s*", normalized)
    if bare:
        day = _WEEKDAY_MAP.get(bare.group(1))
        return [day] if day else []
    days: list[int] = []
    for _start, _end, span_days in _weekday_spans(normalized):
        days.extend(span_days)
    if "周末" in normalized:
        days.extend([6, 7])
    if "每天" in normalized:
        days.extend([1, 2, 3, 4, 5, 6, 7])
    return sorted(set(days))


# ---------------------------------------------------------------------------
# Periods and wall-clock times
# ---------------------------------------------------------------------------

_PERIOD_RANGE_RE = re.compile(
    r"(?:第\s*)?(\d{1,2})\s*(?:-|至|到)\s*(\d{1,2})\s*节"
)
_PERIOD_SLASH_RE = re.compile(
    r"(?:第\s*)?(\d{1,2})\s*/\s*(\d{1,2})\s*节"
)
_PERIOD_COLON_RE = re.compile(
    r"(?:节次|课节)\s*[:：]?\s*(\d{1,2})\s*(?:-|至|到)\s*(\d{1,2})"
)
_PERIOD_LIST_RE = re.compile(
    r"(?:第\s*)?(\d{1,2})\s*[、,，]\s*(\d{1,2})\s*节"
)
_PERIOD_SINGLE_RE = re.compile(r"(?:第\s*)?(\d{1,2})\s*节")
_TIME_RANGE_RE = re.compile(
    r"(\d{1,2})\s*[:：]\s*(\d{2})\s*(?:-|至|到)\s*(\d{1,2})\s*[:：]\s*(\d{2})"
)
_TIME_OF_DAY_RE = re.compile(r"^(?:上午|下午|晚上|中午|早上|早晨|傍晚)\s*")


def _valid_period_pair(first: int, second: int) -> tuple[int, int] | None:
    if not (1 <= first <= MAX_PERIODS and 1 <= second <= MAX_PERIODS):
        return None
    if first > second:
        first, second = second, first
    return first, second


def parse_period_slots(text: str) -> list[tuple[int, int]]:
    """Parse all ``1-2节`` / ``第3节`` / ``1、2节`` slots from text."""

    if not text:
        return []
    normalized = normalize_text(text)
    found: list[tuple[int, int, int, int]] = []  # start, end, match_start, match_end
    occupied: list[tuple[int, int]] = []

    def add(match: re.Match[str], first: int, second: int) -> None:
        pair = _valid_period_pair(first, second)
        if pair is None:
            return
        if any(start <= match.start() < end for start, end in occupied):
            return
        found.append((pair[0], pair[1], match.start(), match.end()))
        occupied.append((match.start(), match.end()))

    for match in _PERIOD_COLON_RE.finditer(normalized):
        add(match, int(match.group(1)), int(match.group(2)))
    for match in _PERIOD_SLASH_RE.finditer(normalized):
        add(match, int(match.group(1)), int(match.group(2)))
    for match in _PERIOD_RANGE_RE.finditer(normalized):
        add(match, int(match.group(1)), int(match.group(2)))
    for match in _PERIOD_LIST_RE.finditer(normalized):
        add(match, int(match.group(1)), int(match.group(2)))
    for match in _PERIOD_SINGLE_RE.finditer(normalized):
        add(match, int(match.group(1)), int(match.group(1)))
    for match in re.finditer(
        r"(?m)^\s*(\d{1,2})\s*(?:-|至|到)\s*(\d{1,2})\s*$", normalized
    ):
        add(match, int(match.group(1)), int(match.group(2)))
    for match in re.finditer(
        r"(?m)^\s*(\d{1,2})\s*[,，、]\s*(\d{1,2})\s*$", normalized
    ):
        add(match, int(match.group(1)), int(match.group(2)))
    for match in re.finditer(r"(?m)^\s*(\d{1,2})\s*$", normalized):
        add(match, int(match.group(1)), int(match.group(1)))

    # A bare "1-2" / "1,2" / "0102" / "3" is only accepted when the caller
    # is parsing a dedicated period cell.
    if not found and "节" not in normalized:
        match = re.fullmatch(r"\s*(\d{1,2})\s*(?:-|至|到)\s*(\d{1,2})\s*", normalized)
        if match:
            pair = _valid_period_pair(int(match.group(1)), int(match.group(2)))
            if pair:
                return [pair]
        match = re.fullmatch(r"\s*(\d{1,2})\s*[,，、]\s*(\d{1,2})\s*", normalized)
        if match:
            pair = _valid_period_pair(int(match.group(1)), int(match.group(2)))
            if pair:
                return [pair]
        match = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{1,2})\s*", normalized)
        if match:
            pair = _valid_period_pair(int(match.group(1)), int(match.group(2)))
            if pair:
                return [pair]
        match = re.fullmatch(r"\s*(\d{2})(\d{2})\s*", normalized)
        if match:
            pair = _valid_period_pair(int(match.group(1)), int(match.group(2)))
            if pair:
                return [pair]
        match = re.fullmatch(r"\s*(\d{1,2})\s*", normalized)
        if match:
            number = int(match.group(1))
            if 1 <= number <= MAX_PERIODS:
                return [(number, number)]

    found.sort(key=lambda item: item[2])
    result: list[tuple[int, int]] = []
    for first, second, _start, _end in found:
        pair = (first, second)
        if pair not in result:
            result.append(pair)
    return result


def parse_time_slots(text: str, template: Template) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for match in _TIME_RANGE_RE.finditer(normalize_text(text)):
        start = f"{int(match.group(1)):02d}:{match.group(2)}"
        end = f"{int(match.group(3)):02d}:{match.group(4)}"
        pair = template.period_range_for_time(start, end)
        if pair and pair not in result:
            result.append(pair)
    return result


# ---------------------------------------------------------------------------
# Weeks
# ---------------------------------------------------------------------------

_WEEK_EXPR_RE = re.compile(
    r"(?:第\s*)?"
    r"(\d{1,2}(?:\s*(?:-|至|到)\s*\d{1,2})?"
    r"(?:\s*[,，、]\s*\d{1,2}(?:\s*(?:-|至|到)\s*\d{1,2})?)*)"
    r"\s*周"
)
_BARE_WEEK_EXPR_RE = re.compile(
    r"\s*(\d{1,2}(?:\s*(?:-|至|到)\s*\d{1,2})?"
    r"(?:\s*[,，、]\s*\d{1,2}(?:\s*(?:-|至|到)\s*\d{1,2})?)*)\s*"
)


def _parse_week_expression(expression: str) -> list[int]:
    weeks: list[int] = []
    for part in re.split(r"[,，、]", expression):
        part = part.strip()
        if not part:
            continue
        range_match = re.fullmatch(
            r"(\d{1,2})\s*(?:-|至|到)\s*(\d{1,2})", part
        )
        if range_match:
            first = int(range_match.group(1))
            last = int(range_match.group(2))
            if first > last:
                first, last = last, first
            weeks.extend(range(max(1, first), min(MAX_WEEKS, last) + 1))
            continue
        single_match = re.fullmatch(r"\d{1,2}", part)
        if single_match:
            number = int(part)
            if 1 <= number <= MAX_WEEKS:
                weeks.append(number)
    return sorted(set(weeks))


def _detect_week_type(text: str) -> str:
    if "单双周" in text or "单双" in text:
        return "all"
    if re.search(r"单周|单数周|周\s*[（(]?\s*单", text) or re.search(
        r"[（(]\s*单\s*[）)]", text
    ):
        return "odd"
    if re.search(r"双周|双数周|周\s*[（(]?\s*双", text) or re.search(
        r"[（(]\s*双\s*[）)]", text
    ):
        return "even"
    if re.search(r"\bodd\b", text, re.IGNORECASE):
        return "odd"
    if re.search(r"\beven\b", text, re.IGNORECASE):
        return "even"
    return "all"


def parse_weeks(
    text: str, assume_weeks: bool = False
) -> tuple[list[int], str, str]:
    """Return ``(weeks, week_type, week_expr)``.

    ``weeks`` is an explicit list when the source names concrete weeks, and an
    empty list when the course is "all weeks" or only a parity is known.
    """

    if not text:
        return [], "all", ""
    normalized = normalize_text(text)
    week_type = _detect_week_type(normalized)

    expression = ""
    match = _WEEK_EXPR_RE.search(normalized)
    if match:
        expression = match.group(1)
    elif assume_weeks:
        bare = _BARE_WEEK_EXPR_RE.fullmatch(normalized)
        if bare:
            expression = bare.group(1)

    if not expression and "全周" in normalized:
        return [], "all", "全周"
    if not expression and "每周" in normalized:
        return [], "all", "全周"

    weeks = _parse_week_expression(expression) if expression else []
    if weeks and week_type == "odd":
        weeks = [week for week in weeks if week % 2 == 1]
    elif weeks and week_type == "even":
        weeks = [week for week in weeks if week % 2 == 0]

    if expression:
        raw_label = f"{expression}周"
        if week_type == "odd":
            raw_label += "(单)"
        elif week_type == "even":
            raw_label += "(双)"
        return weeks, week_type, raw_label
    if week_type == "odd":
        return [], "odd", "单周"
    if week_type == "even":
        return [], "even", "双周"
    return [], "all", ""


# ---------------------------------------------------------------------------
# Course-name / teacher / classroom extraction
# ---------------------------------------------------------------------------

_NAME_LABELS = ("课程名称", "课程名", "教学班名称", "科目", "课程")
_TEACHER_LABELS = ("任课教师", "授课教师", "主讲教师", "教师", "老师")
_CLASSROOM_LABELS = ("上课地点", "上课教室", "教室", "地点", "场地", "教学地点")
_WEEKS_LABELS = ("周次", "起止周", "上课周次", "教学周", "周数")
_CREDITS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*学分")
_CLASS_LABELS = ("教学班", "上课班级", "行政班", "班级")
_NOTE_LABELS = ("备注", "说明")

_COURSE_KEYWORDS = (
    "数学",
    "英语",
    "语文",
    "物理",
    "化学",
    "生物",
    "历史",
    "地理",
    "政治",
    "思政",
    "体育",
    "音乐",
    "美术",
    "艺术",
    "计算机",
    "程序",
    "设计",
    "数据结构",
    "算法",
    "网络",
    "数据",
    "人工智能",
    "机器学习",
    "经济",
    "管理",
    "会计",
    "金融",
    "法律",
    "法学",
    "哲学",
    "文学",
    "外语",
    "写作",
    "阅读",
    "听力",
    "口语",
    "实验",
    "实践",
    "实训",
    "导论",
    "原理",
    "概论",
    "基础",
    "研究",
    "分析",
    "工程",
    "技术",
    "系统",
    "通信",
    "电子",
    "电路",
    "力学",
    "光学",
    "统计",
    "概率",
    "线性代数",
    "微积分",
    "大学",
    "高等",
    "专业",
    "课程",
)

_ROOM_RE = re.compile(
    r"(?P<room>"
    r"(?:[\u4e00-\u9fa5A-Za-z]{0,10}(?:教学楼|实验楼|综合楼|图书馆|体育馆|"
    r"实训楼|中心|楼|馆|教|室)[ \t]*[A-Za-z]?[ \t]*\d{1,4}[A-Za-z]?)"
    r"|(?:[A-Za-z]{1,4}[ \t]*\d{2,4}[A-Za-z]?)"
    r"|(?:线上|腾讯会议|钉钉|超星|学习通|雨课堂|Zoom|Teams)"
    r")"
)

_ROOM_HINT_RE = re.compile(
    r"(?:教室|地点|场地|实验楼|教学楼|综合楼|实训楼|体育馆|图书馆|楼|馆|室)"
)

_NAMED_ROOM_RE = re.compile(
    r"(?P<room>"
    r"[\u4e00-\u9fa5A-Za-z]{0,12}"
    r"(?:体育馆|图书馆|操场|运动场|报告厅|会议室|活动中心|实验中心|训练中心|"
    r"教学楼|实验楼|综合楼|实训楼|楼|馆|室|中心)"
    r"(?:[ \t]*[A-Za-z]?[ \t]*\d{1,4}[A-Za-z]?)?"
    r")"
)

_GENERIC_HEADERS = {
    "课程表",
    "课表",
    "学生课表",
    "学期课表",
    "课程清单",
    "课程列表",
    "教学安排",
    "上课安排",
    "备注",
    "说明",
    "合计",
    "总计",
    "序号",
    "姓名",
    "学号",
    "专业",
    "班级",
    "星期",
    "节次",
    "时间",
    "教师",
    "老师",
    "教室",
    "地点",
    "学分",
    "周次",
}


def _is_title_line(line: str) -> bool:
    value = (line or "").strip()
    if not value:
        return False
    if re.fullmatch(
        r"(?:学生)?(?:课程表|课表|课程清单|课程列表|教学安排|上课安排|作息时间表?)",
        value,
    ):
        return True
    if re.search(
        r"(?:课程表|课表|课程清单|课程列表|教学安排|上课安排)$", value
    ) and len(value) <= 48:
        return True
    if re.match(r"^\s*\d{4}\s*[-—~至]?\s*\d{0,4}\s*.*(?:学年|学期)", value):
        return True
    return False

_NON_NAME_PARENTHETICAL = {
    "篮球",
    "足球",
    "排球",
    "羽毛球",
    "乒乓球",
    "网球",
    "健美操",
    "瑜伽",
    "游泳",
    "武术",
    "跆拳道",
    "舞蹈",
    "声乐",
    "器乐",
    "绘画",
    "书法",
    "编程",
    "实验",
    "实践",
    "上机",
    "必修",
    "选修",
    "限选",
    "任选",
    "公选",
    "理论",
    "听力",
    "口语",
    "写作",
    "阅读",
}


def _strip_label(text: str, labels: Iterable[str]) -> str:
    pattern = "|".join(re.escape(label) for label in labels)
    return re.sub(
        rf"^\s*(?:{pattern})\s*[:：]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


def extract_labeled_value(text: str, labels: Iterable[str]) -> str:
    if not text:
        return ""
    pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{pattern})\s*[:：]\s*([^\n;；|]+)",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(" \t:：,，;；")
    return ""


def extract_credits(text: str) -> float | None:
    match = _CREDITS_RE.search(text or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _looks_like_person_name(line: str) -> bool:
    candidate = re.sub(r"\s+", "", line)
    candidate = re.sub(r"[（(].*?[）)]", "", candidate)
    candidate = candidate.strip(" ·.")
    if not re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", candidate):
        return False
    if candidate in {"必修", "选修", "限选", "任选", "公选", "实践", "理论"}:
        return False
    if candidate in {"教授", "副教授", "讲师", "助教", "老师", "教师", "博士", "硕士"}:
        return False
    if candidate in {
        "上册",
        "下册",
        "实验",
        "理论",
        "概论",
        "导论",
        "基础",
        "专题",
        "讲座",
        "研讨",
        "上机",
        "实训",
    }:
        return False
    if any(keyword in candidate for keyword in _COURSE_KEYWORDS):
        return False
    if _ROOM_HINT_RE.search(candidate):
        return False
    return True


def _looks_like_sentence(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    if re.search(r"[，。；！？]", value):
        return True
    return value.startswith(("以下", "下面", "本课程", "说明", "注意", "提示", "请"))


def _is_temporal_noise(text: str) -> bool:
    """Remove dates / times / week labels from the text stream.

    A bare ``1-2`` must survive because it is a valid period expression.
    """

    value = (text or "").strip()
    if not value:
        return False
    if re.fullmatch(r"\d{4}\s*[-/.]\s*\d{1,2}(?:\s*[-/.]\s*\d{1,2})?", value):
        return True
    if re.fullmatch(r"\d{1,2}\s*/\s*\d{1,2}(?:\s*/\s*\d{1,2})?", value):
        return True
    if re.fullmatch(r"\d{1,2}\s*\.\s*\d{1,2}(?:\s*\.\s*\d{1,2})?", value):
        return True
    if re.fullmatch(r"(?:第\s*)?\d{1,2}\s*周", value):
        return True
    return bool(re.fullmatch(r"共\s*\d+\s*周", value))


def _is_noise_token(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return True
    if value.startswith("本地") and len(value) > 10:
        return True
    if re.fullmatch(r"[\d\s/:：\-~—.]+", value):
        return True
    if re.fullmatch(r"第?\s*\d{1,2}\s*周", value):
        return True
    if re.fullmatch(r"\d{1,2}/\d{1,2}(?:\s*[（(]?[一二三四五六日天][）)]?)?", value):
        return True
    if re.fullmatch(r"\d{1,2}:\d{2}\s*[-~—]\s*\d{1,2}:?\d{2}", value):
        return True
    return False


def _looks_like_meta_line(line: str) -> bool:
    """Detect a line such as ``张三 · 教A101`` from a grid cell."""

    match = re.match(r"^([\u4e00-\u9fa5]{2,4})\s*[·•|｜]\s*(.+)$", (line or "").strip())
    if not match:
        return False
    tail = match.group(2)
    return bool(_ROOM_RE.search(tail) or re.search(r"\d{2,4}", tail))


def _looks_like_course_name(line: str) -> bool:
    candidate = line.strip()
    if len(candidate) < 2 or len(candidate) > 80:
        return False
    if (
        candidate in _GENERIC_HEADERS
        or _is_title_line(candidate)
        or _is_noise_token(candidate)
        or _looks_like_meta_line(candidate)
    ):
        return False
    if _looks_like_sentence(candidate):
        return False
    if _is_field_only_line(candidate):
        return False
    if _looks_like_person_name(candidate):
        return False
    if _ROOM_RE.fullmatch(candidate.strip()):
        return False
    if any(keyword in candidate for keyword in _COURSE_KEYWORDS):
        return True
    if re.search(r"[\u4e00-\u9fa5]{4,}", candidate):
        return True
    if re.search(r"[A-Za-z]{3,}", candidate):
        return True
    return False


def _is_field_only_line(line: str) -> bool:
    value = line.strip()
    if not value:
        return True
    if value in _GENERIC_HEADERS:
        return True
    patterns = (
        r"^(?:周|星期|礼拜)\s*[一二三四五六日天1-7]",
        r"^第?\s*\d{1,2}\s*(?:-|至|到)\s*\d{1,2}\s*节",
        r"^第?\s*\d{1,2}\s*节",
        r"^\d{1,2}\s*[:：]\s*\d{2}\s*(?:-|至|到)",
        r"^\d+(?:\.\d+)?\s*学分",
        r"^(?:教师|老师|任课教师|授课教师|教室|地点|上课地点|"
        r"周次|起止周|备注|班级|学号|姓名)\s*[:：]",
        r"^第?\s*\d{1,2}\s*(?:-|至|到)\s*\d{1,2}\s*周",
        r"^[（(]?(?:必修|选修|限选|任选|公选|实践|理论)[）)]?$",
        r"^[\d\s.,，、\-~至到]+$",
    )
    return any(re.match(pattern, value) for pattern in patterns)


def clean_course_name(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"^\s*(?:\d{1,2}[.、)]|[-*•●])\s*", "", text)
    text = re.sub(r"^[【\[]\s*", "", text)
    text = re.sub(r"\s*[】\]]$", "", text)
    text = _strip_label(text, _NAME_LABELS)
    text = re.sub(r"^(?:课程|科目)\s*[:：]\s*", "", text)
    text = text.strip(" \t:：,，;；|/")
    return text


def _suffix_course_name(line: str) -> tuple[str, str]:
    """Parse the name from ``周一 下午5/6节 诚意楼415 自控系统``.

    In this format the course name is *after* the weekday/time/classroom.
    """

    spans = _weekday_spans(line)
    if not spans:
        return "", ""
    rest = line[spans[0][1] :].strip()
    if not rest:
        return "", ""
    rest = _TIME_OF_DAY_RE.sub("", rest)
    for pattern in (
        _PERIOD_SLASH_RE,
        _PERIOD_RANGE_RE,
        _PERIOD_COLON_RE,
        _PERIOD_LIST_RE,
        _PERIOD_SINGLE_RE,
        _TIME_RANGE_RE,
        _WEEK_EXPR_RE,
    ):
        rest = pattern.sub(" ", rest)
    for pattern in (_ROOM_RE, _NAMED_ROOM_RE):
        match = pattern.search(rest)
        if match:
            rest = rest[: match.start()] + " " + rest[match.end() :]
            break
    rest = re.sub(
        r"(?:任课教师|授课教师|主讲教师|教师|老师)\s*[:：]?\s*[^\s,，;；|]+",
        " ",
        rest,
    )
    rest = re.sub(r"\s+", " ", rest).strip(" \t:：,，;；|")
    if not rest:
        return "", ""
    name, teacher = split_name_and_teacher(rest)
    if not name:
        return "", ""
    if (
        _is_field_only_line(name)
        or _looks_like_sentence(name)
        or _is_noise_token(name)
        or _looks_like_meta_line(name)
    ):
        return "", ""
    return name, teacher


def _suffix_name_from_lines(lines: Sequence[str]) -> tuple[str, str]:
    for line in lines:
        if not _weekday_spans(line):
            continue
        if not (parse_period_slots(line) or _TIME_RANGE_RE.search(line)):
            continue
        name, teacher = _suffix_course_name(line)
        if name:
            return name, teacher
    return "", ""


def extract_course_name(lines: Sequence[str], full_text: str = "") -> str:
    labeled = extract_labeled_value(full_text or "\n".join(lines), _NAME_LABELS)
    if labeled:
        return clean_course_name(labeled)

    for line in lines:
        candidate = clean_course_name(line)
        if not candidate:
            continue
        if candidate in _GENERIC_HEADERS or _is_title_line(candidate):
            continue
        if _is_noise_token(candidate) or _looks_like_sentence(candidate):
            continue
        if _looks_like_meta_line(candidate):
            continue
        if _is_field_only_line(candidate):
            continue
        # If the line also contains a weekday, use the part before it.
        spans = _weekday_spans(candidate)
        if spans:
            candidate = clean_course_name(candidate[: spans[0][0]])
            if not candidate or _is_field_only_line(candidate):
                continue
        if not _looks_like_course_name(candidate):
            continue
        # A short person-like line before a later time line is a teacher.
        if _looks_like_person_name(candidate):
            continue
        return candidate

    # The common "周X + 时间 + 教室 + 课程名" layout puts the name last.
    suffix_name, _suffix_teacher = _suffix_name_from_lines(lines)
    if suffix_name:
        return suffix_name

    # Last resort: remove obvious fields and take the first meaningful chunk.
    fallback = clean_course_name(full_text or "")
    fallback = re.sub(_WEEK_EXPR_RE, " ", fallback)
    fallback = _PERIOD_SLASH_RE.sub(" ", fallback)
    fallback = _PERIOD_RANGE_RE.sub(" ", fallback)
    fallback = _PERIOD_SINGLE_RE.sub(" ", fallback)
    fallback = _TIME_RANGE_RE.sub(" ", fallback)
    fallback = re.sub(r"\s+", " ", fallback).strip(" \t:：,，;；|")
    if _looks_like_sentence(fallback) or _is_title_line(fallback) or _is_noise_token(fallback):
        return ""
    return fallback[:80]


def split_name_and_teacher(text: str) -> tuple[str, str]:
    value = clean_course_name(text)
    if not value:
        return "", ""
    labeled_teacher = extract_labeled_value(value, _TEACHER_LABELS)
    if labeled_teacher:
        value = re.sub(
            r"(?:任课教师|授课教师|主讲教师|教师|老师)\s*[:：].*$", "", value
        ).strip()
        return clean_course_name(value), labeled_teacher

    # "高等数学 张三" / "高等数学（张三）"
    parenthetical = re.search(r"[（(]\s*([\u4e00-\u9fa5]{2,4})\s*[）)]\s*$", value)
    if (
        parenthetical
        and parenthetical.group(1) not in _NON_NAME_PARENTHETICAL
        and _looks_like_person_name(parenthetical.group(1))
    ):
        return clean_course_name(value[: parenthetical.start()]), parenthetical.group(1)

    tokens = value.split()
    if len(tokens) >= 2 and _looks_like_person_name(tokens[-1]):
        return clean_course_name(" ".join(tokens[:-1])), tokens[-1]
    return value, ""


def extract_teacher(text: str, lines: Sequence[str] = ()) -> str:
    labeled = extract_labeled_value(text, _TEACHER_LABELS)
    if labeled:
        return labeled.strip(" \t:：,，;；")
    match = re.search(r"([\u4e00-\u9fa5]{2,4})\s*(?:老师|教师)", text or "")
    if match:
        return match.group(1)
    # Grid cells are often exported as "张三 · 教A101".
    match = re.search(r"(?:^|\n)\s*([\u4e00-\u9fa5]{2,4})\s*[·•|｜]\s*", text or "")
    if match:
        return match.group(1)

    # One-line records carry the teacher in the prefix before the weekday:
    # "高等数学A 张三 周一 1-2节".
    spans = _weekday_spans(text or "")
    if spans:
        prefix = (text or "")[: spans[0][0]].strip()
        _, prefix_teacher = split_name_and_teacher(prefix)
        if prefix_teacher:
            return prefix_teacher

    # A standalone short Chinese name between the course name and a time line.
    lines = list(lines)
    for line in lines:
        if not _weekday_spans(line):
            continue
        if not (parse_period_slots(line) or _TIME_RANGE_RE.search(line)):
            continue
        _suffix_name, suffix_teacher = _suffix_course_name(line)
        if suffix_teacher:
            return suffix_teacher
    time_indexes = [
        index
        for index, line in enumerate(lines)
        if _weekday_spans(line) or parse_period_slots(line) or _TIME_RANGE_RE.search(line)
    ]
    first_time = min(time_indexes) if time_indexes else len(lines)
    for index in range(1, first_time):
        candidate = lines[index].strip()
        if _looks_like_person_name(candidate):
            return candidate
    return ""


def extract_classroom(text: str, lines: Sequence[str] = ()) -> str:
    labeled = extract_labeled_value(text, _CLASSROOM_LABELS)
    if labeled:
        return labeled.strip(" \t:：,，;；|")
    match = _ROOM_RE.search(text or "")
    if match:
        room = match.group("room").strip()
        # Avoid treating a course name such as "大学英语" as a building.
        if room and not any(keyword in room for keyword in ("大学", "课程", "学院")):
            return room
    named = _NAMED_ROOM_RE.search(text or "")
    if named:
        room = named.group("room").strip()
        if room and not any(keyword in room for keyword in ("大学", "课程", "学院")):
            return room
    for line in lines:
        stripped = line.strip()
        if re.fullmatch(r"[A-Za-z]?\d{3,4}[A-Za-z]?", stripped):
            return stripped
        if (
            2 <= len(stripped) <= 20
            and _ROOM_HINT_RE.search(stripped)
            and not _weekday_spans(stripped)
            and not parse_period_slots(stripped)
            and not _TIME_RANGE_RE.search(stripped)
        ):
            return stripped
    return ""


def extract_class_name(text: str) -> str:
    return extract_labeled_value(text, _CLASS_LABELS)


def extract_note(text: str) -> str:
    return extract_labeled_value(text, _NOTE_LABELS)


# ---------------------------------------------------------------------------
# Text segmentation
# ---------------------------------------------------------------------------


def split_blocks(lines: Sequence[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    return blocks or ([list(lines)] if lines else [])


def _split_course_units(lines: Sequence[str]) -> list[list[str]]:
    """Split a block that contains several multi-line course records."""

    if len(lines) <= 2:
        return [list(lines)]
    units: list[list[str]] = []
    current: list[str] = []
    seen_time = False
    for line in lines:
        has_time = bool(
            _weekday_spans(line) or parse_period_slots(line) or _TIME_RANGE_RE.search(line)
        )
        if (
            current
            and seen_time
            and not has_time
            and not _is_field_only_line(line)
            and _looks_like_course_name(line)
            and (
                _weekday_spans(current[-1])
                or parse_period_slots(current[-1])
                or _TIME_RANGE_RE.search(current[-1])
                or _ROOM_RE.search(current[-1])
                or _WEEK_EXPR_RE.search(current[-1])
            )
        ):
            units.append(current)
            current = []
            seen_time = False
        current.append(line)
        if has_time:
            seen_time = True
    if current:
        units.append(current)
    return units if len(units) > 1 else [list(lines)]


def split_time_groups(
    lines: Sequence[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Group lines around weekday tokens.

    Returns ``(preamble_lines, groups)`` where each group has ``text`` and
    ``weekdays``.  A group keeps the following non-time lines (weeks, room,
    etc.) attached to it.
    """

    groups: list[dict[str, Any]] = []
    preamble: list[str] = []
    current: dict[str, Any] | None = None
    for line in lines:
        spans = _weekday_spans(line)
        if not spans:
            if current is not None:
                current["lines"].append(line)
            else:
                preamble.append(line)
            continue
        for index, (start, _end, days) in enumerate(spans):
            segment_start = 0 if index == 0 else start
            segment_end = spans[index + 1][0] if index + 1 < len(spans) else len(line)
            segment = line[segment_start:segment_end].strip()
            if not segment:
                continue
            group = {"lines": [segment], "weekdays": list(days)}
            groups.append(group)
            current = group
    for group in groups:
        group["text"] = "\n".join(group["lines"])
    return preamble, groups


def _line_oriented(lines: Sequence[str]) -> bool:
    complete = 0
    weekday_lines = 0
    for line in lines:
        spans = _weekday_spans(line)
        if not spans:
            continue
        weekday_lines += 1
        prefix = line[: spans[0][0]].strip()
        if prefix and (
            parse_period_slots(line)
            or _TIME_RANGE_RE.search(line)
            or _WEEK_EXPR_RE.search(line)
        ):
            complete += 1
    return complete >= 2 and complete >= max(2, weekday_lines // 2 + 1)


# ---------------------------------------------------------------------------
# Free-text parser
# ---------------------------------------------------------------------------


def parse_text(text: str, template: Template, source: str = "") -> ParseOutcome:
    normalized = normalize_text(text)
    outcome = ParseOutcome()
    if not normalized:
        outcome.issues.append("输入内容为空。")
        return outcome

    raw_lines = normalized.split("\n")
    filtered_lines: list[str] = []
    for line in raw_lines:
        stripped = line.strip()
        if stripped and (
            stripped.startswith("=====")
            or (stripped.startswith("【") and stripped.endswith("】"))
        ):
            continue
        if stripped and (
            _is_header_text(line) or _is_temporal_noise(line) or _is_title_line(line)
        ):
            continue
        filtered_lines.append(line)

    # OCR often emits the weekday header as separate "周一"/"周二" lines.
    first_period = next(
        (
            index
            for index, line in enumerate(filtered_lines)
            if line.strip()
            and (parse_period_slots(line) or _TIME_RANGE_RE.search(line))
        ),
        len(filtered_lines),
    )
    weekday_only = [
        index
        for index in range(first_period)
        if re.fullmatch(r"(?:周|星期|礼拜)\s*[一二三四五六日天1-7]", filtered_lines[index].strip())
    ]
    if len(weekday_only) >= 3:
        drop = set(weekday_only)
        filtered_lines = [
            line for index, line in enumerate(filtered_lines) if index not in drop
        ]

    lines = [line for line in filtered_lines if line.strip()]
    if not lines:
        outcome.issues.append("输入内容为空。")
        return outcome

    blocks = split_blocks(filtered_lines)
    for block in blocks:
        block = [line for line in block if line.strip()]
        if not block:
            continue
        if _line_oriented(block):
            units = [[line] for line in block if _weekday_spans(line)]
        else:
            units = _split_course_units(block)
        for unit in units:
            unit_outcome = _parse_block(unit, template, source)
            outcome.extend(unit_outcome)
            if not unit_outcome.courses:
                outcome.unparsed.extend(unit)

    outcome.courses = dedupe_courses(outcome.courses)
    outcome.courses = merge_adjacent_slots(outcome.courses)
    if not outcome.courses:
        outcome.issues.append("未识别到课程。请尝试表格格式、检查时间/星期写法，或手动添加。")
    outcome.issues = list(dict.fromkeys(outcome.issues))
    outcome.unparsed = list(dict.fromkeys(outcome.unparsed))[:100]
    return outcome


def _is_header_text(text: str) -> bool:
    """Detect a timetable header row such as ``节次 周一 周二 ...``."""

    value = text or ""
    if re.search(r"节次\s*[/／]?\s*时间", value):
        return True
    if len(re.findall(r"\d{1,2}/\d{1,2}", value)) >= 2 and len(parse_weekdays(value)) >= 2:
        return True
    if (
        re.search(r"共\s*\d+\s*周|第\s*\d+\s*周", value)
        and len(parse_weekdays(value)) >= 2
    ):
        return True
    return len(parse_weekdays(value)) >= 2 and bool(
        re.search(r"节次|星期|时间|课程表|课表", value)
    )


def _parse_block(lines: Sequence[str], template: Template, source: str) -> ParseOutcome:
    expanded: list[str] = []
    for line in lines:
        for part in re.split(r"[;；|]", line):
            part = part.strip()
            if part:
                expanded.append(part)
    lines = expanded
    if not lines:
        return ParseOutcome()
    block_text = "\n".join(lines)
    outcome = ParseOutcome()
    if _is_header_text(block_text) and not parse_period_slots(block_text):
        return outcome

    name = extract_course_name(lines, block_text)
    name, name_teacher = split_name_and_teacher(name)
    teacher = extract_teacher(block_text, lines) or name_teacher
    classroom = extract_classroom(block_text, lines)
    credits = extract_credits(block_text)
    class_name = extract_class_name(block_text)
    note = extract_note(block_text)
    base_weeks, base_type, base_week_expr = parse_weeks(block_text)
    base_slots = parse_period_slots(block_text) or parse_time_slots(block_text, template)

    preamble, groups = split_time_groups(lines)
    if not groups:
        if name:
            course = Course(
                name=name,
                teacher=teacher,
                classroom=classroom,
                weeks=base_weeks,
                week_type=base_type,
                week_expr=base_week_expr,
                credits=credits,
                class_name=class_name,
                note=note,
                source=source,
                raw=block_text,
            )
            course.add_issue("未识别上课星期/节次，已放入待安排")
            if not base_weeks and base_type == "all":
                course.add_issue("未识别周次，按全周处理")
            outcome.courses.append(course)
        return outcome

    for group in groups:
        group_text = str(group.get("text", ""))
        group_lines = list(group.get("lines", []))
        weekdays = list(group.get("weekdays") or parse_weekdays(group_text))
        slots = parse_period_slots(group_text) or parse_time_slots(group_text, template)
        if not slots:
            slots = base_slots
        weeks, week_type, week_expr = parse_weeks(group_text)
        if not weeks and week_type == "all" and not week_expr:
            weeks, week_type, week_expr = base_weeks, base_type, base_week_expr

        group_name = _group_course_name(group_text, name)
        group_teacher = extract_teacher(group_text, group_lines) or teacher
        group_classroom = extract_classroom(group_text, group_lines) or classroom
        group_credits = extract_credits(group_text) or credits
        group_class = extract_class_name(group_text) or class_name
        group_note = extract_note(group_text) or note

        if not weekdays:
            weekdays = [None]  # type: ignore[list-item]
        for weekday in weekdays:
            if slots:
                for start, end in slots:
                    course = Course(
                        name=group_name or name,
                        teacher=group_teacher,
                        classroom=group_classroom,
                        weekday=weekday,
                        start_period=start,
                        end_period=end,
                        weeks=weeks,
                        week_type=week_type,
                        week_expr=week_expr,
                        credits=group_credits,
                        class_name=group_class,
                        note=group_note,
                        source=source,
                        raw=block_text,
                    )
                    _add_course_issues(course, total_weeks=template.total_weeks)
                    outcome.courses.append(course)
            else:
                course = Course(
                    name=group_name or name,
                    teacher=group_teacher,
                    classroom=group_classroom,
                    weekday=weekday,
                    weeks=weeks,
                    week_type=week_type,
                    week_expr=week_expr,
                    credits=group_credits,
                    class_name=group_class,
                    note=group_note,
                    source=source,
                    raw=block_text,
                )
                course.add_issue("未识别具体节次，已放入待安排")
                _add_course_issues(course, total_weeks=template.total_weeks)
                outcome.courses.append(course)

    return outcome


def _group_course_name(group_text: str, fallback: str) -> str:
    spans = _weekday_spans(group_text)
    if not spans:
        return fallback
    prefix = group_text[: spans[0][0]].strip()
    if prefix:
        candidate, _teacher = split_name_and_teacher(prefix)
        if (
            candidate
            and not _is_field_only_line(candidate)
            and _looks_like_course_name(candidate)
        ):
            return candidate
    # "周一 5/6节 诚意楼415 自控系统" puts the name after the room.
    suffix_name, _suffix_teacher = _suffix_course_name(group_text)
    if suffix_name:
        return suffix_name
    return fallback


def _add_course_issues(course: Course, total_weeks: int) -> None:
    if not course.name or course.name == "未命名课程":
        course.add_issue("缺少课程名称")
    if not course.weekday:
        course.add_issue("未识别上课星期")
    if not course.start_period or not course.end_period:
        course.add_issue("未识别节次")
    elif course.end_period > MAX_PERIODS:
        course.add_issue("节次超出常见范围，请核对")
    if not course.weeks and course.week_type == "all":
        course.add_issue("未识别周次，按全周处理")
    if not course.scheduled:
        course.add_issue("尚未排入课表")


# ---------------------------------------------------------------------------
# Table parser
# ---------------------------------------------------------------------------

_HEADER_FIELDS: dict[str, tuple[str, ...]] = {
    "name": ("课程名称", "课程名", "教学班名称", "课程", "科目", "课程/环节"),
    "teacher": ("任课教师", "授课教师", "主讲教师", "教师", "老师"),
    "classroom": ("上课地点", "上课教室", "教室", "地点", "场地", "教学地点"),
    "weekday": ("上课星期", "星期", "周几", "星期几"),
    "periods": ("上课节次", "节次", "课节", "节"),
    "weeks": ("上课周次", "周次", "起止周", "教学周", "周数"),
    "time": ("上课时间", "课程时间", "时间"),
    "credits": ("学分",),
    "class_name": ("教学班", "上课班级", "行政班", "班级"),
    "note": ("备注", "说明"),
    "code": ("课程代码", "课程编号", "课程号", "序号"),
}


def _normalized_header(value: str) -> str:
    value = normalize_cell(value)
    value = re.sub(r"[\s\n\r（()）:：]", "", value)
    return value


def _header_field(value: str) -> str | None:
    header = _normalized_header(value)
    if not header:
        return None
    if header in {"课程名称", "课程名", "教学班名称", "课程", "科目", "课程/环节"}:
        return "name"
    if "课程代码" in header or "课程编号" in header or "课程号" in header or "序号" in header:
        return "code"
    if "上课时间" in header or "课程时间" in header or header == "时间":
        return "time"
    if "星期" in header or "周几" in header:
        return "weekday"
    if "节次" in header or "课节" in header or header == "节":
        return "periods"
    if "周次" in header or "起止周" in header or "教学周" in header or "周数" in header:
        return "weeks"
    if "学分" in header:
        return "credits"
    if "教室" in header or "地点" in header or "场地" in header:
        return "classroom"
    if "教师" in header or "老师" in header or "主讲" in header:
        return "teacher"
    if "班级" in header or "教学班" in header:
        return "class_name"
    if "备注" in header or "说明" in header:
        return "note"
    return None


def _trim_matrix(rows: Sequence[Sequence[str]]) -> list[list[str]]:
    matrix = [[normalize_cell(cell) for cell in row] for row in rows]
    while matrix and all(not cell for cell in matrix[0]):
        matrix.pop(0)
    while matrix and all(not cell for cell in matrix[-1]):
        matrix.pop()
    if not matrix:
        return []
    width = max(len(row) for row in matrix)
    for row in matrix:
        row.extend([""] * (width - len(row)))
    # Remove fully empty leading/trailing columns.
    while width and all(not row[column] for row in matrix for column in (0,)):
        matrix = [row[1:] for row in matrix]
        width -= 1
    while width and all(not row[width - 1] for row in matrix):
        matrix = [row[: width - 1] for row in matrix]
        width -= 1
    return matrix


def _find_header(
    matrix: Sequence[Sequence[str]],
) -> tuple[int, dict[int, str]] | None:
    best: tuple[int, dict[int, str]] | None = None
    best_score = 0
    for row_index, row in enumerate(matrix[:15]):
        mapping: dict[int, str] = {}
        for column, cell in enumerate(row):
            field_name = _header_field(cell)
            if field_name and field_name not in mapping.values():
                mapping[column] = field_name
        if len(mapping) < 2:
            continue
        if not {"name", "time", "weekday", "periods"} & set(mapping.values()):
            continue
        score = len(mapping)
        if "name" in mapping.values():
            score += 3
        if "time" in mapping.values():
            score += 2
        if score > best_score:
            best_score = score
            best = (row_index, mapping)
    return best


def _cell(row: Sequence[str], column: int | None) -> str:
    if column is None or column >= len(row):
        return ""
    return row[column].strip()


def _parse_table_impl(
    table: TableData | Sequence[Sequence[str]],
    template: Template,
    source: str = "",
) -> ParseOutcome:
    rows = table.rows if isinstance(table, TableData) else table
    matrix = _trim_matrix(rows)
    if not matrix:
        return ParseOutcome(issues=["表格为空。"])
    table_source = source or (table.source if isinstance(table, TableData) else "")

    header = _find_header(matrix)
    if header:
        header_row, mapping = header
        outcome = _parse_course_list_table(matrix, header_row, mapping, template, table_source)
        if outcome.courses:
            return outcome

    grid = _parse_grid_table(matrix, template, table_source)
    if grid.courses:
        return grid

    # A transposed grid (weekdays down the first column) is common in Word.
    transposed = [list(row) for row in zip(*matrix)]
    grid = _parse_grid_table(transposed, template, table_source + "（转置）")
    if grid.courses:
        return grid

    key_value = _parse_key_value_table(matrix, template, table_source)
    if key_value.courses:
        return key_value

    text = "\n".join(" ".join(cell for cell in row if cell) for row in matrix)
    outcome = parse_text(text, template, table_source)
    if not outcome.courses:
        outcome.issues.append("表格未匹配到课程列或星期/节次网格。")
    return outcome


def parse_table(
    table: TableData | Sequence[Sequence[str]],
    template: Template,
    source: str = "",
) -> ParseOutcome:
    """Parse one table and merge duplicated/adjacent cells."""

    outcome = _parse_table_impl(table, template, source)
    outcome.courses = dedupe_courses(merge_adjacent_slots(outcome.courses))
    outcome.issues = list(dict.fromkeys(outcome.issues))
    return outcome


def parse_tables(
    tables: Sequence[TableData], template: Template, source: str = ""
) -> ParseOutcome:
    outcome = ParseOutcome()
    for index, table in enumerate(tables):
        table_source = table.source or f"{source} 表格{index + 1}"
        parsed = parse_table(table, template, table_source)
        outcome.extend(parsed)
    outcome.courses = dedupe_courses(merge_adjacent_slots(outcome.courses))
    outcome.issues = list(dict.fromkeys(outcome.issues))
    return outcome


def _parse_course_list_table(
    matrix: Sequence[Sequence[str]],
    header_row: int,
    mapping: dict[int, str],
    template: Template,
    source: str,
) -> ParseOutcome:
    outcome = ParseOutcome()
    column_of = {field: column for column, field in mapping.items()}
    last_values: dict[str, str] = {}

    for row_index in range(header_row + 1, len(matrix)):
        row = matrix[row_index]
        if not any(cell.strip() for cell in row):
            continue
        if _find_header([row]):
            continue

        def value(field: str) -> str:
            return _cell(row, column_of.get(field))

        name_cell = value("name")
        if name_cell and _normalized_header(name_cell) in _GENERIC_HEADERS:
            continue
        if name_cell and re.fullmatch(r"[\d\s.,，、\-]+", name_cell):
            continue

        name = name_cell or last_values.get("name", "")
        teacher = value("teacher") or last_values.get("teacher", "")
        classroom = value("classroom") or last_values.get("classroom", "")
        credits_text = value("credits") or last_values.get("credits", "")
        class_name = value("class_name") or last_values.get("class_name", "")
        note = value("note") or last_values.get("note", "")
        credits = None
        if credits_text:
            try:
                credits = float(re.search(r"\d+(?:\.\d+)?", credits_text).group(0))
            except (AttributeError, ValueError):
                credits = None

        if name_cell:
            last_values["name"] = name_cell
        if teacher:
            last_values["teacher"] = teacher
        if classroom:
            last_values["classroom"] = classroom
        if credits_text:
            last_values["credits"] = credits_text
        if class_name:
            last_values["class_name"] = class_name

        if not name:
            continue

        # If the name cell contains embedded time information, parse it and
        # merge the explicit columns as defaults.
        if (
            _weekday_spans(name_cell)
            or parse_period_slots(name_cell)
            or _TIME_RANGE_RE.search(name_cell)
        ):
            embedded = _parse_block(name_cell.splitlines(), template, source)
            for course in embedded.courses:
                course.teacher = course.teacher or teacher
                course.classroom = course.classroom or classroom
                course.credits = course.credits or credits
                course.class_name = course.class_name or class_name
                course.note = course.note or note
                outcome.courses.append(course)
            continue

        time_text = value("time")
        weekday_text = value("weekday")
        period_text = value("periods")
        weeks_text = value("weeks")

        records = _records_from_fields(
            time_text=time_text,
            weekday_text=weekday_text,
            period_text=period_text,
            weeks_text=weeks_text,
            template=template,
        )
        if not records:
            # The row may put the full time expression into a generic column.
            fallback_text = " ".join(
                part for part in (time_text, weekday_text, period_text, weeks_text) if part
            )
            if fallback_text:
                records = _records_from_fields(
                    time_text=fallback_text,
                    weekday_text="",
                    period_text="",
                    weeks_text="",
                    template=template,
                )

        if not records:
            course = Course(
                name=name,
                teacher=teacher,
                classroom=classroom,
                credits=credits,
                class_name=class_name,
                note=note,
                source=source,
                raw=" | ".join(row),
            )
            course.add_issue("未识别上课星期/节次，已放入待安排")
            if not weeks_text:
                course.add_issue("未识别周次，按全周处理")
            outcome.courses.append(course)
            continue

        for record in records:
            weekday, start, end, weeks, week_type, week_expr = record
            course = Course(
                name=name,
                teacher=teacher,
                classroom=classroom,
                weekday=weekday,
                start_period=start,
                end_period=end,
                weeks=weeks,
                week_type=week_type,
                week_expr=week_expr,
                credits=credits,
                class_name=class_name,
                note=note,
                source=source,
                raw=" | ".join(row),
            )
            _add_course_issues(course, total_weeks=template.total_weeks)
            outcome.courses.append(course)
    return outcome


def _records_from_fields(
    time_text: str,
    weekday_text: str,
    period_text: str,
    weeks_text: str,
    template: Template,
) -> list[tuple[Any, Any, Any, list[int], str, str]]:
    """Combine separate weekday / period / time / week columns."""

    records: list[tuple[Any, Any, Any, list[int], str, str]] = []
    weeks, week_type, week_expr = parse_weeks(weeks_text, assume_weeks=True)
    if not weeks and week_type == "all":
        # A "1-16" cell without the character 周.
        bare = _BARE_WEEK_EXPR_RE.fullmatch(normalize_text(weeks_text))
        if bare:
            weeks = _parse_week_expression(bare.group(1))
            week_expr = compress_week_expr(weeks)

    weekday_days = parse_weekdays(weekday_text)
    period_slots = parse_period_slots(period_text) or parse_time_slots(
        period_text, template
    )

    clauses = [time_text] if time_text else []
    if time_text and re.search(r"[;；\n]", time_text):
        clauses = [part for part in re.split(r"[;；\n]+", time_text) if part.strip()]
    if not clauses and (weekday_text or period_text):
        clauses = [""]

    for clause in clauses:
        clause_weekdays = parse_weekdays(clause) or weekday_days
        clause_slots = parse_period_slots(clause) or parse_time_slots(clause, template)
        if not clause_slots:
            clause_slots = period_slots
        clause_weeks, clause_type, clause_expr = parse_weeks(clause)
        if not clause_weeks and clause_type == "all" and not clause_expr:
            clause_weeks, clause_type, clause_expr = weeks, week_type, week_expr
        if not clause_weekdays:
            clause_weekdays = [None]
        if not clause_slots:
            clause_slots = [(None, None)]
        for weekday in clause_weekdays:
            for start, end in clause_slots:
                records.append(
                    (
                        weekday,
                        start,
                        end,
                        clause_weeks,
                        clause_type,
                        clause_expr,
                    )
                )
    return records


def compress_week_expr(weeks: Sequence[int]) -> str:
    if not weeks:
        return ""
    numbers = sorted(set(weeks))
    parts: list[str] = []
    start = prev = numbers[0]
    for number in numbers[1:]:
        if number == prev + 1:
            prev = number
        else:
            parts.append(str(start) if start == prev else f"{start}-{prev}")
            start = prev = number
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(parts) + "周"


def _parse_grid_table(
    matrix: Sequence[Sequence[str]], template: Template, source: str
) -> ParseOutcome:
    outcome = ParseOutcome()
    header_row = -1
    weekday_columns: dict[int, int] = {}
    for row_index, row in enumerate(matrix[:15]):
        found: dict[int, int] = {}
        for column, cell in enumerate(row):
            days = parse_weekdays(cell)
            if len(days) == 1:
                found[column] = days[0]
        if len(found) >= 2:
            header_row = row_index
            weekday_columns = found
            break
    if header_row < 0 or len(weekday_columns) < 2:
        return outcome

    first_weekday_column = min(weekday_columns)
    for row_index in range(header_row + 1, len(matrix)):
        row = matrix[row_index]
        if not any(cell.strip() for cell in row):
            continue
        period_text = " ".join(
            cell for cell in row[:first_weekday_column] if cell.strip()
        )
        slots = parse_period_slots(period_text) or parse_time_slots(period_text, template)
        if not slots:
            # Some grids put the period label in the first weekday column of a
            # preceding "上午/下午" row; skip those group headers.
            continue
        for column, weekday in weekday_columns.items():
            cell_text = _cell(row, column)
            if not cell_text:
                continue
            courses = _parse_grid_cell(cell_text, template, source)
            for course in courses:
                if course.weekday is None:
                    course.weekday = weekday
                if course.start_period is None:
                    course.start_period, course.end_period = slots[0]
                if not course.weeks and course.week_type == "all":
                    course.add_issue("未识别周次，按全周处理")
                _add_course_issues(course, total_weeks=template.total_weeks)
                outcome.courses.append(course)
    return outcome


def _parse_grid_cell(cell_text: str, template: Template, source: str) -> list[Course]:
    if _is_header_text(cell_text):
        return []
    # Multiple independent records in one cell are usually separated by blank
    # lines or horizontal rules.
    chunks = [
        chunk
        for chunk in re.split(r"\n\s*\n|(?:\n\s*[-—_]{3,}\s*\n)", cell_text)
        if chunk.strip()
    ]
    if len(chunks) == 1:
        chunks = [cell_text]
    courses: list[Course] = []
    for chunk in chunks:
        parsed = _parse_block(chunk.splitlines(), template, source)
        if parsed.courses:
            courses.extend(parsed.courses)
        else:
            # A single line such as "高等数学 张三 A101".
            course = Course(
                name=extract_course_name(chunk.splitlines(), chunk),
                teacher=extract_teacher(chunk, chunk.splitlines()),
                classroom=extract_classroom(chunk, chunk.splitlines()),
                source=source,
                raw=chunk,
            )
            if course.name and not _is_noise_token(course.name) and not _is_header_text(chunk):
                course.add_issue("未识别周次，按全周处理")
                courses.append(course)
    return courses


def _parse_key_value_table(
    matrix: Sequence[Sequence[str]], template: Template, source: str
) -> ParseOutcome:
    outcome = ParseOutcome()

    # Transposed key/value table: first row is "课程名称 | 高数 | 英语 | ...".
    for row in matrix:
        if not row:
            continue
        if _header_field(row[0]) == "name":
            name_columns = [
                column for column in range(1, len(row)) if row[column].strip()
            ]
            if len(name_columns) >= 2:
                for column in name_columns:
                    values: dict[str, str] = {}
                    for other in matrix:
                        if column >= len(other):
                            continue
                        key = _header_field(other[0])
                        if key:
                            values[key] = other[column].strip()
                    record_name = values.pop("name", row[column].strip())
                    outcome.extend(
                        _outcome_from_record(record_name, values, template, source)
                    )
                if outcome.courses:
                    return outcome

    # Vertical key/value table.
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for row in matrix:
        if len(row) < 2:
            continue
        key = _header_field(row[0])
        value = " ".join(cell for cell in row[1:] if cell.strip()).strip()
        if key == "name":
            if current.get("name"):
                records.append(current)
            current = {"name": value}
            continue
        if key and current:
            current[key] = value
    if current.get("name"):
        records.append(current)

    for record in records:
        name = record.pop("name", "")
        outcome.extend(_outcome_from_record(name, record, template, source))
    return outcome


def _outcome_from_record(
    name: str,
    values: dict[str, str],
    template: Template,
    source: str,
) -> ParseOutcome:
    outcome = ParseOutcome()
    time_text = values.get("time", "")
    weekday_text = values.get("weekday", "")
    period_text = values.get("periods", "")
    weeks_text = values.get("weeks", "")
    records = _records_from_fields(
        time_text=time_text,
        weekday_text=weekday_text,
        period_text=period_text,
        weeks_text=weeks_text,
        template=template,
    )
    credits_text = values.get("credits", "")
    credits = None
    if credits_text:
        try:
            credits = float(re.search(r"\d+(?:\.\d+)?", credits_text).group(0))
        except (AttributeError, ValueError):
            credits = None
    if not records:
        course = Course(
            name=clean_course_name(name),
            teacher=values.get("teacher", ""),
            classroom=values.get("classroom", ""),
            credits=credits,
            class_name=values.get("class_name", ""),
            note=values.get("note", ""),
            source=source,
        )
        course.add_issue("未识别上课星期/节次，已放入待安排")
        if course.name:
            outcome.courses.append(course)
        return outcome
    for weekday, start, end, weeks, week_type, week_expr in records:
        course = Course(
            name=clean_course_name(name),
            teacher=values.get("teacher", ""),
            classroom=values.get("classroom", ""),
            weekday=weekday,
            start_period=start,
            end_period=end,
            weeks=weeks,
            week_type=week_type,
            week_expr=week_expr,
            credits=credits,
            class_name=values.get("class_name", ""),
            note=values.get("note", ""),
            source=source,
        )
        _add_course_issues(course, total_weeks=template.total_weeks)
        outcome.courses.append(course)
    return outcome


# ---------------------------------------------------------------------------
# OCR layout reconstruction
# ---------------------------------------------------------------------------


@dataclass
class OCRLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float = 1.0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def reconstruct_ocr_grid(lines: Sequence[OCRLine]) -> TableData | None:
    """Best-effort recovery of a timetable grid from OCR bounding boxes."""

    if not lines:
        return None

    def header_weekday(line: OCRLine) -> int | None:
        text = line.text.strip()
        if len(text) > 12:
            return None
        # A course cell such as "周一 1-2节" must not become a column header.
        if parse_period_slots(text) or _TIME_RANGE_RE.search(text):
            return None
        if not re.fullmatch(
            r"(?:周|星期|礼拜)\s*[一二三四五六日天1-7]"
            r"(?:\s*[（(]?\s*\d{1,2}\s*[/.\-月]\s*\d{1,2}\s*日?\s*[）)]?)?",
            text,
        ):
            return None
        days = parse_weekdays(text)
        return days[0] if len(days) == 1 else None

    def period_label(line: OCRLine) -> tuple[int, int] | None:
        text = line.text.strip()
        if len(text) > 18:
            return None
        if re.fullmatch(
            r"(?:第\s*)?\d{1,2}\s*(?:[-~至到]\s*\d{1,2})?\s*节",
            text,
        ) or _TIME_RANGE_RE.fullmatch(text):
            slots = parse_period_slots(text)
            if not slots and _TIME_RANGE_RE.fullmatch(text):
                slots = parse_time_slots(text, Template())
            return slots[0] if len(slots) == 1 else None
        return None

    weekday_boxes: list[tuple[float, int]] = []
    for line in lines:
        day = header_weekday(line)
        if day is not None:
            weekday_boxes.append((line.cx, day))
    period_boxes: list[tuple[float, tuple[int, int]]] = []
    for line in lines:
        slot = period_label(line)
        if slot is not None:
            period_boxes.append((line.cy, slot))

    # Deduplicate and sort.
    weekday_boxes = _dedupe_positions(weekday_boxes)
    period_boxes = _dedupe_positions(period_boxes)
    if len(weekday_boxes) < 2 or len(period_boxes) < 1:
        return None

    weekday_boxes.sort(key=lambda item: item[0])
    period_boxes.sort(key=lambda item: item[0])
    weekday_map = {position: day for position, day in weekday_boxes}
    period_map = {position: slot for position, slot in period_boxes}

    weekday_positions = [position for position, _ in weekday_boxes]
    period_positions = [position for position, _ in period_boxes]

    min_x = min(line.x0 for line in lines) - 10
    max_x = max(line.x1 for line in lines) + 10
    min_y = min(line.y0 for line in lines) - 10
    max_y = max(line.y1 for line in lines) + 10

    cells: dict[tuple[int, int], list[OCRLine]] = {}
    for line in lines:
        if header_weekday(line) is not None or period_label(line) is not None:
            continue
        if line.text.strip() in {"节次", "时间", "星期", "节次/时间", "课程", "课程表", "上午", "下午", "晚上", "中午"}:
            continue
        if not (min_x <= line.cx <= max_x and min_y <= line.cy <= max_y):
            continue
        column = min(
            range(len(weekday_positions)),
            key=lambda index: abs(line.cx - weekday_positions[index]),
        )
        row = min(
            range(len(period_positions)),
            key=lambda index: abs(line.cy - period_positions[index]),
        )
        cells.setdefault((row, column), []).append(line)

    if not cells:
        return None

    # Reject a "grid" whose cells contain entire header/date blocks.  This is
    # a sign that OCR merged several header boxes into one cell; parsing it as
    # a grid gives confidently wrong weekdays.
    for cell_lines in cells.values():
        cell_text = "\n".join(line.text for line in cell_lines)
        if len(cell_text) > 160 or len(re.findall(r"\d{1,2}/\d{1,2}", cell_text)) >= 3:
            return None

    header = ["节次"] + [f"周{_day_to_chinese(day)}" for _, day in weekday_boxes]
    rows: list[list[str]] = [header]
    for row_index, (_position, slot) in enumerate(period_boxes):
        label = f"{slot[0]}节" if slot[0] == slot[1] else f"{slot[0]}-{slot[1]}节"
        row = [label]
        for column in range(len(weekday_boxes)):
            cell_lines = sorted(
                cells.get((row_index, column), []), key=lambda line: (line.y0, line.x0)
            )
            row.append("\n".join(line.text for line in cell_lines))
        rows.append(row)
    return TableData(rows=rows, source="图片 OCR 网格")


def _dedupe_positions(
    values: Sequence[tuple[float, Any]], tolerance: float = 18.0
) -> list[tuple[float, Any]]:
    result: list[tuple[float, Any]] = []
    for position, value in sorted(values, key=lambda item: item[0]):
        if result and abs(position - result[-1][0]) <= tolerance:
            continue
        result.append((position, value))
    return result


def _day_to_chinese(day: int) -> str:
    return {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "日"}.get(
        day, "一"
    )
