"""审计：在渲染之前，用同一份坐标把「会出丑的地方」数出来。

2.9 的 judge 用光学重心等代理指标，结果 3.9:1 的页面拿 100 分。3.0 改成
**可复现的硬检查**：重叠、越界、覆盖率、对比度、字阶、节奏、指纹。

每条检查都返回 (level, message, page_no)。level: err / warn / info。
"""
from __future__ import annotations

import math
import os
from collections import Counter

from PIL import Image

from .grid import H, W


def TM_has_cjk(s):
    return any(0x4E00 <= ord(c) <= 0x9FFF for c in s)


def _lum(hexcolor):
    h = str(hexcolor).lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

    def f(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _blend(fg, bg, alpha):
    a = alpha / 100.0
    f = [int(str(fg).lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(str(bg).lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "".join("%02X" % int(round(f[i] * a + b[i] * (1 - a))) for i in range(3))


def _inter(a, b, pad=0.0):
    x = max(0.0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x) - pad)
    y = max(0.0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y) - pad)
    return x * y


def _contains(box, x, y):
    return box.x - 0.5 <= x <= box.x + box.w + 0.5 and box.y - 0.5 <= y <= box.y + box.h + 0.5


def _img_lum(path):
    try:
        im = Image.open(path).convert("L")
        im = im.resize((8, 8))
        px = list(im.getdata())
        return (sum(px) / len(px)) / 255.0
    except Exception:
        return 0.5


def _text_sizes(page):
    return [o["size"] for o in page["ops"] if o["op"] == "text"]


def audit(pages, lang, banned=()):
    issues = []
    n = len(pages)
    paper0 = lang.paper

    for pi, page in enumerate(pages, 1):
        ops = page["ops"]
        bg0 = page.get("bg") or paper0
        texts = [o for o in ops if o["op"] == "text" and "".join(o["lines"]).strip()]
        media = [o for o in ops if o["op"] == "media"]
        tables = [o for o in ops if o["op"] in ("table", "chart")]

        # ---- 1 越界
        for o in ops:
            b = o["box"]
            bleed_ok = o["op"] == "media" and abs(b.w) >= W - 1
            if b.x < -1.5 or b.y < -1.5 or b.x + b.w > W + 1.5 or b.y + b.h > H + 1.5:
                if not bleed_ok:
                    issues.append(("err", "元素越界", pi,
                                   f'{o["op"]} @ {b.as_tuple()}'))

        # ---- 2 文本相撞
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                ov = _inter(texts[i]["box"], texts[j]["box"])
                if ov > 6.0:
                    a = "".join(texts[i]["lines"])[:12]
                    b = "".join(texts[j]["lines"])[:12]
                    issues.append(("err", "文字重叠", pi, f"{a} × {b} = {ov:.0f}pt²"))
        for t in texts:
            for m in tables:
                ov = _inter(t["box"], m["box"])
                if ov > 6.0:
                    issues.append(("err", "文字压表/图", pi,
                                   "".join(t["lines"])[:14]))

        # ---- 3 边距纪律（正文不许贴边）
        for t in texts:
            b = t["box"]
            if b.x < lang.margin - 8 and b.x > 0.5:
                issues.append(("warn", "左边缘超出安全区", pi,
                               f'x={b.x:.1f} < {lang.margin:.1f}｜{"".join(t["lines"])[:10]}'))
            if b.x + b.w > W - lang.margin + 8:
                issues.append(("warn", "右边缘超出安全区", pi,
                               f'{"".join(t["lines"])[:10]}'))

        # ---- 4 覆盖率
        boxes = [o["box"] for o in ops
                 if o["op"] in ("text", "media", "table", "chart")
                 or (o["op"] == "panel" and o["box"].w * o["box"].h > 0.02 * W * H)]
        grid = 40
        cell = W / grid, H / (grid * 9 / 16)
        cover = set()
        for b in boxes:
            x0 = max(0, int(b.x / cell[0]))
            x1 = min(grid - 1, int((b.x + b.w) / cell[0]))
            y0 = max(0, int(b.y / cell[1]))
            y1 = min(int(round(H / cell[1])) - 1, int((b.y + b.h) / cell[1]))
            for gx in range(x0, x1 + 1):
                for gy in range(y0, y1 + 1):
                    cover.add((gx, gy))
        total = grid * int(round(H / cell[1]))
        cov = len(cover) / float(total)
        page["coverage"] = round(cov, 3)
        lo, hi = lang.density
        airy = page["kind"] in ("cover", "section", "statement", "quote", "closing")
        if not airy and cov < lo - 0.10:
            issues.append(("warn", "内容偏空", pi, f"覆盖 {cov:.2f} < 目标 {lo:.2f}"))
        if cov > hi + 0.12 and not media:
            issues.append(("warn", "内容过满", pi, f"覆盖 {cov:.2f} > 目标 {hi:.2f}"))
        # 下半页空：正文类页面的最低点必须落到 72% 高度以下（页脚不算）
        if not airy:
            body_items = [o for o in ops
                          if o["op"] in ("text", "media", "table", "chart")
                          or (o["op"] == "panel" and o["box"].w * o["box"].h > 0.02 * W * H)
                          if o["box"].y < H - 34]
            if body_items:
                low = max(o["box"].y + o["box"].h for o in body_items)
                if low < H * 0.70:
                    issues.append(("warn", "下半页空", pi, f"内容止于 {low / H:.0%}H"))

        # ---- 5 对比度（逐个文字算子取它下面的那一层）
        layers = []
        for k, o in enumerate(ops):
            if o["op"] in ("panel", "media", "rule"):
                layers.append((k, o))
        for k, t in enumerate(ops):
            if t["op"] != "text" or not "".join(t["lines"]).strip():
                continue
            cx, cy = t["box"].cx, t["box"].cy
            bgc = bg0
            for lk, lo in sorted(layers):
                if lk >= k:
                    break
                if lo["op"] == "panel" and lo.get("image") and _contains(lo["box"], cx, cy):
                    lum = _img_lum(lo["image"])
                    bgc = "%02X%02X%02X" % tuple(int(255 * lum) for _ in range(3))
                elif lo["op"] == "panel" and _contains(lo["box"], cx, cy):
                    bgc = _blend(lo["color"], bgc, lo.get("alpha", 100))
                elif lo["op"] == "media" and _contains(lo["box"], cx, cy):
                    lum = _img_lum(lo["path"])
                    base = "%02X%02X%02X" % tuple(int(255 * lum) for _ in range(3))
                    sc = lo.get("scrim")
                    if sc and sc.get("alpha"):
                        bgc = _blend(sc["color"], base, sc["alpha"])
                    else:
                        bgc = base
            if (t.get("opacity") or 100) < 55:
                continue      # 装饰性大字（水印/序号）不参与对比度判定
            if t.get("opacity"):
                fg = _blend(t["color"], bgc, t.get("opacity"))
            else:
                fg = t["color"]
            cr = contrast(fg, bgc)
            t["contrast"] = round(cr, 2)
            big = t["size"] >= 24
            need = 3.0 if big else 4.5
            if cr < need:
                issues.append(("err", "对比度不足", pi,
                               f'{cr:.1f}:1 < {need}:1｜{"".join(t["lines"])[:12]}'))

        # ---- 5a 留白：最大连续空白矩形 + 四边留白
        GX, GY = 60, 34
        grid = [[0] * GX for _ in range(GY)]
        cw, ch = W / GX, H / GY
        for o in ops:
            if o["op"] not in ("text", "media", "panel", "table", "chart"):
                continue
            b = o["box"]
            if o["op"] == "panel" and b.w * b.h > 0.9 * W * H:
                continue                      # 整页底色不算内容墨
            x0, x1 = max(0, int(b.x / cw)), min(GX - 1, int((b.x + b.w) / cw))
            y0, y1 = max(0, int(b.y / ch)), min(GY - 1, int((b.y + b.h) / ch))
            for yy in range(y0, y1 + 1):
                for xx in range(x0, x1 + 1):
                    grid[yy][xx] = 1
        # 最大全零矩形（柱状图法）
        heights = [0] * GX
        best = 0
        for r in range(GY):
            for c in range(GX):
                heights[c] = 0 if grid[r][c] else heights[c] + 1
            stack = []
            for c in range(GX + 1):
                hh = heights[c] if c < GX else 0
                start = c
                while stack and stack[-1][1] >= hh:
                    idx, hv = stack.pop()
                    best = max(best, hv * (c - idx))
                    start = idx
                stack.append((start, hh))
        page["largest_empty"] = round(best / (GX * GY), 3)
        page["ink"] = round(1 - sum(sum(r) for r in grid) / (GX * GY), 3)
        texts_x = [o["box"].x for o in ops if o["op"] == "text" and o["box"].w > 20]
        if texts_x:
            m_l = min(texts_x)
            m_r = W - max(o["box"].x + o["box"].w for o in ops
                          if o["op"] == "text" and o["box"].w > 20)
            if abs(m_l - m_r) > 26 and abs(m_l - lang.margin) > 26 and abs(m_r - lang.margin) > 26:
                issues.append(("warn", "左右留白不均", pi,
                               f"左 {m_l:.0f}pt / 右 {m_r:.0f}pt"))

        # ---- 5b 视觉失衡（AeSlides 的椭圆归一化重心距离）
        wsum = 0.0
        cx = cy = 0.0
        for o in ops:
            if o["op"] != "text":
                continue
            b = o["box"]
            w = max(1.0, b.w * b.h) * 0.55
            wsum += w
            cx += (b.x + b.w / 2) * w
            cy += (b.y + b.h / 2) * w
        if wsum > 0:
            cx /= wsum
            cy /= wsum
            dx = (cx - W / 2) / (W * 0.06)
            dy = (cy - H / 2) / (H * 0.16)
            d = math.hypot(dx, dy)
            page["imbalance"] = round(d, 2)
            limit = 2.6 if page.get("has_img") else 1.7
            if d > limit and page["kind"] in ("points", "compare", "table", "metrics"):
                issues.append(("warn", "视觉重心偏", pi, f"d={d:.1f}"))

        # ---- 5c 配图覆盖（全册 80% 页要有图）
        page["has_img"] = any(
            o["op"] == "media" or (o["op"] == "panel" and o.get("image"))
            for o in ops)

        # ---- 5d 行长：中文一行不宜超过 42 字
        for t in texts:
            if not t.get("lines"):
                continue
            n = max(len(l) for l in t["lines"])
            if n > 44 and TM_has_cjk("".join(t["lines"])):
                issues.append(("warn", "行长过长", pi, f"{n} 字/行"))

        # ---- 5e 要点过多（一页一观点，最多 5 条）
        if page["kind"] in ("points",) and page.get("n_items", 0) > 5:
            issues.append(("warn", "要点过多", pi, f'{page["n_items"]} 条'))

        # ---- 5f 对齐轴：正文左缘应落在少数几条线上
        xs = sorted({round(o["box"].x, 0) for o in texts if o["size"] >= 12})
        page["axes"] = len(xs)
        if len(xs) > 4:
            issues.append(("warn", "对齐轴过多", pi, f"{len(xs)} 条左缘"))

        # ---- 5g 间距过密：同列相邻文本块，间隙 < 0.42 倍字号
        col = [o for o in texts if o["size"] >= 12]
        col.sort(key=lambda o: o["box"].y)
        for a, b in zip(col, col[1:]):
            gap = b["box"].y - (a["box"].y + a["box"].h)
            smax = max(a["size"], b["size"])
            if smax <= 34 and -3 < gap < max(5.0, 0.34 * smax):
                issues.append(("warn", "间距过紧", pi, f'{gap:.0f}pt｜{smax:.0f}pt 字'))
                break

        # ---- 5h 对称：两栏宽度 / 左右边距
        # ---- 6 字阶
        sizes = sorted(set(round(s, 1) for s in _text_sizes(page)), reverse=True)
        real = [s for s in sizes if s >= 10]
        if len(real) > 5:
            issues.append(("warn", "字号层级过多", pi, f"{len(real)} 级：{real}"))
        page["sizes"] = real

    # ---- 7 册级节奏
    kinds = [p["kind"] for p in pages]
    tones = [p["tone"] for p in pages]
    for i in range(2, len(pages)):
        if kinds[i] == kinds[i - 1] == kinds[i - 2]:
            issues.append(("warn", "同版式连续三页", i + 1, kinds[i]))
    for i in range(2, len(pages)):
        if tones[i] == tones[i - 1] == tones[i - 2]:
            issues.append(("warn", "同色调连续三页", i + 1, tones[i]))
    if len(set(tones)) == 1 and n >= 5:
        issues.append(("warn", "全册只有一种色调", 0, tones[0]))
    if len(set(kinds)) <= 2 and n >= 5:
        issues.append(("warn", "版式种类过少", 0, str(set(kinds))))

    # ---- 7b 配图覆盖：一册里 ≥80% 的页要有图
    if pages and any(p.get("has_img") for p in pages) is not None:
        n_img = sum(1 for p in pages if p.get("has_img"))
        ratio = n_img / max(1, len(pages))
        if ratio < 0.8:
            issues.append(("warn", "配图不足", 0,
                           f"{n_img}/{len(pages)} 页有图（目标 ≥80%）"))

    # ---- 8 指纹
    # 不依赖任何样板文案：结构性识别「水印式」重复与角落低透明度字
    seen = {}
    for pi, page in enumerate(pages):
        for t in page.get("texts", []):
            key = "".join(t.get("lines") or []).strip()
            if 2 <= len(key) <= 24 and not TM_has_cjk(key * 2):
                seen.setdefault(key.lower(), []).append(pi)
    for k, v in seen.items():
        if len(v) >= 3:
            issues.append(("warn", "疑似水印", v[0] + 1, f"{k!r} 重复 {len(v)} 页"))
    # 角落低透明度字（<60%）
    for pi, page in enumerate(pages):
        for o in page["ops"]:
            if o["op"] != "text" or o.get("alpha", 100) >= 60:
                continue
            b = o["box"]
            if b.y + b.h > H * 0.86 or b.y < H * 0.06:
                issues.append(("warn", "角落低透明度字", pi + 1, "疑似水印"))
                break
    all_text = " ".join("".join(p.get("text") or []) for p in pages)
    for b in banned:
        if b and b in all_text:
            issues.append(("err", "命中样板指纹", 0, b))

    # ---- 9 重复句
    sents = Counter()
    for p in pages:
        for line in p.get("text") or []:
            s = line.strip()
            if len(s) >= 6:
                sents[s] += 1
    for s, c in sents.items():
        if c > 1:
            issues.append(("info", "重复表述", 0, f"{s[:18]}×{c}"))

    return issues


def score(pages, issues):
    errs = sum(1 for i in issues if i[0] == "err")
    warns = sum(1 for i in issues if i[0] == "warn")
    base = 100
    base -= errs * 12
    base -= warns * 3
    # 覆盖率偏离也计分
    return max(0, min(100, base))


def report(pages, issues, lang, path=None):
    lines = []
    lines.append(f"# 体检 · {lang.name}（{len(pages)} 页）")
    lines.append("")
    by_page = {}
    for item in issues:
        lvl, msg, pi, detail = item
        by_page.setdefault(pi, []).append((lvl, msg, detail))
    for p in pages:
        pi = p["index"]
        cov = p.get("coverage", 0)
        le = p.get("largest_empty", 0)
        sizes = p.get("sizes") or []
        flag = "  ".join(f"[{m}]" for l, m, d in by_page.get(pi, []) if l == "err")
        lines.append(f"P{pi:02d} {p['kind']:<9} {p['tone']:<5} 墨 {cov:.2f} "
                     f"空隙 {le:.2f} 字级 {len(sizes)} {flag}")
        for lvl, msg, detail in by_page.get(pi, []):
            lines.append(f"      - {msg}: {detail}")
    lines.append("")
    for lvl, msg, detail in by_page.get(0, []):
        lines.append(f"- [{lvl}] {msg}: {detail}")
    s = score(pages, issues)
    errs = sum(1 for i in issues if i[0] == "err")
    warns = sum(1 for i in issues if i[0] == "warn")
    lines.append("")
    lines.append(f"**合规分 {s}**（100 − 硬伤×12 − 待调×3；这是「没犯多少规矩」，"
                 f"不是设计质量分）— {errs} 处硬伤，{warns} 处待调")
    out = "\n".join(lines)
    if path:
        with open(path, "w", encoding="utf8") as f:
            f.write(out)
    return out, s
