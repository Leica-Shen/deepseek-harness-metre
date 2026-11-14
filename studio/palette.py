"""图片主色：让每一页的颜色跟着图走。

样板的做法（源 01 P10、源 04 P01、源 05 P06）是：**整页底色是产品图主色的极浅版**，
面板是中间版，标题/数字可以用主色本身。整册因此不会「一页一个色」，也不会「八页一个色」。

本模块只做三件事：
1. 从图里取主色（去掉近白近黑，按饱和度加权）；
2. 生成 pale / light / deep 三档；
3. 与语言纸色混合，得到「这页的纸」。

对比度不在这里保证——审计层会逐个文本算子验。
"""
from __future__ import annotations

import colorsys
import os
from functools import lru_cache

from PIL import Image

_cache = {}


def _hex(rgb):
    return "".join("%02X" % max(0, min(255, int(round(c)))) for c in rgb)


def _rgb(h):
    h = str(h).lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def mix(a, b, k):
    """a 占 (1-k)，b 占 k。"""
    x, y = _rgb(a), _rgb(b)
    return _hex([x[i] * (1 - k) + y[i] * k for i in range(3)])


def luma(h):
    r, g, b = (c / 255.0 for c in _rgb(h))
    def f(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def sat(h):
    r, g, b = (c / 255.0 for c in _rgb(h))
    mx, mn = max(r, g, b), min(r, g, b)
    return 0.0 if mx == 0 else (mx - mn) / mx


@lru_cache(maxsize=256)
def analyze(path):
    """返回 {main, light, pale, deep, dark_ok, lum, sat}；解析失败返回 None。"""
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return None
    im.thumbnail((96, 96))
    px = list(im.getdata())
    buckets = {}
    for r, g, b in px:
        h = _hex((r, g, b))
        L, S = luma(h), sat(h)
        if L > 0.94 or L < 0.05:
            continue                     # 近白近黑不参与主色
        key = (r >> 4, g >> 4, b >> 4)
        w = 0.25 + S                     # 饱和的像素更像「主色」
        acc = buckets.setdefault(key, [0.0, 0.0, 0.0, 0.0])
        acc[0] += r * w
        acc[1] += g * w
        acc[2] += b * w
        acc[3] += w
    if not buckets:
        return None
    # 取权重最高的若干桶加权平均
    top = sorted(buckets.values(), key=lambda a: -a[3])[:6]
    tw = sum(a[3] for a in top) or 1.0
    main = _hex([sum(a[i] for a in top) / tw for i in range(3)])
    # 主色太淡时，往饱和方向提一点，否则页面会「没有颜色」
    if sat(main) < 0.18:
        r, g, b = (c / 255.0 for c in _rgb(main))
        hh, ss, vv = colorsys.rgb_to_hsv(r, g, b)
        r, g, b = colorsys.hsv_to_rgb(hh, min(0.62, ss + 0.18), min(0.92, vv * 0.96))
        main = _hex([r * 255, g * 255, b * 255])
    lum = sum(luma(_hex(p)) for p in px) / max(1, len(px))
    return {
        "main": main,
        "light": mix(main, "FFFFFF", 0.62),
        "pale": mix(main, "FFFFFF", 0.88),
        "deep": mix(main, "000000", 0.42),
        "lum": round(lum, 3),
        "sat": round(sat(main), 3),
        "path": os.path.basename(path),
    }


def page_palette(image_path, lang):
    """把图片主色翻译成这一页可用的三档颜色；不适用时返回 None。

    palette_mode:
      none  —— 不跟随图片（保持语言原色）
      tint  —— 跟随纸色与面板，强调色仍用语言色
      both  —— 纸色、面板、强调色都跟随（标题大数字可以用主色）
    """
    mode = getattr(lang, "palette_mode", "none")
    if mode == "none" or not image_path or not os.path.exists(str(image_path)):
        return None
    pal = analyze(str(image_path))
    if not pal:
        return None
    return pal
