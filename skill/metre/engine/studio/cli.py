"""studio：度量驱动的幻灯片引擎。"""
from __future__ import annotations

__version__ = "3.0.0"
__codename__ = "立骨"


def build(content, out_path, base_dir=".", audit_path=None, render_dir=None,
          verbose=True):
    """内容 JSON(dict) → pptx。返回 (pages, issues, score)。"""
    import json
    from . import audit as AUD
    from . import compose as CP
    from . import languages as LG
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


BANNED = ()  # 指纹改为结构化检测（audit.watermark），源码不保存任何样板文案


def render_png(pptx_path, out_dir, width=None):
    """Keynote 出图（本机唯一稳定的渲染器）。"""
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
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode:
        print("渲染失败：", r.stderr.strip()[:300])
        return None
    return out_dir


def load(path):
    import json
    with open(path, encoding="utf8") as f:
        return json.load(f)


def main(argv=None):
    import glob
    import json
    import os
    import sys
    argv = argv or sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        print("""用法：
  python3 -m studio.cli spec                      # 五套语言的参数
  python3 -m studio.cli build deck.json out.pptx   # 生成 + 体检
  python3 -m studio.cli build deck.json out.pptx --png preview/
  python3 -m studio.cli new > deck.json            # 空内容骨架
  python3 -m studio.cli fetch assets/咖啡 "coffee roasting|espresso" --n 6   # 联网取图
  python3 -m studio.cli palette topic=咖啡 out=palette.json   # 上网查配色
  python3 -m studio.cli selftest                   # 自检：版式/确定性/安全/规模
""")
        return 0
    cmd = argv[0]
    if cmd == "spec":
        if "--json" in argv:
            import json as _json
            from .api import spec as _spec
            print(_json.dumps(_spec(), ensure_ascii=False, indent=2))
            return 0
        from . import languages as LG
        for lid, l in LG.LANGS.items():
            print(f"{lid:<10} {l.name}  {l.display}/{l.ea_display}  "
                  f"纸 {l.paper} 墨 {l.title_c} 强调 {l.accent}  "
                  f"字阶 {l.type.cover}/{l.type.h1}/{l.type.h2}/{l.type.lead}/{l.type.body}/"
                  f"{l.type.small}/{l.type.micro}")
            print(f"           {l.tagline}")
            print(f"           留白 {l.margin}pt 标题起点 {l.head_top:.2f}H "
                  f"密度 {l.density[0]}–{l.density[1]} 装饰 {','.join(l.ornaments)}")
        return 0
    if cmd == "new":
        from . import languages as LG
        skeleton = {
            "language": "grid",
            "pages": [
                {"kind": "cover", "kicker": "2026 · 提案", "title": "标题",
                 "sub": "一句话副题", "image": ""},
                {"kind": "points", "kicker": "第一节", "title": "三个要点",
                 "items": ["要点一", "要点二", "要点三"]},
                {"kind": "closing", "title": "谢谢"},
            ],
        }
        print(json.dumps(skeleton, ensure_ascii=False, indent=2))
        return 0
    if cmd == "palette":
        from . import colorlab as CL
        import json as _json
        args = dict(a.split("=", 1) for a in argv[1:] if "=" in a)
        out = args.pop("out", "palette.json")
        mode = args.pop("mode", "analogic")
        d = CL.suggest(topic=args.get("topic"), seed=args.get("seed"),
                       mood=args.get("mood"), mode=mode)
        _json.dump(d, open(out, "w", encoding="utf8"), ensure_ascii=False, indent=2)
        print(f"→ {out}")
        print(f"  纸 {d['paper']}  墨 {d['ink']}  强调 {d['accent']}  备选 {', '.join(d['accents'])}")
        print(f"  对比度 强调/纸 {d['checks']['accent_vs_paper']}:1  墨/纸 {d['checks']['ink_vs_paper']}:1")
        return 0
    if cmd == "style":
        import json as _json
        from . import languages as LG
        me = LG.LANGS.get("me")
        if not me:
            print("没有 style/me.json；先用默认设置")
            return 1
        if argv[1:2] and argv[1].startswith("--set"):
            kv = argv[1][6:] if "=" in argv[1] else ""
            print("改风格请直接编辑 style/me.json（这是单一事实源）")
            return 0
        print(f"当前默认风格：{me.name}")
        print(f"  纸 {me.paper}  墨 {me.title_c}  强调 {me.accent}  底板 {me.panel_c}")
        pool = LG.FONT_POOL.get(me.font_tone, [])
        names = " / ".join(t[0] for t in pool) or me.ea_display
        print(f"  字体池 {me.font_tone}：{names}")
        print(f"  圆角 {me.radius_ratio:.2f}  "
              f"阴影 {'无' if not me.shadow else list(me.shadow)}")
        print(f"  对齐 {me.align_bias}  居中页型 {','.join(me.center_kinds) or '无'}")
        print(f"  边距 {me.margin}pt  布局偏好 {','.join(me.layout_pool)}")
        print(f"  文件 style/me.json")
        return 0
    if cmd == "selftest":
        from . import selftest as ST
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        paths = argv[1:] or sorted(glob.glob(os.path.join(root, "examples", "**", "deck.json"),
                                             recursive=True))
        if not paths:
            print("✗ 找不到任何 deck（默认跑仓库 examples/**/deck.json）；"
                  "请显式传入路径")
            return 2
        ok_m, _bad = ST.matrix(image=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "examples", "coffee", "assets", "cover.jpg"))
        ok, rep = ST.run(paths)
        ok = ok and ok_m
        hits = ST.check_skill_file(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SKILL.md"))
        if hits:
            print("SKILL.md 含风险指令：", hits)
            ok = False
        print("\n结果：", "全部通过" if ok else "有失败项")
        return 0 if ok else 1
    if cmd == "fetch":
        from . import images as IMG
        if len(argv) < 3:
            print("用法：fetch <输出目录> <查询词1|查询词2> [--n 6] [--prefix img]")
            return 2
        out_dir, qs = argv[1], argv[2]
        n = 6
        prefix = "img"
        if "--n" in argv:
            n = int(argv[argv.index("--n") + 1])
        if "--prefix" in argv:
            prefix = argv[argv.index("--prefix") + 1]
        man = IMG.fetch([q.strip() for q in qs.split("|") if q.strip()], out_dir,
                        count=n, prefix=prefix)
        print(f"\n{len(man['items'])} 张，来源 JSON 已写入 {out_dir}/来源.json")
        return 0
    if cmd == "build":
        if len(argv) < 3:
            print("用法：build deck.json out.pptx [--png dir]")
            return 2
        src, out = argv[1], argv[2]
        png = None
        if "--png" in argv:
            png = argv[argv.index("--png") + 1]
        content = load(src)
        base = __import__("os").path.dirname(__import__("os").path.abspath(src))
        try:
            pages, issues, score = build(
                content, out, base_dir=base,
                audit_path=out.replace(".pptx", "-体检.md"), render_dir=png)
        except (ValueError, FileNotFoundError) as exc:
            print(f"\n✗ 构建失败：{exc}")
            return 2
        hard = [i for i in issues if i[0] == "err"]
        if hard and "--allow-hard" not in argv:
            print(f"\n✗ {len(hard)} 处硬伤，未通过门禁；"
                  f"修好后重跑，或加 --allow-hard 强制出片")
            return 1
        return 0
    print("未知命令", cmd)
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(main())
