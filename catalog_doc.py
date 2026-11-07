"""신도 카탈로그 문서(catalog.json) 다루기 — editor_server.py 가 쓰고, 따로 불러서 시험할 수도 있다.

render_page_html 은 editor_assets/render.js 의 createPageElement 와 같은 결과를 낸다.
render.js 를 바꾸면 이 파일도 같이 바꿀 것. (문서 구조는 render.js 머리 주석이 정본)
"""
import html
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

BASE = Path(__file__).resolve().parent
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SITE_ASSETS = ("render.js", "viewer.js", "viewer.css", "catalog.css",
               "vendor/page-flip.browser.js", "vendor/page-flip.LICENSE.txt")
SITE_MARK = ".sindo-site"
SITE_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".avif", ".bmp"}


def esc(s):
    return html.escape(s, quote=True)


# ── render.js 와 같은 값을 내기 위한 JS 흉내 ──────────────────────────────

_JS_NUM = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?|0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+", re.ASCII)


def _truthy(v):
    if v is None or v is False:
        return False
    if isinstance(v, (int, float)):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ""
    return True  # JS 에서는 [] 와 {} 도 참


def _fmt(v):
    """JS String(number)"""
    if not math.isfinite(v):
        return "NaN" if v != v else ("Infinity" if v > 0 else "-Infinity")
    if v == int(v) and abs(v) < 1e21:
        return str(int(v))
    return repr(float(v))  # ponytail: 1e-7 같은 아주 작은 수는 JS 표기(1e-7)와 다를 수 있다. 편집기는 그런 값을 안 넣는다


def _jstr(v):
    """JS String(v) — 단 null 은 '' (render.js esc 와 같게)"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return _fmt(v)
    return v if isinstance(v, str) else ""  # ponytail: 객체·배열은 JS 와 다르게 빈 글자로 본다


def _s(v):
    """JS String(v || '')"""
    return _jstr(v) if _truthy(v) else ""


def _num(o, key, d):
    """render.js num(o[key], d): Number() 로 바꿔서 유한하면 그 값, 아니면 d"""
    if not isinstance(o, dict) or key not in o:
        return _fmt(d)
    v = o[key]
    if v is None or isinstance(v, (bool, int, float)):
        f = float(v or 0)
    elif isinstance(v, str) and not v.strip():
        f = 0.0
    elif isinstance(v, str) and _JS_NUM.fullmatch(v.strip()):
        t = v.strip()
        f = float(int(t, 0)) if t[:2].lower() in ("0x", "0o", "0b") else float(t)
    else:
        return _fmt(d)
    return _fmt(f) if math.isfinite(f) else _fmt(d)


_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}|rgba?\([0-9\s.,%]+\)|transparent")


def safe_color(v):
    v = v.strip() if isinstance(v, str) else ""
    return v if _COLOR.fullmatch(v) else ""


def safe_align(v):
    return v if isinstance(v, str) and v in ("left", "center", "right", "justify") else ""


def overlay_style(o):
    s = f"left:{_num(o, 'x', 0)}mm;top:{_num(o, 'y', 0)}mm;width:{_num(o, 'w', 50)}mm;"
    if o.get("type") == "image":
        return s + f"height:{_num(o, 'h', 40)}mm;"
    st = o.get("style") if isinstance(o.get("style"), dict) else {}
    s += f"min-height:{_num(o, 'h', 10)}mm;font-size:{_num(st, 'size', 12)}pt;"
    if safe_color(st.get("color")):
        s += f"color:{safe_color(st.get('color'))};"
    if _truthy(st.get("bold")) or (isinstance(o.get("style"), str) and o["style"]):  # JS: "글자".bold 는 함수라 참
        s += "font-weight:700;"
    if safe_align(st.get("align")):
        s += f"text-align:{safe_align(st.get('align'))};"
    if safe_color(st.get("bg")):
        s += f"background:{safe_color(st.get('bg'))};"
    return s


def overlay_html(o):
    image = o.get("type") == "image"
    inner = (f'<img src="{esc(_s(o.get("src")))}" alt="" draggable="false">' if image
             else f'<div class="ov-text-body">{_s(o.get("html"))}</div>')
    return (f'<div class="ov ov-{"image" if image else "text"}" data-ov="{esc(_jstr(o.get("id")))}" '
            f'style="{overlay_style(o)}">{inner}</div>')


# ── 번호 채우기 (render.js fillNumbers 를 html 글자 위에서) ──────────────────

_TAG = re.compile(r"<!--.*?(?:-->|\Z)|<(/?)([a-zA-Z][^\s/>]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>", re.S)
_ATTR = re.compile(r"([^\s\"'>/=]+)(?:\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+))?")


def _classes(v):
    return [t for t in re.split(r"[\t\n\f\r ]+", v or "") if t]


def _toggle(cls, token, force):
    """DOMTokenList.toggle(token, force) 뒤의 class 속성 값 (None = 속성 없음)"""
    toks = list(dict.fromkeys(_classes(cls)))
    if (token in toks) == force:
        return cls  # 바뀌지 않으면 속성 글자도 그대로
    return " ".join([t for t in toks if t != token] + ([token] if force else []))


class _Tag:
    def __init__(self, m):
        self.m, self.end_tag, self.name = m, bool(m.group(1)), (m.group(2) or "").lower()
        self.attrs = {}  # 이름 → (값, 속성 전체의 위치)
        if m.group(2) and not self.end_tag:
            for a in _ATTR.finditer(m.group(3)):
                raw = a.group(2) or ""
                if raw[:1] in "\"'":
                    raw = raw[1:-1]
                self.attrs.setdefault(a.group(1).lower(), (html.unescape(raw), (m.start(3) + a.start(), m.start(3) + a.end())))

    def start_of(self, name=None):
        return bool(self.m.group(2)) and not self.end_tag and (name is None or self.name == name)

    def has_class(self, c):
        return c in _classes(self.attrs.get("class", ("",))[0])


def _close_index(tags, i):
    """tags[i] 의 짝이 되는 닫는 태그 번호 (없으면 None)"""
    name, depth = tags[i].name, 1
    for k in range(i + 1, len(tags)):
        t = tags[k]
        if t.m.group(2) and t.name == name:
            depth += -1 if t.end_tag else 1
            if depth == 0:
                return k
    return None


def _replace_content(s, tags, i, text, edits):
    """tags[i] 요소의 내용을 text 로 (textContent = text). 다음에 볼 태그 번호를 돌려준다."""
    k = _close_index(tags, i)
    edits.append((tags[i].m.end(), tags[k].m.start() if k is not None else len(s), text))
    return k if k is not None else len(tags)


def _apply(s, edits):
    for a, b, text in sorted(edits, reverse=True):
        s = s[:a] + text + s[b:]
    return s


def fill_numbers(s, index, nums):
    """html 글자 안의 .pno 에 쪽 번호, a[data-ref] 안 첫 .pref 에 대상 쪽 번호(없으면 '?', a 에 broken)"""
    n = str(index + 1)
    tags = [_Tag(m) for m in _TAG.finditer(s)]
    edits, i = [], 0
    while i < len(tags):
        t = tags[i]
        if t.start_of() and t.name not in VOID and t.has_class("pno"):
            i = _replace_content(s, tags, i, n, edits)
        i += 1
    s = _apply(s, edits)

    tags = [_Tag(m) for m in _TAG.finditer(s)]
    edits, i = [], 0
    while i < len(tags):
        t = tags[i]
        if not (t.start_of("a") and "data-ref" in t.attrs):
            i += 1
            continue
        target = nums.get(t.attrs["data-ref"][0])
        old = t.attrs.get("class")
        new = _toggle(old[0] if old else None, "broken", not target)
        if old and new != old[0]:
            edits.append((*old[1], f'class="{esc(new)}"'))
        elif not old and new is not None:
            at = t.m.end() - (2 if t.m.group(0).endswith("/>") else 1)
            edits.append((at, at, f' class="{esc(new)}"'))
        # a 는 다음 </a> 나 다음 <a 에서 끝난다 (a 안에 a 는 못 들어감)
        i += 1
        while i < len(tags) and not (tags[i].name == "a" and tags[i].m.group(2)):
            u = tags[i]
            if u.start_of() and u.name not in VOID and u.has_class("pref"):
                i = _replace_content(s, tags, i, str(target) if target else "?", edits)
                while i < len(tags) and not (tags[i].name == "a" and tags[i].m.group(2)):
                    i += 1
                break
            i += 1
    return _apply(s, edits)


def number_map(doc):
    return {p.get("id"): i + 1 for i, p in enumerate(doc["pages"])}


def render_page_html(page, index, nums):
    """render.js createPageElement(page, index, nums).outerHTML 과 같은 DOM 이 되는 html"""
    n = index + 1
    cls = ("page " + _s(page.get("cls"))).strip()
    cls = _toggle(cls, "even", n % 2 == 0)
    cls = _toggle(cls, "odd", n % 2 == 1)
    style = _s(page.get("style"))
    head = (f'<section class="{esc(cls)}"' + (f' style="{esc(style)}"' if style else "") +
            f' data-id="{esc(_jstr(page.get("id")))}" data-kind="{esc(_s(page.get("kind")) or "content")}">')
    body = (_s(page.get("html")) + '<div class="ov-layer">' +
            "".join(overlay_html(o) for o in (page.get("overlays") or []) if isinstance(o, dict)) + "</div>")
    return head + fill_numbers(body, index, nums) + "</section>"


# ── 인쇄용 (재단 여유 3mm, 제본 여백 15mm, 두 권) ─────────────────────────────

# 인쇄용 글꼴: 윈도에 깔린 Noto Sans KR 가변 글꼴(NotoSansKR-VF.ttf)에서 fontTools 로 400·700 굵기만 뽑은 고정 글꼴.
# 크롬은 가변 글꼴을 PDF에 이름 없는 Type3 글꼴로 넣어서 인쇄소에서 문제가 된다. 글자 폭은 화면 글꼴과 같다.
PRINT_FONTS = {"NotoSansKR-Regular.ttf": 400, "NotoSansKR-Bold.ttf": 700}
FONT_DIR = BASE / "editor_assets" / "fonts"
PRINT_FONT_CSS = "".join(f'@font-face{{font-family:"Noto Sans KR";src:url({(FONT_DIR / f).as_uri()});font-weight:{w}}}\n'
                         for f, w in PRINT_FONTS.items())
# 종이 = A4(210x297) + 사방 재단 여유 3mm. 쪽(.page)은 그대로 두고 .sheet 가운데에 놓는다.
# 제본 쪽 여백 15mm: 글 폭(186mm)은 그대로 두고 3mm 만 바깥쪽으로 민다 (홀수 쪽 = 오른쪽 쪽 = 안쪽이 왼쪽)
PRINT_CSS = PRINT_FONT_CSS + """
@page{size:216mm 303mm;margin:0}
html,body{margin:0;background:#fff}
.sheet{width:216mm;height:303mm;padding:3mm;overflow:hidden;break-after:page}
.sheet>.page{margin:0;overflow:visible;break-after:auto}
.page.odd:not(.full):not(.cover){padding-left:15mm;padding-right:9mm}
.page.even:not(.full):not(.cover){padding-left:9mm;padding-right:15mm}
.page.odd:not(.full):not(.cover)>.ov-layer{transform:translateX(3mm)}
.page.even:not(.full):not(.cover)>.ov-layer{transform:translateX(-3mm)}
/* 쪽 끝에 닿는 것은 재단 여유까지 3mm 늘린다 */
.page>.tab{width:9mm}
.page.odd>.tab{right:-3mm;padding-right:3mm}
.page.even>.tab{left:-3mm;padding-left:3mm}
.page.full .pic,.page.full .full-slot{inset:-3mm}
.cover>.c-photo{inset:-3mm -3mm 110mm -3mm}
.cover>.c-gray{top:-3mm;height:115mm}
.cover>.c-url{bottom:-3mm;height:25mm;padding-bottom:3mm}
"""
# 채우지 않은 자리(브랜드 사진·한 줄 소개·스토리 안내 글, 빈 사진 칸)는 인쇄하지 않는다 — 편집기에서만 보임
PRINT_CSS += ".noimg,.s-tag.empty,.s-body.empty{display:none}.story .s-pic:has(>.noimg){display:none}"
# 재단선 표시(켰을 때만): 종이 바깥에 10mm 여백을 더 두고 모서리마다 가는 선
CROP_CSS = """
@page{size:236mm 323mm;margin:0}
.crop{position:relative;width:236mm;height:323mm;padding:10mm;break-after:page}
.crop>.sheet{break-after:auto}
.crop>i{position:absolute;width:.1mm;height:.1mm;background:#000}
"""
_CROP_LINES = "".join(f'<i style="{s}"></i>' for s in (
    *(f"left:{x}mm;{y}:0;height:9mm" for x in (13, 223) for y in ("top", "bottom")),
    *(f"top:{y}mm;{x}:0;width:9mm" for y in (13, 310) for x in ("left", "right"))))


def print_html(doc, base=BASE, other_nums=None, marks=False, rng=None):
    """인쇄용 html. other_nums: 이 문서에 없는 쪽 id → 보일 번호 (다른 권 쪽을 '2권 15' 처럼).
    rng=(시작, 끝): 그 쪽들만 그림 (번호·왼쪽/오른쪽 쪽은 전체 기준) — 큰 권을 나눠 찍을 때"""
    nums = {**(other_nums or {}), **number_map(doc)}
    css = (BASE / "editor_assets" / "catalog.css").read_text(encoding="utf-8") + PRINT_CSS + (CROP_CSS if marks else "")
    sheets = "".join((f'<div class="crop">{_CROP_LINES}' if marks else "") +
                     f'<div class="sheet">{render_page_html(p, i, nums)}</div>' + ("</div>" if marks else "")
                     for i, p in enumerate(doc["pages"]) if rng is None or rng[0] <= i < rng[1])
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            f'<base href="{esc(Path(base).resolve().as_uri())}/">'
            f'<title>{esc(_s(doc.get("title")) or "SINDO 제품 카탈로그")}</title>'
            f"<style>{css}</style></head><body class=\"final\">{sheets}</body></html>")


# 권: (파일 이름, 이름, 넣을 분류). None = 나머지 분류 전부
VOLUMES = (("인쇄용_1권_칼편.pdf", "1권", ("칼",)), ("인쇄용_2권_주방도구편.pdf", "2권", None))
COVER_DIR = "표지"
COVER_README = """인쇄용 표지 그림을 넣는 폴더입니다.

Canva에서 216 x 303 mm 크기로 만들어 JPG 나 PNG 로 내려받은 뒤, 아래 이름으로 이 폴더에 넣어 주세요.
(A4 210 x 297 mm 에 사방 3mm 씩 잘려 나갈 여유를 더한 크기입니다)

  1권_앞표지.jpg    1권_뒤표지.jpg
  2권_앞표지.jpg    2권_뒤표지.jpg

또는 Canva에서 [공유] → [다운로드] → 파일 형식 'PDF 인쇄' 로 앞표지·뒤표지 두 쪽짜리 PDF를 받아 이 폴더에 넣어도 됩니다.
  - 파일 이름은 아무거나 괜찮습니다. 첫 쪽 = 앞표지, 마지막 쪽 = 뒤표지로 씁니다.
  - PDF가 하나뿐이면 1권·2권 모두 그 표지를 씁니다. 권마다 다르게 하려면 1권_표지.pdf, 2권_표지.pdf 로 이름을 붙이세요.

편집기에서 PDF 만들기를 누르면 "인쇄" 폴더에 인쇄용_1권_표지.pdf, 인쇄용_2권_표지.pdf 도 함께 만들어집니다.
앞표지와 뒤표지가 둘 다 있어야 그 권의 표지 PDF를 만듭니다.
글자와 로고는 가장자리에서 6mm 이상 안쪽에 두세요. 바깥 3mm 는 잘려 나갑니다.
"""
_CRUMB = re.compile(r'<p class="crumb"[^>]*>([^<]*)')
_TOC_A = re.compile(r'<a class="(ch|it)[" ][^>]*?data-ref="([^"]*)"[^>]*>.*?</a>', re.S)


def chapter_of(page):
    """쪽 머리의 분류 이름 (표지·목차·그림 쪽이나 머리가 없으면 '')"""
    m = page.get("kind") not in ("cover", "toc", "image") and _CRUMB.search(page.get("html") or "")
    return html.unescape(m.group(1)).strip() if m else ""


def toc_pages(entries):
    """목차 항목 [(대분류인지, html)] → 쪽마다 단 목록. editor.js tocPages 와 같은 규칙 (한 쪽 3단, 단 높이 236mm)"""
    cols, col, h = [], [], 0
    for ch, a in entries:
        if h + (11 + 5.5 if ch else 5.5) > 236 and col:
            cols.append(col)
            col, h = [], 0
        col.append(a)
        h += 11 if ch else 5.5
    cols.append(col)
    return [cols[i:i + 3] for i in range(0, len(cols), 3)]


def _with_body(s, inner):
    """쪽 html 의 .body 내용을 inner 로"""
    tags = [_Tag(m) for m in _TAG.finditer(s)]
    i = next((k for k, t in enumerate(tags) if t.start_of("div") and t.has_class("body")), None)
    if i is None:
        return s
    edits = []
    _replace_content(s, tags, i, inner, edits)
    return _apply(s, edits)


def split_volumes(doc):
    """[(파일 이름, 권 이름, 권 문서)]. 첫 분류 쪽 앞(표지·목차 등)은 두 권 모두 앞에 넣고, 목차는 그 권 항목만으로 다시 짠다.
    분류가 없는 쪽(그림 쪽 등)은 바로 앞 쪽을 따르되, 권이 바뀌는 자리에서는 뒤 권 쪽에 붙인다(다음 장 여는 그림 쪽). 쪽 번호는 권마다 1부터."""
    pages = doc["pages"]
    first = next((i for i, p in enumerate(pages) if chapter_of(p)), len(pages))
    vol_of = lambda ch: next(k for k, v in enumerate(VOLUMES) if v[2] is None or ch in v[2])
    bodies, ch, held = [[] for _ in VOLUMES], "", []
    for p in pages[first:]:
        c = chapter_of(p)
        if not c:
            held.append(p)  # 다음 분류 쪽을 볼 때까지 미룬다
            continue
        k = vol_of(c)
        bodies[k if not ch or vol_of(ch) != k else vol_of(ch)].extend(held)
        held, ch = [], c
        bodies[k].append(p)
    if held:
        bodies[vol_of(ch)].extend(held)
    entries = [m for p in pages if p.get("kind") == "toc" for m in _TOC_A.finditer(p.get("html") or "")]
    out = []
    for (name, label, _), body in zip(VOLUMES, bodies):
        if not body:
            continue
        ids = {p.get("id") for p in body}
        mine = [(m.group(1) == "ch", m.group(0)) for m in entries if html.unescape(m.group(2)) in ids]
        front, toc = [], None
        for p in pages[:first]:
            if p.get("kind") != "toc":
                front.append(p)
            elif toc is None:  # 목차 쪽이 여럿이면 첫 자리에 새 목차를 모두 넣는다
                toc = [dict(p, id=p["id"] if k == 0 else f'{p["id"]}-{k + 1}', html=_with_body(
                    p.get("html") or "", '<div class="toc">' + "".join(
                        '<div class="tcol">' + "".join(col) + "</div>" for col in cols) + "</div>"))
                       for k, cols in enumerate(toc_pages(mine))]
                front += toc
        out.append((name, label, dict(doc, pages=front + body)))
    return out


TRIM_MM, BLEED_MM, COVER_DPI = (210, 297), 3, 400


def _fit_cover(page, pymupdf):
    """크기가 안 맞는 표지 한 쪽 → 216x303mm 그림(JPEG). A4(210x297)를 꼭 채우게 배율을 정해 (잘림 최소)
    가운데 맞추고, 모자란 재단 여유는 가장자리 색을 늘려 채운다."""
    import io
    import numpy as np
    from PIL import Image
    tw, th = TRIM_MM
    w, h = page.rect.width / 72 * 25.4, page.rect.height / 72 * 25.4
    k = max(tw / w, th / h)                                   # A4 를 빈틈없이 덮는 가장 작은 배율
    px = COVER_DPI / 25.4                                     # mm → 픽셀
    pix = page.get_pixmap(matrix=pymupdf.Matrix(k * COVER_DPI / 72, k * COVER_DPI / 72), alpha=False)
    img = np.asarray(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    out = []
    for size, mm in ((img.shape[0], th + 2 * BLEED_MM), (img.shape[1], tw + 2 * BLEED_MM)):
        need = round(mm * px)
        if size >= need:                                      # 크면 가운데만
            a = (size - need) // 2
            out.append((slice(a, a + need), (0, 0)))
        else:                                                 # 작으면 가장자리 색으로 늘림
            a = (need - size) // 2
            out.append((slice(0, size), (a, need - size - a)))
    img = np.pad(img[out[0][0], out[1][0]], (out[0][1], out[1][1], (0, 0)), mode="edge")
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "JPEG", quality=95, dpi=(COVER_DPI, COVER_DPI))
    cut = (max(0, h * k - th) / 2 / k, max(0, w * k - tw) / 2 / k)  # 원본 기준 위아래·좌우로 잘리는 mm
    return buf.getvalue(), w, h, cut


def cover_from_pdf(src, dest):
    """Canva에서 받은 표지 PDF의 첫 쪽(앞)·마지막 쪽(뒤) → 216x303mm 표지 PDF. → (쪽 수, 안내)
    크기가 이미 216x303mm 면 그대로(글자·그림 품질 그대로) 옮기고, 다르면 A4에 맞춰 자동으로 맞춘다."""
    try:
        import pymupdf
    except ImportError:
        return 0, f"표지 PDF({src.name})를 읽을 프로그램(pymupdf)이 없어 표지 PDF를 만들지 못했습니다."
    try:
        with pymupdf.open(src) as s:
            if s.page_count < 2:
                return 0, f"표지 PDF({src.name})가 한 쪽뿐입니다. 앞표지·뒤표지 두 쪽이 필요합니다."
            pages = [s[0], s[s.page_count - 1]]
            r = pages[0].rect
            w, h = r.width / 72 * 25.4, r.height / 72 * 25.4
            full = (TRIM_MM[0] + 2 * BLEED_MM, TRIM_MM[1] + 2 * BLEED_MM)
            with pymupdf.open() as d:
                if abs(w - full[0]) <= 1.5 and abs(h - full[1]) <= 1.5:
                    for pg in pages:
                        d.insert_pdf(s, from_page=pg.number, to_page=pg.number)
                    note = ""
                else:
                    pt = 72 / 25.4
                    for pg in pages:
                        jpg, w, h, cut = _fit_cover(pg, pymupdf)
                        new = d.new_page(width=full[0] * pt, height=full[1] * pt)
                        new.insert_image(new.rect, stream=jpg)
                    note = (f"표지 PDF가 {w:.0f} x {h:.0f} mm 라서 책 크기(A4 210 x 297 mm)에 맞게 자동으로 맞췄습니다. "
                            f"표지 그림의 위아래 약 {cut[0]:.1f}mm, 좌우 약 {cut[1]:.1f}mm 가 잘리고, 바깥 3mm 재단 여유는 "
                            "가장자리 색을 늘려 채웠습니다. 인쇄용 표지 PDF를 열어 확인해 주세요.")
                d.save(dest)
    except Exception as e:
        return 0, f"표지 PDF({src.name})를 읽지 못했습니다: {e}"
    return 2, note


def cover_html(files):
    """표지 그림들을 한 장씩 216x303mm 종이 가득"""
    imgs = "".join(f'<div class="cv"><img src="{esc(Path(f).resolve().as_uri())}" alt=""></div>' for f in files)
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>@page{size:216mm 303mm;margin:0}'
            'html,body{margin:0}.cv{width:216mm;height:303mm;overflow:hidden;break-after:page}'
            '.cv img{width:100%;height:100%;object-fit:cover;display:block}</style></head><body>' + imgs + "</body></html>")


# ── 파일 ─────────────────────────────────────────────────────────────

_SRC = re.compile(r"(?<![\w-])src\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.I)


def _local_path(src):
    """src 값 → 작업 폴더 기준 상대경로 (밖 주소·data: 면 None)"""
    p = unquote(html.unescape(src).split("?")[0].split("#")[0]).strip()
    if not p or re.match(r"^([a-zA-Z][\w+.-]*:|//|/|\\)", p):
        return None
    return p


def asset_paths(doc):
    out = set()
    for page in doc["pages"]:
        srcs = [a or b for a, b in _SRC.findall(page.get("html") or "")]
        for o in page.get("overlays") or []:
            if o.get("type") == "image":
                srcs.append(_s(o.get("src")))
            else:
                srcs += [a or b for a, b in _SRC.findall(_s(o.get("html")))]
        out.update(p for p in map(_local_path, srcs) if p)
    return out


def load_doc(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def validate_doc(doc):
    """문제 목록 (빈 목록이면 괜찮음)"""
    if not isinstance(doc, dict) or not isinstance(doc.get("pages"), list):
        return ["문서에 pages 목록이 없습니다."]
    if not doc["pages"]:
        return ["쪽이 하나도 없습니다."]
    problems, seen = [], set()
    for i, p in enumerate(doc["pages"], 1):
        if not isinstance(p, dict):
            problems.append(f"{i}쪽: 쪽 정보가 잘못되었습니다.")
            continue
        pid = p.get("id")
        if not isinstance(pid, str) or not pid:
            problems.append(f"{i}쪽: id 가 없습니다.")
        elif pid in seen:
            problems.append(f"{i}쪽: id '{pid}' 가 겹칩니다.")
        seen.add(pid)
        if not isinstance(p.get("html"), str):
            problems.append(f"{i}쪽: html 이 글자가 아닙니다.")
        if not isinstance(p.get("overlays"), list) or not all(isinstance(o, dict) for o in p["overlays"]):
            problems.append(f"{i}쪽: overlays 가 목록이 아닙니다.")
    return problems


def save_doc(path, doc, backups_dir):
    """검사 → (5분에 한 번) 백업 → 임시 파일에 쓰고 바꿔치기"""
    problems = validate_doc(doc)
    if problems:
        raise ValueError(" / ".join(problems[:5]) + (f" 외 {len(problems) - 5}개" if len(problems) > 5 else ""))
    path, backups_dir = Path(path), Path(backups_dir)
    if path.exists():
        backups_dir.mkdir(parents=True, exist_ok=True)
        olds = sorted(backups_dir.glob("catalog-*.json"))
        if not olds or time.time() - olds[-1].stat().st_mtime > 300:
            shutil.copyfile(path, backups_dir / f"catalog-{datetime.now():%Y%m%d-%H%M%S}.json")
            olds = sorted(backups_dir.glob("catalog-*.json"))
        for old in olds[:-40]:
            old.unlink(missing_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def catalog_js(doc):
    return "window.CATALOG_DATA = " + json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + ";\n"


HOWTO = """신도 디지털 카탈로그 — 홈페이지에 올리는 법

■ 쉬운 방법: 편집기의 [홈페이지에 올리기] 버튼
1. 처음 한 번만: 카탈로그 폴더의 "홈페이지_올리기_설정.txt" 를 메모장으로 열어 FTP 비밀번호를 적고 저장합니다.
   (파일이 없으면 버튼을 처음 누를 때 만들어지고 메모장으로 열립니다)
2. 편집기에서 [홈페이지에 올리기] 를 누르면 이 폴더(site)를 새로 만든 뒤, 바뀐 파일만 홈페이지에 올립니다.
3. 다 올리면 편집기가 카탈로그 주소를 알려 줍니다. 예) https://sindoltd.com/web/upload/catalog/index.html
4. 홈페이지 메뉴나 버튼에서 그 주소로 연결합니다.

■ 손으로 올릴 때 (파일질라 같은 FTP 프로그램)
1. 이 폴더(site) 안의 파일과 폴더를 "전부" 그대로 홈페이지 서버의 한 폴더에 올립니다.
   예) sindoltd.ftp.cafe24.com 에 접속 → /web/upload/catalog 폴더를 만들고 그 안에 모두 올리기
2. 카탈로그를 고친 뒤에는 편집기에서 "홈페이지용 내보내기"를 다시 누르고, 같은 폴더에 전부 덮어써서 올립니다.

※ index.html 만 올리면 안 됩니다. catalog.js, editor_assets, images 등 폴더 구조를 그대로 유지해야 합니다.
※ 이 폴더는 내보내기를 할 때마다 지우고 새로 만듭니다. 여기에 다른 파일을 넣어 두지 마세요.
"""


def export_site(doc, base, out_dir):
    """홈페이지용 폴더 만들기 → {"path", "files", "missing"}"""
    base, out_dir = Path(base).resolve(), Path(out_dir).resolve()
    if out_dir == base or base.is_relative_to(out_dir):
        raise ValueError("내보낼 폴더가 작업 폴더와 겹칩니다.")
    if out_dir.exists():
        if not (out_dir / SITE_MARK).exists():
            raise ValueError(f"{out_dir} 폴더가 이미 있는데 내보내기로 만든 폴더가 아닙니다. 이름을 바꾸거나 옮긴 뒤 다시 해 주세요.")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    files, missing = 0, []

    def put(rel, data=None):
        nonlocal files
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if data is not None:
            dest.write_text(data, encoding="utf-8")
        else:
            src = (base / rel).resolve()
            if not src.is_relative_to(base) or not src.is_file():
                missing.append(rel)
                return
            shutil.copyfile(src, dest)
        files += 1

    if (base / "viewer.html").is_file():
        shutil.copyfile(base / "viewer.html", out_dir / "index.html")
        files += 1
    else:
        missing.append("viewer.html")
    put("catalog.js", catalog_js(doc))
    for a in SITE_ASSETS:
        put("editor_assets/" + a)
    for rel in sorted(asset_paths(doc)):
        if ".." in Path(rel).parts or Path(rel).suffix.lower() not in SITE_IMAGE_EXTS:  # 엑셀·코드가 홈페이지로 새지 않게
            missing.append(rel)
        else:
            put(rel)
    put(SITE_MARK, "이 폴더는 신도 카탈로그 편집기의 '홈페이지용 내보내기'가 만든 폴더입니다. 내보낼 때마다 지우고 새로 만듭니다.\n")
    put("올리는 법.txt", HOWTO)
    return {"path": str(out_dir), "files": files, "missing": missing}


def find_browser():
    env = os.environ.get
    for p in (Path(env("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
              Path(env("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
              Path(env("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
              Path(env("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
              Path(env("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe"):
        if p.is_file():
            return str(p)
    return None


def shrink_pdf(path):
    """크롬이 투명 사진을 압축 없는 PNG로 넣어 PDF가 너무 커진다 → 그림만 300dpi 상한으로 다시 압축 (글자·선은 그대로)"""
    try:
        import pymupdf
    except ImportError:
        return
    path = Path(path)
    tmp = path.with_name(path.stem + ".tmp.pdf")
    try:
        with pymupdf.open(path) as d:
            d.rewrite_images(dpi_threshold=320, dpi_target=300, quality=88, lossy=True, lossless=True)
            d.save(tmp, garbage=3, deflate=True)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)   # 실패하면 큰 그대로 둔다 (인쇄는 됨)


CHUNK = 40      # 한 번에 찍는 쪽 수


def join_parts(out_dir, jobs, counts):
    """'이름.pdf.part0040.pdf' 조각들을 순서대로 합쳐 '이름.pdf' 로. 권(합친 것)이 먼저, 표지가 뒤. → (jobs, counts)"""
    import pymupdf
    parts, others = {}, []
    for (name, text), n in zip(jobs, counts):
        m = re.fullmatch(r"(.+[.]pdf)[.]part[0-9]{4}[.]pdf", name)
        if m:
            parts.setdefault(m.group(1), []).append(out_dir / name)
        else:
            others.append(((name, text), n))
    out_jobs, out_counts = [], []
    for name, files in parts.items():                # 권 순서 그대로
        tmp = out_dir / (name + ".tmp")
        with pymupdf.open() as d:
            for f in files:
                with pymupdf.open(f) as one:
                    d.insert_pdf(one)
            d.save(tmp, garbage=3, deflate=True)
            pages = d.page_count
        os.replace(tmp, out_dir / name)
        for f in files:
            f.unlink(missing_ok=True)
        out_jobs.append((name, ""))
        out_counts.append(pages)
    for job, n in others:
        out_jobs.append(job)
        out_counts.append(n)
    return out_jobs, out_counts


def chrome_pdfs(jobs):
    """[(html 글자, pdf 경로)] 를 크롬(없으면 엣지) 여러 개로 한꺼번에 PDF로. 쪽 수 목록을 돌려준다."""
    exe = find_browser()
    if not exe:
        raise RuntimeError("크롬이나 엣지를 찾지 못해 PDF를 만들 수 없습니다.")
    started = time.time()
    # 전용 프로필 폴더를 줘야 이미 떠 있는 크롬에 붙지 않는다. 출력은 버린다(파이프를 잡으면 시간 초과 때 멈출 수 있음)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        running = []

        def busy(p, out):
            """아직 일하는 중인지. PDF를 다 써 놓고 안 꺼지는 크롬(가끔 있음)은 끈다"""
            if p.poll() is not None:
                return False
            f = Path(out)
            if f.is_file() and f.stat().st_mtime >= started and time.time() - f.stat().st_mtime > 5:
                with open(f, "rb") as fh:
                    fh.seek(max(0, f.stat().st_size - 64))
                    if b"%%EOF" in fh.read():
                        p.kill()                      # 이 함수가 띄운 크롬만
                        p.wait()
                        return False
            if time.time() - started > 900:           # 15분 넘으면 포기
                p.kill()
                p.wait()
                return False
            return True
        for k, (text, out) in enumerate(jobs):
            while len(running) >= 3:                  # 크롬은 한꺼번에 3개까지만 (많이 띄우면 사진 많은 권에서 멈춤)
                running = [(p, o) for p, o in running if busy(p, o)]
                time.sleep(0.3)
            src = Path(tmp) / f"print{k}.html"
            src.write_text(text, encoding="utf-8")
            running.append((subprocess.Popen(
                [exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={Path(tmp) / f'p{k}'}",
                 f"--print-to-pdf={Path(out).resolve()}", src.as_uri()],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)), out))
        while running:
            running = [(p, o) for p, o in running if busy(p, o)]
            time.sleep(0.3)
    counts = []
    for _, out in jobs:
        out = Path(out)
        if not out.is_file() or out.stat().st_mtime < started:
            raise RuntimeError(f"PDF를 만들지 못했습니다. {out.name} 파일이 다른 프로그램에 열려 있으면 닫고 다시 해 주세요.")
        counts.append(len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", out.read_bytes())))
    return counts


def make_print_pdfs(doc, base, out_dir, marks=False, multiple=2):
    """인쇄소에 보낼 PDF: 권마다 하나, 표지 그림이 있으면 권마다 표지 PDF도. 쪽 수는 multiple 의 배수로 빈 쪽을 채운다.
    → {"path", "pages", "files": [{"name", "pages"}], "notes"}"""
    base, out_dir = Path(base).resolve(), Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    covers = base / COVER_DIR
    covers.mkdir(exist_ok=True)
    if not (covers / "읽어보세요.txt").exists():
        (covers / "읽어보세요.txt").write_text(COVER_README, encoding="utf-8")
    notes = []
    if not all((FONT_DIR / f).is_file() for f in PRINT_FONTS):
        notes.append("인쇄용 글꼴 파일(editor_assets/fonts)이 없어 인쇄소에서 글꼴 문제가 생길 수 있습니다.")
    vols = split_volumes(doc)
    pdfs0 = [f for f in covers.glob("*.pdf") if f.is_file()]
    for name, label, sub in vols:
        # 표지 PDF를 따로 만드는 권은 책 안의 표지 쪽(첫 쪽 표지·뒤표지 그림 쪽)을 뺀다 — 인쇄소에서 겹치지 않게
        has_cover = (all(any((covers / f"{label}_{side}.{e}").is_file() for e in ("jpg", "jpeg", "png")) for side in ("앞표지", "뒤표지"))
                     or (covers / f"{label}_표지.pdf").is_file() or len(pdfs0) == 1)
        if has_cover:
            sub["pages"] = [q for q in sub["pages"]
                            if q.get("kind") != "cover" and "backcover" not in (q.get("cls") or "").split()]
            while sub["pages"] and sub["pages"][-1].get("kind") == "blank" and not sub["pages"][-1].get("overlays"):
                sub["pages"].pop()          # 뒤표지 앞 빈 쪽은 온라인 책 맞춤용 — 인쇄에선 아래에서 다시 짝수로 맞춘다
        pad = -len(sub["pages"]) % multiple
        if pad:
            sub["pages"] = sub["pages"] + [{"id": f"pad-{k}", "kind": "blank", "cls": "", "style": "", "html": "",
                                            "overlays": []} for k in range(pad)]
            notes.append(f"{label}: 쪽 수를 {'짝수' if multiple == 2 else f'{multiple}의 배수'}로 맞추려고 끝에 빈 쪽 {pad}개를 넣었습니다.")
    nums = [number_map(sub) for _, _, sub in vols]
    jobs = []
    for k, (name, label, sub) in enumerate(vols):
        other = {pid: f"{vols[j][1]} {n}" for j in range(len(vols)) if j != k for pid, n in nums[j].items()}
        n_pages = len(sub["pages"])
        for lo in range(0, n_pages, CHUNK):           # 40쪽씩 따로 찍고 나중에 합친다
            jobs.append((f"{name}.part{lo:04d}.pdf", print_html(sub, base, other, marks, (lo, min(n_pages, lo + CHUNK)))))
    missing, pdf_covers = [], []
    pdfs = sorted(f for f in covers.glob("*.pdf") if f.is_file())
    for _, label, _ in vols:
        found = {}
        for side in ("앞표지", "뒤표지"):
            f = next((covers / f"{label}_{side}.{e}" for e in ("jpg", "jpeg", "png")
                      if (covers / f"{label}_{side}.{e}").is_file()), None)
            if f:
                found[side] = f
            else:
                missing.append(f"{label}_{side}")
        if len(found) == 2:
            jobs.append((f"인쇄용_{label}_표지.pdf", cover_html([found["앞표지"], found["뒤표지"]])))
            continue
        # 그림이 없으면 Canva에서 받은 PDF (권 이름이 붙은 것 → 하나뿐인 PDF 순서)
        pdf = covers / f"{label}_표지.pdf"
        pdf = pdf if pdf.is_file() else (pdfs[0] if len(pdfs) == 1 else None)
        if pdf:
            pdf_covers.append((f"인쇄용_{label}_표지.pdf", pdf))
            missing = [m for m in missing if not m.startswith(label + "_")]
    if missing:  # 둘 다 있어야 그 권 표지 PDF를 만든다
        notes.append("표지 그림이 아직 없어 표지 PDF는 만들지 않았습니다. (표지 폴더의 읽어보세요.txt 참고)"
                     if len(missing) == 2 * len(vols) else
                     f"표지 폴더에 {', '.join(missing)} 그림이 없어 그 권의 표지 PDF는 만들지 않았습니다.")
    for name in [v[0] for v in VOLUMES] + [f"인쇄용_{v[1]}_표지.pdf" for v in VOLUMES]:  # 예전 실행에서 남은 파일이 새 파일과 섞이지 않게
        if name not in {n for n, _ in jobs} | {n for n, _ in pdf_covers}:
            (out_dir / name).unlink(missing_ok=True)
    counts = chrome_pdfs([(text, out_dir / name) for name, text in jobs])
    jobs, counts = join_parts(out_dir, jobs, counts)
    for name, _ in jobs:
        shrink_pdf(out_dir / name)
    files = [{"name": name, "pages": n} for (name, _), n in zip(jobs, counts)]
    for name, src in pdf_covers:
        n, note = cover_from_pdf(src, out_dir / name)
        if n:
            files.append({"name": name, "pages": n})
            counts.append(n)
        if note:
            notes.append(note)
    return {"path": str(out_dir), "pages": sum(counts), "files": files, "notes": list(dict.fromkeys(notes))}


if __name__ == "__main__":  # 짧은 자체 시험: python catalog_doc.py  (render.js 와의 전체 비교는 크롬으로 따로)
    _p = {"id": "a", "kind": "content", "cls": "", "style": "--c:#123", "overlays": [
        {"id": "ov-1", "type": "text", "x": 1, "y": "2", "w": 3.5, "html": "글", "style": {"color": "red", "bold": 1, "align": "center"}}],
        "html": '<b class="pno"></b><a data-ref="a">x<b class="pref"></b></a><a class="it" data-ref="z"><b class="pref">9</b></a>'}
    _h = render_page_html(_p, 1, {"a": 2})
    assert _h == ('<section class="page even" style="--c:#123" data-id="a" data-kind="content"><b class="pno">2</b>'
                  '<a data-ref="a">x<b class="pref">2</b></a><a class="it broken" data-ref="z"><b class="pref">?</b></a>'
                  '<div class="ov-layer"><div class="ov ov-text" data-ov="ov-1" style="left:1mm;top:2mm;width:3.5mm;'
                  'min-height:10mm;font-size:12pt;font-weight:700;text-align:center;"><div class="ov-text-body">글</div></div>'
                  '</div></section>'), _h
    assert validate_doc({"pages": [{"id": "a", "html": "", "overlays": []}, {"id": "a", "html": 1, "overlays": {}}]}) == [
        "2쪽: id 'a' 가 겹칩니다.", "2쪽: html 이 글자가 아닙니다.", "2쪽: overlays 가 목록이 아닙니다."]
    print("ok")
