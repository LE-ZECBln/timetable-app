"""Common values used by the structured-input suggestion library.

These are deliberately plain Python lists so they are easy to edit for a
particular school or major.
"""

from __future__ import annotations

COURSE_NAME_SUGGESTIONS: list[str] = [
    "高等数学",
    "线性代数",
    "概率论与数理统计",
    "复变函数与积分变换",
    "大学英语",
    "学术英语",
    "英语听说",
    "大学物理",
    "大学化学",
    "大学计算机基础",
    "程序设计基础",
    "数据结构",
    "算法设计与分析",
    "操作系统",
    "计算机网络",
    "数据库原理",
    "软件工程",
    "人工智能导论",
    "机器学习",
    "自动控制原理",
    "现代控制理论",
    "数值分析",
    "电路分析",
    "模拟电子技术",
    "数字电子技术",
    "信号与系统",
    "通信原理",
    "工程制图",
    "理论力学",
    "材料力学",
    "马克思主义基本原理",
    "思想道德与法治",
    "中国近现代史纲要",
    "毛泽东思想和中国特色社会主义理论体系概论",
    "体育",
    "军事理论",
    "心理健康教育",
]

# A short row shown directly above the full expandable library.
TOP_COURSE_SUGGESTIONS: list[str] = [
    "高等数学",
    "大学英语",
    "线性代数",
    "概率论与数理统计",
    "大学物理",
    "数据结构",
]

CLASSROOM_BUILDINGS: list[str] = [
    "正心楼",
    "致知楼",
    "诚意楼",
    "格物楼",
    "电机楼",
    "理学楼",
]

WEEKDAY_SUGGESTIONS: list[str] = [
    "周一",
    "周二",
    "周三",
    "周四",
    "周五",
    "周六",
    "周日",
]

PERIOD_SUGGESTIONS: list[str] = [
    "1-2节",
    "3-4节",
    "5-6节",
    "7-8节",
    "9-10节",
    "11-12节",
    "5/6节",
    "9/10节",
    "9/11节",
]

WEEK_SUGGESTIONS: list[str] = [
    "1-16周",
    "1-8周",
    "9-16周",
    "1-8,10-16周",
    "单周",
    "双周",
    "全周",
]

# Common whole time slots (weekday, period expression).  Clicking one fills both
# the weekday and period fields; the user can still edit either afterwards.
TIME_SLOT_SUGGESTIONS: list[tuple[str, str]] = [
    ("周一", "1-2节"),
    ("周一", "3-4节"),
    ("周一", "5-6节"),
    ("周一", "9-11节"),
    ("周二", "1-2节"),
    ("周二", "3-4节"),
    ("周二", "5-6节"),
    ("周二", "9-10节"),
    ("周三", "1-2节"),
    ("周三", "3-4节"),
    ("周三", "5-6节"),
    ("周三", "9-11节"),
    ("周四", "1-2节"),
    ("周四", "3-4节"),
    ("周四", "5-6节"),
    ("周四", "9-10节"),
    ("周五", "1-2节"),
    ("周五", "3-4节"),
    ("周五", "5-6节"),
    ("周五", "9-10节"),
]
