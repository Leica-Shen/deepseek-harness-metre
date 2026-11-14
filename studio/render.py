"""渲染器：把 op 列表写成 pptx。

只做三件事：几何照抄 op 的 box、样式照抄 lang、任何自适应都关掉
（auto_size=None / word_wrap=True / 手动 a:br）。关掉自适应是 3.0 的
核心决定：版面在出片前就已经算定，渲染器不许再「猜」。

坐标换算：1 pt = 12700 EMU。
"""
from __future__ import annotations

import hashlib
import math
import os
import tempfile
from lxml import etree
from PIL import Image, ImageOps
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
PT = 12700
ALIGN = {"l": PP_ALIGN.LEFT, "ctr": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT,
         "just": PP_ALIGN.JUSTIFY}


def rgb(h):
    h = str(h).lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _paint_fill(shape_or_fill, color, alpha=None):
    fill = shape_or_fill
    fill.solid()
    fill.fore_color.rgb = rgb(color)
    if alpha is not None and alpha < 100:
        srgb = fill._xPr.find(A + "solidFill").find(A + "srgbClr")
        a = etree.SubElement(srgb, A + "alpha")
        a.set("val", str(int(alpha * 1000)))


def _no_line(shape):
    shape.line.fill.background()


def _line(shape, color, pt):
    shape.line.color.rgb = rgb(color)
    shape.line.width = Pt(pt)


def _shadow(shape, blur=15.0, dist=5.0, direction=5400000, alpha=30,
            color="1F3550"):
    spPr = shape._element.spPr
    for old in spPr.findall(A + "effectLst"):
        spPr.remove(old)
    eff = etree.SubElement(spPr, A + "effectLst")
    sh = etree.SubElement(eff, A + "outerShdw")
    sh.set("blurRad", str(int(blur * PT)))
    sh.set("dist", str(int(dist * PT)))
    sh.set("dir", str(direction))
    sh.set("algn", "t")
    sh.set("rotWithShape", "0")
    c = etree.SubElement(sh, A + "srgbClr")
    c.set("val", str(color))
    al = etree.SubElement(c, A + "alpha")
    al.set("val", str(int(alpha * 1000)))


def _round(shape, radius_pt, box):
    """把 roundRect 的调整值按「半径 / 短边」写成相对值。"""
    try:
        short = max(1.0, min(box.w, box.h))
        adj = max(0.0, min(0.5, radius_pt / short))
        shape.adjustments[0] = adj
    except Exception:
        pass


def _grad_scrim(slide, box, color, alpha_from, alpha_to, angle_deg):
    """渐变暗幕：真实 gradFill，WPS 与 PowerPoint 都支持线性渐变。"""
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(int(box.x * PT)),
                                Emu(int(box.y * PT)), Emu(int(box.w * PT)),
                                Emu(int(box.h * PT)))
    _no_line(sh)
    sh.fill.gradient()
    sh.fill.gradient_angle = angle_deg
    stops = sh.fill.gradient_stops
    stops[0].color.rgb = rgb(color)
    stops[0].position = 0.0
    stops[1].color.rgb = rgb(color)
    stops[1].position = 1.0
    # alpha 用 XML 精确写：起止不同
    grad = sh.fill._xPr.find(A + "gradFill")
    for gs, al in zip(grad.findall(A + "gsLst")[0], (alpha_from, alpha_to)):
        srgb = gs.find(A + "srgbClr")
        for old in srgb.findall(A + "alpha"):
            srgb.remove(old)
        a = etree.SubElement(srgb, A + "alpha")
        a.set("val", str(int(al * 1000)))
    # 角度
    lin = grad.find(A + "lin")
    if lin is None:
        lin = etree.SubElement(grad, A + "lin")
    lin.set("ang", str(int(angle_deg * 60000)))
    lin.set("scaled", "1")
    return sh


def _crop_for(path, box, fit, focus):
    """算等比填充裁切量。返回 (l,t,r,b) 千分比。"""
    try:
        iw, ih = Image.open(path).size
    except Exception:
        return (0, 0, 0, 0)
    src = iw / float(ih)
    dst = box.w / float(box.h) if box.h else src
    if fit == "contain":
        return (0, 0, 0, 0)
    if src > dst:                       # 图更宽 → 左右裁
        keep = dst / src
        fx = min(1.0, max(0.0, focus[0]))
        over = 1.0 - keep
        l = over * fx
        r = over - l
        return (int(l * 100000), 0, int(r * 100000), 0)
    else:                               # 图更高 → 上下裁
        keep = src / dst
        fy = min(1.0, max(0.0, focus[1]))
        over = 1.0 - keep
        t = over * fy
        b = over - t
        return (0, int(t * 100000), 0, int(b * 100000))


def _text_frame(slide, box, lang):
    tb = slide.shapes.add_textbox(Emu(int(box.x * PT)), Emu(int(box.y * PT)),
                                  Emu(int(max(box.w, 2) * PT)),
                                  Emu(int(max(box.h, 2) * PT)))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.TOP
    return tb, tf


def _style_run(run, *, font, ea, size, bold, color, tracking=0.0, italic=False,
               opacity=None, image_fill=None, slide=None, box=None):
    f = run.font
    f.size = Pt(size)
    f.bold = bool(bold)
    f.italic = bool(italic)
    f.name = font
    if image_fill and slide is not None and box is not None:
        rid = _image_rid(slide, image_fill, box)
        if rid:
            rPr0 = run._r.get_or_add_rPr()
            for old in rPr0.findall(A + "solidFill"):
                rPr0.remove(old)
            _apply_blip(rPr0, rid)
        else:
            f.color.rgb = rgb(color)
    else:
        f.color.rgb = rgb(color)
    rPr = run._r.get_or_add_rPr()
    # 主题字体也要写死，避免母版字体回流
    for tag, face in (("a:ea", ea), ("a:cs", font)):
        el = rPr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rPr, qn(tag))
        el.set("typeface", face)
    if tracking:
        rPr.set("spc", str(int(round(tracking * 100))))
    if opacity is not None and opacity < 100:
        srgb = rPr.find(A + "solidFill").find(A + "srgbClr")
        a = etree.SubElement(srgb, A + "alpha")
        a.set("val", str(int(opacity * 1000)))


def _emit_text(slide, op, lang=None):
    box = op["box"]
    tb, tf = _text_frame(slide, box, lang)
    tf.word_wrap = False if op.get("no_wrap") else True
    lines = op["lines"] or [""]
    p = tf.paragraphs[0]
    p.alignment = ALIGN.get(op.get("align", "l"), PP_ALIGN.LEFT)
    p.line_spacing = Pt(op["size"] * op["leading"])
    if op.get("space_after"):
        p.space_after = Pt(op["space_after"])
    if op.get("bullet"):
        marL = int(op["hang"] * PT)
        pPr = p._pPr if p._pPr is not None else p._p.get_or_add_pPr()
        pPr.set("marL", str(marL))
        pPr.set("indent", str(-marL))
        bu = etree.SubElement(pPr, A + "buChar")
        bu.set("char", op["bullet"])
        # buFont 必须紧跟在 buChar 之前
        bf = etree.Element(A + "buFont")
        bf.set("typeface", "Arial")
        pPr.insert(list(pPr).index(bu), bf)
    from .textmetrics import is_ea_char
    for i, line in enumerate(lines):
        if i:
            p.add_line_break()
        # 按字符类型切 run：中文与符号走 ea 字体，其余走 latin 字体，
        # 免得展示字体缺「¥」「—」这类字时被替换成奇怪形状
        segs, cur, cur_ea = [], "", None
        for ch in line:
            ea_ch = is_ea_char(ch)
            if cur_ea is None or ea_ch == cur_ea:
                cur += ch
                cur_ea = ea_ch
            else:
                segs.append((cur, cur_ea))
                cur, cur_ea = ch, ea_ch
        if cur:
            segs.append((cur, cur_ea))
        for text_seg, ea_seg in segs:
            r = p.add_run()
            r.text = text_seg
            _style_run(r, font=op["ea"] if ea_seg else op["font"],
                       ea=op["ea"], size=op["size"],
                       bold=op["bold"], color=op["color"],
                       tracking=op.get("tracking", 0.0),
                       italic=op.get("italic", False),
                       opacity=op.get("opacity"),
                       image_fill=op.get("image_fill"), slide=slide,
                       box=op["box"])
    return tb


def _emit_rule(slide, op, lang=None):
    b = op["box"]
    h = max(0.6, b.h if b.h > 0.6 else op.get("pt", 1.0))
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(int(b.x * PT)),
                                Emu(int(b.y * PT)), Emu(int(max(b.w, 1) * PT)),
                                Emu(int(h * PT)))
    _no_line(sh)
    _paint_fill(sh.fill, op["color"])
    return sh


def _image_rid(slide, path, box):
    """把图片塞进包的 media，拿到 rId 后删掉临时形状，供 blipFill 引用。"""
    try:
        pic = slide.shapes.add_picture(path, Emu(int(box.x * PT)),
                                       Emu(int(box.y * PT)),
                                       Emu(int(max(box.w, 1) * PT)),
                                       Emu(int(max(box.h, 1) * PT)))
        rid = pic._element.blipFill.blip.rEmbed
        pic._element.getparent().remove(pic._element)
        return rid
    except Exception:
        return None


def _apply_blip(spPr, rid, stretch=True):
    for tag in ("a:solidFill", "a:noFill", "a:gradFill", "a:pattFill", "a:blipFill"):
        for old in spPr.findall(A + tag):
            spPr.remove(old)
    bf = etree.Element(A + "blipFill")
    blip = etree.SubElement(bf, A + "blip")
    blip.set("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed", rid)
    if stretch:
        st = etree.SubElement(bf, A + "stretch")
        etree.SubElement(st, A + "fillRect")
    ln = spPr.find(A + "ln")
    if ln is not None:
        ln.addprevious(bf)
    else:
        spPr.append(bf)


def _emit_panel(slide, op, lang=None):
    b = op["box"]
    shape = MSO_SHAPE.ROUNDED_RECTANGLE if op.get("radius", 0) > 0 else MSO_SHAPE.RECTANGLE
    sh = slide.shapes.add_shape(shape, Emu(int(b.x * PT)), Emu(int(b.y * PT)),
                                Emu(int(max(b.w, 1) * PT)),
                                Emu(int(max(b.h, 1) * PT)))
    if op.get("image"):
        rid = _image_rid(slide, op["image"], b)
        if rid:
            _apply_blip(sh._element.spPr, rid)
        else:
            _paint_fill(sh.fill, op["color"], op.get("alpha", 100))
    else:
        _paint_fill(sh.fill, op["color"], op.get("alpha", 100))
    if op.get("radius", 0) > 0:
        _round(sh, op["radius"], b)
    if op.get("line"):
        _line(sh, op["line"], op.get("line_pt", 1.0))
    else:
        _no_line(sh)
    if op.get("shadow"):
        sd = op["shadow"]
        if isinstance(sd, (tuple, list)) and len(sd) == 4:
            _shadow(sh, sd[0], sd[1], sd[2] * 60000, int(sd[3]),
                    color=op.get("shadow_color", "1F3550"))
        else:
            _shadow(sh)
    if op.get("rotate"):
        sh.rotation = op["rotate"]
    return sh


def _emit_dot(slide, op, lang=None):
    b = op["box"]
    sh = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(b.x * PT)),
                                Emu(int(b.y * PT)), Emu(int(b.w * PT)),
                                Emu(int(b.h * PT)))
    _no_line(sh)
    _paint_fill(sh.fill, op["color"], op.get("alpha", 100))
    return sh


def _emit_hex(slide, op, lang=None):
    b = op["box"]
    sh = slide.shapes.add_shape(MSO_SHAPE.HEXAGON, Emu(int(b.x * PT)),
                                Emu(int(b.y * PT)), Emu(int(b.w * PT)),
                                Emu(int(b.h * PT)))
    if op.get("color"):
        _paint_fill(sh.fill, op["color"], op.get("alpha", 100))
    else:
        sh.fill.background()
    if op.get("line"):
        _line(sh, op["line"], 0.75)
    else:
        _no_line(sh)
    return sh


def _emit_frame(slide, op, lang=None):
    b = op["box"]
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(int(b.x * PT)),
                                Emu(int(b.y * PT)), Emu(int(max(b.w, 1) * PT)),
                                Emu(int(max(b.h, 1) * PT)))
    sh.fill.background()
    _line(sh, op["color"], op.get("pt", 0.75))
    return sh


_BAKE_DIR = os.path.join(tempfile.gettempdir(), "lppt-bake")


def _bake(path, grayscale=False, tint=None):
    """把「灰阶 / 单色染色」烘焙进图片，避免依赖渲染器对 blip 效果的支持。"""
    if not grayscale and not tint:
        return path
    try:
        os.makedirs(_BAKE_DIR, exist_ok=True)
        stem = hashlib.sha1((path + str(grayscale) + str(tint) +
                             str(os.path.getmtime(path))).encode()).hexdigest()[:16]
        dst = os.path.join(_BAKE_DIR, stem + ".jpg")
        if os.path.exists(dst):
            return dst
        im = Image.open(path).convert("RGB")
        if grayscale:
            im = ImageOps.grayscale(im)
            im = ImageOps.autocontrast(im, cutoff=1)
            im = im.convert("RGB")
        if tint:
            overlay = Image.new("RGB", im.size, rgb(tint))
            im = Image.blend(im, overlay, 0.22)
        im.save(dst, quality=90)
        return dst
    except Exception:
        return path


def _emit_media(slide, op, lang=None):
    b = op["box"]
    path = _bake(op["path"], op.get("grayscale"), op.get("tint"))
    if not path or not os.path.exists(path):
        return None
    pic = slide.shapes.add_picture(path, Emu(int(b.x * PT)), Emu(int(b.y * PT)),
                                   Emu(int(max(b.w, 1) * PT)),
                                   Emu(int(max(b.h, 1) * PT)))
    l, t, r, bo = _crop_for(path, b, op.get("fit", "cover"), op.get("focus", (0.5, 0.5)))
    if any((l, t, r, bo)):
        pic.crop_left, pic.crop_top, pic.crop_right, pic.crop_bottom = (
            l / 100000.0, t / 100000.0, r / 100000.0, bo / 100000.0)
    if op.get("radius", 0) > 0:
        spPr = pic._element.spPr
        for old in spPr.findall(A + "prstGeom"):
            spPr.remove(old)
        geom = etree.SubElement(spPr, A + "prstGeom")
        geom.set("prst", "roundRect")
        av = etree.SubElement(geom, A + "avLst")
        gd = etree.SubElement(av, A + "gd")
        gd.set("name", "adj")
        short = max(1.0, min(b.w, b.h))
        gd.set("fmla", "val %d" % int(max(0, min(50000, op["radius"] / short * 100000))))
        # prstGeom 必须在 spPr 中子元素顺序正确
        ln = spPr.find(A + "ln")
        if ln is not None:
            spPr.remove(geom)
            ln.addprevious(geom)
    if op.get("frame"):
        _line(pic, op["frame"], op.get("frame_pt", 1.0))
    sc = op.get("scrim")
    if sc and sc.get("alpha", 0) > 0:
        mode = sc.get("mode", "full")
        if mode == "full":
            sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(int(b.x * PT)),
                                        Emu(int(b.y * PT)), Emu(int(b.w * PT)),
                                        Emu(int(b.h * PT)))
            _no_line(sh)
            _paint_fill(sh.fill, sc["color"], sc["alpha"])
        elif mode == "bottom":
            h = b.h * 0.55
            _grad_scrim(slide, type(b)(b.x, b.y + b.h - h, b.w, h), sc["color"],
                        0, sc["alpha"], 90)
        elif mode == "left":
            w = b.w * 0.6
            _grad_scrim(slide, type(b)(b.x, b.y, w, b.h), sc["color"],
                        sc["alpha"], 0, 0)
        elif mode == "right":
            w = b.w * 0.6
            _grad_scrim(slide, type(b)(b.x + b.w - w, b.y, w, b.h), sc["color"],
                        0, sc["alpha"], 0)
    return pic


def _emit_table(slide, op, lang=None):
    """细线表：只有横线，没有竖线；表头用墨色，正文用灰。"""
    b = op["box"]
    cols = op["columns"]
    rows = op["rows"]
    lang = op["lang"]
    nrow, ncol = len(rows) + 1, len(cols)
    shape = slide.shapes.add_table(nrow, ncol, Emu(int(b.x * PT)),
                                   Emu(int(b.y * PT)), Emu(int(b.w * PT)),
                                   Emu(int(b.h * PT)))
    tbl = shape.table
    # 列宽：按内容长度分
    from . import textmetrics as TM
    weights = []
    for ci in range(ncol):
        w = max([TM.text_width(str(cols[ci]), 12, lang.body_font, lang.ea_body)] +
                [TM.text_width(str(r[ci]), 12, lang.body_font, lang.ea_body) for r in rows])
        weights.append(max(0.6, w))
    total = sum(weights)
    for ci, wt in enumerate(weights):
        tbl.columns[ci].width = Emu(int(b.w * wt / total * PT))
    head_h = op.get("head_h", 30)
    row_h = op.get("row_h", 34)
    for ri in range(nrow):
        tbl.rows[ri].height = Emu(int((head_h if ri == 0 else row_h) * PT))
    # 去默认样式
    tblPr = shape._element.graphic.graphicData.tbl.tblPr
    for attr in ("firstRow", "bandRow", "firstCol", "lastRow", "lastCol"):
        tblPr.set(attr, "0")
    style = tblPr.find(A + "tableStyleId")
    if style is not None:
        tblPr.remove(style)
    head_fill = op.get("head_fill")
    for ri in range(nrow):
        for ci in range(ncol):
            cell = tbl.cell(ri, ci)
            if ri == 0 and head_fill:
                cell.fill.solid()
                cell.fill.fore_color.rgb = rgb(head_fill)
            else:
                cell.fill.background()
            cell.margin_left = cell.margin_right = Emu(int(0 * PT))
            cell.margin_top = cell.margin_bottom = Emu(int(4 * PT))
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = ALIGN["l"] if ci == 0 else ALIGN.get(op.get("align", "l"), PP_ALIGN.LEFT)
            txt = cols[ci] if ri == 0 else rows[ri - 1][ci]
            r = p.add_run()
            r.text = str(txt)
            _style_run(r, font=lang.body_font, ea=lang.ea_body,
                       size=op.get("head_size", 13) if ri == 0 else op.get("size", 13),
                       bold=(ri == 0) or (ci == 0),
                       color=op.get("head_color", lang.title_c) if ri == 0 else op.get("color", lang.body_c))
            # 边框：只有横线
            tcPr = cell._tc.get_or_add_tcPr()
            for side, on, width in (("a:lnT", ri == 0, 1.2),
                                    ("a:lnB", True, 0.75),
                                    ("a:lnL", False, 0), ("a:lnR", False, 0)):
                el = etree.SubElement(tcPr, qn(side))
                el.set("w", str(int(width * PT)))
                el.set("cap", "flat")
                el.set("cmpd", "sng")
                el.set("algn", "ctr")
                if on:
                    sf = etree.SubElement(el, A + "solidFill")
                    c = etree.SubElement(sf, A + "srgbClr")
                    c.set("val", op.get("rule_color", lang.rule_c))
                else:
                    etree.SubElement(el, A + "noFill")
    return shape


def _emit_chart(slide, op, lang=None):
    """原生图表，但把 Office 默认样式全部关掉：无网格、无边框、无图例框。"""
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION
    b = op["box"]
    lang = op["lang"]
    cd = CategoryChartData()
    cd.categories = op["categories"]
    for name, vals in op["series"]:
        cd.add_series(name, vals)
    kind = op.get("kind", "bar")
    ct = {"bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
          "hbar": XL_CHART_TYPE.BAR_CLUSTERED,
          "line": XL_CHART_TYPE.LINE_MARKERS,
          "pie": XL_CHART_TYPE.DOUGHNUT,
          "area": XL_CHART_TYPE.AREA}[kind]
    gf = slide.shapes.add_chart(ct, Emu(int(b.x * PT)), Emu(int(b.y * PT)),
                                Emu(int(b.w * PT)), Emu(int(b.h * PT)), cd)
    ch = gf.chart
    ch.has_title = False
    ch.has_legend = bool(op.get("legend"))
    if ch.has_legend:
        ch.legend.position = XL_LEGEND_POSITION.TOP
        ch.legend.include_in_layout = False
        ch.legend.font.size = Pt(10)
        ch.legend.font.name = lang.body_font
        ch.legend.font.color.rgb = rgb(meta)
    ink = op.get("ink", lang.body_c)
    meta = op.get("meta", lang.meta_c)
    paper = op.get("paper", lang.paper)
    rule_c = op.get("rule", lang.rule_c)
    colors = op.get("colors") or [lang.accent]
    for i, s in enumerate(ch.series):
        col = colors[i % len(colors)]
        if kind in ("bar", "hbar", "area", "line"):
            s.format.fill.solid()
            s.format.fill.fore_color.rgb = rgb(col)
            s.format.line.fill.background()
        if kind == "line":
            s.format.line.color.rgb = rgb(col)
            s.format.line.width = Pt(2.0)
        if kind in ("pie",):
            for j, pt in enumerate(s.points):
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = rgb(colors[j % len(colors)])
                pt.format.line.color.rgb = rgb(paper)
                pt.format.line.width = Pt(1.5)
    try:
        plot = ch.plots[0]
        plot.gap_width = op.get("gap", 90)
        plot.has_data_labels = bool(op.get("labels", True))
        dl = plot.data_labels
        dl.font.size = Pt(op.get("label_size", 12))
        dl.font.name = lang.body_font
        dl.font.color.rgb = rgb(op.get("label_color", ink))
        dl.font.bold = True
        if kind not in ("pie",):
            dl.position = XL_LABEL_POSITION.OUTSIDE_END
        else:
            dl.position = XL_LABEL_POSITION.CENTER
            dl.font.color.rgb = rgb("FFFFFF")
    except Exception:
        pass
    # 绘图区对齐：不让 Office 自动留白把柱子和正文左边距错开
    try:
        cs = ch._chartSpace
        pa = cs.find(qn("c:chart")).find(qn("c:plotArea"))
        lay = pa.find(qn("c:layout"))
        if lay is None:
            lay = etree.SubElement(pa, qn("c:layout"))
            pa.remove(lay)
            pa.insert(0, lay)
        for ch_el in list(lay):
            lay.remove(ch_el)
        ml = etree.SubElement(lay, qn("c:manualLayout"))
        etree.SubElement(ml, qn("c:layoutTarget")).set("val", "inner")
        for tag, val in (("c:xMode", "factor"), ("c:yMode", "factor"),
                         ("c:x", "%.4f" % op.get("plot_x", 0.055)),
                         ("c:y", "%.4f" % op.get("plot_y", 0.02)),
                         ("c:w", "%.4f" % op.get("plot_w", 0.935)),
                         ("c:h", "%.4f" % op.get("plot_h", 0.90))):
            el = etree.SubElement(ml, qn(tag))
            if tag.endswith("Mode"):
                el.set("val", val)
            else:
                el.set("val", val)
    except Exception:
        pass
    va = ch.value_axis
    va.has_major_gridlines = bool(op.get("gridlines"))
    if not op.get("gridlines"):
        try:
            va.major_gridlines.format.line.fill.background()
        except Exception:
            pass
    va.format.line.color.rgb = rgb(rule_c)
    va.format.line.width = Pt(0.75)
    va.tick_labels.font.size = Pt(op.get("tick_size", 10))
    va.tick_labels.font.name = lang.body_font
    va.tick_labels.font.color.rgb = rgb(meta)
    ca = ch.category_axis
    ca.format.line.fill.background()
    ca.tick_labels.font.size = Pt(op.get("tick_size", 11))
    ca.tick_labels.font.name = lang.body_font
    ca.tick_labels.font.color.rgb = rgb(ink)
    ca.has_major_gridlines = False
    try:
        ca.major_tick_mark = 0
        va.major_tick_mark = 0
    except Exception:
        pass
    return gf


_EMITTERS = {
    "text": _emit_text, "rule": _emit_rule, "panel": _emit_panel,
    "dot": _emit_dot, "hex": _emit_hex, "frame": _emit_frame,
    "media": _emit_media, "table": _emit_table, "chart": _emit_chart,
    "folio": _emit_text,
}


def slide_bg(slide, color):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = rgb(color)


def _texture(color, kind):
    """程序生成纸纹/条纹底图（不随包携带任何位图）。"""
    try:
        import numpy as np
        os.makedirs(_BAKE_DIR, exist_ok=True)
        stem = hashlib.sha1((str(color) + kind).encode()).hexdigest()[:16]
        dst = os.path.join(_BAKE_DIR, f"tex-{stem}.png")
        if os.path.exists(dst):
            return dst
        base = np.array(rgb(color), dtype=np.float32)
        w, h = 1200, 675
        rng = np.random.default_rng(abs(hash(str(color) + kind)) % (2 ** 32))
        if kind == "grain":
            noise = rng.normal(0, 2.6, (h, w, 1))
            arr = np.clip(base[None, None, :] + noise, 0, 255).astype(np.uint8)
        elif kind == "stripe":
            pitch = 9
            col = np.where((np.arange(w) // pitch) % 2 == 0, 1.0, 0.965)[None, :, None]
            noise = rng.normal(0, 1.2, (h, w, 1))
            arr = np.clip(base[None, None, :] * col + noise, 0, 255).astype(np.uint8)
        else:
            return None
        Image.fromarray(arr, "RGB").save(dst)
        return dst
    except Exception:
        return None


def render_deck(pages, out_path, *, size=(960, 540)):
    """pages: [dict(bg, ops, bg_img, texture, lang)] 或四/五元组。"""
    prs = Presentation()
    prs.slide_width = Emu(int(size[0] * PT))
    prs.slide_height = Emu(int(size[1] * PT))
    blank = prs.slide_layouts[6]
    for row in pages:
        if isinstance(row, dict):
            bg, ops = row["bg"], row["ops"]
            bg_img = row.get("bg_img")
            page_lang = row.get("lang")
            tex = row.get("texture")
        else:
            bg, ops, bg_img = row[0], row[1], row[2]
            page_lang = row[3] if len(row) > 3 else None
            tex = row[4] if len(row) > 4 else None
        s = prs.slides.add_slide(blank)
        slide_bg(s, bg)
        if tex and tex != "none":
            tp = _texture(bg, tex)
            if tp:
                s.shapes.add_picture(tp, 0, 0, Emu(int(size[0] * PT)),
                                     Emu(int(size[1] * PT)))
        if bg_img:
            s.shapes.add_picture(bg_img, 0, 0, Emu(int(size[0] * PT)),
                                 Emu(int(size[1] * PT)))
        for op in ops:
            fn = _EMITTERS.get(op["op"])
            if fn is None:
                continue
            try:
                fn(s, op, page_lang)
            except Exception as exc:  # 单个 op 失败不应拖垮整册
                print(f"  ! op {op['op']} 渲染失败: {exc}")
    prs.save(out_path)
    return out_path


def render_folio(slide, op):
    _emit_text(slide, op, op["lang"])
