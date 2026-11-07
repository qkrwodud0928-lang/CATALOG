"""제품 카드·기타 나이프 줄 ↔ 홈페이지(Cafe24) 상품 번호 잇기, 빈 사진 칸에 홈페이지 대표 사진 넣기

    python -X utf8 link_photos.py --doc catalog.json --links --photos            # 둘 다
    python -X utf8 link_photos.py --doc catalog.json --links --dry-run           # 저장 없이 몇 개 찾는지만
    python -X utf8 link_photos.py --doc catalog.json --photos --limit 100        # 100개만 하고 멈춤 (다시 돌리면 이어서)
    python -X utf8 link_photos.py --doc catalog.json --relink                    # 이미 있는 번호도 찾은 번호로 바꿈

상품 번호 찾는 순서 (엑셀 '마스터'의 행마다)
 1. inbox 폴더의 Cafe24 상품 내보내기 파일(xlsx·csv: 상품번호, 상품명, 자체 상품코드, 이미지등록(상세))
    자체 상품코드 ↔ 엑셀 자체상품코드(원본)·모델코드(추출), 안 되면 상품명으로 맞춘다. 사진은 이미지등록(상세)
 2. 그래도 없으면 홈페이지 사이트맵으로 맞춘 표(sitemap_map.json), 사진은 상세 화면의 대표 사진(og:image)

카드는 사진 칸 이름(images/G0585, images/G0585-1)이 엑셀 그룹ID. -1 처럼 나뉜 카드는 카드에 적힌 품번의 행만 본다.
사진이 이미 들어 있는 칸은 절대 건드리지 않는다. 사진은 --doc 파일 옆 images 폴더에 저장한다.
카드에 이미 있는 상품 번호(편집기에서 직접 넣은 것일 수 있음)는 기본으로 그대로 두고, 다르면 확인 표에 적는다.
"""
import argparse
import csv
import html
import io
import json
import re
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote

import openpyxl
from PIL import Image

import catalog_doc as CD

BASE = Path(__file__).resolve().parent
XLSX = BASE / "신도_카탈로그_데이터.xlsx"
INBOX = BASE / "inbox"
# ponytail: 사이트맵 표·상세 화면 저장 폴더가 작업용 임시 폴더에 있다. 오래 쓸 거면 작업 폴더로 옮기고 --web 기본값을 바꿀 것
WEB = Path(r"C:\Users\박재영\AppData\Local\Temp\claude\C--Users-----CATALOG\e8ce6fd4-1919-4e69-90e1-ff72d33cef67\scratchpad\web")
SITE = "https://sindoltd.com"
BIG = SITE + "/web/product/big/"
UA = {"User-Agent": "Mozilla/5.0"}
MAX_SIDE, QUALITY = 1200, 88
SLOT_OK = re.compile(r"images/[0-9A-Za-z가-힣_\-]{1,80}")  # 이 꼴의 사진 칸만 파일로 저장한다
SELLING = "판매중·진열"


def norm(t):
    return re.sub(r"[^0-9a-z가-힣]", "", str(t or "").lower())


def text(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h or ""))).strip()


def codes_of(*vals, short=2):
    """'SBK-95, 105 / X1' → {'sbk95', '105', 'x1'}"""
    return {c for v in vals for c in (norm(x) for x in re.split(r"[,/]", str(v or ""))) if len(c) >= short}


# ── 엑셀 · 상품 번호 ─────────────────────────────────────────────────

def load_rows(xlsx=XLSX):
    ws = openpyxl.load_workbook(xlsx, read_only=True)["마스터"]
    it = ws.iter_rows(values_only=True)
    head = list(next(it))
    rows = [dict(zip(head, r)) for r in it if r and r[0] is not None]
    for r in rows:
        r["_codes"] = codes_of(r["모델코드(추출)"], r["자체상품코드(원본)"])
    return rows


def find_export(inbox=INBOX):
    """inbox 의 Cafe24 상품 내보내기 파일 (상품번호·자체 상품코드 칸이 있는 것 중 가장 새것)"""
    files = sorted((p for p in Path(inbox).glob("*") if p.suffix.lower() in (".xlsx", ".csv") and not p.name.startswith("~$")),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files:
        try:
            table = read_table(p)
        except Exception:
            continue
        if table and {"상품번호", "자체상품코드"} <= set(table[0]):
            return p, table
    return None, None


def read_table(p):
    """xlsx·csv 첫 시트 → [머리글(띄어쓰기 뺀 것), {머리글: 값}, …]"""
    if p.suffix.lower() == ".xlsx":
        raw = list(openpyxl.load_workbook(p, read_only=True).worksheets[0].iter_rows(values_only=True))
    else:
        data = p.read_bytes()
        for enc in ("utf-8-sig", "cp949"):  # Cafe24 csv 는 utf-8 또는 euc-kr
            try:
                raw = list(csv.reader(io.StringIO(data.decode(enc))))
                break
            except UnicodeDecodeError:
                continue
        else:
            return None
    if not raw:
        return None
    head = [re.sub(r"\s+", "", str(h or "")) for h in raw[0]]
    return [head] + [dict(zip(head, r)) for r in raw[1:] if r and any(v not in (None, "") for v in r)]


def photo_url(v):
    """이미지등록(상세) 값 → 주소. 파일 이름·big/ 아래 경로·/web/… 경로·전체 주소 모두 받는다"""
    v = str(v or "").strip().replace("\\", "/")
    if not v:
        return None
    if v.startswith("//"):
        v = "https:" + v
    elif v.startswith("/"):
        v = SITE + v
    elif not re.match(r"https?://", v, re.I):
        if v.lower().startswith("web/product/"):
            v = SITE + "/" + v
        else:
            v = BIG + v.split("big/", 1)[-1]
    return quote(v, safe=":/?=&%#~+,;@")


def product_numbers(rows, export=None, web=WEB):
    """엑셀 No → 상품 번호, 상품 번호 → 사진 주소(내보내기 파일에 있을 때)"""
    by_code, by_name, photo = {}, {}, {}
    for e in (export or [])[1:]:
        no = str(e.get("상품번호") or "").strip()
        if not no.isdigit():
            continue
        no = int(no)
        by_code.setdefault(norm(e.get("자체상품코드")), no)
        by_name.setdefault(norm(e.get("상품명")), no)
        url = photo_url(e.get("이미지등록(상세)")) or photo_url(e.get("이미지등록(목록)"))
        if url:
            photo.setdefault(no, url)
    by_code.pop("", None)
    by_name.pop("", None)
    rowmap = {}
    p = Path(web) / "sitemap_map.json"
    if p.is_file():
        rowmap = {int(k): int(v) for k, v in json.loads(p.read_text(encoding="utf-8"))["rowmap"].items() if v}
    out = {}
    for r in rows:
        whole = [norm(r["자체상품코드(원본)"]), norm(r["모델코드(추출)"])]
        no = (next((by_code[c] for c in whole if c in by_code), None)
              or next((by_code[c] for c in r["_codes"] if len(c) >= 4 and c in by_code), None)
              or by_name.get(norm(r["상품명(원본)"]))
              or rowmap.get(r["No"]))
        if no:
            out[r["No"]] = no
    return out, photo


# ── 쪽 html 안의 카드 · 줄 ─────────────────────────────────────────────

def inner(s, tags, i):
    k = CD._close_index(tags, i)
    return s[tags[i].m.end():tags[k].m.start() if k is not None else len(s)], k


def card_codes(h):
    vals = re.findall(r'<span[^>]*class="code[^"]*"[^>]*>(.*?)</span>', h, re.S)
    vals += re.findall(r'<p[^>]*class="model"[^>]*>.*?<b[^>]*>(.*?)</b>', h, re.S)
    return codes_of(*(text(v) for v in vals))


def page_items(s):
    """쪽 html → 카드(article.w/.g)와 기타 나이프 줄(div.mr) 목록 (html 안 위치 포함)"""
    tags = [CD._Tag(m) for m in CD._TAG.finditer(s)]
    items, brand, group = [], "", 0
    for i, t in enumerate(tags):
        if t.start_of("article") and (t.has_class("w") or t.has_class("g")):
            h, k = inner(s, tags, i)
            j = next((j for j in range(i + 1, k or len(tags)) if tags[j].start_of() and "data-slot" in tags[j].attrs), None)
            slot = tags[j].attrs["data-slot"][0] if j is not None else ""
            sh, sk = inner(s, tags, j) if j is not None else ("", None)
            h4 = re.search(r"<h4[^>]*>(.*?)</h4>", h, re.S)
            h4 = h4.group(1) if h4 else ""
            orig = re.search(r"<small>((?:(?!<small>).)*)</small>\s*$", h4, re.S)  # 끝의 회색 원본 상품명
            items.append(dict(kind="card", tag=t, html=h, slot=slot, codes=card_codes(h), slot_html=sh,
                              slot_span=(tags[j].m.end(), tags[sk].m.start()) if sk is not None else None,
                              name=text(h4[:orig.start()] if orig else h4), orig=text(orig.group(1)) if orig else ""))
        elif t.start_of("div") and t.has_class("mb"):
            brand = text(re.sub(r"<small>.*?</small>", "", inner(s, tags, i)[0], flags=re.S))
        elif t.start_of("div") and t.has_class("mr"):
            h = inner(s, tags, i)[0]
            cells = re.findall(r"<span[^>]*>(.*?)</span>", re.sub(r"<small>.*?</small>", "", h, flags=re.S), re.S)
            name = text(cells[0]) if cells else ""
            if name:
                group += 1  # 이름이 적힌 줄부터 한 제품 (이름 빈 줄은 같은 제품의 다른 사이즈)
            items.append(dict(kind="row", tag=t, html=h, brand=brand, group=group, codes=card_codes(h), name=name,
                              type=t.attrs.get("data-type", ("",))[0], size=re.sub(r"\D", "", text(cells[2])) if len(cells) > 2 else "",
                              code=text((re.findall(r'class="code[^"]*">(.*?)</span>', h, re.S) or [""])[0])))
    return items


def card_product(it, groups, nos):
    """카드 → (상품 번호 or None, 그룹ID)"""
    gid = it["slot"][len("images/"):] if it["slot"].startswith("images/") else ""
    split = False
    if gid not in groups:
        m = re.fullmatch(r"(.+)-\d+", gid)
        if not (m and m.group(1) in groups):
            return None, gid
        gid, split = m.group(1), True
    t = norm(text(it["html"]))
    hit = lambda r: any(c in it["codes"] or (len(c) >= 4 and c in t) for c in r["_codes"])
    rs = groups[gid]
    cand = [r for r in rs if hit(r)]
    if not split:  # 품번이 안 맞으면 그룹의 판매중 행부터
        cand += sorted((r for r in rs if r not in cand), key=lambda r: r["상태"] != SELLING)
    return next((nos[r["No"]] for r in cand if r["No"] in nos), None), gid


def code_index(rows):
    """품번 → 행들, 브랜드 → 행들, 그룹ID → 행들 (판매중 먼저)"""
    by_code, by_brand, by_group = {}, {}, {}
    for r in sorted(rows, key=lambda r: (r["상태"] != SELLING, r["No"])):
        for c in r["_codes"]:
            by_code.setdefault(c, []).append(r)
        by_brand.setdefault(r["브랜드"], []).append(r)
        by_group.setdefault(r["그룹ID"], []).append(r)
    return by_code, by_brand, by_group


NO_BRAND = {"브랜드 미상": "미분류(브랜드 없음)"}  # 쪽에 적힌 브랜드 → 엑셀 브랜드


def row_products(items, index, nos):
    """기타 나이프 줄마다 상품 번호
     1. 줄의 품번이 모두 적힌 엑셀 행(제 행)이 있으면 그 행의 그룹 안에서만 찾는다 (그룹에 번호가 없으면 연결 안 함)
     2. 제 행이 없으면 품번이 맞는 같은 브랜드 행 (3000 처럼 짧은 숫자 품번은 다른 제품과 겹쳐서 안 씀)
     3. 품번이 없으면 브랜드·종류·사이즈가 한 그룹에만 맞을 때 그 그룹
     4. 그래도 없으면 같은 제품(이름 줄부터)의 첫 번호 (제 행이 있는 줄은 빼고)"""
    by_code, by_brand, by_group = index
    out, own = {}, set()
    for it in items:
        if it["kind"] != "row":
            continue
        codes, brand = it["codes"], NO_BRAND.get(it["brand"], it["brand"])
        home = [r for c in codes for r in by_code.get(c, []) if codes <= r["_codes"]]
        home = [r for r in home if r["브랜드"] == brand] or home  # 같은 품번이 두 브랜드에 있으면 이 브랜드 것
        if home:
            own.add(id(it))
            cand = home + [r for g in dict.fromkeys(r["그룹ID"] for r in home) for r in by_group[g]]
        else:
            cand = [r for c in codes if not (c.isdigit() and len(c) < 5) for r in by_code.get(c, [])]
            if brand in by_brand:
                cand = [r for r in cand if r["브랜드"] == brand]
        if not codes and it["brand"] in by_brand:
            same = [r for r in by_brand[it["brand"]] if r["세부유형"] == it["type"]
                    and (not it["size"] or it["size"] in str(r["사이즈(mm)"] or "").split("/"))]
            if len({r["그룹ID"] for r in same}) == 1:
                cand = same
        cand = [r for r in cand if r["No"] in nos]
        out[id(it)] = nos[cand[0]["No"]] if cand else None
    first = {}
    for it in items:
        if it["kind"] == "row" and out[id(it)]:
            first.setdefault(it["group"], out[id(it)])
    for it in items:
        if it["kind"] == "row" and not out[id(it)] and it["group"] and id(it) not in own:
            out[id(it)] = first.get(it["group"])
    return out


def set_attr(t, name, value):
    """시작 태그 t 에 name="value" 를 넣거나 바꾸는 편집 (catalog_doc._apply 용)"""
    if name in t.attrs:
        return (*t.attrs[name][1], f'{name}="{value}"')
    at = t.m.end() - (2 if t.m.group(0).endswith("/>") else 1)
    return (at, at, f' {name}="{value}"')


def empty_slot(it):
    return it["kind"] == "card" and it["slot_span"] and "noimg" in it["slot_html"] and "<img" not in it["slot_html"].lower()


# ── 홈페이지 ─────────────────────────────────────────────────────────

def get(url, binary=False):
    err = None
    for k in range(3):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
            time.sleep(0.3)  # 홈페이지에 부담 안 주게
            return data if binary else data.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                raise  # 없는 상품(404) 등은 다시 해도 같다
            err = e
        except Exception as e:
            err = e
        time.sleep(2 * (k + 1))
    raise err


def og_image(no, web=WEB):
    """상세 화면의 대표 사진 주소 (상세 화면은 web/html 에 저장해 두고 다시 쓴다)"""
    f = Path(web) / "html" / f"{no}.html"
    h = f.read_text(encoding="utf-8", errors="replace") if f.is_file() else ""
    if "og:image" not in h:
        h = get(f"{SITE}/product/detail.html?product_no={no}")
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(h, encoding="utf-8")
        tmp.replace(f)
    m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', h)
    url = html.unescape(m.group(1)) if m else ""
    if url.startswith("//"):
        url = "https:" + url
    return url if url.startswith(SITE + "/web/product/") else None  # 기본 공유 그림(로고 등)은 안 쓴다


def save_jpeg(data, dest):
    """받은 그림이 진짜 사진인지 보고 → RGB JPEG(긴 변 1200px 이하, 품질 88)로 저장"""
    Image.open(io.BytesIO(data)).verify()
    im = Image.open(io.BytesIO(data))
    im.load()
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")  # 투명한 곳은 흰 바탕
        bg.paste(im, mask=im.getchannel("A"))
        im = bg
    else:
        im = im.convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    im.save(tmp, "JPEG", quality=QUALITY)
    tmp.replace(dest)


def fetch_photo(no, hint, dest, web=WEB):
    """dest 에 사진 저장 (Cafe24 내보내기의 사진 주소, 없으면 상세 화면의 대표 사진). 성공하면 True"""
    url = hint or og_image(no, web)
    if not url:
        return False
    save_jpeg(get(url, binary=True), dest)
    return True


# ── 실행 ─────────────────────────────────────────────────────────────

def editor_running(port=8800):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def run(doc_path, links, photos, limit=0, dry=False, rows=None, export=None, web=WEB, fetch=fetch_photo, log=print,
        relink=False):
    doc_path = Path(doc_path).resolve()
    doc = CD.load_doc(doc_path)
    folder = doc_path.parent
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    # 문서 어딘가에 쓰이고 있는 사진 파일 (이런 파일은 옮기지 않는다)
    used = {unquote(m) for m in re.findall(r'images/[^"?\\\s]+', json.dumps(doc["pages"], ensure_ascii=False))}
    rows = load_rows() if rows is None else rows
    if export is None:
        ex_path, export = find_export()
        log(f"Cafe24 내보내기 파일: {ex_path.name}" if ex_path else "Cafe24 내보내기 파일 없음 → 홈페이지 사이트맵 자료로 찾습니다")
    nos, hints = product_numbers(rows, export, web)
    groups = {}
    for r in sorted(rows, key=lambda r: r["No"]):
        groups.setdefault(r["그룹ID"], []).append(r)

    index = code_index(rows)
    st = dict(card=0, row=0, card_hit=0, row_hit=0, linked=0, had=0, added=0, failed=0, todo_left=0)
    report, done, stop = [], 0, False
    for pi, page in enumerate(doc["pages"]):
        s = page.get("html") or ""
        if 'class="w' not in s and 'class="g' not in s and 'class="mr' not in s:
            continue
        items = page_items(s)
        rowp = row_products(items, index, nos)
        title = text((re.search(r'<p class="ttl"><b>(.*?)</b>', s, re.S) or [None, ""])[1])
        edits = []
        for it in items:
            if it["kind"] == "card":
                no, gid = card_product(it, groups, nos)
            else:
                no, gid = rowp[id(it)], it["code"]
            card = it["kind"] == "card"
            st[it["kind"]] += 1
            st[it["kind"] + "_hit"] += bool(no)
            st["had"] += card and "<img" in it["slot_html"].lower()
            cur = it["tag"].attrs.get("data-prod", ("",))[0].strip()  # 편집기에서 직접 넣은 번호일 수 있다
            differ = links and no and cur and cur != str(no)
            want_link = links and no and (not cur or (relink and differ))
            pno = int(cur) if cur.isdigit() and not want_link else no  # 사진은 카드에 걸린 번호의 것으로
            want_photo = photos and pno and empty_slot(it) and SLOT_OK.fullmatch(it["slot"])
            if want_link or want_photo:
                if stop or (limit and done >= limit):
                    st["todo_left"] += 1
                    want_link = want_photo = False
                else:
                    done += 1
            if want_link:
                edits.append(set_attr(it["tag"], "data-prod", no))
                st["linked"] += 1
            got = False
            if want_photo and dry:
                st["added"] += 1  # 저장 없이 볼 때는 '넣을 수 있는 칸' 수
            elif want_photo:
                rel = it["slot"] + ".jpg"
                dest = folder / rel
                shared = dest.is_file() and rel in used  # 같은 이름의 다른 칸이 쓰는 사진 → 함께 쓴다 (덮어쓰지 않음)
                if dest.is_file() and not shared:
                    # 빈 칸인데 파일만 남음 = 편집기에서 사진을 뺀 것. 다시 쓰지 않고 backups 로 옮긴다 (편집기와 같은 방식)
                    keep = folder / "backups" / Path(it["slot"]).parent / f"{dest.stem}-{stamp}{dest.suffix}"
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    dest.replace(keep)
                try:
                    got = shared or fetch(pno, hints.get(pno), dest, web)
                except KeyboardInterrupt:
                    log("멈춤 — 여기까지 한 것을 저장합니다")
                    stop = True
                except Exception as e:
                    log(f"  사진 못 받음 {gid} (상품 {pno}): {e}")
                if got:
                    used.add(rel)
                    src = f"{quote(rel)}?v={dest.stat().st_mtime_ns // 1_000_000}"
                    edits.append((*it["slot_span"], f'<img src="{src}" alt="">'))
                    st["added"] += 1
                elif not stop:
                    st["failed"] += 1
            where = [pi + 1, it["brand"] if not card else title, it["name"], it.get("orig", ""), gid]
            if not no and not cur:
                report.append(where + ["상품 번호 못 찾음"])
            elif card and pno and empty_slot(it) and not got:
                report.append(where + ["사진 없음"])
            if differ:  # 직접 넣은 번호일 수 있어 기본은 그대로 둔다 (--relink 면 바꿈)
                report.append(where + [f"상품 번호 다름: 지금 {cur}, 찾은 번호 {no}" + (" → 찾은 번호로 바꿈" if want_link else "")])
        if edits and not dry:
            page["html"] = CD._apply(s, edits)

    log(f"제품 카드 {st['card']}개 중 상품 번호 찾음 {st['card_hit']}개 ({st['card_hit'] * 100 // max(1, st['card'])}%)")
    log(f"기타 나이프 줄 {st['row']}개 중 상품 번호 찾음 {st['row_hit']}개 ({st['row_hit'] * 100 // max(1, st['row'])}%)")
    if links:
        log(f"홈페이지 연결 {'넣을 것' if dry else '넣음'}: {st['linked']}개")
    if photos:
        log(f"사진: 원래 있던 칸 {st['had']}개, {'넣을 수 있는 칸' if dry else '새로 넣음'} {st['added']}개"
            + ("" if dry else f", 못 받음 {st['failed']}개"))
    if st["todo_left"]:
        log(f"남은 것 {st['todo_left']}개 — 다시 실행하면 이어서 합니다")
    if dry:
        log("(저장 안 함: --dry-run)")
        return st, report
    if (st["linked"] or st["added"]) and doc_path.resolve() == (BASE / "catalog.json").resolve() and editor_running():
        log("작업 중에 편집기가 켜져서 카탈로그에 넣지 않았습니다. 편집기를 끄고(검은 창 닫기) 다시 실행해 주세요.")
        return st, report
    if st["linked"] or st["added"]:
        backups = folder / "backups"
        backups.mkdir(exist_ok=True)
        shutil.copyfile(doc_path, backups / f"catalog-{datetime.now():%Y%m%d-%H%M%S}.json")  # 먼저 백업
        CD.save_doc(doc_path, doc, backups)  # 검사 → 임시 파일에 쓰고 바꿔치기
        log(f"저장함: {doc_path}")
    out = folder / "사진_링크_확인.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "확인할 제품"
    ws.append(["쪽", "브랜드·제목", "제품명", "원래 상품명", "그룹ID·품번", "문제"])
    for r in report:
        ws.append(r)
    for col, w in zip("ABCDEF", (6, 18, 40, 50, 14, 18)):
        ws.column_dimensions[col].width = w
    try:
        wb.save(out)
        log(f"확인할 제품 {len(report)}개 → {out.name}")
    except PermissionError:
        log(f"{out.name} 이 열려 있어 저장하지 못했습니다. 닫고 다시 실행해 주세요.")
    return st, report


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="카탈로그 제품 ↔ 홈페이지 상품 연결, 빈 사진 칸 채우기")
    ap.add_argument("--doc", required=True, help="catalog.json 경로 (사진은 이 파일 옆 images 폴더에 저장)")
    ap.add_argument("--links", action="store_true", help="카드·줄에 홈페이지 상품 번호(data-prod) 넣기")
    ap.add_argument("--relink", action="store_true", help="이미 있는 상품 번호도 찾은 번호로 바꾸기 (--links 포함)")
    ap.add_argument("--photos", action="store_true", help="빈 사진 칸에 홈페이지 대표 사진 넣기")
    ap.add_argument("--limit", type=int, default=0, help="이 개수만 하고 멈춤 (다시 돌리면 이어서)")
    ap.add_argument("--dry-run", action="store_true", help="저장하지 않고 몇 개 찾는지만 보기")
    ap.add_argument("--web", default=str(WEB), help="sitemap_map.json 과 상세 화면 저장 폴더")
    a = ap.parse_args()
    a.links = a.links or a.relink
    if not (a.links or a.photos):
        ap.error("--links 나 --photos 중 하나는 골라 주세요.")
    doc = Path(a.doc).resolve()
    if not doc.is_file():
        print(f"문서 파일이 없습니다: {doc}")
        return 1
    if not a.dry_run and doc == (BASE / "catalog.json").resolve() and editor_running():
        print("편집기가 켜져 있습니다. 편집기를 끄고(검은 창 닫기) 다시 실행해 주세요. (켜 둔 채면 편집기가 저장할 때 이 작업이 지워집니다)")
        return 1
    run(doc, a.links, a.photos, a.limit, a.dry_run, web=Path(a.web), relink=a.relink)
    return 0


if __name__ == "__main__":
    sys.exit(main())
