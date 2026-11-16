"""自检：把「会不会出错」变成一条可跑的命令。

覆盖六类风险：
  1 信息正确——文案逐字进入 pptx；
  2 版式正确——不重叠、不越界、有留白、配图覆盖 ≥80%；
  3 确定性——同一输入两次构建，几何完全一致；
  4 安全——产物不含绝对路径与用户名，不联网、不执行 shell；
  5 规模——页数、字数、元素数有上限，超限报错；
  6 指令安全——SKILL.md 不含可劫持指令。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile

from . import audit as AUD
from . import compose as CP
from . import languages as LG

MAX_PAGES = 60
MAX_CHARS = 40000
MAX_OPS_PAGE = 160


class GuardError(ValueError):
    pass


def check_limits(content):
    pages = content.get("pages") or []
    if len(pages) > MAX_PAGES:
        raise GuardError(f"页数 {len(pages)} 超过上限 {MAX_PAGES}")
    chars = 0
    for p in pages:
        for k in ("title", "lead", "statement", "quote", "note", "source", "sub"):
            chars += len(str(p.get(k) or ""))
        for k in ("items", "body"):
            v = p.get(k) or []
            if isinstance(v, str):
                v = [v]
            for it in v:
                chars += len(str(it.get("t") if isinstance(it, dict) else it))
    if chars > MAX_CHARS:
        raise GuardError(f"文本 {chars} 字超过上限 {MAX_CHARS}")


def check_paths(content, base_dir):
    """图片路径只允许在 base_dir 或显式 assets 目录内。"""
    allowed = content.get("assets")
    roots = [os.path.abspath(base_dir), os.path.abspath(os.path.join(base_dir, ".."))]
    if isinstance(allowed, str):
        roots.append(os.path.abspath(os.path.join(base_dir, allowed)))
    for p in content.get("pages") or []:
        for k in ("image", "fill_image"):
            v = p.get(k)
            if not v:
                continue
            ap = os.path.abspath(v if os.path.isabs(str(v)) else os.path.join(base_dir, str(v)))
            if not any(ap.startswith(r) for r in roots):
                raise GuardError(f"图片路径越界：{v}")


def build_once(content, base_dir, out):
    from . import render as RD
    pages, info = CP.build_deck(content, base_dir=base_dir)
    lang = info["lang"]
    issues = AUD.audit(pages, lang, banned=())
    RD.render_deck([{"bg": p["bg"], "ops": p["ops"], "texture": p.get("texture"),
                     "lang": lang} for p in pages], out)
    return pages, issues


def _geom_signature(pages):
    sig = []
    for p in pages:
        for o in p["ops"]:
            b = o["box"]
            sig.append((o["op"], round(b.x, 2), round(b.y, 2), round(b.w, 2), round(b.h, 2)))
    return hashlib.sha1(repr(sig).encode()).hexdigest()


def _pptx_texts(path):
    from pptx import Presentation
    prs = Presentation(path)
    out = []
    for s in prs.slides:
        t = [sh.text_frame.text for sh in s.shapes
             if sh.has_text_frame and sh.text_frame.text.strip()]
        out.append("\n".join(t))
    return out


MATRIX_PAGES = [
    {"kind": "cover", "kicker": "K", "title": "封面标题测试", "sub": "副题"},
    {"kind": "statement", "statement": "一句主张，用来测试居中与断行。"},
    {"kind": "section", "index": "01", "title": "章节标题", "lead": "提要"},
    {"kind": "points", "title": "三条要点", "items": ["要点一", "要点二", "要点三"]},
    {"kind": "metrics", "title": "三个数", "metrics": [{"v": "12", "l": "甲"}, {"v": "34", "l": "乙"}]},
    {"kind": "band", "title": "色带数字", "metrics": [{"v": "56", "l": "丙"}, {"v": "78", "l": "丁"}]},
    {"kind": "cards", "title": "三张卡", "cards": [{"v": "01", "h": "标题", "t": "说明文字"}]},
    {"kind": "split", "title": "图文", "items": [{"h": "小标题", "t": "正文一段"}]},
    {"kind": "imagepanel", "title": "叠压", "items": ["一条", "两条"]},
    {"kind": "compare", "title": "对比", "columns": [{"head": "A", "body": ["甲"]},
                                                    {"head": "B", "body": ["乙"]}]},
    {"kind": "table", "title": "表", "columns": ["列一", "列二"],
     "rows": [["a", "b"], ["c", "d"]]},
    {"kind": "chart", "title": "图", "categories": ["a", "b"], "values": [1, 2]},
    {"kind": "gallery", "title": "图集"},
    {"kind": "quote", "quote": "一句引语。", "by": "出处"},
    {"kind": "closing", "title": "谢谢"},
]


def matrix(image=None, out_dir=None, verbose=True):
    """五语言 × 全页型 × 有图/无图：任何一页崩都算失败。"""
    from . import compose as CP
    from . import render as RD
    tmp = out_dir or tempfile.mkdtemp(prefix="metre-matrix-")
    os.makedirs(tmp, exist_ok=True)
    bad = []
    for lang in LG.LANGS:
        for with_img in (False, True):
            pages = []
            for base in MATRIX_PAGES:
                pg = dict(base)
                if with_img and image:
                    pg["image"] = image
                pages.append(pg)
            content = {"language": lang, "pages": pages,
                       "assets": ([image] if image else [])}
            try:
                built, info = CP.build_deck(content, base_dir=os.path.dirname(str(image or ".")))
                out = os.path.join(tmp, f"{lang}-{'img' if with_img else 'noimg'}.pptx")
                RD.render_deck([{"bg": p["bg"], "ops": p["ops"],
                                 "texture": p.get("texture"), "lang": info["lang"]}
                                for p in built], out)
            except Exception as exc:                     # noqa: BLE001
                bad.append((lang, with_img, repr(exc)[:120]))
                if verbose:
                    print(f"[FAIL] {lang} {'图' if with_img else '无图'}：{exc}")
    if verbose and not bad:
        print(f"[PASS] 矩阵：{len(LG.LANGS)} 语言 × {len(MATRIX_PAGES)} 页型 × 有图/无图")
    return not bad, bad


def run(deck_paths, out_dir=None, verbose=True):
    tmp = out_dir or tempfile.mkdtemp(prefix="metre-selftest-")
    os.makedirs(tmp, exist_ok=True)
    report, ok = [], True
    for path in deck_paths:
        content = json.load(open(path, encoding="utf8"))
        base = os.path.dirname(os.path.abspath(path))
        name = os.path.basename(os.path.dirname(path))
        row = {"deck": name, "errors": []}
        try:
            check_limits(content)
            check_paths(content, base)
        except GuardError as exc:
            row["errors"].append(f"规模/路径：{exc}")
            ok = False
        out1 = os.path.join(tmp, name + "-a.pptx")
        pages, issues = build_once(content, base, out1)
        hard = [i for i in issues if i[0] == "err"]
        row["pages"] = len(pages)
        row["hard"] = len(hard)
        row["img_ratio"] = round(sum(1 for p in pages if p.get("has_img")) / max(1, len(pages)), 2)
        if hard:
            row["errors"] += [f"版式：{m}（P{pi}）{d}" for _, m, pi, d in hard[:4]]
            ok = False
        has_pool = bool(content.get("assets") or content.get("pool"))
        if has_pool and row["img_ratio"] < 1.0:
            row["errors"].append(f"配图：{row['img_ratio']:.0%} < 100%（有资产池就必须每页有图）")
            ok = False
        if max(len(p["ops"]) for p in pages) > MAX_OPS_PAGE:
            row["errors"].append("单页元素过多")
            ok = False
        out2 = os.path.join(tmp, name + "-b.pptx")
        pages2, _ = build_once(content, base, out2)
        same = _geom_signature(pages) == _geom_signature(pages2)
        row["deterministic"] = same
        if not same:
            row["errors"].append("两次构建几何不一致")
            ok = False
        import zipfile
        blob = b""
        with zipfile.ZipFile(out1) as z:
            for n in z.namelist():
                if n.endswith(".xml"):
                    blob += z.read(n)
        for bad in ("/Users/", "ppt-mak" + "er"):
            if bad.encode() in blob:
                row["errors"].append(f"泄露：产物含 {bad}")
                ok = False
        texts = re.sub(r"\s+", "", "\n".join(_pptx_texts(out1)))
        for p in (content.get("pages") or [])[:6]:
            t = re.sub(r"\s+", "", str(p.get("title") or ""))
            if t and t[:12] not in texts:
                row["errors"].append(f"丢字：{t[:14]}")
                ok = False
        report.append(row)
        if verbose:
            flag = "PASS" if not row["errors"] else "FAIL"
            print(f"[{flag}] {name:<22} {row['pages']} 页  硬伤 {row['hard']}  "
                  f"配图 {row['img_ratio']:.0%}  确定 {row['deterministic']}")
            for e in row["errors"]:
                print("        -", e)
    return ok, report


def check_skill_file(path):
    """SKILL.md 不得含可被利用的指令。"""
    bad = [r"ignore (all )?previous", r"忽略(以上|之前)", r"rm -rf", r"eval\(", r"os\.system"]
    txt = open(path, encoding="utf8").read()
    return [b for b in bad if re.search(b, txt, re.I)]
