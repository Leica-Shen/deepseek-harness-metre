"""版面算子（op）：版式函数只产出 op 列表，渲染器只负责把 op 画进 pptx。

好处是版面可以**在渲染前**被审计：重叠、越界、覆盖率、对比度全部用同一份
坐标算，不依赖导出的 PNG。
"""
from __future__ import annotations

from . import textmetrics as TM
from .grid import Box


# ------------------------------------------------------------------ 文本


def measure_para(text, width, size, lang, bold=False, tracking=0.0,
                 leading=None, hang=0.0):
    """返回 (lines, height)。hang 为悬挂缩进（项目符号）。"""
    lead = leading if leading is not None else lang.body_leading
    avail = max(8.0, width - hang)
    lines = TM.wrap_smart(text, size, avail, lang.body_font, lang.ea_body,
                          bold=bold, tracking=tracking)
    return lines, len(lines) * size * lead


def text(box: Box, lines, *, size, lang, color, leading=1.4, bold=False,
         align="l", tracking=0.0, caps=False, font=None, ea=None,
         bullet=None, hang=0.0, opacity=None, shrink=False, italic=False,
         space_after=0.0, image_fill=None):
    return {
        "op": "text", "box": box, "lines": list(lines), "size": size,
        "font": font or lang.body_font, "ea": ea or lang.ea_body,
        "color": color, "leading": leading, "bold": bold, "align": align,
        "tracking": tracking, "caps": caps, "bullet": bullet, "hang": hang,
        "opacity": opacity, "italic": italic, "space_after": space_after,
        "image_fill": image_fill,
    }


def line_h(lines, size, leading):
    return len(lines) * size * leading


# ------------------------------------------------------------------ 装饰


def rule(box: Box, color, pt=1.0, dash=None):
    return {"op": "rule", "box": box, "color": color, "pt": pt, "dash": dash}


def panel(box: Box, color, alpha=100, radius=0.0, line=None, line_pt=1.0,
          shadow=False, rotate=0.0, image=None):
    """image 非空时，这个形状用图片填充（圆、圆角矩形、椭圆都行）。"""
    return {"op": "panel", "box": box, "color": color, "alpha": alpha,
            "radius": radius, "line": line, "line_pt": line_pt,
            "shadow": shadow, "rotate": rotate, "image": image}


def dot(box: Box, color, alpha=100):
    return {"op": "dot", "box": box, "color": color, "alpha": alpha}


def hexagon(box: Box, color, alpha=100, line=None):
    return {"op": "hex", "box": box, "color": color, "alpha": alpha, "line": line}


def thin_frame(box: Box, color, pt=0.75):
    return {"op": "frame", "box": box, "color": color, "pt": pt}


# ------------------------------------------------------------------ 图像


def media(box: Box, path, *, fit="cover", focus=(0.5, 0.5), radius=0.0,
          scrim=None, frame=None, frame_pt=1.0, tone_overlay=None,
          grayscale=False, tint=None, opacity=None, tag=None):
    """scrim: {"color": "000000", "alpha": 55, "mode": "full|bottom|left|right"}"""
    return {"op": "media", "box": box, "path": path, "fit": fit,
            "focus": focus, "radius": radius, "scrim": scrim,
            "frame": frame, "frame_pt": frame_pt,
            "tone_overlay": tone_overlay, "grayscale": grayscale,
            "tint": tint, "opacity": opacity, "tag": tag}


# ------------------------------------------------------------------ 数据


def chart(box: Box, spec):
    return {"op": "chart", "box": box, **spec}


def table(box: Box, spec):
    return {"op": "table", "box": box, **spec}


# ------------------------------------------------------------------ 页脚


def folio(box: Box, page_no, total, lang, color, label=""):
    return {"op": "folio", "box": box, "page": page_no, "total": total,
            "lang": lang, "color": color, "label": label}


def kicker(box: Box, text, lang, color, size=None, align="l"):
    """小标签：全大写 + 字距。中文字距为正会散架，故中文不加字距。"""
    size = size or lang.type.micro
    caps = lang.label_case == "upper" and not TM.has_cjk(text)
    tr = lang.tracking_label if caps else 0.0
    return {
        "op": "text", "box": box, "lines": [text.upper() if caps else text],
        "size": size, "font": lang.micro_font, "ea": lang.ea_micro,
        "color": color, "leading": 1.2, "bold": False, "align": align,
        "tracking": tr, "caps": caps, "bullet": None, "hang": 0.0,
        "opacity": None, "italic": False, "space_after": 0.0,
    }


def kicker_w(text, lang, size=None):
    size = size or lang.type.micro
    caps = lang.label_case == "upper" and not TM.has_cjk(text)
    t = text.upper() if caps else text
    tr = lang.tracking_label if caps else 0.0
    return TM.text_width(t, size, lang.micro_font, lang.ea_body, False, tr)
