"""主题解析：让颜色、字体、排版跟着品牌 / 图片 / 情绪走，而不是写死。

优先级（后者覆盖前者）：
  language 默认 → theme（品牌/情绪）→ style（显式数值）→ fonts（显式字体）
"""
from __future__ import annotations

MOODS = {
    # 情绪 → 字体气质 + 对齐 + 布局偏好 + 密度倾向
    "editorial": dict(font_tone="classic", align_bias="mixed",
                      layouts=("stack", "inset", "side-r", "full")),
    "tech": dict(font_tone="modern", align_bias="left",
                 layouts=("side-r", "side-l", "stack", "full")),
    "warm": dict(font_tone="warm", align_bias="mixed",
                 layouts=("inset", "side-r", "stack", "side-l")),
    "luxury": dict(font_tone="classic", align_bias="center",
                   layouts=("full", "inset", "side-l", "stack")),
    "bold": dict(font_tone="sharp", align_bias="left",
                 layouts=("full", "stack", "side-l", "side-r")),
    "calm": dict(font_tone="classic", align_bias="center",
                 layouts=("inset", "stack", "side-r", "full")),
}

_ALIAS = {"商务": "editorial", "科技": "tech", "温和": "warm", "高端": "luxury",
          "冲击": "bold", "安静": "calm"}


def resolve(content):
    """content['theme'] → 一组可喂给 languages.derive 的覆盖值。"""
    t = content.get("theme") or {}
    if isinstance(t, str):
        t = {"mood": t}
    if not isinstance(t, dict):
        return {}
    out = {}
    mood = _ALIAS.get(str(t.get("mood") or "").strip(), str(t.get("mood") or "").strip().lower())
    m = MOODS.get(mood)
    if m:
        out["font_tone"] = m["font_tone"]
        out["align_bias"] = m["align_bias"]
        out["__layouts"] = m["layouts"]
    # 品牌色 / 纸色：只接受 6 位十六进制，避免任意字符串进 XML
    for k_src, k_dst in (("brand_color", "accent"), ("accent", "accent"),
                         ("paper", "paper"), ("ink", "ink"),
                         ("panel", "panel_c")):
        v = t.get(k_src)
        if isinstance(v, str) and len(v.strip().lstrip("#")) == 6:
            out[k_dst] = v.strip().lstrip("#").upper()
    if out.get("accent") and "accent2" not in out:
        out["accent2"] = out["accent"]
    return out
