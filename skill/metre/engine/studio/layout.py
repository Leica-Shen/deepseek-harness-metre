"""排版算子：把「一堆块」放进一个区域，并保证不重叠、不偏心。

三条律：
1. 组内间距 ≤ 组间间距（靠距离分组，不靠加框）。
2. 剩余空间只有三种合法去处：加大组内间距（有上限）、整体居中、交给填空装置。
   绝不「把元素等比放大」。
3. 任何块的高度都由度量层给出，不从字符数猜。
"""
from __future__ import annotations


def stack(heights, area_h, gap=0.0, policy="top", max_gap=None):
    """返回 (offsets, gap_used, used_h)。

    policy: top / center / bottom / spread
    spread 会先把 gap 撑到 max_gap，仍有余量则按 center 处理。
    """
    n = len(heights)
    if n == 0:
        return [], gap, 0.0
    total = sum(heights)
    natural = total + gap * (n - 1)
    free = area_h - natural

    if policy == "spread" and n > 1 and free > 0 and max_gap is not None:
        extra = min(free, (max_gap - gap) * (n - 1))
        if extra > 0:
            gap = gap + extra / (n - 1)
            free -= extra
    used = sum(heights) + gap * (n - 1)

    if policy in ("center", "spread") and free > 0:
        y = free / 2.0
    elif policy == "bottom" and free > 0:
        y = free
    else:
        y = 0.0

    offs = []
    for h in heights:
        offs.append(y)
        y += h + gap
    return offs, gap, used


def split(weights, total, gap=0.0):
    """按权重分配总长，返回各段长度（已扣除间 gap）。"""
    n = len(weights)
    avail = total - gap * (n - 1)
    s = float(sum(weights)) or 1.0
    return [avail * w / s for w in weights]


def snap(v, step=2.0):
    return round(v / step) * step


def align_to(v, ref, tol=0.5):
    return ref if abs(v - ref) <= tol else v
