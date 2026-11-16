#!/usr/bin/env python3
"""在 skill 目录里直接出片：把 engine/ 加入 sys.path 后调用 Metre。

用法：
  python3 tools/build.py deck.json out.pptx
  python3 tools/build.py deck.json out.pptx --style style.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "engine"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deck")
    ap.add_argument("out")
    ap.add_argument("--style")
    a = ap.parse_args()
    deck = json.load(open(a.deck, encoding="utf8"))
    if a.style:
        st = json.load(open(a.style, encoding="utf8"))
        deck.setdefault("style", {}).update({
            k: st["palette"][k] for k in ("paper", "ink", "accent") if k in st.get("palette", {})
        })
        if st.get("shape", {}).get("radius_ratio") is not None:
            deck["style"]["radius_ratio"] = st["shape"]["radius_ratio"]
    from studio import build
    try:
        build(deck, a.out, base_dir=os.path.dirname(os.path.abspath(a.deck)))
    except ImportError:
        print("缺少 python-pptx：pip install python-pptx")
        return 2
    print("→", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
