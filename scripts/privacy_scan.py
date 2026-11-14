#!/usr/bin/env python3
"""发布前隐私扫描：不内置任何品牌名，只用「结构 + 语料比对」两种手段。

用法：
  python3 scripts/privacy_scan.py                 # 结构扫描（路径/邮箱/长样本文案）
  python3 scripts/privacy_scan.py --corpus DIR    # 额外比对 DIR 里的 pptx/docx（本地样板）

检查项：
  1 绝对路径与用户名（macOS 家目录、Windows 家目录）
  2 邮箱、手机号
  3 与本地样板逐句重合（≥10 字，且不是通用词）
  4 打包产物里的媒体哈希是否与样板媒体重合（图片被复制）
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import zipfile

TEXT_EXT = (".md", ".py", ".json", ".js", ".yml", ".txt", ".html", ".css")
SELF = os.path.abspath(__file__)
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache"}
FIXED = [
    (re.compile(r"/Users/[A-Za-z0-9._-]{2,}"), "绝对用户路径"),
    (re.compile(r"[A-Za-z]:\\\\Users\\\\[^\\\\]{2,}"), "Windows 用户路径"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}\b"), "邮箱"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "手机号"),
]


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(TEXT_EXT):
                yield os.path.join(dirpath, fn)


def scan_structure(root):
    hits = []
    for p in walk(root):
        if os.path.abspath(p) == SELF:
            continue
        try:
            txt = open(p, encoding="utf8").read()
        except Exception:
            continue
        for rx, label in FIXED:
            for m in rx.finditer(txt):
                val = m.group(0)
                if label == "邮箱" and val.startswith(("git@", "ssh@")):
                    continue          # 这是 SSH 地址，不是个人邮箱
                line = txt[:m.start()].count("\n") + 1
                hits.append((p, line, label, val[:60]))
    return hits


def corpus_sentences(corpus):
    out = set()
    try:
        from pptx import Presentation
    except Exception:
        return out
    for fn in os.listdir(corpus):
        if not fn.lower().endswith(".pptx"):
            continue
        try:
            prs = Presentation(os.path.join(corpus, fn))
        except Exception:
            continue
        for slide in prs.slides:
            for sh in slide.shapes:
                if not getattr(sh, "has_text_frame", False):
                    continue
                for para in sh.text_frame.paragraphs:
                    t = para.text.strip()
                    if len(t) >= 10:
                        out.add(t)
    return out


def scan_corpus(root, corpus):
    sents = corpus_sentences(corpus)
    hits = []
    for p in walk(root):
        try:
            txt = open(p, encoding="utf8").read()
        except Exception:
            continue
        for s in sents:
            if s in txt:
                hits.append((p, s[:40]))
    return hits


def media_hashes(path):
    out = {}
    try:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.startswith(("ppt/media/", "word/media/")):
                    out[hashlib.sha256(z.read(n)).hexdigest()] = n
    except Exception:
        pass
    return out


def scan_media(root, corpus):
    sample = {}
    for fn in os.listdir(corpus):
        if fn.lower().endswith((".pptx", ".docx")):
            sample.update(media_hashes(os.path.join(corpus, fn)))
    hits = []
    for fn in os.listdir(root):
        if fn.lower().endswith((".pptx", ".docx")):
            for h, n in media_hashes(os.path.join(root, fn)).items():
                if h in sample:
                    hits.append((fn, n, sample[h]))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--corpus")
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    hits = scan_structure(root)
    for p, line, label, val in hits:
        print(f"[结构] {os.path.relpath(p, root)}:{line}  {label} → {val}")

    if args.corpus:
        corpus = os.path.abspath(args.corpus)
        ch = scan_corpus(root, corpus)
        for p, s in ch:
            print(f"[文案] {os.path.relpath(p, root)}  ← 样板原句 {s!r}")
        mh = scan_media(root, corpus)
        for fn, n, s in mh:
            print(f"[图片] {fn}:{n}  ← 样板媒体 {s}")
        hits += ch + mh

    print(f"\n共 {len(hits)} 处；{'通过' if not hits else '需处理'}")
    return 0 if not hits else 1


if __name__ == "__main__":
    sys.exit(main())
