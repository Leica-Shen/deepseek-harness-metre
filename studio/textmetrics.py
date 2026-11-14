"""度量层：把「字」算成「版面」。

2.9 的溢出/重叠根因是**估行**：CJK 按字符数除以宽度，中英混排误差到 ±40%。
本模块用真实字体度量，并把换行结果直接写成 `a:br`，让 PowerPoint / WPS / Keynote
三者看到的断行与设计时一致。

单位一律用 pt（1/72 in）。画布 960 × 540 pt。
"""
from __future__ import annotations

import os
import unicodedata
from functools import lru_cache

from PIL import ImageFont

# ---------------------------------------------------------------- 字体登记

_SYS = "/System/Library/Fonts"
_SUP = os.path.join(_SYS, "Supplemental")
_USR = os.path.expanduser("~/Library/Fonts")

# family -> [(path, index)]。bold=True 时优先取粗体面。
REGISTRY = {
    "Optima": [(_SYS + "/Optima.ttc", 0), (_SYS + "/Optima.ttc", 1)],
    "Futura": [(_SUP + "/Futura.ttc", 0), (_SUP + "/Futura.ttc", 2)],
    "Bangla MN": [(_SUP + "/Bangla MN.ttc", 0), (_SUP + "/Bangla MN.ttc", 1)],
    "Big Caslon": [(_SUP + "/BigCaslon.ttf", 0), (_SUP + "/BigCaslon.ttf", 0)],
    "Arial": [(_SUP + "/Arial.ttf", 0), (_SUP + "/Arial Bold.ttf", 0)],
    "Gill Sans": [(_SUP + "/GillSans.ttc", 0), (_SUP + "/GillSans.ttc", 1)],
    "Didot": [(_SUP + "/Didot.ttc", 0), (_SUP + "/Didot.ttc", 2)],
    "Helvetica Neue": [(_SYS + "/HelveticaNeue.ttc", 0), (_SYS + "/HelveticaNeue.ttc", 1)],
    # 中文：文件用来**度量**；写入 pptx 的是字体族名（系统里装了就一致）
    "PingFang SC": [(_SYS + "/Hiragino Sans GB.ttc", 0), (_SYS + "/Hiragino Sans GB.ttc", 0)],
    "Songti SC": [(_SUP + "/Songti.ttc", 0), (_SUP + "/Songti.ttc", 0)],
    "Source Han Sans CN": [(_USR + "/SourceHanSansCN-Regular.otf", 0),
                           (_USR + "/SourceHanSansCN-Bold.otf", 0)],
    "Source Han Serif CN": [(_USR + "/SourceHanSerifCN-Regular.otf", 0),
                            (_USR + "/SourceHanSerifCN-Bold.otf", 0)],
    "LXGW WenKai": [(_USR + "/LXGWWenKai-Regular.ttf", 0), (_USR + "/LXGWWenKai-Regular.ttf", 0)],
    "Smiley Sans": [(_USR + "/SmileySans-Oblique.ttf", 0), (_USR + "/SmileySans-Oblique.ttf", 0)],
    "Alibaba PuHuiTi 3.0": [(_USR + "/AlibabaPuHuiTi-3-55-Regular.ttf", 0),
                            (_USR + "/AlibabaPuHuiTi-3-55-Regular.ttf", 0)],
    "Noto Serif SC": [(_USR + "/NotoSerifSC[wght].ttf", 0), (_USR + "/NotoSerifSC[wght].ttf", 0)],
    "Noto Sans SC": [(_USR + "/NotoSansSC[wght].ttf", 0), (_USR + "/NotoSansSC[wght].ttf", 0)],
}
# 度量回落：找不到就按这几档近似
_FALLBACK = {"sans": "Helvetica Neue", "serif": "Big Caslon", "cjk": "PingFang SC"}

_PROBE = 1000.0


@lru_cache(maxsize=256)
def check_fonts(families=None):
    """启动体检：缺字体时给人话，而不是 IndexError。"""
    missing = []
    for fam in (families or ["Optima", "Futura", "Bangla MN", "Big Caslon",
                             "Source Han Sans CN", "Source Han Serif CN",
                             "LXGW WenKai", "Smiley Sans",
                             "Alibaba PuHuiTi 3.0"]):
        faces = REGISTRY.get(fam)
        if not faces:
            continue
        if not os.path.exists(faces[0][0]):
            missing.append((fam, faces[0][0]))
    return missing


def _pil(family: str, bold: bool):
    faces = REGISTRY.get(family)
    if not faces:
        for k, v in _FALLBACK.items():
            if k in family.lower():
                faces = REGISTRY[v]
                break
    if not faces:
        faces = REGISTRY["Helvetica Neue"]
    path, idx = faces[1 if bold else 0]
    try:
        return ImageFont.truetype(path, int(_PROBE), index=idx)
    except Exception as exc:
        try:
            path, idx = faces[0]
            return ImageFont.truetype(path, int(_PROBE), index=idx)
        except Exception:
            raise RuntimeError(
                f"缺少字体文件 {path}（{family}）。Metre 在 macOS 上用系统字体度量；"
                f"请安装 {family} 或改 languages.py 的字体配置。原始错误：{exc}")


@lru_cache(maxsize=20000)
def _ratio(family: str, bold: bool, ch: str) -> float:
    """单字 advance / em。CJK 与全角标点恒为 1.0。"""
    if is_wide(ch):
        return 1.0
    f = _pil(family, bold)
    try:
        return f.getlength(ch) / _PROBE
    except Exception:
        return 0.55


@lru_cache(maxsize=64)
def _vm(family: str, bold: bool):
    f = _pil(family, bold)
    try:
        asc, desc = f.getmetrics()
    except Exception:
        asc, desc = _PROBE * 0.8, _PROBE * 0.2
    return asc / _PROBE, desc / _PROBE


def ascent_ratio(family: str, bold: bool = False) -> float:
    return _vm(family, bold)[0]


# ---------------------------------------------------------------- 字符分类

_WIDE_RANGES = (
    (0x1100, 0x115F), (0x2E80, 0x303E), (0x3041, 0x33FF), (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF), (0xA000, 0xA4CF), (0xAC00, 0xD7A3), (0xF900, 0xFAFF),
    (0xFE30, 0xFE6F), (0xFF00, 0xFF60), (0xFFE0, 0xFFE6), (0x20000, 0x3FFFD),
)

# 不能出现在行首
_NO_BREAK_BEFORE = set("，。、；：？！）】」』〉》”’%‰℃·—…～〕〗〙〛・,.;:?!)]}\"'")
# 不能出现在行尾
_NO_BREAK_AFTER = set("（【「『〈《“‘〔〖〘〚([{'\"")


def is_wide(ch: str) -> bool:
    if not ch:
        return False
    o = ord(ch)
    for lo, hi in _WIDE_RANGES:
        if lo <= o <= hi:
            return True
    return unicodedata.east_asian_width(ch) in ("W", "F")


# 这些符号在拉丁展示字体里常缺字或形状不对，交给中文字体排
SYMBOL_EA = set("¥￥€£℃±×÷‰§¶·•…—–")


def is_ea_char(ch: str) -> bool:
    return is_wide(ch) or ch in SYMBOL_EA


def is_space(ch: str) -> bool:
    return ch in " \t\u00a0\u3000"


# ---------------------------------------------------------------- 单段测量

def text_width(chars, size: float, latin: str, ea: str, bold: bool = False,
               tracking: float = 0.0) -> float:
    """一段（已断行）文本的宽度，单位 pt。tracking 单位 pt/字。"""
    w = 0.0
    for ch in chars:
        fam = ea if is_ea_char(ch) else latin
        w += _ratio(fam, bold, ch) * size
    w += tracking * max(0, len(chars) - 1)
    return w


def _atoms(text: str):
    """切成不可再分的排版单元：拉丁词 / 单个 CJK 字 / 单个空格。"""
    out = []
    buf = ""
    for ch in text:
        if is_wide(ch) or is_space(ch):
            if buf:
                out.append(buf)
                buf = ""
            out.append(ch)
        else:
            buf += ch
    if buf:
        out.append(buf)
    return out


_PAIRS = ("——", "……")


def _merge_pairs(atoms):
    """把「——」「……」并成一个不可拆的原子，避免破折号被拆到两行。"""
    out = []
    i = 0
    while i < len(atoms):
        if i + 1 < len(atoms) and atoms[i] + atoms[i + 1] in _PAIRS:
            out.append(atoms[i] + atoms[i + 1])
            i += 2
        else:
            out.append(atoms[i])
            i += 1
    return out


def _cjk_atom(a: str) -> bool:
    return len(a) == 1 and is_wide(a)


def _atomic_width(a: str, size, latin, ea, bold, tracking) -> float:
    """原子宽度；tracking 按字数摊，空格不计。"""
    w = text_width(a, size, latin, ea, bold, tracking=0.0)
    if tracking and not is_space(a):
        w += tracking * len(a)
    return w


def wrap(text: str, size: float, width: float, latin: str, ea: str,
         bold: bool = False, tracking: float = 0.0, max_lines: int = 0):
    """贪心断行 + 中文避头尾 + 拉丁词不断裂。返回行字符串列表。

    断点判定：空白处可断；CJK 字间可断；拉丁词之间只能在空格断。
    避头尾：行首禁则字符前移一个原子，行尾禁则字符后移一个原子。
    """
    if not text:
        return [""]
    if width <= 0:
        return [text]
    atoms = _atoms(text)
    lens = [_atomic_width(a, size, latin, ea, bold, tracking) for a in atoms]

    def width_of(idxs):
        return sum(lens[i] for i in idxs)

    def can_break_before(i):
        """第 i 个原子是否可以成为新行行首。"""
        if i <= 0 or i >= len(atoms):
            return False
        prev, cur = atoms[i - 1], atoms[i]
        if is_space(cur):
            return False            # 空格不单独起行
        if _cjk_atom(cur) and cur in _NO_BREAK_BEFORE:
            return False
        if _cjk_atom(prev) and prev in _NO_BREAK_AFTER:
            return False
        if _cjk_atom(cur) and not _cjk_atom(prev):
            return True             # 英文到中文的边界
        if _cjk_atom(cur) and _cjk_atom(prev):
            return True
        return is_space(prev)       # 拉丁词之间

    lines = []
    start = 0
    n = len(atoms)
    while start < n:
        if max_lines and len(lines) >= max_lines:
            break
        # 尽可能多塞
        total = 0.0
        end = start
        while end < n:
            if total + lens[end] > width + 0.01 and end > start:
                break
            total += lens[end]
            end += 1
        if end >= n:
            lines.append("".join(atoms[start:]).strip())
            break
        # 从 end 往回找最近的合法断点
        brk = None
        for k in range(end, start, -1):
            if can_break_before(k):
                brk = k
                break
        if brk is None:
            # 没有软断点：硬断（长单词/数字串），保证不超框
            brk = end
            # 避免行首标点
            while brk > start + 1 and _cjk_atom(atoms[brk]) and atoms[brk] in _NO_BREAK_BEFORE:
                brk -= 1
        head = "".join(atoms[start:brk]).strip()
        if not head:  # 极端情况：单字都放不下，也至少放一个原子
            head = atoms[start]
            brk = start + 1
        lines.append(head)
        start = brk
        while start < n and is_space(atoms[start]):
            start += 1
    if not lines:
        lines = [""]
    return lines


def block_height(n_lines: int, size: float, leading: float,
                 para_gap: float = 0.0, n_paras: int = 1) -> float:
    """n 行文本的高度（精确行距，pt）。"""
    return n_lines * size * leading + max(0, n_paras - 1) * para_gap


def fit_size(text: str, width: float, height: float, sizes, latin: str, ea: str,
             bold: bool = False, leading: float = 1.16, tracking: float = 0.0,
             para_gap: float = 0.0):
    """在候选字号（由大到小）里挑第一个装得下的；返回 (size, lines)。"""
    fallback = None
    for s in sizes:
        lines = wrap(text, s, width, latin, ea, bold, tracking)
        h = block_height(len(lines), s, leading, para_gap, 1)
        widest = max(text_width(l, s, latin, ea, bold, tracking) for l in lines)
        fallback = (s, lines)
        if h <= height + 0.5 and widest <= width + 0.5:
            return s, lines
    return fallback if fallback else (sizes[-1], wrap(text, sizes[-1], width, latin, ea, bold, tracking))


def truncate(text: str, size: float, width: float, latin: str, ea: str,
             bold: bool = False, tracking: float = 0.0) -> str:
    """单行裁到宽度内，用省略号收尾。"""
    if text_width(text, size, latin, ea, bold, tracking) <= width:
        return text
    ell = "…"
    lo = 0
    for i in range(len(text), 0, -1):
        cand = text[:i] + ell
        if text_width(cand, size, latin, ea, bold, tracking) <= width:
            return cand
        lo = i
    return ell


def wrap_balanced(text: str, size: float, width: float, latin: str, ea: str,
                  bold: bool = False, tracking: float = 0.0, max_lines: int = 0):
    """均衡断行：行数不变的前提下压窄有效宽度，让各行长度接近。

    标题最怕「最后一行只剩一个字」。做法是用贪心得到行数 n，再二分出
    仍能保持 n 行的最小宽度，用这个宽度重新断行。
    """
    base = wrap(text, size, width, latin, ea, bold, tracking, max_lines)
    n = len(base)
    if n <= 1:
        return base
    lo, hi = width * 0.45, width
    best = base
    for _ in range(18):
        mid = (lo + hi) / 2
        cand = wrap(text, size, mid, latin, ea, bold, tracking, max_lines)
        if len(cand) <= n:
            best = cand
            hi = mid
        else:
            lo = mid
    # 长度更均匀者胜出
    def spread(ls):
        ws = [text_width(l, size, latin, ea, bold, tracking) for l in ls]
        return max(ws) - min(ws)
    return best if spread(best) <= spread(base) else base


# ---------------------------------------------------------------- 最优化断行

_P_BREAK_GOOD = 0.0        # 标点后 / 空格处断行：完全合法
_P_BREAK_CJK = 250.0       # 汉字之间硬断：有代价
_P_BREAK_HARD = 40000.0   # 拉丁词内部：几乎禁止
_PUNCT_TAIL = set("，、。；：！？）》」』…—")
# 不宜出现在行首的常用虚词：不是禁则，但给额外代价
_P_START_SOFT = set("的了着过是在和与及或而就都也又很更最把被让给对从向")


def wrap_opt(text: str, size: float, width: float, latin: str, ea: str,
             bold: bool = False, tracking: float = 0.0, max_lines: int = 0):
    """DP 最优化断行（最小 raggedness + 标点优先 + 避头尾）。

    与 TeX 同一套思路：把所有可行断点列出来，用「行末空白平方 + 断点代价」
    求总代价最小。标题因此既均衡、又尽量落在标点上。
    """
    if not text:
        return [""]
    if width <= 0:
        return [text]
    atoms = _atoms(text)
    atoms = _merge_pairs(atoms)
    n = len(atoms)
    if n > 900:
        return wrap(text, size, width, latin, ea, bold, tracking, max_lines)
    wid = [_atomic_width(a, size, latin, ea, bold, tracking) for a in atoms]
    pre = [0.0]
    for w in wid:
        pre.append(pre[-1] + w)

    def seg_w(i, j):            # atoms[i:j]
        return pre[j] - pre[i]

    def legal(i, j):
        """在 atoms[j] 前断行是否合法（i 为本行起点）。"""
        if j >= n:
            return True
        cur, prev = atoms[j], atoms[j - 1]
        if is_space(cur):
            return False
        if _cjk_atom(cur) and cur in _NO_BREAK_BEFORE:
            return False
        if _cjk_atom(prev) and prev in _NO_BREAK_AFTER:
            return False
        if not _cjk_atom(cur) and not _cjk_atom(prev) and not is_space(prev):
            return False         # 拉丁词内部
        return True

    def penalty(j):
        if j >= n:
            return 0.0
        prev = atoms[j - 1]
        nxt = atoms[j]
        if _cjk_atom(nxt) and nxt in _P_START_SOFT:
            return _P_BREAK_CJK + 140.0
        if is_space(prev) or (len(prev) >= 1 and prev[-1] in _PUNCT_TAIL):
            return _P_BREAK_GOOD
        if _cjk_atom(prev):
            return _P_BREAK_CJK
        return _P_BREAK_HARD

    INF = float("inf")
    best = [INF] * (n + 1)
    back = [-1] * (n + 1)
    lines_at = [0] * (n + 1)
    best[0] = 0.0
    for j in range(1, n + 1):
        # 从 j 往前枚举起点 i
        i = j - 1
        while i >= 0:
            w = seg_w(i, j)
            if w > width + 0.01 and j - i > 1:
                break
            if best[i] < INF and legal(i, j) and (not max_lines or lines_at[i] < max_lines):
                slack = max(0.0, width - w) / width
                cost = best[i] + (slack ** 2) * 1000.0 + penalty(j)
                if j >= n:
                    cost = best[i] + 0.0  # 末行不计 raggedness
                if cost < best[j] - 1e-9:
                    best[j] = cost
                    back[j] = i
                    lines_at[j] = lines_at[i] + 1
            i -= 1
    if best[n] == INF:  # 无解（极端长词），退回贪心
        return wrap(text, size, width, latin, ea, bold, tracking, max_lines)
    out = []
    j = n
    while j > 0:
        i = back[j]
        if i < 0:
            return wrap(text, size, width, latin, ea, bold, tracking, max_lines)
        out.append("".join(atoms[i:j]).strip())
        j = i
    out.reverse()
    return [l for l in out if l != ""] or [""]


# ---------------------------------------------------------------- 语义断行

_CLAUSE_TAIL = set("，、。；：！？…—·")
_SENT_TAIL = set("。！？…")


def has_cjk(text: str) -> bool:
    return any(is_wide(c) for c in text)


_CLOSERS = set("”’」』）】》〉…")


def split_clauses(text: str):
    """按标点切成意群，标点留在前段；收尾引号跟着前一段走，绝不单独成行。"""
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in _CLAUSE_TAIL:
            out.append(buf)
            buf = ""
    if buf.strip():
        out.append(buf)
    merged = []
    for c in out:
        if merged and c.strip() and all(ch in _CLOSERS for ch in c.strip()):
            merged[-1] = merged[-1] + c
        else:
            merged.append(c)
    return [c for c in merged if c.strip()] or [text]


def wrap_smart(text: str, size: float, width: float, latin: str, ea: str,
               bold: bool = False, tracking: float = 0.0):
    """中文优先「意群整段换行」：只在标点处断，意群超宽才在字间断。

    中文排版最忌讳把「飞机」「现金流」这类双字词拆到两行；按标点切意群后
    贪心装行，可以让绝大多数标题、要点得到「整句断行」的效果。
    """
    if not text:
        return [""]
    if not has_cjk(text):
        return wrap_opt(text, size, width, latin, ea, bold, tracking)
    clauses = split_clauses(text)
    lines, cur = [], ""
    for cl in clauses:
        trial = cur + cl
        if not cur or text_width(trial, size, latin, ea, bold, tracking) <= width + 0.01:
            cur = trial
            continue
        lines.append(cur.strip())
        cur = cl
        # 单意群超宽：退化为最优断行
        while text_width(cur, size, latin, ea, bold, tracking) > width + 0.01:
            seg = wrap_opt(cur, size, width, latin, ea, bold, tracking)
            if len(seg) <= 1:
                break
            lines.extend(seg[:-1])
            cur = seg[-1]
    if cur.strip():
        lines.append(cur.strip())
    # 孤字行（最后一行只有一个汉字）与前一行合并或前移一个字
    if len(lines) >= 2:
        last = lines[-1]
        if has_cjk(last) and len(last) <= 2:
            prev = lines[-2]
            if len(prev) > 3:
                moved = prev[-1] + last
                if text_width(moved, size, latin, ea, bold, tracking) <= width + 0.01:
                    lines[-2] = prev[:-1]
                    lines[-1] = moved
    return [l for l in lines if l] or [""]


def headline(text: str, width: float, height: float, sizes, latin: str, ea: str,
             bold: bool = False, leading: float = 1.16, tracking: float = 0.0):
    """标题：在能装下的字号里，优先选**不拆意群**且行数少**的最大字号。

    返回 (size, lines)。
    """
    cands = []
    for s in sizes:
        lines = wrap_smart(text, s, width, latin, ea, bold, tracking)
        h = block_height(len(lines), s, leading)
        if h > height + 0.5:
            continue
        widest = max(text_width(l, s, latin, ea, bold, tracking) for l in lines)
        if widest > width + 0.5:
            continue
        # 意群破坏数：行尾不是标点、且下一行不是新意群开头 → 计 1
        breaks = 0
        for i, l in enumerate(lines[:-1]):
            if not (l and l[-1] in _CLAUSE_TAIL):
                breaks += 1
        ws = [text_width(l, s, latin, ea, bold, tracking) for l in lines]
        rag = (max(ws) - min(ws)) / max(1.0, width)
        cands.append((breaks, len(lines), round(rag, 3), -s, s, lines))
    if not cands:
        s = sizes[-1]
        return s, wrap_opt(text, s, width, latin, ea, bold, tracking)
    cands.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    _, _, _, _, s, lines = cands[0]
    return s, lines
