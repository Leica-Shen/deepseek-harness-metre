"""studio：度量驱动的幻灯片引擎。"""
from __future__ import annotations

__version__ = "5.0.0"
__codename__ = "格律"


def build(content, out_path, base_dir=".", audit_path=None, render_dir=None,
          verbose=True):
    """内容 JSON(dict) → pptx。返回 (pages, issues, score)。"""
    from . import audit as AUD
    from . import compose as CP
    from . import render as RD

    pages, info = CP.build_deck(content, base_dir=base_dir)
    lang = info["lang"]
    issues = AUD.audit(pages, lang, banned=BANNED)
    RD.render_deck([{"bg": p["bg"], "ops": p["ops"], "texture": p.get("texture"),
                     "lang": lang} for p in pages], out_path)
    text, score = AUD.report(pages, issues, lang, audit_path)
    if verbose:
        print(text)
        print(f"\n→ {out_path}")
    if render_dir:
        render_png(out_path, render_dir)
    return pages, issues, score


# 指纹改为结构化检测（audit.watermark），源码不保存任何样板文案
BANNED = ()


def render_png(pptx_path, out_dir, width=None):
    """可选：本机有 Keynote 时出预览图；没有就跳过，不影响 pptx。"""
    import os
    import subprocess
    os.makedirs(out_dir, exist_ok=True)
    script = f'''
set src to POSIX file "{os.path.abspath(pptx_path)}"
set outDir to POSIX file "{os.path.abspath(out_dir)}"
tell application "Keynote"
  set d to open src
  delay 1.2
  export d to outDir as slide images with properties {{image format:PNG}}
  close d saving no
end tell'''
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    except FileNotFoundError:
        print("（跳过预览：没有 osascript）")
        return None
    if r.returncode:
        print("（跳过预览：", r.stderr.strip()[:120], "）")
        return None
    return out_dir


def load(path):
    import json
    with open(path, encoding="utf8") as f:
        return json.load(f)
