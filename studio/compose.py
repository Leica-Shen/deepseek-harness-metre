"""版式引擎：页型 → 构图 → op 列表。

与 2.9 的区别：
- 不做「模板套坐标」。每个构图都由度量结果推导：标题几行、正文多高、剩余多少
  空间，再决定纵向分布与填空装置。
- 没有「骨架清单」这种固定枚举，同一个 kind 有多个 variant，由册级节奏挑选。
- 任何构图都先保证**不重叠、不越界**，再谈好看。
"""
from __future__ import annotations

import copy
import os
import random

from . import languages as LG
from . import palette as PAL
from .languages import accent_text, ink_on, contrast
from . import layout as LY
from . import ops as OPS
from . import textmetrics as TM
from .grid import Box, H, W, col, columns, footer_band, safe

# ---------------------------------------------------------------- 小工具


def card_radius(lang, box):
    """圆角 = 短边 × 0.1667（Office 默认比例），与样板一致。"""
    return max(0.0, min(box.w, box.h) * getattr(lang, "radius_ratio", 0.0))


def _shadow_of(lang):
    return getattr(lang, "shadow", ()) or False


def _want_center(ctx, kind):
    if str(ctx.page.get("align") or "").lower() in ("center", "居中"):
        return True
    if str(ctx.page.get("align") or "").lower() in ("left", "l", "左"):
        return False
    bias = getattr(ctx.lang, "align_bias", "left")
    if bias == "center":
        return True
    return kind in getattr(ctx.lang, "center_kinds", ())


def _img_ok(p):
    return bool(p) and isinstance(p, str) and os.path.exists(p)


def _fill_ok(p, min_lum=0.52):
    """图片填充文字只在图足够亮时可用，否则字会糊成一片。"""
    if not _img_ok(p):
        return None
    pal = PAL.analyze(str(p))
    if not pal or pal.get("lum", 0) < min_lum:
        return None
    return p


def _txt(v, default=""):
    if v is None:
        return default
    if isinstance(v, (list, tuple)):
        return "、".join(str(x) for x in v)
    return str(v)


class Ctx:
    """一页的上下文：语言、纸色、页区、页码。"""

    def __init__(self, lang, page, idx, total, tone="light", variant=None,
                 brand="", deck_pal=None):
        self.lang = lang
        self.page = page
        self.idx = idx
        self.total = total
        self.tone = tone
        self.variant = variant or ""
        self.brand = brand
        self.ops = []
        self.pre = []
        self.dark = tone == "dark"
        # 图片主色：这一页的颜色跟着图走（样板 P10 / P06 的做法）
        img = page.get("image")
        self.pal = PAL.page_palette(img, lang) if img else None
        if self.pal is None and deck_pal:
            self.pal = deck_pal
        mode = lang.palette_mode
        if self.pal:
            self.panel_c = self.pal["light"]
            base_tint = self.pal["pale"]
        else:
            self.panel_c = lang.panel_c
            base_tint = PAL.mix(lang.paper, lang.accent, lang.tint_ratio)
        # 纸：light 用语言纸色（有图时混一点图片 pale）；tint 用带色的浅纸；dark 用反白
        if tone == "dark":
            self.bg = lang.paper_alt
        elif tone == "sand":
            self.bg = "F7EFE6" if not self.pal else PAL.mix(self.pal["pale"], "F7EFE6", 0.5)
        elif tone == "tint":
            self.bg = base_tint
        else:
            self.bg = lang.paper if not self.pal else PAL.mix(lang.paper, self.pal["pale"], 0.55)
        self.on = lang.on_dark if self.dark else lang.title_c
        self.body_c = lang.on_dark if self.dark else lang.body_c
        if not self.dark and LG._lum(self.panel_c) < 0.45:
            # 语言面板本身是深色（铁报），浅色页上改用 6% 墨色 tint
            self.panel_c = PAL.mix(self.bg, "#000000", 0.06)
        self.bg_hint = self.bg
        self.meta_c = ("C7CDD6" if self.dark else ink_on(lang.meta_c, self.bg, 4.8))
        self.rule_c = ("46505E" if self.dark else ink_on(lang.rule_c, self.bg, 1.25))
        if self.dark:
            self.accent = ink_on(lang.accent2 or lang.accent, lang.paper_alt, 3.0)
        elif self.pal and mode == "both":
            cand = self.pal["main"]
            self.accent = cand if contrast(cand, self.bg) >= 2.6 else lang.accent
        else:
            self.accent = lang.accent
        # 大数字/标签可用的「图片主色」
        self.pal_accent = (self.pal["main"] if self.pal else lang.accent2)
        self.area = safe(lang, top_bias=0.0)
        self.has_foot = False
        self.foot_span = (lang.margin, W - 2 * lang.margin)
        self.head_top = H * lang.head_top

    # -- 区域
    def content(self):
        m = self.lang.margin
        return Box(m, self.head_top, W - 2 * m, H - self.head_top - m)

    def out(self, *ops):
        for o in ops:
            if o:
                self.ops.append(o)
        return self.ops

    def under(self, *ops):
        """装饰放到底层（先画）。"""
        for o in ops:
            if o:
                self.pre.append(o)
        return self.pre

    # -- 页眉
    def head(self, title, *, kicker="", lead="", role="h1", width=None,
             align="l", max_h=None, color=None, kicker_color=None, x=None, y=None):
        area = self.content()
        if x is not None or y is not None:
            area = Box(area.x if x is None else x,
                       area.y if y is None else y,
                       area.w if x is None else (area.w if x == area.x else area.w),
                       area.h)
        bw = width or area.w
        box = Box(area.x, area.y, bw, 0)
        y = area.y
        used = []
        if kicker:
            kh = self.lang.type.micro * 1.25
            kw = OPS.kicker_w(kicker, self.lang)
            if "chip" in self.lang.ornaments and kw < bw * 0.6:
                pad_x, pad_y = 10.0, 4.5
                used.append(OPS.panel(
                    Box(box.x - pad_x, y - pad_y, kw + pad_x * 2, kh + pad_y * 2),
                    PAL.mix(self.bg_hint, self.accent, 0.14), 100,
                    radius=(kh + pad_y * 2) / 2.0))
            used.append(OPS.kicker(Box(box.x, y, bw, kh), kicker, self.lang,
                                   kicker_color or ink_on(self.accent, self.bg_hint, 4.6),
                                   align=align))
            y += kh + self.lang.type.micro * 0.9
        have = (max_h or (area.h * 0.46)) - (y - area.y)
        size, lines = TM.headline(title, bw, have, self.lang.type.ladder(role),
                                  self.lang.display, self.lang.ea_display,
                                  bold=self.lang.bold_title,
                                  leading=self.lang.leading)
        th = OPS.line_h(lines, size, self.lang.leading)
        used.append(OPS.text(Box(box.x, y, bw, th), lines, size=size,
                             lang=self.lang, color=color or self.on,
                             leading=self.lang.leading, bold=self.lang.bold_title,
                             align=align, font=self.lang.display,
                             ea=self.lang.ea_display))
        y += th
        if lead:
            gap = size * 0.42
            y += gap
            lsz = min(self.lang.type.lead, size * 0.52)
            lw = bw if align != "l" else min(bw, bw * 0.92)
            llines, lh = OPS.measure_para(lead, lw, lsz, self.lang,
                                          leading=1.35)
            used.append(OPS.text(Box(box.x, y, lw, lh), llines, size=lsz,
                                 lang=self.lang, color=self.body_c, leading=1.35,
                                 align=align, font=self.lang.body_font,
                                 ea=self.lang.ea_body))
            y += lh
        self.head_bottom = y
        self.out(*used)
        return y

    def foot(self, note="", *, page_no=True, align_note="l"):
        if self.has_foot:
            return
        self.has_foot = True
        m = self.lang.margin
        fx, fw = self.foot_span
        band = Box(fx, H - m * 0.62, fw, self.lang.type.micro * 1.3)
        if note:
            size = self.lang.type.micro
            lines = TM.wrap_smart(note, size, band.w - 80, self.lang.body_font,
                                  self.lang.ea_body)
            lines = lines[:1]
            self.out(OPS.text(Box(band.x, band.y, band.w - 80, band.h), lines,
                              size=size, lang=self.lang, color=self.meta_c,
                              leading=1.2, font=self.lang.micro_font,
                              ea=self.lang.ea_micro))
        if page_no:
            label = "%02d" % self.idx
            self.out(OPS.text(Box(band.r - 60, band.y, 60, band.h), [label],
                              size=self.lang.type.micro, lang=self.lang,
                              color=self.meta_c, leading=1.2, align="r",
                              font=self.lang.micro_font, ea=self.lang.ea_micro))

    def rule(self, x, y, w, color=None, pt=None):
        self.out(OPS.rule(Box(x, y, w, pt or self.lang.rule_pt),
                          color or self.rule_c, self.lang.rule_pt))

    def body_area(self, gap_after_head=26.0, foot_h=30.0):
        top = self.head_bottom + gap_after_head
        bottom = H - self.lang.margin - foot_h
        return Box(self.lang.margin, top, W - 2 * self.lang.margin, max(20.0, bottom - top))


# ---------------------------------------------------------------- 构图



# ---------------------------------------------------------------- 纵向分布律

def place(heights, area, gap, max_gap=None, anchor="balanced"):
    """把一组块放进区域，返回 (ys, gap_used)。

    规则（这是全套版式的公共法则）：
    1. 先按 gap 排；剩余空间优先加大组内间距，但不超过 max_gap。
    2. 仍有余量则整体下移，上留 42%、下留 58%（视觉重心略高于几何中心）。
    3. 永不放大元素来填空间——要填就换字号或加填空装置。
    """
    n = len(heights)
    if not n:
        return [], gap
    max_gap = max_gap if max_gap is not None else gap
    total = sum(heights) + gap * (n - 1)
    free = area.h - total
    if n > 1 and free > 0:
        add = min(free, (max_gap - gap) * (n - 1))
        if add > 0:
            gap += add / (n - 1)
            free -= add
    used = sum(heights) + gap * (n - 1)
    top = 0.0
    if free > 0:
        if anchor == "top":
            top = 0.0
        elif anchor == "bottom":
            top = free
        else:
            top = free * 0.42
    ys = []
    y = area.y + top
    for h in heights:
        ys.append(y)
        y += h + gap
    return ys, gap


def _orphan(lines, size, width, lang, bold):
    """末行过短（孤字）或首行过长，都不算好断行。"""
    if len(lines) < 2:
        return 0
    ws = [TM.text_width(l, size, lang.display, lang.ea_display, bold) for l in lines]
    last = ws[-1]
    if last < width * 0.34:
        return 3
    if last < width * 0.46:
        return 1
    return 0


def fit_display(text, width, height, sizes, lang, max_lines=3, bold=None,
                leading=None):
    """展示级文字：在「装得下、行数 ≤ max_lines、末行不成孤字」的字号里取最大。"""
    bold = lang.bold_title if bold is None else bold
    leading = lang.leading if leading is None else leading
    fallback = None
    for s in sizes:
        lines = TM.wrap_smart(text, s, width, lang.display, lang.ea_display,
                              bold=bold)
        if len(lines) > max_lines:
            continue
        h = OPS.line_h(lines, s, leading)
        widest = max(TM.text_width(l, s, lang.display, lang.ea_display, bold)
                     for l in lines)
        if h > height + 0.5 or widest > width + 0.5:
            continue
        if fallback is None:
            fallback = (s, lines)
        if _orphan(lines, s, width, lang, bold) == 0:
            return s, lines
    if fallback:
        return fallback
    return TM.headline(text, width, height, sizes, lang.display, lang.ea_display,
                       bold=bold, leading=leading)


def _head_h(ctx):
    return ctx.head_bottom if hasattr(ctx, "head_bottom") else ctx.content().y


def _leftover(area, heights, gap):
    return area.h - (sum(heights) + gap * max(0, len(heights) - 1))



def side_media(ctx, frac=0.38, side="r"):
    """有图就在一侧留一条整幅高的图，返回剩余内容宽（没有图返回 None）。"""
    img = ctx.page.get("image")
    if not _img_ok(img):
        return None
    iw = W * frac
    box = Box(0, 0, iw, H) if side == "l" else Box(W - iw, 0, iw, H)
    ctx.out(OPS.media(box, img, fit="cover", focus=ctx.page.get("focus", (0.5, 0.5)),
                      grayscale=(ctx.lang.media.grayscale or bool(ctx.page.get("mono")))))
    gap = ctx.lang.gutter + 14
    if side == "r":
        ctx.foot_span = (ctx.lang.margin, W - iw - gap - ctx.lang.margin)
        return (ctx.lang.margin, W - iw - gap - ctx.lang.margin)
    ctx.foot_span = (iw + gap, W - iw - gap - ctx.lang.margin)
    return (iw + gap, W - iw - gap - ctx.lang.margin)

# ---------------------------------------------------------------- 封面


def _cover(ctx):
    """封面：图在半幅 / 满幅 / 纯字色块。

    三条硬规矩：标题基线落在 52–62% H；标签与标题的距离固定为字号的 0.9；
    底部只用「细线 + 一行小字」收口，不堆元素。
    """
    lang, p, v = ctx.lang, ctx.page, ctx.variant
    img = p.get("image")
    title = _txt(p.get("title"))
    kicker = _txt(p.get("kicker"))
    sub = _txt(p.get("sub") or p.get("lead"))
    meta = _txt(p.get("meta"))

    # ---- 满幅出血
    if v == "bleed" and _img_ok(img):
        bg = "111111"
        ctx.out(OPS.media(Box(0, 0, W, H), img, fit="cover",
                          focus=p.get("focus", (0.55, 0.5)),
                          grayscale=(lang.media.grayscale or bool(p.get("mono"))),
                          scrim={"color": "000000", "alpha": 68, "mode": "full"}))
        colw = W * 0.60
        x = lang.margin
        size, lines = TM.headline(title, colw, H * 0.40, lang.type.ladder("cover"),
                                  lang.display, lang.ea_display,
                                  bold=lang.bold_title, leading=lang.leading)
        th = OPS.line_h(lines, size, lang.leading)
        ty = H * 0.60 - th
        if kicker:
            ctx.out(OPS.kicker(Box(x, ty - 30, colw, 14), kicker, lang,
                               ink_on(lang.meta_c, "0A0A0A", 7.0)))
        ctx.out(OPS.text(Box(x, ty, colw, th), lines, size=size, lang=lang,
                         color=lang.on_dark, leading=lang.leading,
                         bold=lang.bold_title, font=lang.display,
                         ea=lang.ea_display))
        if sub:
            sy = ty + th + 18
            slines, sh = OPS.measure_para(sub, colw * 0.82, lang.type.small, lang,
                                          leading=1.45)
            ctx.out(OPS.text(Box(x, sy, colw * 0.82, sh), slines,
                             size=lang.type.small, lang=lang, color="E4E1DA",
                             leading=1.45))
        ctx.out(OPS.rule(Box(x, H - lang.margin - 12, 44, 1.6), ctx.accent, 1.6))
        if meta:
            ctx.out(OPS.kicker(Box(x + 56, H - lang.margin - 12, colw, 13), meta,
                               lang, "D8D8D8"))
        return bg

    # ---- 半幅图
    if _img_ok(img):
        side = "l" if v == "split" else "r"
        frac = 0.46 if side == "r" else 0.42
        iw = W * frac
        if side == "l":
            ibox = Box(0, 0, iw, H)
            tx, tw = iw + lang.margin, W - iw - lang.margin * 2
        else:
            ibox = Box(W - iw, 0, iw, H)
            tx, tw = lang.margin, W - iw - lang.margin * 1.7
        ctx.out(OPS.media(ibox, img, fit="cover", focus=p.get("focus", (0.5, 0.5)),
                          grayscale=(lang.media.grayscale or bool(p.get("mono"))),
                          tint=(lang.accent2 if lang.media.duotone else None)))
        # 语言装饰：甜本给文字区一块浅色底；宣言给图一道细框
        if lang.id == "sweet":
            ctx.under(OPS.panel(Box(0, 0, W - iw, H), ctx.panel_c, 100))
        elif lang.id == "manifesto":
            ctx.under(OPS.thin_frame(Box(ibox.x + 18, 18, ibox.w - 36, H - 36),
                                "FFFFFF", 0.75))
        elif lang.id == "iron":
            ctx.under(OPS.panel(Box(0, 0, W - iw, 8), ctx.accent, 100))

        # 标签贴顶，标题落在 56% 附近，底行收口——三处锚点撑满整列
        if kicker:
            ref = ctx.panel_c if lang.id == "sweet" else ctx.bg
            ctx.out(OPS.kicker(Box(tx, lang.margin, tw, 13), kicker, lang,
                               ink_on(ctx.accent, ref, 4.6)))
        sizes = [lang.type.cover, lang.type.cover * 0.88, lang.type.cover * 0.76,
                 lang.type.h1, lang.type.h1 * 0.88, lang.type.h2]
        size, lines = fit_display(title, tw, H * 0.40, sizes, lang, max_lines=3)
        th = OPS.line_h(lines, size, lang.leading)
        ty = min(H * 0.60, max(H * 0.40, H * 0.58 - th * 0.5))
        ty = max(ty, lang.margin + 60)
        ctx.out(OPS.text(Box(tx, ty, tw, th), lines, size=size, lang=lang,
                         color=ctx.on, leading=lang.leading,
                         bold=lang.bold_title, font=lang.display,
                         ea=lang.ea_display))
        y = ty + th + 14
        if sub:
            slines, sh = OPS.measure_para(sub, min(tw, tw * 0.9), lang.type.small,
                                          lang, leading=1.55)
            ctx.out(OPS.text(Box(tx, y, min(tw, tw * 0.9), sh), slines,
                             size=lang.type.small, lang=lang, color=ctx.body_c,
                             leading=1.55))
        base = H - lang.margin - 10
        ctx.out(OPS.rule(Box(tx, base, 40, 1.6), ctx.accent, 1.6))
        meta_line = meta or ctx.brand
        if meta_line:
            ref = ctx.panel_c if lang.id == "sweet" else ctx.bg
            ctx.out(OPS.kicker(Box(tx + 52, base - 6, tw - 52, 13), meta_line, lang,
                               ink_on(lang.meta_c, ref, 4.8)))
        return ctx.bg

    # ---- 纯字色块 / poster
    bg = ctx.bg
    poster = v == "poster" or str(p.get("align") or "").lower() in ("center", "居中")
    tx = lang.margin * 1.1
    tw = W - tx * 2
    if poster:
        tw = W - lang.margin * 2
    size, lines = TM.headline(title, tw, H * 0.38, lang.type.ladder("cover"),
                              lang.display, lang.ea_display,
                              bold=lang.bold_title, leading=lang.leading)
    th = OPS.line_h(lines, size, lang.leading)
    ty = H * 0.56 - th * 0.6
    if poster:
        tx = (W - tw) / 2
    if kicker:
        ctx.out(OPS.kicker(Box(tx, ty - 34, tw, 14), kicker, lang,
                           accent_text(lang, bg, 4.6)))
    fill_img = p.get("fill_image")
    ctx.out(OPS.text(Box(tx, ty, tw, th), lines, size=size, lang=lang,
                     color=ctx.on if ctx.dark else lang.title_c,
                     leading=lang.leading, bold=lang.bold_title,
                     align=("ctr" if poster else "l"),
                     font=lang.display, ea=lang.ea_display,
                     image_fill=_fill_ok(fill_img)))
    if sub:
        sy = ty + th + 18
        slines, sh = OPS.measure_para(sub, tw * 0.62, lang.type.lead, lang,
                                      leading=1.45)
        ctx.out(OPS.text(Box(tx, sy, tw * 0.62, sh), slines, size=lang.type.lead,
                         lang=lang, color=ctx.body_c, leading=1.45))
    ctx.out(OPS.rule(Box(tx, H - lang.margin - 10, W - tx * 2, 0.8), ctx.rule_c, 0.8))
    if meta:
        ctx.out(OPS.kicker(Box(tx, H - lang.margin + 4, tw * 0.7, 12), meta, lang,
                           ctx.meta_c))
    return bg


# ---------------------------------------------------------------- 章节 / 主张


def _section(ctx):
    """章节页：左侧色块承托序号与标题，右侧留白。

    这是样板里「用形状分页」的做法（源 02 的黑块、源 04 的色块）：
    一整块矩形把页面切成两半，比任何装饰都更能定调。
    """
    lang, p = ctx.lang, ctx.page
    n = _txt(p.get("index") or p.get("no") or "")
    title = _txt(p.get("title"))
    lead = _txt(p.get("lead"))
    bg = ctx.bg
    area = safe(lang)
    block_w = (W * 0.44) if lang.id != "iron" else (W * 0.46)
    block_c = ctx.panel_c if not ctx.dark else PAL.mix(lang.paper_alt, "FFFFFF", 0.06)
    ctx.under(OPS.panel(Box(0, 0, block_w, H), block_c, 100))
    inner = Box(lang.margin, lang.margin, block_w - lang.margin * 1.5,
                H - lang.margin * 2)
    y = inner.y + H * 0.06
    if n:
        size = min(lang.type.cover * 1.5, 132)
        ctx.out(OPS.text(Box(inner.x, y, inner.w, size * 1.02), [n], size=size,
                         lang=lang, color=ink_on(ctx.accent, block_c, 2.4),
                         leading=1.0, bold=True, font=lang.display,
                         ea=lang.ea_display))
        y += size * 1.02 + 26
    ctx.out(OPS.rule(Box(inner.x, y, 46, 2.2), ctx.accent, 2.2))
    y += 26
    size, lines = TM.headline(title, inner.w, H * 0.30, lang.type.ladder("h1"),
                              lang.display, lang.ea_display,
                              bold=lang.bold_title, leading=lang.leading)
    th = OPS.line_h(lines, size, lang.leading)
    ctx.out(OPS.text(Box(inner.x, y, inner.w, th), lines, size=size, lang=lang,
                     color=ctx.on, leading=lang.leading, bold=lang.bold_title,
                     font=lang.display, ea=lang.ea_display))
    y += th + 18
    if lead:
        ll, lh = OPS.measure_para(lead, inner.w * 0.86, lang.type.small, lang,
                                  leading=1.5)
        ctx.out(OPS.text(Box(inner.x, y, inner.w * 0.86, lh), ll,
                         size=lang.type.small, lang=lang, color=ctx.body_c,
                         leading=1.5))
    ctx.out(OPS.rule(Box(inner.x, H - lang.margin - 4, 34, 1.6), ctx.accent, 1.6))
    return bg


def _statement(ctx):
    """一句话主张：用 display 字阶，垂直光学居中。"""
    lang, p, v = ctx.lang, ctx.page, ctx.variant
    text = _txt(p.get("statement") or p.get("title") or p.get("quote"))
    by = _txt(p.get("by") or p.get("source"))
    img = p.get("image")
    bg = ctx.bg
    area = safe(lang)
    on_image = False
    if v == "image" and _img_ok(img):
        ctx.out(OPS.media(Box(0, 0, W, H), img, fit="cover",
                          grayscale=(lang.media.grayscale or bool(p.get("mono"))),
                          scrim={"color": "000000", "alpha": 62, "mode": "full"}))
        bg = "111111"
        on_image = True
    center = str(p.get("align") or "").lower() in ("center", "c", "居中")
    tw = area.w * (0.80 if center else 0.86)
    sizes = [lang.type.cover * 0.94, lang.type.cover * 0.80, lang.type.h1,
             lang.type.h1 * 0.86, lang.type.h2, lang.type.h2 * 0.86]
    size, lines = fit_display(text, tw, area.h * 0.66, sizes, lang, max_lines=3)
    th = OPS.line_h(lines, size, lang.leading)
    block = th + (46 if by else 0)
    top = area.y + (area.h - block) * 0.44
    color = lang.on_dark if on_image else (ctx.on if not ctx.dark else lang.on_dark)
    _box_x = area.cx - tw / 2 if center else area.x
    ctx.out(OPS.rule(Box(_box_x if not center else area.cx - 20, top - 34, 40, 2),
                     ctx.accent, 2))
    fill_img = p.get("fill_image")
    ctx.out(OPS.text(Box(_box_x, top, tw, th), lines, size=size, lang=lang,
                     color=color, leading=lang.leading, align=("ctr" if center else "l"),
                     bold=lang.bold_title, font=lang.display, ea=lang.ea_display,
                     image_fill=_fill_ok(fill_img)))
    if by:
        ctx.out(OPS.kicker(Box(_box_x, top + th + 22, tw, 13), by, lang,
                           ctx.meta_c if not on_image and not ctx.dark else "D9D9D9",
                           align=("ctr" if center else "l")))
    return bg


# ---------------------------------------------------------------- 要点 / 数字


def _fit_list(items, width, height, lang, hang=18.0):
    """在「正文字阶 + 上一级」里挑最大字号，使整组装得下。"""
    sizes = []
    for s in (lang.type.lead, lang.type.body * 1.22, lang.type.body,
              lang.type.body * 0.92, lang.type.small):
        s = round(s, 1)
        if s not in sizes:
            sizes.append(s)
    sizes.sort(reverse=True)
    for s in sizes:
        ms = [OPS.measure_para(t, width, s, lang, leading=lang.body_leading, hang=hang)
              for t in items]
        total = sum(h for _, h in ms) + 14.0 * max(0, len(ms) - 1)
        if total <= height:
            return s, ms, total
    s = sizes[-1]
    ms = [OPS.measure_para(t, width, s, lang, leading=lang.body_leading, hang=hang)
          for t in items]
    return s, ms, sum(h for _, h in ms) + 14.0 * max(0, len(ms) - 1)


def _points(ctx):
    """要点：rail（标题做左书脊）/ plain（通栏）/ two（双栏）。"""
    lang, p, v = ctx.lang, ctx.page, ctx.variant
    title = _txt(p.get("title"))
    lead = _txt(p.get("lead"))
    note = _txt(p.get("note") or p.get("source"))
    items = p.get("items") or p.get("body") or []
    if isinstance(items, str):
        items = [items]
    items = [_txt(i.get("h") if isinstance(i, dict) else i) for i in items]
    items = [i for i in items if i]
    bg = ctx.bg
    if not items:
        return _statement(ctx)

    side = side_media(ctx, 0.38, str(p.get("media_side") or "r"))
    area = ctx.content()
    if side:
        area = Box(side[0], area.y, side[1], area.h)
    # 低于四条且无图，用 rail：左窄栏标题 + 右宽栏条目，天然不空
    if not side and (v == "rail" or (v == "" and len(items) <= 3)):
        railw = area.w * 0.32
        rail, right = area.take_left(railw)
        y = area.y + 2
        if _txt(p.get("kicker")):
            ctx.out(OPS.kicker(Box(rail.x, y, railw, 13), _txt(p.get("kicker")),
                               lang, ink_on(ctx.accent, ctx.bg_hint, 4.6)))
            y += 28
        size, lines = TM.headline(title, railw - 12, area.h * 0.42,
                                  lang.type.ladder("h2"), lang.display,
                                  lang.ea_display, bold=lang.bold_title,
                                  leading=lang.leading)
        th = OPS.line_h(lines, size, lang.leading)
        if y + th > area.b - 40:
            size = max(lang.type.h2 * 0.8, size * (area.b - 44 - y) / max(1.0, th))
            lines = TM.wrap_smart(title, size, railw - 12, lang.display,
                                  lang.ea_display, lang.bold_title)
            th = OPS.line_h(lines, size, lang.leading)
        ctx.out(OPS.text(Box(rail.x, y, railw - 12, th), lines, size=size,
                         lang=lang, color=ctx.on, leading=lang.leading,
                         bold=lang.bold_title, font=lang.display,
                         ea=lang.ea_display))
        y += th + 18
        if lead:
            ll, lh = OPS.measure_para(lead, railw - 26, lang.type.small, lang,
                                      leading=1.55)
            if y + lh < area.b - 30:
                ctx.out(OPS.text(Box(rail.x, y, railw - 26, lh), ll,
                                 size=lang.type.small, lang=lang, color=ctx.body_c,
                                 leading=1.55))
        ctx.out(OPS.rule(Box(rail.x, area.b - 2, 34, 1.6), ctx.accent, 1.6))
        body = Box(right.x + railw * 0.16, area.y + 4,
                   right.w - railw * 0.16 - lang.margin * 0.4, area.h - 8)
        hang = 30.0
        size, ms, total = _fit_list(items, body.w, body.h * 0.99, lang, hang)
        heights = [h for _, h in ms]
        max_gap = max(46.0, body.h / max(2, len(heights)) * 0.62)
        ys, gap = place(heights, body, 16.0, max_gap)
        if lang.id == "paper":
            for i, ((lines, h), yy) in enumerate(zip(ms, ys)):
                w = max(TM.text_width(l, size, lang.body_font, lang.ea_body)
                        for l in lines) + 52
                ctx.under(OPS.panel(Box(body.x + hang - 24, yy - 16, w, h + 30),
                                    "FFFFFF", 100, radius=3, shadow=True,
                                    rotate=(-0.8 if i % 2 == 0 else 0.5)))
        for i, ((lines, h), yy) in enumerate(zip(ms, ys)):
            ctx.out(OPS.text(Box(body.x - 2, yy - 3, 26, 13), ["%02d" % (i + 1)],
                             size=lang.type.micro, lang=lang,
                             color=ink_on(lang.accent2 if lang.id == "sweet" else ctx.accent,
                                          ctx.bg_hint, 4.6),
                             leading=1.1, font=lang.micro_font, ea=lang.ea_body))
            ctx.out(OPS.text(Box(body.x + hang, yy, body.w - hang, h), lines,
                             size=size, lang=lang, color=ctx.body_c,
                             leading=lang.body_leading, font=lang.body_font,
                             ea=lang.ea_body))
        ctx.foot(note)
        return bg

    if v == "two" and len(items) >= 4:
        ctx.head(title, kicker=_txt(p.get("kicker")), lead=lead,
                 width=(W - 2 * lang.margin) * 0.86)
        body = ctx.body_area(gap_after_head=26)
        half = (len(items) + 1) // 2
        cw = (body.w - 52) / 2
        boxes = [Box(body.x, body.y, cw, body.h),
                 Box(body.x + cw + 52, body.y, cw, body.h)]
        sizes_ok = min(
            _fit_list(items[:half], cw - 20, body.h * 0.97, lang, 20)[0],
            _fit_list(items[half:], cw - 20, body.h * 0.97, lang, 20)[0])
        for gi, grp in enumerate((items[:half], items[half:])):
            ms = [OPS.measure_para(t, cw - 20, sizes_ok, lang, leading=lang.body_leading,
                                   hang=20) for t in grp]
            ys, gap = place([h for _, h in ms], boxes[gi], 14.0, 40.0)
            for (lines, h), yy in zip(ms, ys):
                ctx.out(OPS.rule(Box(boxes[gi].x - 18, yy + 8, 10, 1.2), ctx.accent, 1.2))
                ctx.out(OPS.text(Box(boxes[gi].x, yy, cw, h), lines,
                                 size=sizes_ok, lang=lang, color=ctx.body_c,
                                 leading=lang.body_leading, font=lang.body_font,
                                 ea=lang.ea_body))
        ctx.out(OPS.rule(Box(body.cx - 0.4, body.y + 4, 0.8, body.h * 0.9),
                         ctx.rule_c, 0.8))
        ctx.foot(note)
        return bg

    colw = side[1] if side else (W - 2 * lang.margin) * 0.78
    ctx.head(title, kicker=_txt(p.get("kicker")), lead=lead, width=colw,
             x=(side[0] if side else None))
    if side:
        body = Box(side[0], ctx.head_bottom + 26, colw,
                   max(80.0, H - lang.margin - 30 - (ctx.head_bottom + 26)))
    else:
        body = ctx.body_area(gap_after_head=26)
    if lang.id == "sweet":
        ctx.under(OPS.panel(Box(body.x - 24, body.y - 18, body.w + 40,
                                body.h + 24), ctx.panel_c, 100,
                            radius=lang.radius_pt))
    hang = 20.0
    size, ms, total = _fit_list(items, body.w * (0.86 if lang.id == "paper" else 1.0),
                                body.h * 0.96, lang, hang)
    heights = [h for _, h in ms]
    ys, gap = place(heights, body, 15.0, 52.0)
    if lang.id == "paper":
        # 便签：文字不转，底板轻转，靠阴影分层（源 03 的构件，不是某一页的花招）
        for i, ((lines, h), yy) in enumerate(zip(ms, ys)):
            w = max(TM.text_width(l, size, lang.body_font, lang.ea_body)
                    for l in lines) + 56
            ctx.under(OPS.panel(Box(body.x + hang - 26, yy - 18, w, h + 34),
                                "FFFFFF", 100, radius=3,
                                shadow=True, rotate=(-0.9 if i % 2 == 0 else 0.6)))
    for (lines, h), yy in zip(ms, ys):
        if lang.id in ("paper", "grid", "manifesto"):
            ctx.out(OPS.rule(Box(body.x - 18, yy + 9, 11, 1.2), ctx.accent, 1.2))
        elif lang.id == "iron":
            ctx.out(OPS.rule(Box(body.x - 16, yy, 3, h), ctx.accent, 3))
        ctx.out(OPS.text(Box(body.x, yy, body.w, h), lines,
                         size=size, lang=lang, color=ctx.body_c,
                         leading=lang.body_leading, font=lang.body_font,
                         ea=lang.ea_body))
    ctx.foot(note)
    return bg


def _metrics(ctx):
    """数字页：row（横排）/ list（年报式，数字一列说明一列）/ 单指标。

    所有变体都先给结论留出位置，再排数字——避免「数字排满、结论被挤掉」。
    """
    lang, p, v = ctx.lang, ctx.page, ctx.variant
    title = _txt(p.get("title"))
    items = p.get("metrics") or p.get("stats") or []
    note = _txt(p.get("note") or p.get("source"))
    takeaway = _txt(p.get("takeaway"))
    bg = ctx.bg
    if not items:
        return _statement(ctx)
    side = side_media(ctx, 0.36, str(p.get("media_side") or "r"))
    head_w = (side[1] if side else (W - 2 * lang.margin) * 0.8)
    ctx.head(title, kicker=_txt(p.get("kicker")), lead=_txt(p.get("lead")),
             width=head_w, max_h=(H - lang.head_top) * 0.30,
             x=(side[0] if side else None))
    body = ctx.body_area(gap_after_head=32, foot_h=48)
    if side:
        body = Box(side[0], body.y, side[1],
                   max(80.0, H - lang.margin - 48 - body.y))
        ctx.foot_span = (side[0], side[1])
    n = len(items)

    def num_size(val, width, cap):
        s = cap
        while s > 18 and TM.text_width(val, s, lang.display, lang.ea_display, True) > width:
            s -= 1
        return s

    # 结论行先量出来，占掉底部
    ta_lines, ta_h = ([], 0.0)
    if takeaway:
        ta_lines, ta_h = OPS.measure_para(takeaway, body.w * 0.76, lang.type.body,
                                          lang, leading=lang.body_leading)
        ta_h += 30

    # ---------- 单指标
    if n == 1:
        it = items[0]
        val = _txt(it.get("v") or it.get("value"))
        lab = _txt(it.get("l") or it.get("label"))
        avail = body.h - ta_h
        s = num_size(val, body.w * 0.62, min(avail * 0.66, 200))
        th = s * 1.02
        llines, lh = OPS.measure_para(lab, body.w * 0.5, lang.type.lead, lang, leading=1.4)
        block = th + 14 + lh
        top = body.y + max(0.0, (avail - block) * 0.34)
        ctx.out(OPS.rule(Box(body.x, top - 26, 64, 2.4), ctx.accent, 2.4))
        ctx.out(OPS.text(Box(body.x - 2, top, body.w * 0.66, th), [val], size=s,
                         lang=lang, color=ctx.on, leading=1.0, bold=True,
                         font=lang.display, ea=lang.ea_display))
        ctx.out(OPS.text(Box(body.x, top + th + 14, body.w * 0.5, lh), llines,
                         size=lang.type.lead, lang=lang, color=ctx.body_c,
                         leading=1.4, font=lang.body_font, ea=lang.ea_body))
        if ta_lines:
            ty = body.y + body.h - ta_h + 26
            ctx.out(OPS.rule(Box(body.x, ty - 12, 10, 1.2), ctx.accent, 1.2))
            ctx.out(OPS.text(Box(body.x + 20, ty, body.w * 0.76, ta_h - 30),
                             ta_lines, size=lang.type.body, lang=lang,
                             color=ctx.body_c, leading=lang.body_leading))
        ctx.foot(note)
        return bg

    # ---------- 年报式
    if v == "list":
        nw = body.w * 0.34
        rows = []
        for it in items:
            val = _txt(it.get("v") or it.get("value"))
            lab = _txt(it.get("l") or it.get("label"))
            s = num_size(val, nw - 12, min((body.h - ta_h) * 0.30, 88))
            ll, lh = OPS.measure_para(lab, body.w - nw - 40, lang.type.body, lang,
                                      leading=lang.body_leading)
            rows.append((val, s, ll, max(s * 1.02, lh)))
        avail = body.h - ta_h
        unit_h = avail / n
        for i, (val, s, ll, hh) in enumerate(rows):
            yy = body.y + i * unit_h
            ctx.out(OPS.text(Box(body.x - 2, yy, nw, s * 1.04), [val], size=s,
                             lang=lang, color=ctx.on, leading=1.02, bold=True,
                             font=lang.display, ea=lang.ea_display))
            ctx.out(OPS.text(Box(body.x + nw + 26,
                                 yy + max(0.0, (s * 1.04 - len(ll) * lang.type.body * lang.body_leading) / 2 + 4),
                                 body.w - nw - 30, hh), ll,
                             size=lang.type.body, lang=lang, color=ctx.body_c,
                             leading=lang.body_leading))
            ctx.out(OPS.rule(Box(body.x, yy + unit_h - 10, body.w, 0.8), ctx.rule_c, 0.8))
        if ta_lines:
            ty = body.y + body.h - ta_h + 26
            ctx.out(OPS.text(Box(body.x, ty, body.w * 0.76, ta_h - 30), ta_lines,
                             size=lang.type.body, lang=lang, color=ctx.body_c,
                             leading=lang.body_leading))
        ctx.foot(note)
        return bg

    # ---------- 横排
    gutter = max(lang.gutter + 12, 34)
    cw = (body.w - gutter * (n - 1)) / n
    avail = body.h - ta_h
    cap = min(avail * (0.56 if ta_h else 0.66), 152 if not ta_h else 138)
    s = min(num_size(_txt(it.get("v") or it.get("value")), cw * 0.95, cap) for it in items)
    labels = []
    for it in items:
        ll, lh = OPS.measure_para(_txt(it.get("l") or it.get("label")), cw * 0.92,
                                  lang.type.small, lang, leading=1.5)
        labels.append((ll, lh))
    block_h = s * 1.04 + 12 + max(lh for _, lh in labels)
    top = body.y + max(0.0, (avail - block_h) * 0.40)
    if not ta_h:
        top = body.y + max(0.0, (avail - block_h) * 0.46)
    if lang.id == "sweet":
        ctx.under(OPS.panel(Box(body.x - 24, top - 58, body.w + 34, block_h + 82),
                            ctx.panel_c, 100, radius=lang.radius_pt))
    for i, it in enumerate(items):
        x = body.x + i * (cw + gutter)
        ctx.out(OPS.rule(Box(x, top - 26, min(cw * 0.5, 96), 1.8), ctx.accent, 1.8))
        num_color = (ink_on(ctx.pal_accent, ctx.panel_c, 3.1)
                     if (lang.id == "sweet" and i == 0) else ctx.on)
        ctx.out(OPS.text(Box(x, top, cw, s * 1.04),
                         [_txt(it.get("v") or it.get("value"))], size=s, lang=lang,
                         color=num_color, leading=1.0, bold=True,
                         font=lang.display, ea=lang.ea_display))
        ll, lh = labels[i]
        ctx.out(OPS.text(Box(x, top + s * 1.04 + 16, cw * 0.92, lh), ll,
                         size=lang.type.small, lang=lang, color=ctx.body_c,
                         leading=1.5, font=lang.body_font, ea=lang.ea_body))
        if i:
            ctx.under(OPS.rule(Box(body.x + i * (cw + gutter) - gutter / 2 - 0.4,
                                   top - 38, 0.8, block_h + 38), ctx.rule_c, 0.8))
    if ta_lines:
        ty = body.y + body.h - ta_h + 26
        ctx.out(OPS.rule(Box(body.x - 18, ty - 12, 10, 1.2), ctx.accent, 1.2))
        ctx.out(OPS.text(Box(body.x, ty, body.w * 0.76, ta_h - 30), ta_lines,
                         size=lang.type.body, lang=lang, color=ctx.body_c,
                         leading=lang.body_leading))
    ctx.foot(note)
    return bg


# ---------------------------------------------------------------- 引语 / 图文


def _quote(ctx):
    """引语：大字衬线 + 出处；可选右侧窄图。"""
    lang, p = ctx.lang, ctx.page
    q = _txt(p.get("quote") or p.get("title"))
    by = _txt(p.get("by") or p.get("source"))
    img = p.get("image")
    bg = ctx.bg
    area = safe(lang)
    if _img_ok(img):
        iw = W * 0.34
        ctx.out(OPS.media(Box(W - iw, 0, iw, H), img, fit="cover",
                          grayscale=(lang.media.grayscale or bool(p.get("mono")))))
        tw = W - iw - lang.margin * 2
        ctx.foot_span = (lang.margin, tw)
    else:
        tw = area.w * 0.78
    shown = q if q.startswith("“") else "“" + q + "”"
    sizes = [lang.type.cover * 0.8, lang.type.h1, lang.type.h1 * 0.88,
             lang.type.h2, lang.type.h2 * 0.9, lang.type.lead]
    size, lines = fit_display(shown, tw, area.h * 0.56, sizes, lang, max_lines=4,
                              bold=False)
    th = OPS.line_h(lines, size, lang.leading)
    block = th + (44 if by else 0)
    y = area.y + (area.h - block) * 0.44
    if lang.id != "iron" and not ctx.dark:
        ctx.under(OPS.panel(Box(area.x - 34, y - 30, tw + 68, block + 54),
                            ctx.panel_c, 100,
                            radius=(14.0 if lang.id == "sweet" else 0.0)))
    ctx.out(OPS.text(Box(area.x, y, tw, th), lines, size=size, lang=lang,
                     color=ctx.on, leading=lang.leading, font=lang.display,
                     ea=lang.ea_display))
    if by:
        ctx.out(OPS.rule(Box(area.x, y + th + 20, 26, 1.4), ctx.accent, 1.4))
        ref = ctx.panel_c if (lang.id != "iron" and not ctx.dark) else ctx.bg
        ctx.out(OPS.kicker(Box(area.x + 38, y + th + 16, tw, 13), by, lang,
                           ink_on(ctx.meta_c, ref, 4.8)))
    return bg


def _split(ctx):
    """图文：图半幅/三分之一出血，正文按高度分布；缺图改密排。"""
    lang, p, v = ctx.lang, ctx.page, ctx.variant
    title = _txt(p.get("title"))
    lead = _txt(p.get("lead"))
    note = _txt(p.get("note") or p.get("source"))
    body_items = p.get("items") or p.get("body") or []
    if isinstance(body_items, str):
        body_items = [body_items]
    img = p.get("image")
    bg = ctx.bg

    placement = str(p.get("layout") or v or "").lower()
    side = p.get("side") or ("l" if placement == "left" else "r")
    frac = {"half": 0.46, "third": 0.36, "wide": 0.54}.get(p.get("media_frac", "half"), 0.46)

    # —— 图在上：通栏条 + 下置文字
    if placement == "stack" and _img_ok(img):
        ih = H * 0.52
        ctx.out(OPS.media(Box(0, 0, W, ih), img, fit="cover",
                          focus=p.get("focus", (0.5, 0.5))))
        head_w = W - 2 * lang.margin
        ctx.head(title, kicker=_txt(p.get("kicker")), lead="", width=head_w * 0.72,
                 max_h=(H - ih) * 0.46, y=ih + 26)
        body_y = max(ctx.head_bottom + 18, ih + 26)
        items2 = [(_txt(i.get("t")) if isinstance(i, dict) else _txt(i)) for i in body_items]
        items2 = [i for i in items2 if i]
        if items2:
            size, ms, total = _fit_list(items2, head_w, H - lang.margin - 26 - body_y, lang, 18)
            heights = [h for _, h in ms]
            ys, gap = place(heights, Box(lang.margin, body_y, head_w,
                                         H - lang.margin - 26 - body_y), 14.0, 40.0)
            for (lines, hh), yy in zip(ms, ys):
                ctx.out(OPS.rule(Box(lang.margin - 18, yy + 8, 10, 1.2), ctx.accent, 1.2))
                ctx.out(OPS.text(Box(lang.margin, yy, head_w, hh), lines,
                                 size=size, lang=lang, color=ctx.body_c,
                                 leading=lang.body_leading, font=lang.body_font,
                                 ea=lang.ea_body))
        ctx.foot(note)
        return bg

    # —— 满幅图 + 压在图上的面板
    if placement == "full" and _img_ok(img):
        ctx.out(OPS.media(Box(0, 0, W, H), img, fit="cover",
                          focus=p.get("focus", (0.5, 0.5)),
                          scrim={"color": "000000", "alpha": 58, "mode": "full"}))
        pw = W * 0.46
        panel = Box(lang.margin * 0.7, H * 0.16, pw, H * 0.62)
        ctx.out(OPS.panel(panel, "141414", 62, radius=card_radius(lang, panel)))
        inner = panel.inset(30, 28, 26, 22)
        y2 = inner.y
        if _txt(p.get("kicker")):
            ctx.out(OPS.kicker(Box(inner.x, y2, inner.w, 13), _txt(p.get("kicker")),
                               lang, "E8B96A"))
            y2 += 24
        size, lines = TM.headline(title, inner.w, inner.h * 0.4, lang.type.ladder("h1"),
                                  lang.display, lang.ea_display,
                                  bold=lang.bold_title, leading=lang.leading)
        th = OPS.line_h(lines, size, lang.leading)
        ctx.out(OPS.text(Box(inner.x, y2, inner.w, th), lines, size=size, lang=lang,
                         color=lang.on_dark, leading=lang.leading,
                         bold=lang.bold_title, font=lang.display, ea=lang.ea_display))
        y2 += th + 14
        if lead:
            ll, lh = OPS.measure_para(lead, inner.w, lang.type.small, lang, leading=1.5)
            ctx.out(OPS.text(Box(inner.x, y2, inner.w, lh), ll, size=lang.type.small,
                             lang=lang, color="E6E6E6", leading=1.5))
            y2 += lh + 12
        for it in body_items[:3]:
            t = _txt(it.get("t") if isinstance(it, dict) else it)
            if not t:
                continue
            tl, th2 = OPS.measure_para(t, inner.w - 14, lang.type.small, lang,
                                       leading=1.45)
            if y2 + th2 > inner.b:
                break
            ctx.out(OPS.rule(Box(inner.x - 14, y2 + 7, 9, 1.2), "E8B96A", 1.2))
            ctx.out(OPS.text(Box(inner.x, y2, inner.w, th2), tl, size=lang.type.small,
                             lang=lang, color="EDEDED", leading=1.45))
            y2 += th2 + 10
        ctx.foot_span = (lang.margin, W * 0.5)
        ctx.foot(note)
        return bg
    if _img_ok(img):
        iw = W * frac
        ibox = Box(0, 0, iw, H) if side == "l" else Box(W - iw, 0, iw, H)
        shape = str(p.get("media_shape") or "").lower()
        if shape in ("circle", "rounded-panel"):
            d = min(ibox.w, H) * (0.72 if shape == "circle" else 0.8)
            cx = ibox.cx - d / 2
            cy = H / 2 - d / 2
            rad = d / 2 if shape == "circle" else 24.0
            ctx.out(OPS.panel(Box(cx, cy, d, d), ctx.panel_c, 100, radius=rad,
                              image=img))
        else:
            ctx.out(OPS.media(ibox, img, fit="cover",
                              focus=p.get("focus", (0.5, 0.5)),
                              radius=lang.media.radius_pt,
                              grayscale=(lang.media.grayscale or bool(p.get("mono"))),
                              tint=(lang.accent2 if lang.media.duotone else None)))
        if lang.id in ("paper", "manifesto"):
            ctx.under(OPS.rule(Box(ibox.x + (14 if side == "l" else -14), 0,
                                   0.8, H), ctx.rule_c, 0.8))
        cw = W - iw - lang.margin * 1.8
        cx = lang.margin if side == "r" else iw + lang.margin * 0.9
        ctx.foot_span = (cx, cw)
    else:
        cw = W - lang.margin * 2
        cx = lang.margin
    ctx.head(title, kicker=_txt(p.get("kicker")), lead=lead, width=cw,
             max_h=H * 0.30, x=cx)
    body = Box(cx, ctx.head_bottom + 30, cw,
               H - lang.margin - 26 - (ctx.head_bottom + 30))

    blocks = []
    for it in body_items:
        if isinstance(it, dict):
            h = _txt(it.get("h"))
            t = _txt(it.get("t") or it.get("body"))
            if h:
                hl, hh = OPS.measure_para(h, cw, lang.type.small, lang, bold=True,
                                          leading=1.3)
                blocks.append(("h", hl, hh, lang.type.small))
            if t:
                tl, thh = OPS.measure_para(t, cw, lang.type.body, lang,
                                           leading=lang.body_leading)
                blocks.append(("t", tl, thh, lang.type.body))
        else:
            tl, thh = OPS.measure_para(_txt(it), cw, lang.type.body, lang,
                                       leading=lang.body_leading)
            blocks.append(("t", tl, thh, lang.type.body))
    for f in p.get("facts") or []:
        vv, ll = _txt(f.get("v")), _txt(f.get("l"))
        s = min(lang.type.lead, 30)
        while s > 14 and TM.text_width(vv, s, lang.display, lang.ea_display, True) > cw * 0.45:
            s -= 1
        blocks.append(("kv", [vv], s * 1.05, s, True))
        blocks.append(("kv", [ll], lang.type.micro * 1.6, lang.type.micro))

    heights = [b[2] for b in blocks]
    gaps = []
    for i, b in enumerate(blocks):
        if i == 0:
            gaps.append(0)
        elif b[0] == "kv" and blocks[i - 1][0] == "kv":
            gaps.append(3)
        elif b[0] == "h":
            gaps.append(20)
        elif blocks[i - 1][0] == "t" and b[0] == "t":
            gaps.append(20)
        else:
            gaps.append(12)
    if not blocks:
        ctx.foot(note)
        return bg
    # 装不下就降一档字号，绝不溢出
    shrink = 1.0
    while sum(heights) + sum(gaps) > body.h and shrink > 0.80:
        shrink -= 0.04
        heights = [h * shrink for h in heights]
        gaps = [g * shrink for g in gaps]
    total = sum(heights) + sum(gaps)
    if sum(heights) + sum(gaps) > body.h + 1 and shrink <= 0.81:
        raise ValueError(
            f"第 {ctx.idx} 页正文放不下（需要 {total:.0f}pt，正文区 {body.h:.0f}pt）；"
            "请拆页或精简文字")
    y = body.y + max(0.0, min(body.h - total, (body.h - total) * 0.40))
    y = max(body.y, y)
    for (kind, lines, hh, size), g in zip(blocks, gaps):
        y += g
        hh = hh * shrink
        size = size * shrink
        if kind == "h":
            ctx.under(OPS.rule(Box(cx, y + 3, 2.4, 14), ctx.accent, 2.4))
            ctx.out(OPS.text(Box(cx + 16, y, cw - 16, hh), lines, size=size,
                             lang=lang, color=ctx.on, leading=1.3, bold=True,
                             font=lang.display, ea=lang.ea_display))
        else:
            ctx.out(OPS.text(Box(cx, y, cw, hh), lines, size=size, lang=lang,
                             color=ctx.on if kind == "kv" else ctx.body_c,
                             leading=(1.05 if kind == "kv" else lang.body_leading),
                             bold=(kind == "kv"),
                             font=(lang.display if kind == "kv" else lang.body_font),
                             ea=(lang.ea_display if kind == "kv" else lang.ea_body)))
        y += hh
    ctx.foot(note)
    return bg


def _compare(ctx):
    """左右对比：中缝细线，栏头同基线。"""
    lang, p = ctx.lang, ctx.page
    title = _txt(p.get("title"))
    cols = p.get("columns") or []
    bg = ctx.bg
    if not cols:
        return _split(ctx)
    side = None
    ctx.head(title, kicker=_txt(p.get("kicker")), lead=_txt(p.get("lead")),
             width=(W - 2 * lang.margin) * 0.82)
    body = ctx.body_area(gap_after_head=30, foot_h=34)
    n = max(1, len(cols))
    gutter = 54
    cw = (body.w - gutter * (n - 1)) / n
    measured = []
    for c in cols:
        items = c.get("body") or c.get("items") or []
        if isinstance(items, str):
            items = [items]
        ms = [OPS.measure_para(_txt(it), cw, lang.type.body, lang,
                               leading=lang.body_leading) for it in items]
        measured.append(ms)
    head_h = lang.type.small * 1.5 + 30
    tallest = max([sum(h for _, h in ms) + 14 * max(0, len(ms) - 1) for ms in measured] or [0])
    top = body.y + max(0.0, (body.h - tallest - head_h) * 0.34)
    if len(cols) >= 2:
        ctx.under(OPS.panel(Box(body.x - 26, top - 26, cw + 52, body.b - top + 34),
                            ctx.panel_c, 100,
                            radius=(12.0 if lang.id == "sweet" else 0.0)))
    for i, c in enumerate(cols):
        x = body.x + i * (cw + gutter)
        ctx.out(OPS.text(Box(x, top, cw, lang.type.small * 1.5), [_txt(c.get("head"))],
                         size=lang.type.small, lang=lang, color=ctx.on,
                         leading=1.3, bold=True, font=lang.display,
                         ea=lang.ea_display))
        ctx.out(OPS.rule(Box(x, top + lang.type.small * 1.5 + 8, cw,
                             1.4 if i == 0 else 0.9),
                         ctx.accent if i == 0 else ctx.rule_c,
                         1.4 if i == 0 else 0.9))
        items_area = Box(x, top + lang.type.small * 1.5 + head_h, cw,
                         max(40.0, body.b - (top + lang.type.small * 1.5 + head_h) - 10))
        ys, _g = place([h for _, h in measured[i]], items_area, 14.0, 46.0)
        for (ll, hh), yy in zip(measured[i], ys):
            ctx.out(OPS.text(Box(x, yy, cw, hh), ll, size=lang.type.body, lang=lang,
                             color=ctx.body_c, leading=lang.body_leading))
        if i:
            ctx.out(OPS.rule(Box(x - gutter / 2 - 0.4, top, 0.8, body.h * 0.88),
                             ctx.rule_c, 0.8))
    ctx.foot(_txt(p.get("source")))
    return bg


# ---------------------------------------------------------------- 表 / 图 / 图集


def _table(ctx):
    """表：行高撑满正文区；表底一行注释。"""
    lang, p = ctx.lang, ctx.page
    title = _txt(p.get("title"))
    note = _txt(p.get("note") or p.get("source"))
    takeaway = _txt(p.get("takeaway"))
    bg = ctx.bg
    rows = p.get("rows") or []
    cols = p.get("columns") or []
    if not rows or not cols:
        return _split(ctx)
    side = side_media(ctx, 0.30, str(p.get("media_side") or "r"))
    ctx.head(title, kicker=_txt(p.get("kicker")), lead=_txt(p.get("lead")),
             width=(side[1] if side else (W - 2 * lang.margin) * 0.7),
             max_h=(H - lang.head_top) * 0.28, x=(side[0] if side else None))
    body = ctx.body_area(gap_after_head=24, foot_h=54)
    if side:
        body = Box(side[0], body.y, side[1], max(80.0, H - lang.margin - 54 - body.y))
        ctx.foot_span = (side[0], side[1])
    note_h = 26 if takeaway else 0
    avail = body.h - note_h
    head_h = 34
    row_h = max(34.0, min(84.0, (avail - head_h) / max(1, len(rows))))
    # 行太多时先压行高与字号；压到地板仍放不下 → 明确报错（不静默溢出）
    floor_h, floor_head = 20.0, 26.0
    while head_h + row_h * len(rows) > avail and row_h > floor_h:
        row_h = max(floor_h, row_h - 2.0)
        head_h = max(floor_head, head_h - 0.5)
    if head_h + row_h * len(rows) > avail + 0.5:
        raise ValueError(
            f"表格放不下：{len(rows)} 行需要 {head_h + row_h*len(rows):.0f}pt，"
            f"正文区只有 {avail:.0f}pt；请拆页或删行")
    h = head_h + row_h * len(rows)
    if h < avail - 60:
        head_h += min(30, (avail - 60 - h) * 0.5)
        row_h += min(22, (avail - 60 - h) * 0.5 / max(1, len(rows)))
        h = head_h + row_h * len(rows)
    ctx.out(OPS.table(Box(body.x, body.y, body.w, h), {
        "columns": cols, "rows": rows, "lang": lang,
        "head_fill": ctx.panel_c,
        "head_h": head_h, "row_h": row_h,
        "size": min(lang.type.small, 14), "head_size": min(lang.type.small, 13.5),
        "head_color": ctx.on, "color": ctx.body_c, "rule_color": ctx.rule_c,
    }))
    if takeaway:
        tl, th = OPS.measure_para(takeaway, body.w * 0.66, lang.type.small, lang,
                                  leading=1.5)
        ctx.out(OPS.rule(Box(body.x, body.y + h + 18, 10, 1.2), ctx.accent, 1.2))
        ctx.out(OPS.text(Box(body.x + 20, body.y + h + 14, body.w * 0.66, th), tl,
                         size=lang.type.small, lang=lang, color=ctx.body_c,
                         leading=1.5))
    ctx.foot(note)
    return bg


def _chart(ctx):
    """图：左侧图占主体（对齐正文左边距），右侧一列结论。"""
    lang, p = ctx.lang, ctx.page
    title = _txt(p.get("title"))
    note = _txt(p.get("note") or p.get("source"))
    takeaway = p.get("takeaway") or p.get("items") or []
    if isinstance(takeaway, str):
        takeaway = [takeaway]
    bg = ctx.bg
    side = side_media(ctx, 0.30, str(p.get("media_side") or "r"))
    ctx.head(title, kicker=_txt(p.get("kicker")), lead=_txt(p.get("lead")),
             width=(side[1] if side else (W - 2 * lang.margin) * 0.8),
             max_h=(H - lang.head_top) * 0.28, x=(side[0] if side else None))
    body = ctx.body_area(gap_after_head=24, foot_h=48)
    if side:
        body = Box(side[0], body.y, side[1], max(80.0, H - lang.margin - 48 - body.y))
    has_side = bool(takeaway)
    if has_side:
        cw = body.w * 0.30
        cbox = Box(body.x + body.w - cw, body.y, cw, body.h)
        gbox = Box(body.x, body.y, body.w - cw - 44, body.h)
    else:
        gbox = body
    series = p.get("series") or []
    ctx.out(OPS.chart(gbox, {
        "categories": p.get("categories") or [],
        "series": [(s.get("name", ""), s.get("values") or []) if isinstance(s, dict)
                   else ("", s) for s in series] or [("", p.get("values") or [])],
        "kind": p.get("chart_type") or p.get("form") or "bar",
        "lang": lang, "colors": p.get("colors") or [ctx.accent, ctx.pal_accent],
        "legend": bool(p.get("legend")),
        "unit": p.get("unit", ""),
        "labels": p.get("labels", True),
        "gridlines": bool(p.get("gridlines")),
        "gap": p.get("gap", 84),
        "ink": ctx.body_c, "meta": ctx.meta_c, "paper": bg,
        "rule": ctx.rule_c,
        "label_size": min(lang.type.small, 13),
        "tick_size": min(lang.type.micro + 1, 11),
    }))
    if has_side:
        ms = [OPS.measure_para(_txt(it), cw - 20, lang.type.small, lang,
                               leading=lang.body_leading) for it in takeaway]
        heights = [h for _, h in ms]
        ys, gap = place(heights, cbox, 16.0, 40.0)
        for (lines, hh), yy in zip(ms, ys):
            ctx.out(OPS.rule(Box(cbox.x - 18, yy + 7, 10, 1.2), ctx.accent, 1.2))
            ctx.out(OPS.text(Box(cbox.x, yy, cw, hh), lines,
                             size=lang.type.small, lang=lang, color=ctx.body_c,
                             leading=lang.body_leading))
    ctx.foot(note)
    return bg


def _gallery(ctx):
    """图集：2–3 张等高图 + 图注。"""
    lang, p = ctx.lang, ctx.page
    title = _txt(p.get("title"))
    imgs = [i for i in (p.get("images") or [])
            if _img_ok(i if isinstance(i, str) else i.get("path"))]
    caps = p.get("captions") or []
    bg = ctx.bg
    if not imgs:
        return _split(ctx)
    ctx.head(title, kicker=_txt(p.get("kicker")), lead=_txt(p.get("lead")),
             width=(W - 2 * lang.margin) * 0.8, max_h=(H - lang.head_top) * 0.26)
    body = ctx.body_area(gap_after_head=24, foot_h=44)
    n = len(imgs)
    gap = lang.gutter
    cw = (body.w - gap * (n - 1)) / n
    cap_h = 26 if caps else 0
    for i, im in enumerate(imgs):
        path = im if isinstance(im, str) else im.get("path")
        x = body.x + i * (cw + gap)
        ctx.out(OPS.media(Box(x, body.y, cw, body.h - cap_h), path, fit="cover",
                          radius=lang.media.radius_pt,
                          grayscale=(lang.media.grayscale or bool(p.get("mono")))))
        if caps:
            c = _txt(caps[i]) if i < len(caps) else ""
            ctx.out(OPS.text(Box(x, body.b - cap_h + 8, cw, 16), [c],
                             size=lang.type.micro, lang=lang, color=ctx.meta_c,
                             leading=1.2, font=lang.micro_font, ea=lang.ea_body))
    ctx.foot(_txt(p.get("source")))
    return bg


def _closing(ctx):
    """结尾四选一：满幅图 / 色块 / 左右分栏 / 安静收束。plan() 会轮换。"""
    lang, p = ctx.lang, ctx.page
    line = _txt(p.get("title") or p.get("line") or "谢谢")
    sub = _txt(p.get("sub") or p.get("lead"))
    img = p.get("image")
    bg = ctx.bg
    variant = str(p.get("variant") or "").lower()
    if not variant:
        variant = "full" if _img_ok(img) else ("block" if lang.id != "grid" else "quiet")
    center = _want_center(ctx, "closing")

    # —— 满幅图
    if variant == "full" and _img_ok(img):
        bg = "141414"
        ctx.out(OPS.media(Box(0, 0, W, H), img, fit="cover",
                          focus=p.get("focus", (0.5, 0.5)),
                          grayscale=(lang.media.grayscale or bool(p.get("mono"))),
                          scrim={"color": "000000", "alpha": 72, "mode": "bottom"}))
        size, lines = fit_display(line, W * 0.62, H * 0.2,
                                  [lang.type.cover, lang.type.h1, lang.type.h2],
                                  lang, max_lines=2)
        th = OPS.line_h(lines, size, lang.leading)
        ty = H * 0.76 - th
        bx = W / 2 - W * 0.31 if center else lang.margin
        ctx.out(OPS.text(Box(bx, ty, W * 0.62, th), lines, size=size, lang=lang,
                         color=lang.on_dark, leading=lang.leading,
                         align=("ctr" if center else "l"),
                         bold=lang.bold_title, font=lang.display, ea=lang.ea_display))
        ctx.out(OPS.rule(Box(bx if not center else W / 2 - 20, ty - 22, 40, 1.6),
                         ctx.accent, 1.6))
        if sub:
            ctx.out(OPS.text(Box(bx, ty + th + 14, W * 0.55, 18), [sub],
                             size=lang.type.small, lang=lang, color="DFDFDF",
                             leading=1.3, align=("ctr" if center else "l")))
        return bg

    # —— 左右分栏：一半色块一半图
    if variant == "split" and _img_ok(img):
        half = W * 0.5
        block_c = ctx.pal_accent if (ctx.pal and lang.palette_mode == "both") else ctx.accent
        block_c = ink_on(block_c, bg, 3.0)
        ctx.under(OPS.panel(Box(0, 0, half, H), block_c, 100))
        ctx.out(OPS.media(Box(half, 0, half, H), img, fit="cover"))
        on = "FFFFFF" if contrast(block_c, "FFFFFF") >= 3.0 else "111111"
        size, lines = fit_display(line, half - lang.margin * 2, H * 0.26,
                                  [lang.type.h1, lang.type.h2, lang.type.lead],
                                  lang, max_lines=2)
        th = OPS.line_h(lines, size, lang.leading)
        ty = H * 0.5 - th / 2
        ctx.out(OPS.text(Box(lang.margin, ty, half - lang.margin * 2, th), lines,
                         size=size, lang=lang, color=on, leading=lang.leading,
                         bold=lang.bold_title, font=lang.display, ea=lang.ea_display))
        if sub:
            ctx.out(OPS.text(Box(lang.margin, ty + th + 16, half - lang.margin * 2, 18),
                             [sub], size=lang.type.small, lang=lang, color=on,
                             leading=1.3))
        return bg

    # —— 安静收束：上下色带
    if variant == "quiet":
        band_c = ctx.pal_accent if (ctx.pal and lang.palette_mode == "both") else ctx.accent
        band_c = ink_on(band_c, bg, 3.0)
        ctx.under(OPS.rule(Box(lang.margin, H - lang.margin - 40, W - lang.margin * 2, 1.2),
                           ctx.rule_c, 1.2))
        size, lines = fit_display(line, W * 0.7, H * 0.24,
                                  [lang.type.h1, lang.type.h2, lang.type.lead],
                                  lang, max_lines=2)
        th = OPS.line_h(lines, size, lang.leading)
        ty = H * 0.46 - th / 2
        ctx.out(OPS.text(Box(lang.margin, ty, W * 0.7, th), lines, size=size, lang=lang,
                         color=ctx.on, leading=lang.leading, bold=lang.bold_title,
                         font=lang.display, ea=lang.ea_display))
        ctx.out(OPS.rule(Box(lang.margin, ty - 26, 36, 2), band_c, 2))
        if sub:
            ctx.out(OPS.text(Box(lang.margin, ty + th + 16, W * 0.6, 18), [sub],
                             size=lang.type.small, lang=lang, color=ctx.body_c,
                             leading=1.3))
        return bg

    # —— 色块（默认）
    band_c = ctx.pal_accent if (ctx.pal and lang.palette_mode == "both") else ctx.accent
    band_c = ink_on(band_c, bg, 3.0)
    band = Box(0, H * 0.60, W, H * 0.40)
    ctx.under(OPS.panel(band, band_c, 100))
    on_band = "FFFFFF" if contrast(band_c, "FFFFFF") >= 3.0 else "111111"
    size, lines = fit_display(line, W * 0.7, band.h * 0.58,
                              [lang.type.cover * 0.8, lang.type.h1, lang.type.h1 * 0.86,
                               lang.type.h2], lang, max_lines=2)
    th = OPS.line_h(lines, size, lang.leading)
    ty = band.y + (band.h - th) / 2 - (20 if sub else 0)
    bx = (W - W * 0.7) / 2 if center else lang.margin
    ctx.out(OPS.text(Box(bx, ty, W * 0.7, th), lines, size=size, lang=lang,
                     color=on_band, leading=lang.leading,
                     align=("ctr" if center else "l"),
                     bold=lang.bold_title, font=lang.display, ea=lang.ea_display))
    if sub:
        ctx.out(OPS.text(Box(bx, ty + th + 16, W * 0.55, 20), [sub],
                         size=lang.type.small, lang=lang, color=on_band,
                         leading=1.3, align=("ctr" if center else "l")))
    return bg


# ---------------------------------------------------------------- 图形页

def _cards(ctx):
    """卡片组：2–4 张，圆角 16.667%、可带图、文字在卡内垂直居中且绝不溢出。"""
    lang, p = ctx.lang, ctx.page
    title = _txt(p.get("title"))
    kicker = _txt(p.get("kicker"))
    note = _txt(p.get("note") or p.get("source"))
    cards = p.get("cards") or p.get("items") or []
    if isinstance(cards, str):
        cards = [{"h": cards}]
    if not cards:
        return _points(ctx)
    cards = [c if isinstance(c, dict) else {"h": _txt(c)} for c in cards]
    bg = ctx.bg
    ctx.head(title, kicker=kicker, lead="",
             width=(W - 2 * lang.margin) * 0.8, max_h=(H - lang.head_top) * 0.26)
    body = ctx.body_area(gap_after_head=30, foot_h=44)

    n = len(cards)
    cols = 2 if n in (2, 4) else min(3, n)
    rows = 1 if n <= 3 else 2
    gap = max(20.0, lang.gutter + 4)
    cw = (body.w - gap * (cols - 1)) / cols
    ch = (body.h - gap * (rows - 1)) / rows
    pad = 28.0 if cw > 240 else 22.0

    for i, c in enumerate(cards):
        r, cc = divmod(i, cols)
        x = body.x + cc * (cw + gap)
        y = body.y + r * (ch + gap)
        box = Box(x, y, cw, ch)
        rad = card_radius(lang, box)
        dark_card = lang.id == "iron"
        if lang.id == "iron":
            ctx.under(OPS.panel(box, "141414", 100))
            ctx.under(OPS.rule(Box(x, y, cw, 4), ctx.accent, 4))
        elif lang.id == "grid":
            ctx.under(OPS.panel(box, ctx.panel_c, 100))
            ctx.under(OPS.rule(Box(x, y, cw, 1.6), ctx.accent, 1.6))
        else:
            ctx.under(OPS.panel(box, ctx.panel_c, 100, radius=rad,
                                shadow=_shadow_of(lang)))
        on_card = lang.on_dark if dark_card else ctx.on
        body_card = lang.on_dark if dark_card else ctx.body_c

        img = c.get("image")
        inner_top = y + pad
        if _img_ok(img):
            # 图在卡内留边，圆角比卡略小——像"卡上贴一张照片"，而不是图切卡
            ih = ch * 0.40
            ipad = pad * 0.72
            ctx.out(OPS.media(Box(x + ipad, y + ipad, cw - ipad * 2, ih), img,
                              fit="cover",
                              radius=max(0.0, rad - ipad * 0.5)))
            inner_top = y + ipad + ih + pad * 0.62
        inner = Box(x + pad, inner_top, cw - pad * 2,
                    max(24.0, (y + ch - pad * 0.7) - inner_top))

        # 量：数字 → 小标题 → 说明（可缩可截）
        num = _txt(c.get("v") or c.get("no"))
        head_t = _txt(c.get("h") or c.get("head") or c.get("title"))
        body_t = _txt(c.get("t") or c.get("body") or c.get("text"))
        blocks = []
        yy = 0.0
        if num:
            s_num = min(lang.type.h1, 56)
            while s_num > 18 and TM.text_width(num, s_num, lang.display,
                                               lang.ea_display, True) > inner.w:
                s_num -= 1
            blocks.append(("num", [num], s_num * 1.06, s_num, True))
            yy += s_num * 1.06 + 10
        if head_t:
            hl, hh = OPS.measure_para(head_t, inner.w, lang.type.body, lang,
                                      bold=True, leading=1.35)
            blocks.append(("head", hl, hh, lang.type.body, True))
            yy += hh + 10
        if body_t:
            room = inner.h - yy
            s_body = lang.type.small
            while s_body > 10.5:
                tl, th = OPS.measure_para(body_t, inner.w, s_body, lang,
                                          leading=lang.body_leading)
                if th <= room:
                    break
                s_body -= 0.5
            tl, th = OPS.measure_para(body_t, inner.w, s_body, lang,
                                      leading=lang.body_leading)
            max_lines = max(1, int(room / (s_body * lang.body_leading)))
            if len(tl) > max_lines:
                tl = tl[:max_lines]
                tl[-1] = tl[-1][:max(1, len(tl[-1]) - 1)] + "…"
                th = len(tl) * s_body * lang.body_leading
            blocks.append(("body", tl, th, s_body, False))

        total = sum(b[2] for b in blocks) + 10 * max(0, len(blocks) - 1)
        # 硬保证：总高超过可用高度就按比例缩，绝不出卡
        if total > inner.h and blocks:
            k = inner.h / total
            blocks = [(a, b, h * k, max(9.0, s * k), d) for a, b, h, s, d in blocks]
            total = sum(b[2] for b in blocks) + 10 * max(0, len(blocks) - 1)
        top = inner.y + max(0.0, (inner.h - total) * 0.42)
        for kind, lines, hh, size, bold in blocks:
            ctx.out(OPS.text(Box(inner.x, top, inner.w, hh), lines, size=size,
                             lang=lang,
                             color=(on_card if bold else body_card),
                             leading=(1.06 if kind == "num" else
                                      (1.35 if kind == "head" else lang.body_leading)),
                             bold=bold, font=(lang.display if kind == "num" else lang.body_font),
                             ea=(lang.ea_display if kind == "num" else lang.ea_body)))
            top += hh + 10
    ctx.foot(note)
    return bg


def _band(ctx):
    """色带页：一条通栏色带托住数字组，上方纸面留标题。

    色带是样板里最强的一类「形状」（源 02 的红块、源 04 的蓝条），
    它把页面切成上下两半，比任何装饰都更能打破单调。
    """
    lang, p = ctx.lang, ctx.page
    title = _txt(p.get("title"))
    lead = _txt(p.get("lead"))
    note = _txt(p.get("note") or p.get("source"))
    items = p.get("metrics") or p.get("stats") or []
    takeaway = _txt(p.get("takeaway"))
    bg = ctx.bg
    band_c = ctx.pal_accent if (ctx.pal and lang.palette_mode == "both") else ctx.accent
    if lang.id == "sweet":
        band_c = ink_on(band_c, bg, 3.0)
    img = p.get("image")
    if _img_ok(img):
        top_h = H - lang.margin - H * (0.40 if items else 0.34) + 12
        ctx.under(OPS.media(Box(0, 0, W, top_h), img, fit="cover",
                            scrim={"color": "FFFFFF", "alpha": 90, "mode": "full"}))
    band_h = H * (0.40 if items else 0.34)
    band = Box(0, H - lang.margin - band_h + 12, W, band_h)
    ctx.head(title, kicker=_txt(p.get("kicker")), lead=lead,
             width=(W - 2 * lang.margin) * 0.78,
             max_h=band.y - H * lang.head_top - 30)
    ctx.under(OPS.panel(band, band_c, 100))
    if not items:
        ctx.foot(note)
        return bg
    n = len(items)
    inner = Box(lang.margin, band.y + 34, W - 2 * lang.margin, band.h - 68)
    gutter = max(lang.gutter + 10, 28)
    cw = (inner.w - gutter * (n - 1)) / n
    vals = []
    for it in items:
        val = _txt(it.get("v") or it.get("value"))
        lab = _txt(it.get("l") or it.get("label"))
        s = min(inner.h * 0.46, 96)
        while s > 18 and TM.text_width(val, s, lang.display, lang.ea_display, True) > cw * 0.96:
            s -= 1
        ll, lh = OPS.measure_para(lab, cw * 0.94, lang.type.small, lang, leading=1.45)
        vals.append((val, s, ll, lh))
    block = max(v[1] * 1.04 + 14 + v[3] for v in vals)
    top = band.y + max(20.0, (band.h - block) / 2)
    on_band = "FFFFFF"
    for i, (val, s, ll, lh) in enumerate(vals):
        x = inner.x + i * (cw + gutter)
        ctx.out(OPS.text(Box(x, top - 20, cw * 0.42, 2.4), [], size=10, lang=lang,
                         color=on_band, leading=1.0) if False else OPS.rule(
                             Box(x, top - 22, min(cw * 0.4, 72), 2.0), on_band, 2.0))
        ctx.out(OPS.text(Box(x, top, cw, s * 1.06), [val], size=s, lang=lang,
                         color=on_band, leading=1.0, bold=True,
                         font=lang.display, ea=lang.ea_display))
        ctx.out(OPS.text(Box(x, top + s * 1.06 + 16, cw * 0.94, lh), ll,
                         size=lang.type.small, lang=lang, color=on_band,
                         leading=1.45, font=lang.body_font, ea=lang.ea_body))
    if takeaway:
        tl, th = OPS.measure_para(takeaway, (W - 2 * lang.margin) * 0.8, lang.type.small,
                                  lang, leading=1.5)
        ty = band.y - 20 - th
        if ty > H * lang.head_top + 40:
            ctx.out(OPS.text(Box(lang.margin, ty, (W - 2 * lang.margin) * 0.8, th), tl,
                             size=lang.type.small, lang=lang, color=ctx.body_c,
                             leading=1.5))
    ctx.foot(note)
    return bg


def _imagepanel(ctx):
    """图 + 压在图上的面板：面板从图片左侧压进来，形成前后层次。

    样板里最常见的「设计感」来源不是构图复杂，而是**两个矩形互相叠压**
    （源 01 P05、源 05 P09）。这一版把它做成独立页型。
    """
    lang, p = ctx.lang, ctx.page
    title = _txt(p.get("title"))
    lead = _txt(p.get("lead"))
    items = p.get("items") or p.get("body") or []
    if isinstance(items, str):
        items = [items]
    img = p.get("image")
    note = _txt(p.get("note") or p.get("source"))
    bg = ctx.bg
    if not _img_ok(img):
        return _split(ctx)
    iw = W * 0.60
    ctx.out(OPS.media(Box(W - iw, 0, iw, H), img, fit="cover",
                      focus=p.get("focus", (0.5, 0.5)),
                      grayscale=(lang.media.grayscale or bool(p.get("mono")))))
    panel_w = W * 0.46
    panel_h = H * 0.62
    px = lang.margin * 0.6
    py = H * 0.5 - panel_h * 0.42
    panel = Box(px, py, panel_w, panel_h)
    ctx.out(OPS.panel(panel, ctx.panel_c, 100,
                        radius=(16.0 if lang.id == "sweet" else 0.0),
                        shadow=(lang.id in ("sweet", "paper"))))
    ctx.foot_span = (panel.x, min(panel.w, W - iw - panel.x - 16))
    inner = panel.inset(34, 32, 30, 26)
    y = inner.y
    if _txt(p.get("kicker")):
        ctx.out(OPS.kicker(Box(inner.x, y, inner.w, 13), _txt(p.get("kicker")),
                           lang, ink_on(ctx.accent, ctx.panel_c, 4.6)))
        y += 26
    size, lines = TM.headline(title, inner.w, inner.h * 0.36,
                              lang.type.ladder("h1"), lang.display,
                              lang.ea_display, bold=lang.bold_title,
                              leading=lang.leading)
    th = OPS.line_h(lines, size, lang.leading)
    ctx.out(OPS.text(Box(inner.x, y, inner.w, th), lines, size=size, lang=lang,
                     color=ctx.on, leading=lang.leading, bold=lang.bold_title,
                     font=lang.display, ea=lang.ea_display))
    y += th + 16
    if lead:
        ll, lh = OPS.measure_para(lead, inner.w * 0.94, lang.type.small, lang,
                                  leading=1.5)
        ctx.out(OPS.text(Box(inner.x, y, inner.w * 0.94, lh), ll,
                         size=lang.type.small, lang=lang, color=ctx.body_c, leading=1.5))
        y += lh + 18
    for it in items[:3]:
        t = _txt(it.get("t") if isinstance(it, dict) else it)
        if not t:
            continue
        tl, th2 = OPS.measure_para(t, inner.w - 18, lang.type.small, lang,
                                   leading=lang.body_leading)
        if y + th2 > inner.b:
            break
        ctx.out(OPS.rule(Box(inner.x, y + 7, 9, 1.4), ctx.accent, 1.4))
        ctx.out(OPS.text(Box(inner.x + 18, y, inner.w - 18, th2), tl,
                         size=lang.type.small, lang=lang, color=ctx.body_c,
                         leading=lang.body_leading))
        y += th2 + 12
    ctx.foot(note)
    return bg


COMPOSITIONS = {
    "cover": _cover, "section": _section, "statement": _statement,
    "points": _points, "metrics": _metrics, "quote": _quote, "split": _split,
    "compare": _compare, "table": _table, "chart": _chart,
    "gallery": _gallery, "closing": _closing,
    "cards": _cards, "band": _band, "imagepanel": _imagepanel,
}

KIND_ALIASES = {
    "cover": "cover", "封面": "cover",
    "section": "section", "divider": "section", "章节": "section",
    "statement": "statement", "claim": "statement", "主张": "statement",
    "points": "points", "list": "points", "bullets": "points", "要点": "points",
    "metrics": "metrics", "numbers": "metrics", "stats": "metrics", "数字": "metrics",
    "quote": "quote", "引语": "quote",
    "split": "split", "content": "split", "text_image": "split", "图文": "split",
    "compare": "compare", "对比": "compare",
    "table": "table", "表": "table",
    "chart": "chart", "图": "chart",
    "gallery": "gallery", "images": "gallery", "图集": "gallery",
    "cards": "cards", "card": "cards", "卡片": "cards",
    "band": "band", "色带": "band",
    "imagepanel": "imagepanel", "overlay": "imagepanel", "叠压": "imagepanel",
    "closing": "closing", "end": "closing", "结尾": "closing",
}


def _kind(page):
    raw = str(page.get("kind") or page.get("type") or "split").strip().lower()
    if raw not in KIND_ALIASES:
        legal = " / ".join(sorted(set(KIND_ALIASES.values())))
        raise ValueError(f"未知页型 kind={raw!r}；可用：{legal}")
    return KIND_ALIASES[raw]


# ---------------------------------------------------------------- 册级节奏

MEDIA_LAYOUTS = ["side-r", "stack", "side-l", "full", "side-r", "stack"]
CLOSING_VARIANTS = ["full", "block", "split", "quiet", "full", "quiet"]

VARIANTS = {
    "cover": ["split-r", "bleed", "split", "block", "poster"],
    "section": ["plain"],
    "statement": ["plain", "image", "dark"],
    "points": ["plain", "rail", "two"],
    "metrics": ["row", "list"],
    "quote": ["plain"],
    "split": ["right", "left", "stack", "full"],
    "compare": ["plain"],
    "table": ["plain"],
    "chart": ["plain"],
    "gallery": ["plain"],
    "closing": ["plain"],
    "cards": ["plain"],
    "band": ["plain"],
    "imagepanel": ["plain"],
}


def _pick_variant(kind, page, recent):
    cands = list(VARIANTS.get(kind, ["plain"]))
    if kind == "points":
        n = len(page.get("items") or page.get("body") or [])
        lang = page.get("_lang")
        if (n and n <= 3 and "rail" in cands
                and getattr(lang, "id", "") != "iron"):
            cands = ["rail", "plain", "two"]
    # 有图才有图变体
    if kind in ("cover", "statement", "split", "closing"):
        if not _img_ok(page.get("image")):
            cands = [c for c in cands if c != "bleed" and c != "image"]
    if kind == "split":
        cands = [("left" if page.get("side") == "l" else "right")] + [
            c for c in cands if c != ("left" if page.get("side") == "l" else "right")]
    for c in cands:
        if c not in recent[-2:]:
            return c
    return cands[0] if cands else "plain"


def plan(pages, lang):
    """册级节奏：先定色调，再定变体。

    色调规则（不是随机，是可解释的）：
    - 封面/结尾有图就压深；
    - 章节页用深底或浅色板；
    - 深底页固定放在全册 45% 与（页数够时）结尾前一张，且只落在主张/图文/引语这类
      能承受反白的页型上；
    - 浅色板每三页一次，用来打断白纸，不连用。
    """
    n = len(pages)
    kinds = [_kind(p) for p in pages]
    dark_ok = "dark" in lang.tones
    tint_ok = str(lang.panel_c).upper() != str(lang.paper).upper()
    dark_slots, tint_slots = set(), set()
    if dark_ok and n >= 5:
        dark_slots.add(min(n - 2, max(2, int(round(n * 0.45)) - 1)))
    if dark_ok and n >= 8:
        dark_slots.add(max(3, n - 3))
    if tint_ok:
        for i in range(2, n - 1):
            if (i - 2) % 3 == 1:
                tint_slots.add(i)
    heavy = ("statement", "split", "quote", "metrics", "compare")

    for p in pages:
        p["_lang"] = lang
    out, recent = [], {}
    last_media = ""
    for i, (p, kind) in enumerate(zip(pages, kinds)):
        # 媒体布置：同一册内轮换，不允许连续两页同一布置
        if kind in ("split", "points", "metrics", "table", "chart", "imagepanel"):
            want = p.get("layout") or p.get("variant")
            if not want or want in ("right", "left"):
                cand = MEDIA_LAYOUTS[i % len(MEDIA_LAYOUTS)]
                if cand == last_media:
                    cand = MEDIA_LAYOUTS[(i + 1) % len(MEDIA_LAYOUTS)]
                p["layout"] = cand
                last_media = cand
        if kind == "closing" and not p.get("variant"):
            p["variant"] = CLOSING_VARIANTS[i % len(CLOSING_VARIANTS)]
        tone = str(p.get("tone") or "").strip().lower()
        if tone not in ("light", "dark", "tint", "sand"):
            tone = ""
        if not tone:
            if kind in ("cover", "closing") and _img_ok(p.get("image")):
                tone = "dark"
            elif kind == "section":
                tone = "dark" if dark_ok else "tint"
            elif i in dark_slots and dark_ok and kind in heavy:
                tone = "dark"
            elif i in tint_slots and tint_ok:
                tone = "tint"
            else:
                tone = "light"
        if tone in ("dark", "sand") and not dark_ok:
            tone = "light"
        if tone == "tint" and not tint_ok:
            tone = "light"
        # 连续三页同色 → 换
        if len(out) >= 2 and out[-1]["tone"] == out[-2]["tone"] == tone:
            tone = "tint" if (tone == "light" and tint_ok) else "light"
        # 浅色板本身是深色（如铁报的黑板）时按深底走，否则字色会翻错
        if tone == "tint" and LG._lum(lang.panel_c) < 0.42:
            tone = "dark"
        r = recent.setdefault(kind, [])
        v = p.get("variant") or _pick_variant(kind, p, r)
        r.append(v)
        out.append({"page": p, "kind": kind, "tone": tone, "variant": v})
    return out


def _pool_from(content, base_dir):
    """收集可用图片：content["assets"] 可以是目录、文件列表或 来源.json。"""
    raw = content.get("assets") or content.get("pool") or []
    if isinstance(raw, str):
        p = raw if os.path.isabs(raw) else os.path.normpath(os.path.join(base_dir, raw))
        if os.path.isdir(p):
            files = [os.path.join(p, f) for f in sorted(os.listdir(p))
                     if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
        elif os.path.isfile(p) and p.endswith(".json"):
            try:
                man = json.load(open(p, encoding="utf8"))
                d = os.path.dirname(p)
                files = [os.path.join(d, i["file"]) for i in man.get("items", [])]
            except Exception:
                files = []
        else:
            files = [p]
        raw = files
    out = []
    for f in raw:
        f = str(f)
        if not os.path.isabs(f):
            f = os.path.normpath(os.path.join(base_dir, f))
        if os.path.exists(f):
            out.append(f)
    return out


def assign_images(items, pool):
    """给没有图的页配图：优先「用得最少」的那张，左右交替，避免连续同图。"""
    if not pool:
        return 0
    n = len(pool)
    used = {}
    cursor = 0

    def pick(prefer=None):
        nonlocal cursor
        best_i, best_c = cursor % n, None
        for step in range(n):
            i = (cursor + step) % n
            c = used.get(pool[i], 0) - (0.5 if prefer and pool[i] == prefer else 0)
            if best_c is None or c < best_c:
                best_i, best_c = i, c
        cursor = (best_i + 1) % n
        used[pool[best_i]] = used.get(pool[best_i], 0) + 1
        return pool[best_i]

    count = 0
    for k, it in enumerate(items):
        p, kind = it["page"], it["kind"]
        if _img_ok(p.get("image")) or kind == "section":
            continue
        if kind == "closing":
            if not _img_ok(p.get("image")):
                p["image"] = pool[-1]
                count += 1
            continue
        if kind == "statement":
            p["image"] = pick()
            p["variant"] = "image"
            count += 1
            continue
        if kind == "cards":
            for c in (p.get("cards") or []):
                if isinstance(c, dict) and not _img_ok(c.get("image")):
                    c["image"] = pick()
                    count += 1
            continue
        p["image"] = pick(pool[0] if kind == "cover" else None)
        count += 1
        if not p.get("layout") and not p.get("media_side"):
            p["media_side"] = "r" if k % 2 == 0 else "l"
        if not p.get("media_frac"):
            p["media_frac"] = "third" if kind in ("points", "compare", "metrics") else "half"
    # 兜底：若可配图页仍不足 80%，给结尾/主张页补图
    def renders_image(it):
        p, kind = it["page"], it["kind"]
        if kind == "closing":
            return str(p.get("variant") or "") in ("full", "split")
        if kind == "statement":
            return str(p.get("variant") or "") == "image"
        return bool(p.get("image")) and kind not in ("section", "chart")

    total = len(items)
    guard = 0
    while sum(1 for it in items if renders_image(it)) / max(1, total) < 0.8 and guard < total:
        guard += 1
        for it in items:
            p, kind = it["page"], it["kind"]
            if kind == "closing" and str(p.get("variant") or "") in ("block", "quiet"):
                p["variant"] = "full"
                p.setdefault("image", pool[-1])
                break
            if kind == "statement" and not p.get("image"):
                p["image"] = pick()
                p["variant"] = "image"
                break
    return count


def build_deck(content, base_dir="."):
    """content(dict) → (pages, info)。pages 给渲染器用。"""
    lang = LG.get(content.get("language") or content.get("profile") or "grid")
    if content.get("style"):
        lang = LG.derive(lang, content["style"])
    raw = copy.deepcopy(content.get("pages") or [])
    if not raw:
        raise ValueError("内容里没有 pages")
    brand = content.get("brand") or content.get("meta") or ""
    # 全册色温：优先用显式 palette_from，否则用第一个带图的页
    theme_img = content.get("palette_from") or ""
    if theme_img and not os.path.isabs(str(theme_img)):
        theme_img = os.path.normpath(os.path.join(base_dir, str(theme_img)))
    if not theme_img:
        for pg in raw:
            cand = pg.get("image")
            if cand:
                theme_img = cand if os.path.isabs(str(cand)) else os.path.normpath(
                    os.path.join(base_dir, str(cand)))
                break
    items = plan(raw, lang)
    pool = _pool_from(content, base_dir)
    if pool:
        assign_images(items, pool)
    if not theme_img and pool:
        theme_img = pool[0]
    deck_pal = PAL.page_palette(theme_img, lang) if theme_img else None
    pages = []
    for i, it in enumerate(items, 1):
        p = dict(it["page"])
        # 相对路径按内容文件所在目录解析
        for k in ("image", "fill_image"):
            if p.get(k) and not os.path.isabs(str(p[k])):
                p[k] = os.path.normpath(os.path.join(base_dir, str(p[k])))
            if p.get(k) and not os.path.exists(str(p[k])):
                raise FileNotFoundError(
                    f"第 {i} 页的 {k} 不存在：{p[k]}（写错路径会被拒绝，不再静默跳过）")
        if p.get("images"):
            p["images"] = [os.path.normpath(os.path.join(base_dir, str(x)))
                           if not os.path.isabs(str(x)) else x for x in p["images"]]
        # 卡片也能带图（卡片上半幅）
        for c in (p.get("cards") or []):
            if isinstance(c, dict) and c.get("image") and not os.path.isabs(str(c["image"])):
                c["image"] = os.path.normpath(os.path.join(base_dir, str(c["image"])))
        ctx = Ctx(lang, p, i, len(items), tone=it["tone"],
                  variant=(p.get("variant") or it["variant"]),
                  brand=brand, deck_pal=deck_pal)
        fn = COMPOSITIONS[it["kind"]]
        bg = fn(ctx)
        # 常规页统一页脚；封面/章节/结尾自己处理
        if it["kind"] in ("points", "split", "gallery", "compare", "quote") and not ctx.has_foot:
            ctx.foot(_txt(p.get("source")))
        texture = lang.texture if (it["tone"] != "dark" and lang.texture != "none") else "none"
        pages.append({
            "bg": bg or ctx.bg,
            "texture": texture,
            "ops": list(ctx.pre) + ctx.ops,
            "kind": it["kind"],
            "tone": it["tone"],
            "variant": ctx.variant,
            "index": i,
            "lang": lang,
            "text": _page_text(p),
        })
    return pages, {"lang": lang, "brand": brand}


def _page_text(p):
    out = []
    for k in ("title", "kicker", "lead", "sub", "statement", "quote", "note", "source"):
        if p.get(k):
            out.append(_txt(p[k]))
    for k in ("items", "body"):
        v = p.get(k) or []
        if isinstance(v, str):
            v = [v]
        for it in v:
            out.append(_txt(it.get("t") if isinstance(it, dict) else it))
    for m in p.get("metrics") or []:
        out.append(_txt(m.get("v")) + " " + _txt(m.get("l")))
    return out
