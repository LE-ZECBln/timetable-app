"""Offline Chinese OCR wrapper.

RapidOCR (ONNX Runtime) is bundled in ``vendor/``.  The engine is loaded lazily
so the app starts instantly and images are only processed when needed.  No
image, text, or model input ever leaves the machine.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any, Sequence

from PIL import Image, ImageOps

from .parsing import OCRLine, TableData, reconstruct_ocr_grid

_ENGINE: Any = None
_ENGINE_ERROR: str = ""


@dataclass
class OCRResult:
    text: str = ""
    lines: list[OCRLine] = field(default_factory=list)
    tables: list[TableData] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str = ""
    available: bool = True

    @property
    def average_score(self) -> float:
        if not self.lines:
            return 0.0
        return sum(line.score for line in self.lines) / len(self.lines)


def get_engine() -> Any:
    """Load RapidOCR once per process."""

    global _ENGINE, _ENGINE_ERROR
    if _ENGINE is not None:
        return _ENGINE
    if _ENGINE_ERROR:
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on local install
        _ENGINE_ERROR = (
            "本地 OCR 引擎不可用（未安装 rapidocr_onnxruntime）："
            f"{exc}。仍可上传 Word/PDF/Excel/文本，或把图片中的文字粘贴到文本框。"
        )
        return None
    try:
        _ENGINE = RapidOCR()
    except Exception as exc:  # pragma: no cover
        _ENGINE_ERROR = f"本地 OCR 引擎加载失败：{exc}"
        return None
    return _ENGINE


def ocr_available() -> bool:
    """Check importability without loading the (large) ONNX models."""

    try:
        import importlib.util

        return importlib.util.find_spec("rapidocr_onnxruntime") is not None
    except Exception:
        return False


def ocr_image(
    image: Image.Image | bytes,
    max_dimension: int = 2600,
    source: str = "图片",
) -> OCRResult:
    if isinstance(image, (bytes, bytearray)):
        try:
            image = Image.open(io.BytesIO(image))
        except Exception as exc:
            return OCRResult(error=f"无法读取图片：{exc}", available=True)
    if not isinstance(image, Image.Image):
        return OCRResult(error="不支持的图片对象。", available=True)

    engine = get_engine()
    if engine is None:
        return OCRResult(error=_ENGINE_ERROR or "OCR 引擎不可用。", available=False)

    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    width, height = image.size
    if max(width, height) > max_dimension:
        ratio = max_dimension / float(max(width, height))
        image = image.resize((max(1, int(width * ratio)), max(1, int(height * ratio))))

    try:
        import numpy as np  # bundled with the OCR runtime

        array = np.array(image.convert("RGB"))
        result, _elapsed = engine(array)
    except Exception as exc:  # pragma: no cover - engine/runtime specific
        return OCRResult(error=f"OCR 识别失败：{exc}", available=True)

    lines: list[OCRLine] = []
    for item in result or []:
        if not item or len(item) < 3:
            continue
        box, text, score = item[0], item[1], item[2]
        text = str(text or "").strip()
        if not text:
            continue
        try:
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
        except (TypeError, ValueError, IndexError):
            continue
        try:
            confidence = float(score)
        except (TypeError, ValueError):
            confidence = 1.0
        lines.append(
            OCRLine(
                text=text,
                x0=min(xs),
                y0=min(ys),
                x1=max(xs),
                y1=max(ys),
                score=confidence,
            )
        )

    lines.sort(key=lambda line: (round(line.cy / 12), line.cx))
    text = "\n".join(line.text for line in lines)
    tables: list[TableData] = []
    grid = reconstruct_ocr_grid(lines)
    if grid is not None:
        grid.source = f"{source} OCR 网格"
        tables.append(grid)

    notes = [
        f"OCR 识别 {len(lines)} 行文本，平均置信度 {sum(l.score for l in lines) / len(lines):.0%}"
        if lines
        else "OCR 未识别到文字。",
    ]
    if grid is not None:
        notes.append("已根据文字坐标还原为课表网格。")
    elif lines:
        notes.append("未还原出可靠网格，已按文本识别；建议重点核对星期与节次。")
    return OCRResult(text=text, lines=lines, tables=tables, notes=notes)


def ocr_pdf_page(page: Any, source: str = "PDF") -> OCRResult:
    """Render a pypdfium2 page and OCR it."""

    try:
        bitmap = page.render(scale=2.0)
        image = bitmap.to_pil()
    except Exception as exc:  # pragma: no cover
        return OCRResult(error=f"PDF 页面渲染失败：{exc}", available=True)
    return ocr_image(image, source=source)


def lines_to_text(lines: Sequence[OCRLine]) -> str:
    ordered = sorted(lines, key=lambda line: (round(line.cy / 12), line.cx))
    return "\n".join(line.text for line in ordered)
