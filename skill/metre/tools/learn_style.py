#!/usr/bin/env python3
"""从一份 .pptx 里量设计参数（只用标准库，不需要 python-pptx）。

只量「设计语言」，不提取正文内容：
  纸/墨/强调色、字号阶、字体名、圆角比例、阴影、边距、图片面积与位置、对齐比例。

用法：
  python3 tools/learn_style.py 参考.pptx -o style.json
"""
from __future__ import annotations

import argparse
import json
import re
import statistics as st
import zipfile
from collections import Counter
from xml.etree import ElementTree as ET

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
EMU = 914400.0


def _hex(el):
    if el is None:
        return None
    c = el.find(A + "srgbClr")
    if c is not None:
        return c.get("val", "").upper()[:6]
    return None


def _luma(h):
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except Exception:
        return 0.5
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def read_theme(z):
    out = {}
    try:
        root = ET.fromstring(z.read("ppt/theme/theme1.xml"))
    except Exception:
        return out
    scheme = root.find(f".//{A}clrScheme")
    if scheme is not None:
        for tag in ("dk1", "dk2", "lt1", "lt2", "accent1", "accent2"):
            el = scheme.find(A + tag)
            if el is not None:
                c = el.find(A + "srgbClr")
                if c is not None:
                    out[tag] = c.get("val", "").upper()[:6]
                else:
                    s = el.find(A + "sysClr")
                    if s is not None:
                        out[tag] = s.get("lastClr", "").upper()[:6]
    fonts = {}
    for tag in ("majorFont", "minorFont"):
        el = root.find(f".//{A}{tag}/{A}latin")
        if el is not None:
            fonts[tag] = el.get("typeface")
    if fonts:
        out["fonts"] = fonts
    return out


def read_slides(z):
    fills, sizes, align, anchors = Counter(), Counter(), Counter(), Counter()
    radii, shadows, pics = [], Counter(), []
    for name in sorted(n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)):
        root = ET.fromstring(z.read(name))
        for sp in root.iter(P + "sp"):
            spPr = sp.find(P + "spPr")
            if spPr is None:
                continue
            geom = spPr.find(A + "prstGeom")
            prst = geom.get("prst") if geom is not None else None
            if prst == "roundRect":
                gd = geom.find(A + "avLst/" + A + "gd")
                radii.append(int(gd.get("fmla").split()[1]) / 100000 if gd is not None else 0.16667)
            c = _hex(spPr.find(A + "solidFill"))
            if c:
                fills[c] += 1
            if spPr.find(A + "effectLst/" + A + "outerShdw") is not None:
                shadows["yes"] += 1
            for p in sp.iter(A + "p"):
                a = p.find(A + "pPr")
                if a is not None and a.get("algn"):
                    align[a.get("algn")] += 1
                for r in p.iter(A + "r"):
                    rPr = r.find(A + "rPr")
                    if rPr is not None and rPr.get("sz"):
                        sizes[int(rPr.get("sz")) / 100] += 1
            body = sp.find(P + "txBody")
            if body is not None and body.find(A + "bodyPr") is not None:
                b = body.find(A + "bodyPr").get("anchor")
                if b:
                    anchors[b] += 1
        for pic in root.iter(P + "pic"):
            xfrm = pic.find(f".//{A}xfrm")
            if xfrm is None:
                continue
            off, ext = xfrm.find(A + "off"), xfrm.find(A + "ext")
            if off is None or ext is None:
                continue
            pics.append((int(off.get("x")) / EMU, int(off.get("y")) / EMU,
                         int(ext.get("cx")) / EMU, int(ext.get("cy")) / EMU))
        for t in root.iter(P + "txBody"):
            pass
    return fills, sizes, align, anchors, radii, shadows, pics


def learn(path):
    with zipfile.ZipFile(path) as z:
        theme = read_theme(z)
        fills, sizes, align, anchors, radii, shadows, pics = read_slides(z)
        try:
            pres = ET.fromstring(z.read("ppt/presentation.xml"))
            sz = pres.find(P + "sldSz")
            W, H = int(sz.get("cx")) / EMU / 72, int(sz.get("cy")) / EMU / 72
        except Exception:
            W, H = 960.0, 540.0

    colors = [c for c, _ in fills.most_common(24) if c]
    lights = [c for c in colors if _luma(c) > 0.88]
    darks = [c for c in colors if _luma(c) < 0.25]
    light = max(lights, key=lambda c: fills[c]) if lights else "FCFCFA"
    dark = max(darks, key=lambda c: fills[c]) if darks else "1A1A1A"
    # 强调色：排除纸与墨后，饱和度最高且出现 >=2 次
    def sat(h):
        try:
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        except Exception:
            return 0
        mx, mn = max(r, g, b), min(r, g, b)
        return 0 if mx == 0 else (mx - mn) / mx
    cand = [c for c in colors if c not in (light, dark) and fills[c] >= 2]
    accent = max(cand, key=sat) if cand else (theme.get("accent1") or "C0552B")

    top_sizes = sorted((s for s, n in sizes.most_common(20) if n >= 2), reverse=True)
    scale = top_sizes[:6] or [44, 32, 24, 18, 14, 10]

    img_area = [w * h / (W * H) for _, _, w, h in pics] if pics else []
    areas = [w * h / (W * H) for _, _, w, h in pics] if pics else []

    return {
        "source": {"file": path.split("/")[-1], "pages": None, "size": [round(W), round(H)]},
        "palette": {
            "paper": light, "ink": dark, "accent": accent,
            "accent2": theme.get("accent2", accent),
        },
        "type": {
            "scale_pt": [round(s, 1) for s in scale],
            "display": (theme.get("fonts") or {}).get("majorFont"),
            "body": (theme.get("fonts") or {}).get("minorFont"),
            "ratio": round(scale[0] / max(1e-6, scale[-1]), 2) if len(scale) > 1 else None,
        },
        "shape": {
            "radius_ratio": round(st.median(radii), 4) if radii else None,
            "shadow_share": round(shadows["yes"] / max(1, sum(fills.values())), 2),
        },
        "layout": {
            "image_area_median": round(st.median(areas), 3) if areas else 0,
            "images_per_page": round(len(pics) / max(1, len([n for n in []]) or 1), 2) if pics else 0,
            "align": dict(align), "anchor": dict(anchors),
        },
        "notes": [
            "只量设计参数，不提取文字内容",
            "圆角比例 = adj（短边比例），不是像素",
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("-o", "--out", default="style.json")
    a = ap.parse_args()
    if not a.file.lower().endswith((".pptx", ".potx")):
        print("只支持 pptx（pdf 请先转成 pptx 或手动填 style.json）")
        return 2
    data = learn(a.file)
    json.dump(data, open(a.out, "w", encoding="utf8"), ensure_ascii=False, indent=2)
    print(f"→ {a.out}")
    print(f"  纸 {data['palette']['paper']} 墨 {data['palette']['ink']} "
          f"强调 {data['palette']['accent']}")
    print(f"  字阶 {data['type']['scale_pt']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
