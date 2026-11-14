"""联网取图：从 Wikimedia Commons 检索、下载、登记许可。

为什么用 Commons：图有明确的许可字段（CC0 / CC BY / CC BY-SA / PD），
API 免费、无需 key，适合「先能用、再谈好看」。Unsplash/Pexels 需要 key，
留一个 provider 接口，拿到 key 再接。

三种用法（对应渲染层的三个 op）：
- `bg`      整页背景（压暗/染色后使用）
- `fill`    形状内填充图片（圆、圆角矩形、椭圆都能填）
- `decor`   小图装饰（图标条、纹理条）

所有下载都写 `来源.json`：查询词、标题、作者、许可、许可链接、原始页面。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request

UA = "Metre/3.1 (slide research; python-urllib)"
API = "https://commons.wikimedia.org/w/api.php"
OK_LICENSES = ("cc0", "cc by", "cc-by", "public domain", "pd", "cc by-sa",
               "cc-by-sa", "gfdl")


def _get(url, binary=False, timeout=40):
    """优先 urllib；握手失败时退回系统 curl（本机 curl 走系统证书链更稳）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        return data if binary else data.decode("utf8", "replace")
    except Exception:
        import subprocess
        r = subprocess.run(["curl", "-sSL", "--max-time", str(timeout),
                            "-A", UA, url], capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode("utf8", "replace")[:200])
        return r.stdout if binary else r.stdout.decode("utf8", "replace")


def _clean(html):
    return re.sub(r"<[^>]+>", "", str(html or "")).strip()


def search(query, limit=12, min_width=1200, landscape=True):
    """返回候选列表，已按「可商用许可 + 尺寸 + 横图」过滤。"""
    q = urllib.parse.quote(query)
    url = (f"{API}?action=query&generator=search&gsrsearch=filetype%3Abitmap%20{q}"
           f"&gsrlimit={int(limit)}&gsrnamespace=6&prop=imageinfo"
           f"&iiprop=url%7Csize%7Cextmetadata&iiurlwidth=1600&format=json")
    try:
        raw = _get(url)
        data = json.loads(raw)
    except Exception as exc:
        return [], f"请求失败：{exc}"
    pages = (data.get("query") or {}).get("pages") or {}
    out = []
    for p in pages.values():
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata") or {}
        lic = _clean(meta.get("LicenseShortName", {}).get("value"))
        low = lic.lower()
        if not any(k in low or k in lic for k in OK_LICENSES):
            continue
        w, h = ii.get("width", 0), ii.get("height", 0)
        if w < min_width:
            continue
        if landscape and h and w / h < 1.05:
            continue
        thumb = ii.get("thumburl") or ii.get("url")
        if not thumb:
            continue
        out.append({
            "title": p.get("title", "").replace("File:", ""),
            "url": thumb,
            "page": ii.get("descriptionurl") or "",
            "w": w, "h": h,
            "license": lic,
            "license_url": _clean(meta.get("LicenseUrl", {}).get("value")),
            "author": _clean(meta.get("Artist", {}).get("value"))[:80],
            "credit": _clean(meta.get("Credit", {}).get("value"))[:120],
        })
    return out, None


def download(item, out_dir, name):
    os.makedirs(out_dir, exist_ok=True)
    ext = ".png" if ".png" in item["url"].lower() else ".jpg"
    path = os.path.join(out_dir, name + ext)
    data = _get(item["url"], binary=True)
    with open(path, "wb") as f:
        f.write(data)
    item["file"] = os.path.basename(path)
    item["sha256"] = hashlib.sha256(data).hexdigest()[:16]
    item["bytes"] = len(data)
    return path


def fetch(queries, out_dir, count=4, per_query=6, min_width=1200,
          landscape=True, prefix="img", log=print):
    """按一组查询词取图；每组最多 count 张，跨查询去重。

    返回 manifest（也写进 out_dir/来源.json）。
    """
    os.makedirs(out_dir, exist_ok=True)
    manifest_path = os.path.join(out_dir, "来源.json")
    manifest = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"),
                "source": "Wikimedia Commons", "items": []}
    if os.path.exists(manifest_path):
        try:
            manifest = json.load(open(manifest_path, encoding="utf8"))
            manifest.setdefault("items", [])
        except Exception:
            pass
    seen = {i.get("title") for i in manifest["items"]}
    idx = len(manifest["items"])
    for q in queries:
        got = 0
        res, err = search(q, limit=per_query, min_width=min_width,
                          landscape=landscape)
        if err:
            log(f"  ! {q}: {err}")
            continue
        for item in res:
            if got >= count:
                break
            if item["title"] in seen:
                continue
            idx += 1
            try:
                path = download(item, out_dir, f"{prefix}{idx:02d}")
            except Exception as exc:
                log(f"  ! 下载失败 {item['title'][:40]}: {exc}")
                continue
            item["query"] = q
            item["scene"] = os.path.basename(path)
            manifest["items"].append(item)
            seen.add(item["title"])
            got += 1
            log(f"  + {os.path.basename(path)}  {item['title'][:46]}  "
                f"[{item['license']}]")
    json.dump(manifest, open(manifest_path, "w", encoding="utf8"),
              ensure_ascii=False, indent=1)
    return manifest


def credits(manifest_path, lang="zh"):
    """给成品做一页「图片来源」，或写入页脚。"""
    data = json.load(open(manifest_path, encoding="utf8"))
    lines = []
    for i in data.get("items", []):
        lines.append({
            "file": i.get("file"),
            "title": i.get("title"),
            "author": i.get("author"),
            "license": i.get("license"),
            "license_url": i.get("license_url"),
            "page": i.get("page"),
        })
    return lines
