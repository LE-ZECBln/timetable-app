"""PNG/PDF rendering with Pillow (no browser or external service)."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .layout import GridLayout, card_geometry
from .models import Course, WEEKDAY_NAMES, week_date_label

A4_LANDSCAPE_200 = (2338, 1654)
_FONT_CANDIDATES = {
    False: [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\msyh.ttf",
    ],
    True: [
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ],
}


def _font_path(bold: bool = False) -> str | None:
    for candidate in _FONT_CANDIDATES[bold]:
        if Path(candidate).exists():
            return candidate
    return None


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _font_path(bold)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _hex_color(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        return (30, 64, 175)
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 2,
) -> list[str]:
    text = " ".join(str(text or "").split())
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for character in text:
        candidate = current + character
        if _text_width(draw, candidate, font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = character
            if len(lines) >= max_lines - 1:
                break
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if lines and len("".join(lines)) < len(text):
        lines[-1] = _ellipsis(draw, lines[-1] + "…", font, max_width)
    return lines


def _ellipsis(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    value = str(text or "")
    while value and _text_width(draw, value, font) > max_width:
        value = value[:-2] + "…" if len(value) > 2 else value[:-1]
    return value


def _draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    max_width: int | None = None,
    max_lines: int = 1,
) -> int:
    if max_width is not None:
        lines = _wrap(draw, text, font, max_width, max_lines)
    else:
        lines = [str(text or "")]
    y = xy[1]
    for line in lines:
        draw.text((xy[0], y), line, font=font, fill=fill)
        y += int(font.size * 1.28) if hasattr(font, "size") else 14
    return y


def _draw_course(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    course: Course,
    compact: bool = False,
) -> None:
    x0, y0, x1, y1 = box
    background, foreground = course.color_pair
    bg = _hex_color(background)
    fg = _hex_color(foreground)
    draw.rounded_rectangle(box, radius=10, fill=bg, outline=None)
    draw.rounded_rectangle((x0, y0, x0 + 6, y1), radius=3, fill=fg)

    text_x = x0 + 15
    text_width = x1 - text_x - 8
    if text_width <= 10 or y1 - y0 <= 12:
        return
    name_size = 23 if not compact else 17
    meta_size = 14 if not compact else 11
    week_size = 11 if not compact else 9
    name_font = _font(name_size, bold=True)
    meta_font = _font(meta_size, bold=False)
    week_font = _font(week_size, bold=False)

    y = y0 + 9
    name_lines = _wrap(draw, course.name, name_font, text_width, max_lines=2 if not compact else 2)
    for line in name_lines:
        draw.text((text_x, y), line, font=name_font, fill=fg)
        y += name_size + 3
    meta_parts = [part for part in (course.teacher, course.classroom) if part]
    if meta_parts and y + meta_size + 2 < y1 - 4:
        meta = _ellipsis(draw, " · ".join(meta_parts), meta_font, text_width)
        draw.text((text_x, y + 1), meta, font=meta_font, fill=fg)
        y += meta_size + 4
    if y + week_size + 2 < y1 - 4:
        weeks = _ellipsis(draw, course.week_label, week_font, text_width)
        draw.text((text_x, y + 1), weeks, font=week_font, fill=fg)


def render_png(layout: GridLayout, dpi: int = 200) -> bytes:
    width, height = A4_LANDSCAPE_200 if dpi == 200 else (
        int(11.69 * dpi),
        int(8.27 * dpi),
    )
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    margin_x = 70
    margin_top = 58
    margin_bottom = 48
    title_font = _font(44, bold=True)
    subtitle_font = _font(19)
    badge_font = _font(17, bold=True)
    header_font = _font(21, bold=True)
    date_font = _font(12)
    time_font = _font(15, bold=True)
    time_small_font = _font(10)
    footer_font = _font(9)

    title = layout.template.title or "我的课表"
    draw.text((margin_x, margin_top), _ellipsis(draw, title, title_font, width - 420), font=title_font, fill=(15, 23, 42))
    subtitle = f"{layout.week_label} · {layout.days_label} · 共 {layout.template.total_weeks} 周"
    draw.text((margin_x, margin_top + 58), subtitle, font=subtitle_font, fill=(100, 116, 139))

    badge_text = layout.week_label
    badge_w = _text_width(draw, badge_text, badge_font) + 34
    badge_h = 36
    badge_x = width - margin_x - badge_w
    badge_y = margin_top + 8
    draw.rounded_rectangle(
        (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
        radius=18,
        fill=(239, 246, 255),
        outline=(191, 219, 254),
    )
    draw.text(
        (badge_x + 17, badge_y + 8),
        badge_text,
        font=badge_font,
        fill=(29, 78, 216),
    )

    table_x0 = margin_x
    table_y0 = margin_top + 118
    table_x1 = width - margin_x
    table_y1 = height - margin_bottom
    time_width = 190
    header_height = 66
    day_count = max(1, len(layout.days))
    day_width = (table_x1 - table_x0 - time_width) / day_count
    body_height = table_y1 - table_y0 - header_height
    row_height = body_height / max(1, len(layout.template.rows))

    # Header
    draw.rectangle((table_x0, table_y0, table_x1, table_y0 + header_height), fill=(15, 23, 42))
    draw.text(
        (table_x0 + 14, table_y0 + 18),
        "节次 / 时间",
        font=header_font,
        fill=(255, 255, 255),
    )
    for index, day in enumerate(layout.days):
        x0 = table_x0 + time_width + index * day_width
        x1 = x0 + day_width
        center = (x0 + x1) / 2
        day_text = WEEKDAY_NAMES.get(day, str(day))
        day_w = _text_width(draw, day_text, header_font)
        draw.text((center - day_w / 2, table_y0 + 13), day_text, font=header_font, fill=(255, 255, 255))
        if layout.week:
            date_text = week_date_label(layout.template, layout.week, day)
            if date_text:
                date_w = _text_width(draw, date_text, date_font)
                draw.text(
                    (center - date_w / 2, table_y0 + 42),
                    date_text,
                    font=date_font,
                    fill=(203, 213, 225),
                )

    # Body backgrounds and grid
    for row_index, row in enumerate(layout.template.rows):
        y0 = table_y0 + header_height + row_index * row_height
        y1 = y0 + row_height
        draw.rectangle((table_x0, y0, table_x0 + time_width, y1), fill=(248, 250, 252))
        for column_index, day in enumerate(layout.days):
            x0 = table_x0 + time_width + column_index * day_width
            x1 = x0 + day_width
            fill = (255, 255, 255) if day < 6 else (252, 253, 255)
            draw.rectangle((x0, y0, x1, y1), fill=fill)
            if day >= 6:
                draw.rectangle((x0, y0, x1, y1), outline=(226, 232, 240), width=1)

        # Time cell text
        draw.text((table_x0 + 12, y0 + 12), row.period_label, font=time_font, fill=(51, 65, 85))
        draw.text((table_x0 + 12, y0 + 38), row.time_label, font=time_small_font, fill=(100, 116, 139))

    # Grid lines
    for row_index in range(len(layout.template.rows) + 1):
        y = table_y0 + header_height + row_index * row_height
        draw.line((table_x0, y, table_x1, y), fill=(226, 232, 240), width=1)
    for column_index in range(day_count + 1):
        x = table_x0 + time_width + column_index * day_width
        draw.line((x, table_y0 + header_height, x, table_y1), fill=(226, 232, 240), width=1)
    draw.line((table_x0, table_y0, table_x0, table_y1), fill=(226, 232, 240), width=1)
    draw.line((table_x1, table_y0, table_x1, table_y1), fill=(226, 232, 240), width=1)

    # Course cards
    for row_index, _row in enumerate(layout.template.rows):
        y0 = table_y0 + header_height + row_index * row_height
        for column_index, day in enumerate(layout.days):
            key = (row_index, day)
            if key in layout.covered:
                continue
            courses = layout.cell_courses(row_index, day)
            if not courses:
                continue
            span = layout.rowspans.get(key, 1)
            x0 = table_x0 + time_width + column_index * day_width
            x1 = x0 + day_width
            total_height = row_height * span
            count = max(1, len(courses))
            gap = 4
            if count == 1:
                top_ratio, height_ratio = card_geometry(
                    courses[0], layout.template, row_index, span
                )
                if top_ratio > 0.001 or height_ratio < 0.999:
                    card_y0 = y0 + total_height * top_ratio + 4
                    card_y1 = (
                        y0
                        + total_height * (top_ratio + height_ratio)
                        - 4
                    )
                    _draw_course(
                        draw,
                        (int(x0 + 5), int(card_y0), int(x1 - 5), int(card_y1)),
                        courses[0],
                        compact=(card_y1 - card_y0) < 76,
                    )
                    continue
            available = (total_height - 8 - gap * (count - 1)) / count
            max_height = 138 if span == 1 else 190
            if count > 1:
                max_height = 108
            card_height = min(available, max_height)
            for index, course in enumerate(courses):
                card_y0 = y0 + 4 + index * (card_height + gap)
                card_y1 = card_y0 + card_height
                _draw_course(
                    draw,
                    (int(x0 + 5), int(card_y0), int(x1 - 5), int(card_y1)),
                    course,
                    compact=card_height < 76,
                )

    footer = (
        f"本地智能课表生成器 · {layout.week_label} · "
        f"{len(layout.courses)} 条课程安排 · 完全离线"
    )
    footer_w = _text_width(draw, footer, footer_font)
    draw.text(
        (width - margin_x - footer_w, height - 30),
        footer,
        font=footer_font,
        fill=(148, 163, 184),
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_pdf(layout: GridLayout, dpi: int = 200) -> bytes:
    png = render_png(layout, dpi=dpi)
    image = Image.open(io.BytesIO(png)).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PDF", resolution=float(dpi))
    return buffer.getvalue()
