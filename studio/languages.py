"""设计语言：把五份样板里的**语法**写成可执行参数。

一条纪律：这里放的是「这套东西怎么想」——纸、墨、字阶、留白律、图像处理、
装饰词汇、填空手段、透明度用法；不放假内容（水印文案、吉祥物、固定照片、
页码花招）。指纹一律不出现在本文件里。

证据来自本地蒸馏存档的 5 份样板（源 01–05），存档不随包分发。
包里只写结论数值，不写样板原文、品牌名或图片。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Type:
    """字阶：一个家族只允许这几级字号。"""
    cover: float
    h1: float
    h2: float
    lead: float
    body: float
    small: float
    micro: float

    def ladder(self, role: str):
        """某角色可选的字号，从大到小。"""
        table = {
            "cover": [self.cover, self.cover * 0.86, self.cover * 0.74, self.h1],
            "h1": [self.h1, self.h1 * 0.88, self.h2, self.h2 * 0.88],
            "h2": [self.h2, self.h2 * 0.86, self.lead, self.lead * 0.86],
            "lead": [self.lead, self.lead * 0.88, self.body],
            "body": [self.body, self.body * 0.9, self.small],
            "small": [self.small, self.small * 0.92, self.micro],
            "micro": [self.micro],
        }
        return [round(x, 1) for x in table[role]]


@dataclass(frozen=True)
class Media:
    """图片怎么进版：盒子比例、出血、遮罩、框线、圆角。"""
    ratios: tuple = (0.75, 1.0, 1.33, 0.5625)   # 显示框宽高比集合
    bleed: bool = False                          # 允许满幅出血
    scrim: int = 0                               # 图压字时的暗幕不透明度 %
    scrim_mode: str = "bottom"                   # bottom / full / edge
    frame_pt: float = 0.0                        # 细框
    radius_pt: float = 0.0                       # 圆角
    shadow: bool = False
    duotone: str = ""                            # "" 或 颜色值（02 的冷调处理）
    grayscale: bool = False


@dataclass(frozen=True)
class Lang:
    id: str
    name: str          # 两字语言名
    tagline: str       # 一句话：这套语言的气质
    # ---- 纸与墨
    paper: str
    paper_alt: str          # 反白页
    ink: str
    title_c: str
    body_c: str
    meta_c: str
    accent: str
    accent2: str
    rule_c: str
    panel_c: str
    panel_alpha: int
    on_dark: str
    # ---- 字
    display: str
    body_font: str
    micro_font: str
    ea_display: str
    ea_body: str
    type: Type
    ea_micro: str = "Source Han Sans CN"
    # 圆角：一律 Office 默认 16.667%（= 短边比例）；胶囊用 0.5
    radius_ratio: float = 0.1667
    # 阴影：(blur, dist, dir, alpha)；空元组 = 不用阴影
    shadow: tuple = ()
    # 对齐倾向：left / center / mixed；center_kinds 里列的页型默认居中
    align_bias: str = "left"
    center_kinds: tuple = ()
    font_tone: str = "modern"        # 从 FONT_POOL 里选字体的气质
    layout_pool: tuple = ()          # 偏好的图片布置；空 = 全轮换
    leading: float = 1.14           # 标题行距
    body_leading: float = 1.42      # 正文行距
    tracking_label: float = 1.2     # 小标签字距 pt（只有大写标签用）
    label_case: str = "upper"
    bold_title: bool = False
    # ---- 版面
    margin: float = 44.0            # pt
    head_top: float = 0.14          # 标题起点 / 页高
    gutter: float = 20.0
    columns: int = 12
    # ---- 构件
    radius_pt: float = 0.0
    card_shadow: bool = False
    rule_pt: float = 1.0
    # ---- 语言专属
    media: Media = field(default_factory=Media)
    ornaments: tuple = ()
    fill_devices: tuple = ()
    density: tuple = (0.55, 0.85)   # 内容覆盖率目标区间
    palette_mode: str = "tint"      # 图片主色跟随：none / tint / both
    tint_ratio: float = 0.07        # 浅色页把强调色混进纸的比例
    tones: tuple = ("light",)
    texture: str = "none"           # none / grain / stripe
    note: str = ""


# =====================================================================
# 01 甜本 · 源01：轻蓝纸、圆角卡、金色数字、细线、软阴影
#    证据：Optima 6543 字符；卡 DEEBF7×16、奶油 FFF2CC@70%×7；
#    墨 1F4E79、主蓝 2E75B6、金 BF9000、暖橙 C55A11；
#    线宽 1.0pt×50 / 1.5pt×18；圆角为 Office 默认 16.667%；
#    阴影 blur 15pt、dist 5pt、alpha 30%。
# =====================================================================
SWEET = Lang(
    id="sweet", name="甜本",
    tagline="轻蓝纸上的圆角卡片，数字用金色点睛，线只用来分栏不压字",
    paper="F1F5FB", paper_alt="1F3550",
    ink="1F2C3D", title_c="1F3550", body_c="2B3A4D", meta_c="5D6B7C",
    accent="2E75B6", accent2="A06A00", rule_c="C9D6E6",
    panel_c="DEEBF7", panel_alpha=100, on_dark="FFFFFF",
    display="Optima", body_font="Optima", micro_font="Optima",
    ea_display="LXGW WenKai", ea_body="Source Han Sans CN", ea_micro="Alibaba PuHuiTi 3.0",
    type=Type(cover=76, h1=46, h2=34, lead=26, body=19, small=15, micro=10),
    leading=1.12, body_leading=1.46, tracking_label=1.4,
    bold_title=True,
    margin=46.0, head_top=0.155, gutter=22.0,
    radius_pt=12.0, card_shadow=True, rule_pt=1.0,
    media=Media(ratios=(1.0, 1.33, 0.75, 0.5625), scrim=26, scrim_mode="full",
                radius_pt=12.0),
    ornaments=("rule", "chip", "tick", "tint_panel", "corner_mark"),
    fill_devices=("panel", "stat_row", "mini_table", "image", "hairline_rail"),
    density=(0.48, 0.84), palette_mode="both", tint_ratio=0.06,
    tones=("light", "tint"),
    texture="none",
    note="卡片是默认圆角，不另调半径；阴影只用 15/5/30% 这一档。",
)

# =====================================================================
# 02 铁报 · 源02：黑白红、满幅大图、暗幕、巨字、硬边
#    证据：Bangla MN 3899 字符；白 723 / 1C1B19 310 / 6F695E 301 / C00000 70；
#    满幅图 10 张；alpha 30000/50000/74000 用作暗幕；线宽 0.6–4.5pt。
# =====================================================================
IRON = Lang(
    id="iron", name="铁报",
    tagline="黑白红三色，图压满版加深，字大到成为图形",
    paper="FFFFFF", paper_alt="111111",
    ink="1C1B19", title_c="111111", body_c="2A2825", meta_c="6F695E",
    accent="C00000", accent2="E2231A", rule_c="1C1B19",
    panel_c="111111", panel_alpha=100, on_dark="FFFFFF",
    display="Bangla MN", body_font="Bangla MN", micro_font="Bangla MN",
    ea_display="Smiley Sans", ea_body="Source Han Sans CN", ea_micro="Smiley Sans",
    type=Type(cover=96, h1=54, h2=36, lead=26, body=18, small=14, micro=11),
    leading=1.06, body_leading=1.5, tracking_label=1.8,
    bold_title=True,
    margin=40.0, head_top=0.13, gutter=26.0,
    radius_pt=0.0, card_shadow=False, rule_pt=0.75,
    media=Media(ratios=(1.0, 0.75, 1.33, 1.78), bleed=True, scrim=58,
                scrim_mode="full"),
    ornaments=("rule", "bracket", "ghost_word", "block", "index_num"),
    fill_devices=("image", "ghost_word", "oversize_number", "block_band"),
    density=(0.58, 0.95), palette_mode="both", tint_ratio=0.05,
    tones=("light", "dark"),
    texture="none",
    note="暗幕固定 58%，白字永远压 ≥55% 的黑；红只做小面积和单字强调。",
)

# =====================================================================
# 03 纸案 · 源03（ING 路演）：浅灰蓝纸、宽边距、便签、细线分栏
#    证据：Optima 2679 + Futura 180；纸 E2E6ED；墨 1F4E79 / 203864；
#    正文 20pt×703；文本左边距 p25 0.83 in（五份里最宽）；
#    覆盖 0.63（最空）；软边缘 100pt×1。
# =====================================================================
PAPER = Lang(
    id="paper", name="纸案",
    tagline="宽留白的浅灰蓝纸，信息用便签和细线摆，不靠边框",
    paper="E7EBF2", paper_alt="203864",
    ink="1B2A41", title_c="1F3A5F", body_c="27405C", meta_c="5B6B80",
    accent="2E5D9B", accent2="C0703A", rule_c="B9C6D8",
    panel_c="F4F7FB", panel_alpha=100, on_dark="FFFFFF",
    display="Optima", body_font="Optima", micro_font="Futura",
    ea_display="Source Han Serif CN", ea_body="LXGW WenKai", ea_micro="Source Han Sans CN",
    type=Type(cover=82, h1=50, h2=32, lead=25, body=18, small=15, micro=10),
    leading=1.14, body_leading=1.5, tracking_label=1.6,
    bold_title=False,
    margin=60.0, head_top=0.19, gutter=26.0,
    radius_pt=3.0, card_shadow=False, rule_pt=1.0,
    media=Media(ratios=(1.0, 0.75, 1.33), scrim=0, frame_pt=0.0),
    ornaments=("rule", "note", "tick", "seal", "hairline_rail"),
    fill_devices=("note", "pull_quote", "hairline_rail", "image", "tone_band"),
    density=(0.42, 0.74), palette_mode="tint", tint_ratio=0.09,
    tones=("light", "tint"),
    texture="grain",
    note="留白是主角：宁可空，也不放大元素；空到 0.5 以下才补一张便签或引语。",
)

# =====================================================================
# 04 格物 · 源04：白纸、细线、多栏、六边形、报告感
#    证据：Futura 8270；墨 000000/2E75B6；14/16/18/20pt 是正文主力；
#    线宽 1.5pt×6 / 6pt×3；覆盖 0.76；文本左边距 p25 0.35 in。
# =====================================================================
GRID = Lang(
    id="grid", name="格物",
    tagline="白纸细线多栏，字号克制，靠对齐和分栏说话",
    paper="FFFFFF", paper_alt="1C1B19",
    ink="141414", title_c="141414", body_c="262626", meta_c="6B6B6B",
    accent="1F5C99", accent2="B07A2A", rule_c="D5D5D5",
    panel_c="F2F4F6", panel_alpha=100, on_dark="FFFFFF",
    display="Futura", body_font="Futura", micro_font="Futura",
    ea_display="Alibaba PuHuiTi 3.0", ea_body="Alibaba PuHuiTi 3.0", ea_micro="Alibaba PuHuiTi 3.0",
    type=Type(cover=80, h1=38, h2=26, lead=21, body=15.5, small=13, micro=10),
    leading=1.12, body_leading=1.52, tracking_label=1.0,
    bold_title=True,
    margin=44.0, head_top=0.115, gutter=24.0,
    radius_pt=0.0, card_shadow=False, rule_pt=1.2,
    media=Media(ratios=(1.0, 0.75, 1.33), scrim=0, frame_pt=1.0),
    ornaments=("rule", "tick", "hex", "index_num", "hairline_rail"),
    fill_devices=("multi_column", "hairline_rail", "mini_table", "image", "quote_block"),
    density=(0.48, 0.84), palette_mode="tint", tint_ratio=0.05,
    tones=("light", "tint"),
    texture="none",
    note="线是主角：1.2pt 细线分栏；六边形是概率装饰，每册最多两处。",
)

# =====================================================================
# 05 宣言 · 源05：大衬线、天空蓝、沙色、条纹纸、满幅摄影
#    证据：Big Caslon 2300 + Arial 20（全部 9pt 标注）；
#    正文 14pt；标题 36–72pt；正文色 595959；面板 FCE6D5；
#    线宽 0.6–1.0pt；文本左边距 p25 1.14 in（最宽）；图片满幅 10 张。
# =====================================================================
MANIFESTO = Lang(
    id="manifesto", name="宣言",
    tagline="大衬线配天空蓝与沙色，图片出血，字距只在极小标注上",
    paper="FFFFFF", paper_alt="12325C",
    ink="141C2E", title_c="1E386B", body_c="4A4A4A", meta_c="8A8A8A",
    accent="2E54A1", accent2="C58A5A", rule_c="D3D9E4",
    panel_c="EAF0F8", panel_alpha=100, on_dark="FFFFFF",
    display="Big Caslon", body_font="Big Caslon", micro_font="Arial",
    ea_display="Source Han Serif CN", ea_body="Source Han Serif CN", ea_micro="Alibaba PuHuiTi 3.0",
    type=Type(cover=88, h1=52, h2=34, lead=24, body=17, small=13, micro=9),
    leading=1.1, body_leading=1.55, tracking_label=0.8,
    bold_title=False,
    margin=56.0, head_top=0.17, gutter=28.0,
    radius_pt=0.0, card_shadow=False, rule_pt=0.75,
    media=Media(ratios=(0.75, 1.0, 1.33, 0.5625), bleed=True, scrim=38,
                scrim_mode="bottom"),
    ornaments=("rule", "dot", "thin_frame", "seal", "hairline_rail"),
    fill_devices=("image", "pull_quote", "hairline_rail", "tone_band"),
    density=(0.42, 0.76), palette_mode="both", tint_ratio=0.07,
    tones=("light", "dark", "sand"),
    texture="stripe",
    note="9pt Arial 只给标注；正文用 595959，不用纯黑；标题不加字距。",
)

_TONE = {"sweet": "warm", "iron": "sharp", "paper": "classic",
         "grid": "modern", "manifesto": "classic"}

_TUNE = {
    # 圆角比例一律 Office 默认；阴影只给甜本与纸案；对齐按实测倾向
    "sweet": dict(radius_ratio=0.1667, shadow=(15.0, 5.0, 45.0, 30),
                  align_bias="mixed",
                  center_kinds=("statement", "quote", "metrics", "closing")),
    "iron": dict(radius_ratio=0.0, shadow=(), align_bias="left", center_kinds=()),
    "paper": dict(radius_ratio=0.1667, shadow=(10.0, 4.0, 0.0, 18),
                  align_bias="center",
                  center_kinds=("statement", "quote", "section", "closing", "metrics")),
    "grid": dict(radius_ratio=0.0, shadow=(), align_bias="left",
                 center_kinds=("statement",)),
    "manifesto": dict(radius_ratio=0.0, shadow=(), align_bias="mixed",
                      center_kinds=("statement", "quote", "closing")),
}

LANGS = {l.id: replace(l, font_tone=_TONE[l.id], **_TUNE[l.id])
         for l in (SWEET, IRON, PAPER, GRID, MANIFESTO)}

# 外部风格档案（如字帖 Copybook 量出来的）允许覆盖的白名单——
# 只放「设计语言」层，不放页面内容层
# 字体池：按气质分组，同一组里可换（不再锁死一对字体）
FONT_POOL = {
    "warm": [("LXGW WenKai", "Source Han Sans CN", "Alibaba PuHuiTi 3.0"),
             ("Source Han Serif CN", "Source Han Sans CN", "Alibaba PuHuiTi 3.0")],
    "modern": [("Alibaba PuHuiTi 3.0", "Alibaba PuHuiTi 3.0", "Alibaba PuHuiTi 3.0"),
               ("Source Han Sans CN", "Source Han Sans CN", "Alibaba PuHuiTi 3.0")],
    "sharp": [("Smiley Sans", "Source Han Sans CN", "Smiley Sans"),
              ("Smiley Sans", "Alibaba PuHuiTi 3.0", "Smiley Sans")],
    "classic": [("Source Han Serif CN", "Source Han Serif CN", "Alibaba PuHuiTi 3.0"),
                ("LXGW WenKai", "LXGW WenKai", "Source Han Sans CN")],
    "neutral": [("Source Han Sans CN", "Source Han Sans CN", "Alibaba PuHuiTi 3.0"),
                ("Alibaba PuHuiTi 3.0", "Alibaba PuHuiTi 3.0", "Source Han Sans CN")],
}

# 布局池：不同语言偏好的图片布置（默认仍会全轮换）
LAYOUT_POOL = {
    "sweet": ["side-r", "inset", "stack", "side-l"],
    "iron": ["full", "stack", "side-l", "side-r"],
    "paper": ["inset", "side-r", "side-l", "stack"],
    "grid": ["side-r", "side-l", "stack", "full"],
    "manifesto": ["full", "side-l", "stack", "side-r"],
}

STYLE_FIELDS = {
    "paper", "paper_alt", "ink", "title_c", "body_c", "meta_c", "accent",
    "accent2", "rule_c", "panel_c", "panel_alpha", "on_dark",
    "display", "body_font", "micro_font", "ea_display", "ea_body", "ea_micro",
    "radius_ratio", "shadow", "align_bias", "center_kinds",
    "leading", "body_leading", "bold_title", "tracking_label", "label_case",
    "margin", "head_top", "gutter", "columns",
}


def pick_fonts(lang, which=0, seed=0):
    """从字体池里取一组（展示/正文/小字），用于「不锁死字体」。"""
    pool = FONT_POOL.get(getattr(lang, "font_tone", "modern"), FONT_POOL["modern"])
    disp, body, micro = pool[(seed + which) % len(pool)]
    return {"ea_display": disp, "ea_body": body, "ea_micro": micro}


def derive(base, style):
    """在基础语言上套一份测得的风格（只认白名单字段）。"""
    if not style:
        return base
    kw = {}
    for k, v in style.items():
        if k not in STYLE_FIELDS or v is None:
            continue
        if k == "shadow" and isinstance(v, (list, tuple)):
            v = tuple(v)
        if k == "center_kinds" and isinstance(v, list):
            v = tuple(v)
        if k == "columns":
            v = int(v)
        kw[k] = v
    return replace(base, **kw)
ALIASES = {
    "01": "sweet", "sweet": "sweet", "甜本": "sweet",
    "02": "iron", "iron": "iron", "铁报": "iron",
    "03": "paper", "paper": "paper", "纸案": "paper",
    "04": "grid", "grid": "grid", "格物": "grid",
    "05": "manifesto", "manifesto": "manifesto", "宣言": "manifesto",
}


def get(pid: str) -> Lang:
    key = ALIASES.get(str(pid).strip().lower()) or ALIASES.get(str(pid).strip())
    if not key:
        raise KeyError(f"未知设计语言：{pid}；可用：01/02/03/04/05 或 sweet/iron/paper/grid/manifesto")
    return LANGS[key]


def _lum(h):
    h = str(h).lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

    def f(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def ink_on(color: str, bg: str, need: float = 4.6) -> str:
    """把一个颜色调整到与底色达到指定对比度（只动明度，不动色相）。"""
    if contrast(color, bg) >= need:
        return color
    darkbg = _lum(bg) > 0.45
    c = str(color).lstrip("#")
    for i in range(1, 16):
        k = i / 15.0
        t = "000000" if darkbg else "FFFFFF"
        cand = "".join("%02X" % int(round(int(c[j:j + 2], 16) * (1 - k) + int(t[j:j + 2], 16) * k))
                       for j in (0, 2, 4))
        if contrast(cand, bg) >= need:
            return cand
    return "000000" if darkbg else "FFFFFF"


def accent_text(lang: Lang, bg: str, need: float = 4.6) -> str:
    """小字用的强调色：不够对比就沿明度方向调整，直到过线。

    规则来自「强调色不能因为好看就压到 4.5:1 以下」——图形可以用原色，
    文字必须过线。
    """
    return ink_on(lang.accent, bg, need)


hexlib_black = "000000"
hexlib_white = "FFFFFF"


def paper_for(lang: Lang, tone: str) -> str:
    if tone == "dark":
        return lang.paper_alt
    if tone == "tint":
        return lang.panel_c
    if tone == "sand":
        return "F7EFE6"
    return lang.paper


# 布局池在文件末尾才有，这里补上（LANGS 是同一个 dict，直接换值）
LANGS = {k: replace(v, layout_pool=tuple(LAYOUT_POOL[k])) for k, v in LANGS.items()}
