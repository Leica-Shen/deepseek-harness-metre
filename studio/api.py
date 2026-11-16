"""给 AI 客户端用的机器可读契约：语言、页型、字段、示例。"""
from __future__ import annotations

from . import languages as LG

PAGE_KINDS = {
    "cover": {"required": ["title"], "optional": ["kicker", "sub", "image", "fill_image"]},
    "section": {"required": ["title"], "optional": ["index", "lead", "tone"]},
    "statement": {"required": ["statement"], "optional": ["by", "align", "image",
                                                          "fill_image", "variant"]},
    "points": {"required": ["title", "items"], "optional": ["kicker", "lead", "note",
                                                            "layout", "media_side"]},
    "metrics": {"required": ["title", "metrics"], "optional": ["kicker", "lead", "note",
                                                              "layout", "media_side"]},
    "band": {"required": ["title", "metrics"], "optional": ["kicker", "note", "image"]},
    "cards": {"required": ["title", "cards"], "optional": ["kicker", "cards[].image",
                                                          "cards[].v", "cards[].h",
                                                          "cards[].t"]},
    "split": {"required": ["title"], "optional": ["items[]", "image", "layout",
                                                  "media_side", "media_frac", "side"]},
    "imagepanel": {"required": ["title"], "optional": ["items[]", "image", "note"]},
    "compare": {"required": ["title", "columns"], "optional": ["kicker", "lead", "note"]},
    "table": {"required": ["title", "columns", "rows"], "optional": ["note", "unit"]},
    "chart": {"required": ["title", "values"], "optional": ["categories", "chart_type",
                                                             "takeaway", "note"]},
    "gallery": {"required": ["title"], "optional": ["images", "note", "layout"]},
    "quote": {"required": ["quote"], "optional": ["by", "image", "align"]},
    "closing": {"required": ["title"], "optional": ["sub", "image", "variant"]},
}

CONTENT_FIELDS = {
    "language": "me（默认，我的风格）/ sweet / iron / paper / grid / manifesto",
    "theme": "品牌与情绪：{mood, brand_color, paper, ink} —— 颜色与字体优先跟它走",
    "variation": "整数或字符串或 auto：同一份内容可复现，不同册子换脸",
    "fonts": "auto（默认，按气质从池里取）或 {ea_display, ea_body, ea_micro}",
    "style": "显式覆盖白名单字段（纸/墨/强调色/字体/圆角/阴影/留白/对齐…）",
    "color_mode": "language（默认）或 image（纸与强调色跟着封面图）",
    "accent_from_image": "配合 color_mode=image：强调色取图里最饱和的一簇",
    "assets": "图片池：目录 / 文件列表 / 来源.json；没有图的页自动分配",
    "palette_from": "指定某张图作为全册色温来源",
    "pages": "页数组，每页至少一个 kind",
}

PAGE_FIELDS = {
    "title": "页标题（一句话，不超过 4 个断言）",
    "statement": "一句主张；可用 align:center",
    "items": "字符串数组，或 [{h,t}] / [{v,h,t}]",
    "metrics": "[{v,l}] 数字与标签",
    "columns/rows": "表头与二维数组；放不下会报错而不是溢出",
    "values/categories": "图表数值与类目",
    "image": "图片路径（相对内容文件）；写错会被拒绝",
    "layout": "side-r / side-l / stack / full / inset（默认按册轮换）",
    "media_side": "r / l：图放哪边（layout 的别名）",
    "media_frac": "third / half / wide",
    "accent": "这一页的强调色（覆盖语言默认）",
    "panel": "这一页的底板色",
    "tone": "light / dark / tint / sand",
    "note": "页脚注释或来源",
}


def spec():
    langs = []
    order = ["me"] + [k for k in LG.LANGS if k != "me"]
    for lid in order:
        l = LG.LANGS[lid]
        langs.append({
            "id": lid, "name": l.name, "tagline": l.tagline,
            "default": lid == "me",
            "paper": l.paper, "ink": l.ink, "accent": l.accent,
            "fonts": {"display": l.ea_display, "body": l.ea_body, "micro": l.ea_micro},
            "font_tone": l.font_tone,
            "radius_ratio": l.radius_ratio, "shadow": list(l.shadow),
            "align_bias": l.align_bias, "center_kinds": list(l.center_kinds),
            "layout_pool": list(l.layout_pool),
            "margins_pt": l.margin, "gutter_pt": l.gutter,
        })
    return {
        "name": "metre", "version": "5.1.0",
        "content_fields": CONTENT_FIELDS,
        "page_fields": PAGE_FIELDS,
        "page_kinds": PAGE_KINDS,
        "languages": langs,
        "font_pool": {k: [list(t) for t in v] for k, v in LG.FONT_POOL.items()},
        "moods": ["editorial", "tech", "warm", "luxury", "bold", "calm"],
        "style_fields": sorted(LG.STYLE_FIELDS),
        "example": {
            "theme": {"mood": "editorial", "brand_color": "C0552B"},
            "variation": 7,
            "pages": [
                {"kind": "cover", "kicker": "2026", "title": "一句话说清这册要讲什么",
                 "sub": "副题", "image": "assets/cover.jpg"},
                {"kind": "points", "title": "三条就够", "items": ["一", "二", "三"]},
                {"kind": "closing", "title": "下一步", "sub": "联系人"},
            ],
        },
        "commands": {
            "build": "python3 -m studio.cli build deck.json out.pptx [--png preview/]",
            "fetch": "python3 -m studio.cli fetch assets/ \"query\" --n 6",
            "spec": "python3 -m studio.cli spec --json",
            "style": "python3 -m studio.cli style",
            "selftest": "python3 -m studio.cli selftest",
        },
    }
