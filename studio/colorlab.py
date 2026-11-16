"""在线配色：按内容/情绪去查色，而不是凭空调一个十六进制。

来源：thecolorapi.com（免费、无需 key）。取一组 scheme 后按对比度筛选，
产出可直接写进 content["theme"] 的 {paper, ink, accent, accent2, accents}。
"""
from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request

API = "https://www.thecolorapi.com/scheme?hex={hex}&mode={mode}&count={n}"
MODES = ("monochrome", "analogic", "complement", "triad", "quad", "analogic-complement")

# 内容类型 → 惯用色（先验，再交给在线 scheme 细化）
TOPIC_SEEDS = {
    "咖啡": "8B5E3C", "烘焙": "C08A4A", "餐饮": "C0552B", "茶": "6B7F4A",
    "科技": "2F6BFF", "软件": "3A5BD9", "AI": "5B4BD6",
    "金融": "1F3A5F", "投资": "173F5F", "保险": "245A6B",
    "环保": "2E7D52", "能源": "3F7A3A", "建筑": "8A7A63",
    "时尚": "B03A5B", "美妆": "C46A7A", "香水": "7A5C8E",
    "教育": "C99A2E", "医疗": "0E7C7B", "运动": "C00000",
    "文旅": "C0552B", "制造": "4A5A6A", "汽车": "1B1F24",
}


def _lum(h):
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except Exception:
        return 0.5
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _sat(h):
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return 0
    mx, mn = max(r, g, b), min(r, g, b)
    return 0 if mx == 0 else (mx - mn) / mx


def _contrast(a, b):
    la, lb = _lum(a) + 0.05, _lum(b) + 0.05
    hi, lo = max(la, lb), min(la, lb)
    return hi / lo


def _mix(a, b, t):
    ca = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ca, cb))


def _get(url, timeout=8):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf8"))
    except Exception:
        r = subprocess.run(["curl", "-s", "-m", str(timeout), url],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
        raise


def scheme(seed, mode="analogic", n=5):
    seed = seed.strip().lstrip("#").upper()
    url = API.format(hex=seed, mode=mode, n=n)
    data = _get(url)
    return [c["hex"]["clean"].lstrip("#").upper()
            for c in data.get("colors", []) if c.get("hex")]


def suggest(topic=None, mood=None, seed=None, mode="analogic", n=5):
    """返回一组可用的配色，附带对比度校验后的结果。"""
    if not seed and topic:
        for k, v in TOPIC_SEEDS.items():
            if k in str(topic):
                seed = v
                break
    seed = (seed or "C0552B").lstrip("#").upper()
    try:
        cols = scheme(seed, mode, n)
    except Exception:
        cols = []
    cols = cols or [seed]
    # 纸/墨从「种子色」推，保证同一册是一个色系；scheme 的其它色只做辅色
    paper = _mix(seed, "FFFFFF", 0.92) if _lum(seed) < 0.85 else "FBFAF7"
    ink = _mix(seed, "000000", 0.84) if _lum(seed) > 0.12 else "161616"
    accent = seed
    if _contrast(accent, paper) < 3.2:
        accent = _mix(accent, "000000", 0.35)
    if _contrast(ink, paper) < 4.5:
        ink = _mix(ink, "000000", 0.45)
    accents = [accent] + [c for c in cols
                          if c != accent and _contrast(c, paper) >= 3.2][:3]
    return {
        "seed": seed, "mode": mode,
        "paper": paper, "ink": ink, "accent": accent, "accent2": _mix(accent, "FFFFFF", 0.35),
        "accents": accents,
        "checks": {"accent_vs_paper": round(_contrast(accent, paper), 2),
                   "ink_vs_paper": round(_contrast(ink, paper), 2)},
    }


def write(path, **kw):
    d = suggest(**kw)
    json.dump(d, open(path, "w", encoding="utf8"), ensure_ascii=False, indent=2)
    return d
