"""画布与栅格：所有几何只在这里推导，版式函数里不出现魔法数字。

坐标单位 pt；画布 960 × 540（16:9，与 2.9 的 13.333×7.5 in 等价）。
"""
from __future__ import annotations

from dataclasses import dataclass

W, H = 960.0, 540.0


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def r(self):
        return self.x + self.w

    @property
    def b(self):
        return self.y + self.h

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    def inset(self, l=0.0, t=0.0, r=0.0, b=0.0):
        return Box(self.x + l, self.y + t, self.w - l - r, self.h - t - b)

    def take_top(self, h):
        """切掉顶部 h，返回 (头部, 剩余)。"""
        h = max(0.0, min(h, self.h))
        return Box(self.x, self.y, self.w, h), Box(self.x, self.y + h, self.w, self.h - h)

    def take_bottom(self, h):
        h = max(0.0, min(h, self.h))
        return Box(self.x, self.y + self.h - h, self.w, h), Box(self.x, self.y, self.w, self.h - h)

    def take_left(self, w):
        w = max(0.0, min(w, self.w))
        return Box(self.x, self.y, w, self.h), Box(self.x + w, self.y, self.w - w, self.h)

    def take_right(self, w):
        w = max(0.0, min(w, self.w))
        return Box(self.x + self.w - w, self.y, w, self.h), Box(self.x, self.y, self.w - w, self.h)

    def union(self, o):
        x = min(self.x, o.x)
        y = min(self.y, o.y)
        return Box(x, y, max(self.r, o.r) - x, max(self.b, o.b) - y)

    def as_tuple(self):
        return (round(self.x, 2), round(self.y, 2), round(self.w, 2), round(self.h, 2))


def safe(lang, top_bias: float = 0.0) -> Box:
    """安全区：四边等距，用语言自己的页边距。"""
    m = lang.margin
    return Box(m, m + top_bias, W - 2 * m, H - 2 * m - top_bias)


def col(box: Box, n: int, span: int = 1, start: int = 0, gutter: float = 20.0) -> Box:
    """把 box 切成 n 栏，取第 start 栏起的 span 栏。"""
    total_g = gutter * (n - 1)
    cw = (box.w - total_g) / n
    x = box.x + start * (cw + gutter)
    w = cw * span + gutter * (span - 1)
    return Box(x, box.y, w, box.h)


def columns(box: Box, n: int, gutter: float = 20.0):
    return [col(box, n, 1, i, gutter) for i in range(n)]


def rows(box: Box, heights, gap: float = 0.0):
    """按给定高度自上而下切行。"""
    out = []
    y = box.y
    for h in heights:
        out.append(Box(box.x, y, box.w, h))
        y += h + gap
    return out


def footer_band(lang) -> Box:
    """页脚带：页码与脚注只在这里。"""
    m = lang.margin
    return Box(m, H - m + 4, W - 2 * m, 14)


def optical_center(y: float, h: float) -> float:
    """视觉中心比几何中心高 3%（人眼对上半部更敏感）。"""
    return y + h * 0.47
