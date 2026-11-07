"""홈페이지 스펙(스펙/*.json) → 카탈로그 문서(catalog.json)에 넣기

    python apply_specs.py --doc catalog.json             넣기 (원본은 catalog.before-specs.json 으로 남김)
    python apply_specs.py --doc catalog.json --dry-run   미리보기 (결과표만 만들고 문서는 그대로)
    python apply_specs.py --doc catalog.json --brand 마사히로 --brand 모라

- 칼 카드: HRC·두께·날 재질·핸들 재질 줄을 채우고, 표는 사이즈마다 한 줄(날 길이 + 모델 넘버)로 맞춘다.
  품번·날 길이는 홈페이지가 기준. 그 밖에 이미 적힌 다른 값은 바꾸지 않고 결과표에 적는다.
- 사이즈마다 두께·재질이 달라도 표에 칸을 더하지 않고 왼쪽 스펙 줄 하나로 모은다 (사용자 요청 2026-10-21):
  숫자(두께)는 평균을 '약 2.3mm' 처럼 소수 한 자리까지, 글자(재질)는 서로 다른 값을 ' / ' 로 이어 적는다.
- 기타 나이프 표: 품번으로 찾아서 빈 사이즈를 채우고, 없는 사이즈는 줄을 더한다.
- 2단 카드(숫돌·가위·도구, 스펙/브랜드_연마.json·_가위.json·_도구.json): 빈 스펙 줄을 채우고, 줄이 없는 항목(방수·원산지 등)은
  줄을 더한다. 모델마다 다른 값은 칼과 같게 한 줄로 (숫자는 '약' 평균, 글은 ' / '). 빈 모델 넘버·방수 표시도 채운다.
- 스펙_검수.xlsx 마지막 칸에 고칠 내용이 적힌 제품은 건너뛴다.
- 결과표: 문서 폴더의 스펙_적용_결과.xlsx
- 편집기가 켜져 있으면 catalog.json 에는 넣지 않는다 (편집기가 저장할 때 이 작업이 지워지므로)
"""
import argparse
import json
import os
import re
import shutil
import socket
import sys
from collections import Counter
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from html import unescape
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import catalog_doc  # noqa: E402  (문서 검사)
import spec_review  # noqa: E402  (검수표를 만든 기준: 쪽·제품 이름)

FIELDS = (("hrc", "HRC"), ("두께", "두께"), ("날 재질", "날 재질"), ("핸들 재질", "핸들 재질"))
LABEL = dict(FIELDS)
KV_ORDER = [lab for _, lab in FIELDS]
COLOR_H, SIZE_H, CODE_H = ("핸들 색상", "색상"), ("날 길이", "사이즈"), "모델 넘버"
MAIN_W = 122.0          # 칼 카드 표 폭 mm (본문 186 - 스펙 60 - 사이 4)
OK_MARKS = {"", "o", "0", "ㅇ", "ok", "확인", "맞음", "v", "✓", "✔", "○", "◯"}
REPORT_NAME = "스펙_적용_결과.xlsx"
TOOL_GROUPS = ("연마", "가위", "도구")   # 스펙/브랜드_연마.json 처럼 이름 끝에 붙는 묶음


# ───────── 글자 ─────────
def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(" ", "&nbsp;")


def text_of(h):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", h or "")).split())


def same(a, b):
    return re.sub(r"\s+", "", str(a)).lower() == re.sub(r"\s+", "", str(b)).lower()


def ncode(c):
    """품번 비교용: 띄어쓰기·대소문자 무시, 숫자만인 품번은 앞의 0 무시 (엑셀이 02261 → 2261 로 바꾼 것)"""
    c = re.sub(r"\s+", "", str(c)).lower()
    return (c.lstrip("0") or "0") if c.isdigit() else c


def tokens(code_text):
    """품번 칸 → 품번들 (쉼표로 여러 개 적힌 칸. 괄호 안 쉼표는 나누지 않음)"""
    out, depth, cur = [], 0, ""
    for ch in code_text:
        depth += (ch in "([") - (ch in ")]" and depth > 0)
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [t.strip() for t in out if t.strip()]


def code_parts(code_text):
    """품번 칸에서 맞춰 볼 글들: 쉼표로 나눈 것, 괄호 뺀 것, 괄호 안 것, '/' 앞뒤"""
    out = []
    for t in tokens(code_text):
        base = re.sub(r"\s*[(\[].*?[)\]]", "", t).strip()
        inside = [x.strip() for m in re.findall(r"[(\[](.*?)[)\]]", t) for x in m.split(",")]
        for x in [t, base] + inside + (base.split("/") if "/" in base else []):
            if x.strip() and x.strip() not in out:
                out.append(x.strip())
    return out


def size_num(t):
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*", t or "")
    return float(m.group(1)) if m else None


def size_text(n):
    return f"{n} mm" if n else ""


KV_W = 41.0            # 칼 카드 스펙 줄 값 폭 mm (60 - 이름 17 - 사이 2)


# 글자 폭 (em). 편집기에서 Noto Sans KR 을 canvas 로 잰 값 (굵은 글씨는 영문·숫자만 6% 넓고 한글은 같음)
EM = {ch: w for chars, w in (
    ("0123456789#$+<=>^~_", .555), (" ", .28), (".,:;'·|", .279), ("()[]{}", .338), ("-", .348), ("/\\°", .39),
    ("%", .921), ("&", .68), ("*\"?", .47), ("!", .323), ("@", .946),
    ("I", .293), ("JLF", .55), ("YVXSTZE", .6), ("ACPRK", .64), ("BGD", .69), ("HNUOQ", .735), ("M", .812), ("W", .878),
    ("ijl", .28), ("frt", .38), ("sz", .475), ("cvxy", .52), ("aegk", .56), ("bdhnopqu", .615), ("w", .802), ("m", .926))
    for ch in chars}


def est_mm(s, bold=False, pt=8.0):
    """글자 폭 어림 (mm)"""
    w = sum(EM[ch] * (1.06 if bold else 1) if ch in EM else (0.92 if "가" <= ch <= "힣" else 1.0) for ch in s)  # 그 밖(한자·기호)은 넉넉히 1
    return w * pt * 0.3528


def splice(s, edits):
    """edits = [(시작, 끝, 새 글)] — 겹치지 않아야 함. 같은 자리 끼워 넣기는 넣은 순서대로"""
    out, pos = [], 0
    for a, b, t, _ in sorted(((a, b, t, i) for i, (a, b, t) in enumerate(edits)), key=lambda x: (x[0], x[1], x[3])):
        if a < pos:
            raise ValueError("겹치는 수정")
        out.append(s[pos:a])
        out.append(t)
        pos = b
    out.append(s[pos:])
    return "".join(out)


# ───────── 작은 HTML 해석기 (원래 글자 위치를 그대로 기억) ─────────
_TAG = re.compile(r"<!--.*?(?:-->|\Z)|<(/?)([a-zA-Z][^\s/>]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>", re.S)
VOID = catalog_doc.VOID


class El:
    __slots__ = ("tag", "attrs", "s", "si", "ei", "e", "kids", "parent")

    def __init__(self, tag, attrs, s, si, parent=None):
        self.tag, self.attrs, self.s, self.si, self.ei, self.e = tag, attrs, s, si, si, si
        self.kids, self.parent = [], parent

    def attr(self, name):
        m = re.search(r'(?:^|\s)' + re.escape(name) + r'\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))', self.attrs)
        return unescape(m.group(1) if m.group(1) is not None else (m.group(2) if m.group(2) is not None else m.group(3))) if m else None

    def has(self, c):
        return c in (self.attr("class") or "").split()

    def walk(self):
        for k in self.kids:
            yield k
            yield from k.walk()

    def find(self, tag, cls=None):
        return [e for e in self.walk() if e.tag == tag and (cls is None or e.has(cls))]

    def kids_of(self, tag, cls=None):
        return [e for e in self.kids if e.tag == tag and (cls is None or e.has(cls))]


def parse(html):
    root = El("#root", "", 0, 0)
    root.ei = root.e = len(html)
    stack = [root]
    for m in _TAG.finditer(html):
        if m.group(0).startswith("<!--"):
            continue
        close, name, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if not close:
            el = El(name, attrs, m.start(), m.end(), stack[-1])
            stack[-1].kids.append(el)
            if name not in VOID and not attrs.rstrip().endswith("/"):
                stack.append(el)
            continue
        for k in range(len(stack) - 1, 0, -1):
            if stack[k].tag == name:
                for j in range(len(stack) - 1, k, -1):      # 안 닫힌 것은 여기서 닫힘
                    stack[j].ei = stack[j].e = m.start()
                stack[k].ei, stack[k].e = m.start(), m.end()
                del stack[k:]
                break
    for el in stack[1:]:
        el.ei = el.e = len(html)
    return root


def inner(html, el):
    return html[el.si:el.ei]


def outer(html, el):
    return html[el.s:el.e]


# ───────── 스펙 ─────────
COLOR_KEYS = ("핸들 색", "핸들 색상", "색상", "색")
COLORS = {"블랙": "#111", "화이트": "#fff", "레드": "#d0342c", "블루": "#1f5fbf", "그린": "#1e8e4e", "옐로우": "#f2c200",
          "오렌지": "#f08a00", "그레이": "#8a8d91", "실버": "#c0c4c8", "골드": "#c9a227", "브라운": "#7a4a21",
          "핑크": "#f29bb7", "퍼플": "#7a3fa0", "아이보리": "#f3ead3", "네이비": "#1f2f5c", "우드": "#b98a52"}  # build_catalog.py 와 같게
COLOR_ALIAS = {"검정": "블랙", "검은색": "블랙", "흑색": "블랙", "빨강": "레드", "빨간색": "레드", "적색": "레드", "파랑": "블루",
               "파란색": "블루", "청색": "블루", "초록": "그린", "녹색": "그린", "노랑": "옐로우", "노란색": "옐로우", "흰색": "화이트",
               "하양": "화이트", "백색": "화이트", "회색": "그레이", "은색": "실버", "금색": "골드", "갈색": "브라운", "분홍": "핑크",
               "보라": "퍼플", "남색": "네이비", "주황": "오렌지"}


def swatches(v):
    """색 이름 → 색 칸 (build_catalog.py 의 swatches 와 같은 모양)"""
    names = [COLOR_ALIAS.get(n.strip(), n.strip()) for n in v.split("/") if n.strip()]
    if names and all(n in COLORS for n in names):
        return "".join(f'<i class="sw" style="background:{COLORS[n]}" title="{n}"></i>' for n in names)
    return esc(v)


class SRow:
    """홈페이지 사이즈 한 줄"""
    __slots__ = ("code", "size", "text", "extra", "i", "color", "other")

    def __init__(self, z, i):
        self.code = str(z[0] or "").strip()
        try:
            self.size = int(z[1] or 0)
        except (TypeError, ValueError):
            self.size = 0
        self.text = size_text(self.size) or str(z[1] or "").strip()     # 2단 카드용 글 ('206×73×22mm')
        third = z[2] if len(z) > 2 else None
        if isinstance(third, dict):
            self.extra = {("hrc" if k.lower() == "hrc" else k): str(v).strip() for k, v in third.items() if str(v).strip()}
        elif third:
            self.extra = {"두께": str(third).strip()}
        else:
            self.extra = {}
        self.color = next((self.extra.pop(k) for k in COLOR_KEYS if k in self.extra), "")
        self.other = [k for k in self.extra if k not in LABEL and k != "원산지"]
        self.i = i

    def empty(self):
        return not (self.code or self.text or self.extra or self.color)

    def label(self):
        return " · ".join(x for x in (self.text, self.code) if x) or "(사이즈·품번 없음)"


def is_tool(stem):
    return stem.rsplit("_", 1)[-1] in TOOL_GROUPS


def has_data(spec, tool=False):
    if tool:            # 숫돌·가위: 사이즈 말고 재질·무게만 있어도 넣음
        return any(str(v).strip() for k, v in spec.items() if not k.startswith("_") and k not in ("메모", "상품번호"))
    return bool(spec.get("사이즈")) or any(spec.get(f) for f, _ in FIELDS)


def sizes_str(spec):
    """스펙_검수.xlsx '사이즈 · 품번' 칸과 똑같은 글 (spec_review.py 와 같게)"""
    def extra(v):
        if isinstance(v, dict):
            return "(" + ", ".join(f"{k} {x}" for k, x in v.items()) + ")"
        return f"(두께 {v})"
    return " / ".join(" ".join(x for x in (z[0], (f"{z[1]}mm" if isinstance(z[1], (int, float)) else str(z[1])) if z[1] else "",
                                           extra(z[2]) if len(z) > 2 else "") if x)
                      for z in spec.get("사이즈", []))


def load_specs(folder, brands):
    """칼(브랜드.json)과 숫돌·가위·도구(브랜드_연마.json 등). --brand 마사히로 는 둘 다, --brand 마사히로_연마 는 그 파일만"""
    out = []
    want = [b.lower() for b in brands or []]
    for f in sorted(Path(folder).glob("*.json")):
        stem = f.stem
        base = stem.rsplit("_", 1)[0] if is_tool(stem) else stem
        short = re.sub(r"\(.*?\)", "", base).strip().lower()
        if want and stem.lower() not in want and base.lower() not in want and short not in want:
            continue
        data = json.loads(f.read_text(encoding="utf-8-sig"))
        for gid, spec in data.items():
            if not gid.startswith("_") and isinstance(spec, dict):
                out.append((stem, gid, spec))
    return out


# ───────── 검수표 ─────────
class Review:
    def __init__(self, path):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        rows = list(wb.worksheets[0].iter_rows(values_only=True))
        wb.close()
        head = [str(h or "").strip() for h in rows[0]]

        def col(prefix):
            return next(i for i, h in enumerate(head) if h.startswith(prefix))
        ix = {k: col(p) for k, p in (("page", "쪽"), ("brand", "브랜드"), ("name", "제품"), ("hrc", "HRC"), ("두께", "두께"),
                                     ("날 재질", "날 재질"), ("핸들 재질", "핸들 재질"), ("sizes", "사이즈"), ("ok", "확인"))}
        cell = lambda r, k: "" if ix[k] >= len(r) or r[ix[k]] is None else str(r[ix[k]]).strip()  # noqa: E731
        self.rows = [{k: cell(r, k) for k in ix} for r in rows[1:] if any(v is not None for v in r)]

    def status(self, brand, spec, name="", page=""):
        """('ok' | 'pending' | 'missing', 고칠 내용). name·page 는 검수표를 만들 때와 같은 기준(spec_review.cards).
        HRC·두께 같은 값 칸은 직원이 고쳤을 수 있어 줄 찾기에 안 씀. 줄이 하나로 안 좁혀지면 하나라도 고칠 내용이 있으면 건너뜀"""
        mine = [r for r in self.rows if r["brand"] == brand]
        c = [r for r in mine if r["name"] == name and r["page"] == str(page)]
        if len(c) != 1:
            c = [r for r in (c or mine) if r["sizes"] == sizes_str(spec)] or c
        if not c:
            return "missing", ""
        bad = [r["ok"] for r in c if r["ok"].strip().lower().rstrip(".!") not in OK_MARKS]
        return ("pending", " / ".join(bad)) if bad else ("ok", "")


# ───────── 결과 모음 ─────────
class Note:
    """카드(또는 기타 나이프 제품) 하나의 결과"""

    def __init__(self, page, brand, name, group, kind=""):
        self.page, self.brand, self.name, self.group, self.kind = page, brand, name, group, kind
        self.changes, self.checks, self.n = [], [], Counter()

    def change(self, msg, key=None):
        self.changes.append(msg)
        if key:
            self.n[key] += 1

    def check(self, msg, key=None):
        if msg not in self.checks:
            self.checks.append(msg)
        if key:
            self.n[key] += 1


# ───────── 줄 맞추기 (카드 표·기타 나이프 공통) ─────────
def code_keys(code_text):
    return {ncode(x) for x in code_parts(code_text)}


def match_rows(ex, sp):
    """ex = [(품번 칸 글, 사이즈 숫자|None, 사이즈 글, 빈 줄인지)], sp = [SRow]
    → (짝 [(ex i, sp j, 방법)], 남은 ex, 남은 sp). 방법: code / size / blank / elim"""
    used_e, used_s, pairs = set(), set(), []
    toks = [code_keys(e[0]) for e in ex]
    spec_codes = {ncode(s.code) for s in sp if s.code}

    def take(j, cands, how):
        if cands:
            used_e.add(cands[0])
            used_s.add(j)
            pairs.append((cands[0], j, how))

    for exact in (True, False):                     # 품번 + 사이즈 → 품번만
        for j, s in enumerate(sp):
            if j in used_s or not s.code:
                continue
            take(j, [i for i in range(len(ex)) if i not in used_e and ncode(s.code) in toks[i]
                     and (not exact or ex[i][1] == s.size)], "code")
    for j, s in enumerate(sp):                      # 사이즈: 품번 빈 줄 → 다른 품번 줄 → 같은 품번이 또 적힌 줄
        if j in used_s or not s.size:
            continue
        cands = sorted((i for i in range(len(ex)) if i not in used_e and ex[i][1] == s.size),
                       key=lambda i: (bool(toks[i]), bool(toks[i] & spec_codes)))
        take(j, cands, "size")
    blanks = [i for i in range(len(ex)) if i not in used_e and ex[i][3]]      # 아무것도 안 적힌 줄은 빈자리로 씀
    for i, j in zip(blanks, sorted((j for j in range(len(sp)) if j not in used_s),
                                   key=lambda j: (not sp[j].size, sp[j].size, j))):
        take(j, [i], "blank")
    rest_e = [i for i in range(len(ex)) if i not in used_e]
    rest_s = [j for j in range(len(sp)) if j not in used_s]
    if len(rest_e) == 1 and len(rest_s) == 1 and not ex[rest_e[0]][2].strip():   # 남은 한 줄끼리 (카탈로그 쪽 사이즈가 빈 칸)
        take(rest_s[0], rest_e, "elim")
        rest_e, rest_s = [], []
    return pairs, rest_e, rest_s


def merge_code(cur_inner, s, how, note):
    """품번 칸 → 새 inner (안 바뀌면 None)"""
    cur = text_of(cur_inner)
    ts = tokens(cur)
    if not ts:
        note.change(f"품번 넣음: {s.code}", "cells")
        return esc(s.code)
    parts = code_parts(cur)
    if s.code in parts:
        return None
    k = next((x for x in parts if ncode(x) == ncode(s.code)), None)
    if k is not None:                               # 대소문자·띄어쓰기·앞의 0 만 다름
        note.change(f"품번 고침: {k} → {s.code}", "codes")
        word = lambda x: r"(?<![\w.\-])" + re.escape(x) + r"(?![\w.\-])"  # noqa: E731
        new = re.sub(word(esc(k)), lambda m: esc(s.code), cur_inner, count=1)
        return new if new != cur_inner else esc(re.sub(word(k), lambda m: s.code, cur, count=1))
    if len(parts) == 1:
        note.change(f"품번 고침: {cur} → {s.code}", "codes")
        why = {"elim": "남은 줄끼리", "blank": "빈 줄에"}.get(how, "날 길이로")
        note.check(f"품번이 달라 홈페이지 품번으로 바꿈: {cur} → {s.code} ({why} 짝지음)")
        return esc(s.code)
    note.check(f"품번 칸 '{cur}' 에 홈페이지 품번 {s.code} 이 없음 (그대로 둠)", "conflicts")
    return None


def merge_size(cur_inner, s, note, who):
    """날 길이 칸 → 새 inner (안 바뀌면 None)"""
    if not s.size:
        return None
    cur, new = text_of(cur_inner), size_text(s.size)
    if not cur:
        note.change(f"날 길이 넣음: {who} {new}".replace("  ", " "), "cells")
        return new
    n = size_num(cur)
    if n is None:
        note.check(f"날 길이 '{cur}' 그대로 둠 (홈페이지 {new})", "conflicts")
        return None
    if n != s.size:
        msg = f"{who} {cur} → {new}".strip()
        note.change(f"날 길이 고침: {msg}", "sizes")
        note.check(f"날 길이를 홈페이지대로 바꿈 (확인): {msg}")
        return new
    return None


# ───────── 카드 표 ─────────
class Cell:
    __slots__ = ("raw", "cls", "inner", "dirty")

    def __init__(self, inner="", cls="", raw=None):
        self.inner, self.cls, self.raw, self.dirty = inner, cls, raw, raw is None

    def set(self, inner, cls=None):
        self.inner = inner
        if cls is not None:
            self.cls = cls
        self.dirty = True

    def html(self):
        return self.raw if not self.dirty else f'<span class="{self.cls}">{self.inner}</span>'


class Table:
    def __init__(self, html, art):
        ts = [e for e in art.find("div", "t")]
        self.ok = bool(ts)
        if not ts:
            return
        first = ts[0]
        self.two = first.parent is not None and first.parent.tag == "div" and first.parent.has("two")
        self.block = first.parent if self.two else first
        tables = self.block.kids_of("div", "t") if self.two else [first]
        hb = first.kids_of("b")
        self.heads = [text_of(inner(html, b)) for b in hb]
        self.head_raw = {self.heads[i]: outer(html, b) for i, b in enumerate(hb)}
        self.style = first.attr("style") or ""
        self.rows = []
        for t in tables:
            k = len(t.kids_of("b")) or 1
            cells = [Cell(inner(html, c), c.attr("class") or "", outer(html, c)) for c in t.kids_of("span")]
            while len(cells) % k:
                cells.append(Cell())
            for i in range(0, len(cells), k):
                self.rows.append(dict(zip(self.heads, cells[i:i + k])))
        self.n0, self.heads0, self.changed = len(self.rows), list(self.heads), False

    def col(self, names):
        names = (names,) if isinstance(names, str) else names
        return next((h for h in self.heads if h in names), None)

    def cell(self, row, head):
        if head not in row:
            row[head] = Cell()
        return row[head]


STD_W = {"핸들 색상": 16.0, "색상": 16.0, "날 길이": 18.0, "사이즈": 18.0, "두께": 16.0, "HRC": 13.0}


def cell_mm(c, bold=False, small=None):
    """칸 하나에 필요한 폭 mm (칸 안 여백 0.8mm×2 + 조금, 색 칸은 한 개 3.8mm). small = .long 글씨(6.5pt, 자간 -0.02em)"""
    txt = text_of(c.inner)
    if small is None:
        small = "long" in c.cls.split()
    w = est_mm(txt, bold, 6.5) - 0.02 * 6.5 * 0.3528 * len(txt) if small else est_mm(txt, bold)
    return w + 3.8 * c.inner.count('class="sw"') + 2.0


def widths_for(t, code_h, note):
    """표 칸 폭: 모델 넘버는 1fr, 나머지는 mm. 자리가 모자라면 여유 폭 줄임 → 비어 있는 색상 칸 뺌 → 재질 칸을 작은 글씨 폭까지"""
    def need(h, small=False):
        return max([est_mm(h, True) + 2.0] + [cell_mm(r[h], h == code_h, small) for r in t.rows])
    others = lambda: [h for h in t.heads if h != code_h]  # noqa: E731
    color = t.col(COLOR_H)
    if color and not any(r[color].inner.strip() for r in t.rows) and sum(map(need, others())) + need(code_h) > MAIN_W:
        t.heads.remove(color)
        for r in t.rows:
            r.pop(color, None)
        note.change(f"비어 있는 '{color}' 칸을 뺌 (표 자리가 모자라서)")
    cols = others()
    w = {h: need(h) if h in STD_W else min(need(h), 40.0) for h in cols}
    pref = {h: max(STD_W[h], w[h]) if h in STD_W else w[h] for h in cols}
    room = MAIN_W - need(code_h)
    slack = sum(pref.values()) - sum(w.values())
    if sum(pref.values()) <= room:
        w = pref
    elif sum(w.values()) < room:                    # 기본 폭의 여유만 줄임
        k = (room - sum(w.values())) / slack
        w = {h: w[h] + (pref[h] - w[h]) * k for h in cols}
    else:                       # 그래도 모자람: 재질 같은 글 칸을 작은 글씨 폭까지 → 품번도 작은 글씨 → 글 칸은 잘림(결과표에 적힘)
        text = [h for h in cols if h not in STD_W]
        head = {h: est_mm(h, True) + 2.0 for h in text}
        small = {h: min(w[h], max(head[h], need(h, True))) for h in text}
        fixed = sum(w[h] for h in cols if h not in text)
        if fixed + sum(small.values()) > room:
            room = MAIN_W - need(code_h, True)
        have = room - fixed                         # 글 칸들이 쓸 수 있는 폭
        if have >= sum(small.values()):
            give = sum(w[h] - small[h] for h in text)
            k = min(1.0, (sum(w[h] for h in text) - have) / give) if give > 0 else 0
            w.update({h: w[h] - (w[h] - small[h]) * k for h in text})
        elif text:
            k = have / sum(small.values())
            w.update({h: max(head[h], small[h] * k) for h in text})
    return " ".join(f"{w[h]:.1f}".rstrip("0").rstrip(".") + "mm" if h in w else "1fr" for h in t.heads)


def fit(t, widths, total, code_h, note):
    """칸에 안 들어가는 글은 작은 글씨(long)로. 그래도 안 들어가면 결과표에 적음"""
    ws = widths.split()
    if len(ws) != len(t.heads) or not all(re.fullmatch(r"[\d.]+(mm|fr)", x) for x in ws):
        return
    fixed = sum(float(x[:-2]) for x in ws if x.endswith("mm"))
    frs = sum(float(x[:-2]) for x in ws if x.endswith("fr")) or 1
    for h, x in zip(t.heads, ws):
        wmm = float(x[:-2]) if x.endswith("mm") else (total - fixed) * float(x[:-2]) / frs
        for r in t.rows:
            c = r[h]
            if cell_mm(c, h == code_h, False) <= wmm + 0.05:
                continue
            if "long" not in c.cls.split():
                c.set(c.inner, (c.cls + " long").strip())
                note.change(f"'{h}' 글씨를 작게 함 (칸에 맞게): {text_of(c.inner)}")
            if cell_mm(c, h == code_h) > wmm + 0.05:
                note.check(f"'{h}' 글자가 길어 표에서 끝이 잘려 보임: {text_of(c.inner)}", "tcut")


def write_table(t, code_h, extras, note):
    """표 → html. 사이즈 순으로 줄 세우고, 줄이 많으면 2단(칼 카드 규칙과 같게)"""
    def key(r):
        c = r.get(t.col(SIZE_H)) if t.col(SIZE_H) else None
        n = size_num(text_of(c.inner)) if c and text_of(c.inner) else None
        return (n is None, n or 0)
    t.rows.sort(key=key)
    for r in t.rows:
        for h in t.heads:
            t.cell(r, h)
    n = len(t.rows)
    codes = [text_of(r[code_h].inner) for r in t.rows] if code_h else []
    std = all(h in ("핸들 색상", "날 길이", "모델 넘버") for h in t.heads)
    two = std and n > 4 and max([len(c) for c in codes] + [0]) <= 14 and (t.two or t.n0 <= 4)
    if two != t.two:
        note.change("표를 좌우 2단으로 나눔" if two else "표를 1단으로 합침")
    if two:
        widths = " ".join({"핸들 색상": "16mm", "날 길이": "18mm"}.get(h, "1fr") for h in t.heads)
    elif extras:
        widths = widths_for(t, code_h, note)
    elif not t.two and t.heads == t.heads0 and t.style.startswith("grid-template-columns:"):
        widths = t.style[len("grid-template-columns:"):]
    else:
        widths = " ".join({"핸들 색상": "24mm", "날 길이": "30mm"}.get(h, "1fr") for h in t.heads)
    fit(t, widths, (MAIN_W - 4) / 2 if two else MAIN_W, code_h, note)

    def one(rows):
        head = "".join(t.head_raw.get(h) or f"<b>{esc(h)}</b>" for h in t.heads)
        return f'<div class="t" style="grid-template-columns:{widths}">{head}' + \
            "".join(r[h].html() for r in rows for h in t.heads) + "</div>"
    if two:
        half = -(-n // 2)
        return '<div class="two">' + one(t.rows[:half]) + one(t.rows[half:]) + "</div>"
    return one(t.rows)


_NUM = re.compile(r"\d+(?:\.\d+)?")
# 2단 카드 값: (HRC) 숫자(~숫자) 단위. '#1000'(방수)·'10인치'·'210×70mm' 처럼 다른 모양은 평균 내지 않음
_MEAS = re.compile(r"(HRC)?\s*(\d+(?:\.\d+)?)(?:\s*[~\-–]\s*(\d+(?:\.\d+)?))?\s*(mm|cm|kg|g|ml|°C|°|T|)", re.I)


def approx(vals, unit="mm"):
    """두께 값들('2mm', '2~2.5mm', '3.5T') → '약 2.3mm' (평균, 소수 한 자리까지). 숫자가 아닌 게 섞이면 None
    unit=None: 단위를 값에서 읽음 ('약 73g'·'HRC 61'·'80°C') — 단위가 서로 다르면 None"""
    nums, units = [], set()
    for v in vals:
        if unit is None:
            m = _MEAS.fullmatch(v.replace("약", "").strip())
            if not m:
                return None
            units.add(((m.group(1) or "").upper(), m.group(4).lower()))
            ns = [Decimal(x) for x in m.group(2, 3) if x]
            unit_of = (m.group(1) or "").upper(), m.group(4)
        else:
            ns = [Decimal(x) for x in _NUM.findall(v)]
            if not ns or re.sub(r"[\d.~\-–\s]|mm|T|약", "", v, flags=re.I):
                return None
        nums.append(sum(ns) / len(ns))           # '2~2.5' 는 가운데 값
    if len(units) > 1:
        return None
    m = (sum(nums) / len(nums)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP).normalize()
    if unit is None:
        pre, unit = unit_of
        return f"약 {pre + ' ' if pre else ''}{m:f}{unit}"
    return f"약 {m:f}{unit}"


def merged(f, vals):
    """사이즈마다 다른 값을 왼쪽 스펙 줄 하나로"""
    vals = [v for v in vals if v]
    if not vals:
        return ""
    if f == "두께":
        a = approx(vals)
        if a:
            return a
    return " / ".join(dict.fromkeys(vals))


def field_plan(srows, top, heads):
    """항목마다 (스펙 줄 값, 표 칸 여부(항상 아님), 줄마다 값) — 표에 칸을 더하지 않고 왼쪽 줄로 모은다"""
    plan = {}
    for f, lab in FIELDS:
        tv = str(top.get(f) or "").strip()
        vals = [s.extra.get(f) or tv for s in srows] or [tv]
        plan[f] = (merged(f, vals), False, vals)
    return plan


def fill_kvs(html, art, plan, note, edits):
    specs = (art.find("div", "specs") or [None])[0]
    if specs is None:
        if any(v for v, _, _ in plan.values()):
            note.check("스펙 줄 칸이 없어 HRC·재질을 못 넣음")
        return
    kvs = []
    for p in specs.kids_of("p", "kv"):
        b, sp = (p.kids_of("b") or [None])[0], (p.kids_of("span") or [None])[0]
        if b is not None and sp is not None:
            kvs.append((text_of(inner(html, b)), p, sp))
    for f, lab in FIELDS:
        v = plan[f][0]
        if not v:
            continue
        hit = next((k for k in kvs if k[0] == lab), None)
        if hit:
            cur = text_of(inner(html, hit[2]))
            if not cur:
                edits.append((hit[2].si, hit[2].ei, esc(v)))
                note.change(f"{lab} 넣음: {v}", "kv")
                if est_mm(v, pt=8.5) > KV_W - 0.5:
                    note.check(f"{lab} 글자가 길어 카드에서 끝이 '…' 로 잘려 보임: {v}", "cut")
            elif not same(cur, v):
                note.check(f"{lab} 다름 — 카탈로그: {cur} / 홈페이지: {v} (안 바꿈)", "conflicts")
            continue
        order = KV_ORDER.index(lab)
        before = [k for k in kvs if k[0] in KV_ORDER and KV_ORDER.index(k[0]) < order]
        after = [k for k in kvs if not (k[0] in KV_ORDER and KV_ORDER.index(k[0]) < order)]
        pos = before[-1][1].e if before else (after[0][1].s if after else specs.si)
        edits.append((pos, pos, f'<p class="kv"><b>{esc(lab)}</b><span>{esc(v)}</span></p>'))
        note.change(f"{lab} 줄 더해 넣음: {v}", "kv")
        if est_mm(v, pt=8.5) > KV_W - 0.5:
            note.check(f"{lab} 글자가 길어 카드에서 끝이 '…' 로 잘려 보임: {v}", "cut")


def other_keys(srows, note):
    keys = list(dict.fromkeys(k for s in srows for k in s.other))
    if keys:
        note.check("사이즈별 " + "·".join(keys) + " 값은 넣을 칸이 없음")


def apply_wide(html, srows, top, note):
    """칼 카드(article.w) 하나 → 새 html"""
    art = parse(html)
    edits = []
    other_keys(srows, note)
    t = Table(html, art)
    plan = field_plan(srows, top, t.heads if t.ok else [])
    if t.ok and srows:
        ch, sh, code_h = t.col(COLOR_H), t.col(SIZE_H), t.col(CODE_H)
        if not code_h or not sh:
            note.check("표에 날 길이·모델 넘버 칸이 없어 표는 그대로 둠")
        else:
            for f, lab in FIELDS:                   # 사이즈마다 다른 값 → 칸 더하기 (모델 넘버 앞)
                if plan[f][1] and lab not in t.heads:
                    at = t.heads.index(code_h)
                    for g, lab2 in FIELDS[FIELDS.index((f, lab)) + 1:]:
                        if lab2 in t.heads:
                            at = min(at, t.heads.index(lab2))
                    t.heads.insert(at, lab)
                    for r in t.rows:
                        r[lab] = Cell()
                    t.changed = True
                    note.change(f"표에 '{lab}' 칸 더함 (사이즈마다 다름)", "cols")
            ex = [(text_of(r[code_h].inner) if code_h in r else "", size_num(text_of(r[sh].inner)) if sh in r else None,
                   text_of(r[sh].inner) if sh in r else "", all(not c.inner.strip() for c in r.values())) for r in t.rows]
            pairs, rest_e, rest_s = match_rows(ex, srows)
            for i, j, how in pairs:
                r, s = t.rows[i], srows[j]
                who = s.code or text_of(t.cell(r, code_h).inner)
                v = merge_size(t.cell(r, sh).inner, s, note, who)
                if v is not None:
                    t.cell(r, sh).set(v)
                    t.changed = True
                if s.code:
                    v = merge_code(t.cell(r, code_h).inner, s, how, note)
                    if v is not None:
                        c = t.cell(r, code_h)
                        c.set(v, "code")
                        t.changed = True
                if how == "elim" and not any("남은 줄끼리" in c for c in note.checks):
                    note.check(f"남은 줄끼리 짝지음: {s.label()}")
                if s.color and ch:
                    c = t.cell(r, ch)
                    if not c.inner.strip():
                        c.set(swatches(s.color))
                        t.changed = True
                        note.change(f"{ch} 넣음: {who} {s.color}", "cells")
                    elif not same(text_of(c.inner) or " ".join(re.findall(r'title="([^"]*)"', c.inner)), s.color):
                        note.check(f"{who} {ch} 다름 — 홈페이지: {s.color} (안 바꿈)")
                for f, lab in FIELDS:
                    if lab in t.heads and plan[f][2][j]:
                        c, val = t.cell(r, lab), plan[f][2][j]
                        cur = text_of(c.inner)
                        if not cur:
                            c.set(esc(val))
                            t.changed = True
                            note.n["cells"] += 1
                        elif not same(cur, val):
                            note.check(f"{who} {lab} 다름 — 카탈로그: {cur} / 홈페이지: {val} (안 바꿈)", "conflicts")
            for j in rest_s:
                s = srows[j]
                r = {h: Cell() for h in t.heads}
                r[sh] = Cell(size_text(s.size))
                r[code_h] = Cell(esc(s.code), "code")
                if s.color and ch:
                    r[ch] = Cell(swatches(s.color))
                for f, lab in FIELDS:
                    if lab in t.heads:
                        r[lab] = Cell(esc(plan[f][2][j]))
                t.rows.append(r)
                t.changed = True
                note.change(f"줄 더함: {s.label()}", "rows")
            for i in rest_e:
                lab = " · ".join(x for x in (ex[i][2], ex[i][0]) if x) or "빈 줄"
                note.check(f"카탈로그에만 있는 줄 (그대로 둠): {lab}", "extra_rows")
            multi = [ex[i][0] for i, _, _ in pairs if len(tokens(ex[i][0])) > 1]
            if multi:
                note.check("품번 칸에 품번이 여러 개 (그대로 둠): " + " / ".join(multi))
            if t.changed:
                extras = [h for h in t.heads if h in KV_ORDER]
                edits.append((t.block.s, t.block.e, write_table(t, code_h, extras, note)))
    elif srows and not t.ok:
        note.check("카드에 표가 없어 사이즈를 못 넣음")
    fill_kvs(html, art, plan, note, edits)
    return splice(html, edits) if edits else html


# ───────── 2단 카드 (숫돌·가위·도구) ─────────
G_ALIAS = {"칼날길이": "날길이", "날 길이": "날길이", "날 재질": "재질", "hrc": "경도", "HRC": "경도"}   # 같은 뜻의 다른 이름
G_SHORT = {"케이스 포함 크기": "케이스크기", "보관 가능 숫돌 크기": "숫돌크기", "손잡이 길이": "손잡이", "손잡이 가로": "손잡이폭",
           "슬라이스 사이즈": "슬라이스", "벌어지는 폭": "벌어짐", "손잡이너비": "손잡이폭", "칼날길이": "날길이", "날 길이": "날길이",
           "슬라이스 너비": "슬라이스폭", "슬라이스 폭": "슬라이스폭", "슬라이스 두께": "썰기두께", "내냉·내열온도": "내냉·내열",
           "브러쉬 길이": "솔 길이", "벌어지는 너비": "벌어짐", "케이스 높이": "케이스높이", "눈금자 길이": "눈금자",
           "채칼 가로폭": "채칼폭", "손잡이 높이": "손잡이높이", "사용 가능 숫돌 길이": "숫돌길이", "자바라 사이즈": "자바라"}
G_ORDER = ["사이즈", "색상", "재질", "무게", "방수", "경도", "날길이", "날두께", "두께", "너비", "전체길이", "연마면", "구성",
           "케이스", "용량", "내열", "전원", "크기", "원산지"]                    # 더하는 줄 순서 (그 밖은 가나다순으로 뒤에)
G_SKIP = ("사이즈", "상품번호", "메모")
G_LAB_W = 12.5          # 줄 이름 칸 11mm + 사이 2mm 중 1.5mm 까지 (한글 5자). 넘으면 값과 겹침
G_KV_W = 37.5           # 값 폭: 글 칸 51mm - 이름 11 - 사이 2 (조금 남김)
G_CODE_W = 36.0         # 모델 넘버 칸 폭 (51mm - '모델 넘버' 글자)


def g_eq(a, b, f=""):
    """같은 값인지: 띄어쓰기·'약'·대소문자 무시, 색은 이름으로 (검정 = 블랙)"""
    if f == "색상":
        names = lambda v: sorted(COLOR_ALIAS.get(x, x) for x in re.split(r"[/,\s]+", v) if x)  # noqa: E731
        return names(a) == names(b)
    norm = lambda v: re.sub(r"\s|약", "", str(v)).lower()  # noqa: E731
    return norm(a) == norm(b)


def g_merge(vals):
    """모델마다 값 → 한 줄: 다 같으면 그대로, 숫자면 '약' 평균, 아니면 ' / '"""
    vals = [v for v in vals if v]
    if len(set(vals)) <= 1:
        return vals[0] if vals else ""
    return approx(vals, None) or " / ".join(dict.fromkeys(vals))


def grid_fields(srows, top):
    """카드에 넣을 {항목: 값}. 사이즈는 글이 다르면 ' / ' 로 이음 (치수는 평균 내지 않음)"""
    def clean(d):
        out = {}
        for k, v in d.items():
            v = "" if isinstance(v, (list, dict)) else str(v).strip()
            if v and not k.startswith("_") and k not in G_SKIP:
                out.setdefault(G_ALIAS.get(k, k), v)
        return out
    base = clean(top)
    per = [clean(dict(s.extra, **({"색상": s.color} if s.color else {}))) for s in srows] or [{}]
    out = {"사이즈": " / ".join(dict.fromkeys(s.text for s in srows if s.text))}
    for f in dict.fromkeys([*base, *(k for p in per for k in p)]):
        out[f] = g_merge([p.get(f) or base.get(f, "") for p in per])
    return {f: v for f, v in out.items() if v}


def kv_now(html, sp):
    """스펙 줄 지금 값 (색 칸이면 색 이름)"""
    return text_of(inner(html, sp)) or " ".join(re.findall(r'title="([^"]*)"', inner(html, sp)))


def grid_table(html, t, srows, note, edits):
    """표가 있는 2단 카드: 품번이 맞는 줄의 빈 사이즈·색상 칸만 채움 (줄·칸은 안 더함). → 표가 맡은 항목"""
    heads = [text_of(inner(html, b)) for b in t.kids_of("b")]
    cells = t.kids_of("span")
    k = len(heads) or 1
    seen = set()
    for i in range(0, len(cells), k):
        r = dict(zip(heads, cells[i:i + k]))
        who = text_of(inner(html, r[CODE_H])) if CODE_H in r else ""
        hit = [s for s in srows if s.code and ncode(s.code) in code_keys(who)]
        seen.update(s.i for s in hit)
        for h, get in (("사이즈", lambda s: s.text), ("색상", lambda s: s.color)):
            vals = list(dict.fromkeys(v for v in map(get, hit) if v))
            if h not in r or not vals:
                continue
            cur = kv_now(html, r[h])
            if not cur and len(vals) == 1:
                edits.append((r[h].si, r[h].ei, swatches(vals[0]) if h == "색상" else esc(vals[0])))
                note.change(f"표 {h} 넣음: {who} {vals[0]}", "cells")
            elif cur and not any(g_eq(cur, v, h) for v in vals):
                note.check(f"{who} {h} 다름 — 카탈로그: {cur} / 홈페이지: {' / '.join(vals)} (안 바꿈)", "conflicts")
    rest = [s for s in srows if s.code and s.i not in seen]
    if rest and CODE_H in heads:
        # 홈페이지 옵션 품번이 표에 없으면 줄을 더한다 (사용자 요청: 옵션 품번은 다 넣기). 칸 수는 머리와 같게
        def cell(h, s):
            if h == CODE_H:
                return f'<span class="code">{esc(s.code)}</span>'
            if h == "사이즈":
                return f'<span class="">{esc(s.text)}</span>'
            if h == "색상" and s.color:
                return f'<span class="">{swatches(s.color)}</span>'
            return '<span class=""></span>'
        edits.append((t.ei, t.ei, "".join(cell(h, s) for s in rest for h in heads)))
        for s in rest:
            note.change(f"표에 줄 더함: {s.label()}", "rows")
    return {h for h in heads if h in ("사이즈", "색상")}


def apply_grid(html, srows, top, note):
    """2단 카드(article.g) 하나 → 새 html. 빈 줄은 채우고, 없는 항목은 줄을 더하고, 다른 값은 안 바꾸고 결과표에"""
    art = parse(html)
    edits = []
    fields = grid_fields(srows, top)
    t = (art.find("div", "t") or [None])[0]
    in_table = grid_table(html, t, srows, note, edits) if t is not None else set()

    # 모델 넘버 (표 없는 카드)
    codes = list(dict.fromkeys(s.code for s in srows if s.code))
    b = next((x for p in art.find("p", "model") for x in p.kids_of("b")), None)
    if b is not None and codes:
        cur, want = text_of(inner(html, b)), " / ".join(codes)
        if not cur:
            cls = b.attr("class") or ""
            if len(want) > 18 and "long" not in cls.split():        # build_catalog.py 와 같은 기준
                cls = (cls + " long").strip()
            edits.append((b.s, b.e, f'<b class="{cls}">{esc(want)}</b>'))
            note.change(f"모델 넘버 넣음: {want}", "gcode")
            if est_mm(want, True, 6.5 if "long" in cls.split() else 9) > G_CODE_W:
                note.check(f"모델 넘버 글자가 길어 끝이 '…' 로 잘려 보임: {want}", "cut")
        elif any(ncode(c) not in code_keys(cur) for c in codes):
            # 홈페이지에 옵션(사이즈·색)이 더 있으면 홈페이지 품번 목록으로 (사용자 요청: 옵션 품번은 다 넣기)
            if code_keys(cur) & {ncode(c) for c in codes}:
                cls = b.attr("class") or ""
                if len(want) > 18 and "long" not in cls.split():
                    cls = (cls + " long").strip()
                edits.append((b.s, b.e, f'<b class="{cls}">{esc(want)}</b>'))
                note.change(f"모델 넘버를 홈페이지 옵션대로: {cur} → {want}", "gcode")
                note.check(f"모델 넘버를 홈페이지 옵션대로 바꿈: {cur} → {want}")
                if est_mm(want, True, 6.5 if "long" in cls.split() else 9) > G_CODE_W:
                    note.check(f"모델 넘버 글자가 길어 끝이 '…' 로 잘려 보임: {want}", "cut")
            else:
                note.check(f"모델 넘버 다름 — 카탈로그: {cur} / 홈페이지: {want} (안 바꿈)", "conflicts")

    # 방수 표시 (오른쪽 위): 방수가 하나일 때만 ('#1000', 양면 '#1000/#6000')
    badge = (art.find("span", "badge") or [None])[0]
    grit = fields.get("방수", "")
    if badge is not None and re.fullmatch(r"#\d+(?:[/~]#\d+)?", grit):
        cur = text_of(inner(html, badge))
        if not cur:
            edits.append((badge.si, badge.ei, esc(grit)))
            note.change(f"방수 표시 넣음: {grit}", "gbadge")
        elif not g_eq(cur, grit):
            note.check(f"방수 표시 다름 — 카탈로그: {cur} / 홈페이지: {grit} (안 바꿈)", "conflicts")

    # 스펙 줄: 있는 줄은 빈 칸만 채움, 없는 항목은 마지막 줄 뒤에 더함
    kvs = []
    for p in art.find("p", "kv"):
        lb, sp = (p.kids_of("b") or [None])[0], (p.kids_of("span") or [None])[0]
        if lb is not None and sp is not None:
            kvs.append((text_of(inner(html, lb)), p, sp))
    long_v = lambda f, v: est_mm(v, pt=7.5) > G_KV_W and not (f == "색상" and 'class="sw"' in swatches(v))  # noqa: E731
    add = []
    for f, v in fields.items():
        if f in in_table:
            continue
        lab = G_SHORT.get(f, f)
        hit = next((x for x in kvs if x[0] in (f, lab)), None)
        if hit is None:
            add.append((lab, f, v))
            continue
        cur = kv_now(html, hit[2])
        if not cur:
            edits.append((hit[2].si, hit[2].ei, swatches(v) if f == "색상" else esc(v)))
            note.change(f"{hit[0]} 넣음: {v}", "gfill")
            if long_v(f, v):
                note.check(f"{hit[0]} 글자가 길어 카드에서 끝이 '…' 로 잘려 보임: {v}", "cut")
        elif not g_eq(cur, v, f):
            note.check(f"{hit[0]} 다름 — 카탈로그: {cur} / 홈페이지: {v} (안 바꿈)", "conflicts")
    if add:
        add.sort(key=lambda x: (G_ORDER.index(x[1]) if x[1] in G_ORDER else len(G_ORDER), x[0]))
        txt = (art.find("div", "txt") or [None])[0]
        after = next((e for e in (txt.kids if txt else []) if e.tag == "small" or e.has("cert")), None)
        pos = kvs[-1][1].e if kvs else (after.s if after else (txt.ei if txt else None))
        if pos is None:
            note.check("카드에 글 칸이 없어 스펙 줄을 못 넣음: " + ", ".join(lab for lab, _, _ in add))
            add = []
        for lab, f, v in add:
            note.change(f"{lab} 줄 더해 넣음: {v}", "gadd")
            if est_mm(lab, pt=7.5) > G_LAB_W:
                note.check(f"줄 이름 '{lab}' 이 길어 값과 겹쳐 보일 수 있음 (짧은 이름을 정해 주세요)", "longlab")
            if long_v(f, v):
                note.check(f"{lab} 글자가 길어 카드에서 끝이 '…' 로 잘려 보임: {v}", "cut")
        if add:
            edits.append((pos, pos, "".join(f'<p class="kv"><b>{esc(lab)}</b><span>{swatches(v) if f == "색상" else esc(v)}</span></p>'
                                            for lab, f, v in add)))
    return splice(html, edits) if edits else html


# ───────── 문서 훑기 ─────────
def card_name(html, art):
    h4 = (art.find("h4") or [None])[0]
    if h4 is None:
        return ""
    sp = h4.kids_of("span")
    return text_of(inner(html, sp[0] if sp else h4))


def index_cards(doc):
    """그룹 → [(쪽 i, 카드 시작, 끝, 붙은 번호, 종류)]"""
    out = {}
    for pi, p in enumerate(doc["pages"]):
        h = p.get("html") or ""
        if "<article" not in h:
            continue
        for a in parse(h).find("article"):
            kind = "w" if a.has("w") else ("g" if a.has("g") else None)
            pic = next((e for e in a.walk() if e.attr("data-slot")), None)
            m = re.fullmatch(r"images/(G\d+)(?:-(\d+))?", (pic.attr("data-slot") or "") if pic else "")
            if kind and m:
                out.setdefault(m.group(1), []).append((pi, a.s, a.e, m.group(2) or "", kind))
    return out


class Misc:
    """기타 나이프 표: 제품(이름 있는 줄 + 이어지는 이름 빈 줄)"""

    def __init__(self, doc):
        self.products, brand = [], ""
        for pi, p in enumerate(doc["pages"]):
            h = p.get("html") or ""
            if 'class="mr"' not in h:
                continue
            body = next((e for e in parse(h).find("div", "body")), None)
            for el in (body.kids if body else []):
                if el.tag != "div":
                    continue
                if el.has("mb"):
                    brand = text_of(re.sub(r"<small.*?</small>", "", inner(h, el), flags=re.S))
                    self.products.append(None)          # 브랜드가 바뀌면 제품도 끊김
                elif el.has("mr"):
                    sp = el.kids_of("span")
                    if len(sp) < 4:
                        continue
                    row = {"pi": pi, "s": el.s, "e": el.e, "start": h[el.s:el.si], "brand": brand,
                           "spans": [(x.s, x.si, x.ei, x.e) for x in sp[:4]],
                           "cells": [inner(h, x) for x in sp[:4]]}
                    if text_of(row["cells"][0]) or not self.products or self.products[-1] is None:
                        self.products.append([row])
                    else:
                        self.products[-1].append(row)
        self.products = [x for x in self.products if x]

    def find(self, brand, srows):
        """스펙 줄을 기타 나이프 제품에 나눈다 → ({제품 번호: [스펙 줄]}, [(못 정한 줄, 이유)], 어떻게 찾음)"""
        keys = [set().union(*(code_keys(text_of(r["cells"][3])) for r in prod)) for prod in self.products]
        cand = {s.i: [k for k, ks in enumerate(keys) if ncode(s.code) in ks] for s in srows if s.code}
        score = Counter(k for ks in cand.values() for k in ks)
        out, lost = {}, []
        for s in srows:
            ks = cand.get(s.i) or []
            if len(ks) > 1:                         # 같은 품번이 여러 제품에: 다른 품번도 많이 맞는 제품으로
                top = max(score[k] for k in ks)
                best = [k for k in ks if score[k] == top]
                if len(best) == 1:
                    ks = best
            if len(ks) == 1:
                out.setdefault(ks[0], []).append(s)
            elif ks:
                lost.append((s, "같은 품번이 기타 나이프 표의 여러 제품에 있음"))
        placed = {s.i for v in out.values() for s in v} | {s.i for s, _ in lost}
        rest = [s for s in srows if s.i not in placed]
        if out:
            if rest and len(out) == 1:              # 품번 없는 줄은 찾은 제품 하나에
                out[next(iter(out))].extend(rest)
            elif rest:
                lost += [(s, "어느 제품인지 몰라 안 넣음") for s in rest]
            for v in out.values():
                v.sort(key=lambda s: s.i)
            return out, lost, "품번"
        if lost:
            return {}, lost, ""
        want = sorted(s.size for s in srows)        # 품번이 하나도 안 맞으면: 같은 브랜드에서 사이즈 묶음이 똑같은 제품 하나
        b = re.sub(r"\(.*?\)", "", brand).strip()
        mine = [k for k, prod in enumerate(self.products) if re.sub(r"\(.*?\)", "", prod[0]["brand"]).strip() == b]
        same_size = [k for k in mine if want and sorted(size_num(text_of(r["cells"][2])) or 0 for r in self.products[k]) == want]
        if len(same_size) == 1:
            return {same_size[0]: list(srows)}, [], "브랜드·사이즈"
        why = (f"기타 나이프 표의 '{brand}' 제품과 품번·사이즈가 맞지 않아 못 정함" if mine else "카탈로그에서 못 찾음")
        return {}, [(s, why) for s in srows], ""


def apply_misc(doc, prod, srows, top, note, page_edits):
    ex = [(text_of(r["cells"][3]), size_num(text_of(r["cells"][2])), text_of(r["cells"][2]),
           not text_of(r["cells"][3]) and not text_of(r["cells"][2])) for r in prod]
    pairs, rest_e, rest_s = match_rows(ex, srows)
    for i, j, how in pairs:
        r, s = prod[i], srows[j]
        who = s.code or ex[i][0]
        v = merge_size(r["cells"][2], s, note, who)
        if v is not None:
            a, si, ei, e = r["spans"][2]
            page_edits.setdefault(r["pi"], []).append((si, ei, v))
        if s.code:
            v = merge_code(r["cells"][3], s, how, note)
            if v is not None:
                a, si, ei, e = r["spans"][3]
                page_edits.setdefault(r["pi"], []).append((si, ei, v))
        if how == "elim" and not any("남은 줄끼리" in c for c in note.checks):
            note.check(f"남은 줄끼리 짝지음: {s.label()}")
    multi = [ex[i][0] for i, _, _ in pairs if len(tokens(ex[i][0])) > 1]
    if multi:
        note.check("품번 칸에 품번이 여러 개 (그대로 둠): " + " / ".join(multi))
    if rest_s:
        last = prod[-1]
        h = doc["pages"][last["pi"]]["html"]
        sp = last["spans"]
        rows = []
        for j in sorted(rest_s, key=lambda j: (not srows[j].size, srows[j].size)):
            s = srows[j]
            rows.append(last["start"] + h[sp[0][0]:sp[0][1]] + "</span>" + h[sp[1][0]:sp[1][3]]
                        + h[sp[2][0]:sp[2][1]] + size_text(s.size) + "</span>"
                        + h[sp[3][0]:sp[3][1]] + esc(s.code) + "</span></div>")
            note.change(f"줄 더함: {s.label()}", "rows")
        page_edits.setdefault(last["pi"], []).append((last["e"], last["e"], "".join(rows)))
    for i in rest_e:
        lab = " · ".join(x for x in (ex[i][2], ex[i][0]) if x) or "빈 줄"
        note.check(f"카탈로그에만 있는 줄 (그대로 둠): {lab}", "extra_rows")
    if any(top.get(f) for f, _ in FIELDS) or any(s.extra or s.color for s in srows):
        note.check("기타 나이프 표에는 HRC·두께·재질·색 칸이 없어 안 넣음")


# ───────── 쪼갠 그룹(G####-n): 스펙 줄을 카드에 나누기 ─────────
def family(code):
    m = re.match(r"[A-Za-z]+", code)
    if m:
        return m.group(0).upper()
    m = re.match(r"(.+)[-.][^-.]*$", code)
    return m.group(1) if m else None


def split_rows(cards_rows, srows):
    """cards_rows = [[(품번 칸 글, 사이즈)]] → ([카드마다 스펙 줄], 못 나눈 스펙 줄, {스펙 줄 i: 품번 말고 무엇으로 정했는지})
    품번으로 모든 줄을 먼저 정한 뒤에야 날 길이·품번 앞부분으로 정한다 (남의 줄을 가로채지 않게)"""
    pool = [(ci, ri, code_keys(c), n) for ci, rows in enumerate(cards_rows) for ri, (c, n) in enumerate(rows)]
    used, out, guess = set(), [[] for _ in cards_rows], {}
    spec_codes = {ncode(s.code) for s in srows if s.code}
    free = lambda p: (p[0], p[1]) not in used  # noqa: E731

    def take(s, ci, ri=None, how=None):
        if ri is not None:
            used.add((ci, ri))
        out[ci].append(s)
        if how:
            guess[s.i] = how

    placed = lambda: {s.i for x in out for s in x}  # noqa: E731
    for exact in (True, False):                     # 1) 품번 + 사이즈 → 품번만
        for s in srows:
            if s.code and s.i not in placed():
                c = [p for p in pool if free(p) and ncode(s.code) in p[2] and (not exact or p[3] == s.size)]
                if c:
                    take(s, c[0][0], c[0][1])
    for s in srows:                                 # 2) 날 길이: 그 길이의 남은 줄이 딱 하나일 때만
        if s.i in placed() or not s.size:
            continue
        c = [p for p in pool if free(p) and p[3] == s.size and not (p[2] & spec_codes)]
        if len(c) != 1:     # 같은 품번이 두 번 적힌 줄 (그 품번 줄은 1)에서 이미 짝지어짐)
            c = [p for p in pool if free(p) and p[3] == s.size]
        if len(c) == 1:
            take(s, c[0][0], c[0][1], "날 길이로")
    lost = []
    for s in srows:                                 # 3) 품번 앞부분(계열)이 같은 카드가 하나뿐일 때
        if s.i in placed():
            continue
        fam = family(s.code) if s.code else None
        fams = [ci for ci, rows in enumerate(cards_rows)
                if fam and fam in {family(t) for c, _ in rows for t in tokens(c)}]
        if len(fams) == 1:
            take(s, fams[0], how="품번 앞부분이 같아서")
        else:
            lost.append(s)
    for x in out:
        x.sort(key=lambda s: s.i)
    return out, lost, guess


# ───────── 실행 ─────────
def run(doc, specs, review=None):
    """문서를 고친다 (doc 이 바뀜). → (notes, 요약 Counter)"""
    cards = index_cards(doc)
    misc = Misc(doc)
    notes, total = [], Counter()
    art_new = {}          # (쪽, 시작) → 새 카드 html
    page_edits = {}       # 기타 나이프 쪽 → [(시작, 끝, 글)]
    used_prod = {}        # 기타 나이프 제품 번호 → 그룹
    where = spec_review.cards({"pages": [{"html": p.get("html") or ""} for p in doc["pages"]]}) if review else {}
    for brand, gid, spec in specs:
        total["groups"] += 1
        tool = is_tool(brand)
        if not has_data(spec, tool):
            n = Note("", brand, "", gid, "nodata")
            n.check("홈페이지 정보 없음 (메모만 있음) — 건너뜀" + (f": {spec['메모']}" if spec.get("메모") else ""))
            notes.append(n)
            total["nodata"] += 1
            continue
        srows = [SRow(z, i) for i, z in enumerate(spec.get("사이즈") or []) if isinstance(z, (list, tuple)) and len(z) >= 2]
        srows = [x for x in srows if not x.empty()]        # 사이즈·품번이 모두 빈 줄(세트 등)은 표에 안 씀
        hits = cards.get(gid, [])
        first_name = ""
        if hits:
            pi, a, e, _, _ = hits[0]
            first_name = card_name(doc["pages"][pi]["html"][a:e], parse(doc["pages"][pi]["html"][a:e]))
        if review is not None:
            page, name = where.get(gid, ("", "(카탈로그에서 못 찾음)"))[:2]
            st, why = review.status(brand, spec, name, page)
            if st == "pending":
                n = Note(hits[0][0] + 1 if hits else "", brand, first_name, gid, "pending")
                n.check(f"검수표에 고칠 내용이 있어 건너뜀: {why}")
                notes.append(n)
                total["pending"] += 1
                continue
        else:
            st = "ok"
        if hits:
            split = any(x[3] for x in hits) and len(hits) > 1
            if split:
                rows_of = []
                for pi, a, e, suf, kind in hits:
                    h = doc["pages"][pi]["html"][a:e]
                    t = Table(h, parse(h))
                    if t.ok and t.col(CODE_H):
                        sh = t.col(SIZE_H)
                        rows_of.append([(text_of(r[t.col(CODE_H)].inner) if t.col(CODE_H) in r else "",
                                         size_num(text_of(r[sh].inner)) if sh and sh in r else None) for r in t.rows])
                    else:
                        rows_of.append([])
                parts, lost, guess = split_rows(rows_of, srows)
            else:
                parts, lost, guess = [srows] * len(hits), [], {}
            for k, (pi, a, e, suf, kind) in enumerate(hits):
                key = (pi, a)
                h = art_new.get(key, doc["pages"][pi]["html"][a:e])
                n = Note(pi + 1, brand, card_name(h, parse(h)), gid + (f"-{suf}" if suf else ""), "card")
                if st == "missing" and not tool:        # 숫돌·가위는 아직 검수표가 없음 → 고칠 내용 없음으로
                    n.check("검수표(스펙_검수.xlsx)에 없던 제품 — 그래도 넣음")
                if k == 0 and lost:
                    n.check("어느 카드에 넣을지 몰라 안 넣음: " + " / ".join(s.label() for s in lost), "unassigned")
                for s in parts[k]:
                    if s.i in guess:
                        n.check(f"품번이 카탈로그에 없어 {guess[s.i]} 이 카드에 넣음 (확인): {s.label()}")
                new = (apply_wide if kind == "w" else apply_grid)(h, parts[k], spec, n)
                if new != h:
                    art_new[key] = new
                    n.n["changed"] += 1
                    n.n["gchanged" if kind == "g" else "wchanged"] += 1
                notes.append(n)
            continue
        found, lost, how = ({}, [], "") if tool else misc.find(brand, srows)   # 기타 나이프 표는 칼만
        for k in [k for k in found if k in used_prod]:
            lost += [(s, f"기타 나이프 표의 같은 제품을 {used_prod[k]} 이 이미 씀") for s in found.pop(k)]
        if not found:
            n = Note("", brand, "", gid, "notfound")
            whys = list(dict.fromkeys(w for _, w in lost)) or ["카탈로그에서 못 찾음"]
            n.check(" / ".join(whys) + " — " + (" / ".join(s.label() for s in srows) or "(사이즈·품번 없음)"))
            notes.append(n)
            total["notfound"] += 1
            continue
        for m, (k, rows) in enumerate(sorted(found.items())):
            prod = misc.products[k]
            used_prod[k] = gid
            n = Note(prod[0]["pi"] + 1, brand, text_of(prod[0]["cells"][0]) + " (기타 나이프)", gid, "misc")
            if how != "품번":
                n.check(f"품번이 없어 {how}로 찾은 제품")
            if st == "missing":
                n.check("검수표(스펙_검수.xlsx)에 없던 제품 — 그래도 넣음")
            if m == 0 and lost:
                n.check("못 넣은 줄: " + " / ".join(f"{s.label()} ({w})" for s, w in lost), "unassigned")
            before = sum(len(v) for v in page_edits.values())
            apply_misc(doc, prod, rows, spec, n, page_edits)
            if sum(len(v) for v in page_edits.values()) != before:
                n.n["changed"] += 1
            notes.append(n)
    # 쪽에 반영 (카드 단위로만 바꾸므로 나머지 글자는 그대로)
    by_page = {}
    for (pi, a), new in art_new.items():
        by_page.setdefault(pi, []).append((a, None, new))
    for pi in set(by_page) | set(page_edits):
        h = doc["pages"][pi]["html"]
        edits = list(page_edits.get(pi, []))
        if pi in by_page:
            root = parse(h)
            ends = {x.s: x.e for x in root.find("article")}
            edits += [(a, ends[a], new) for a, _, new in by_page[pi]]
        doc["pages"][pi]["html"] = splice(h, edits)
    for n in notes:
        total.update({k: v for k, v in n.n.items()})
    total["cards_changed"] = sum(1 for n in notes if n.n["changed"])
    return notes, total


def write_report(path, notes):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "스펙 적용 결과"
    cols = [("쪽", 6), ("브랜드", 12), ("제품", 34), ("그룹", 10), ("바뀐 것", 60), ("확인할 것", 60)]
    ws.append([c for c, _ in cols])
    for i, (_, w) in enumerate(cols, 1):
        c = ws.cell(1, i)
        ws.column_dimensions[c.column_letter].width = w
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3C88")
    ws.freeze_panes = "A2"
    yellow = PatternFill("solid", fgColor="FFF2B3")
    order = {"card": 0, "misc": 0, "pending": 1, "notfound": 2, "nodata": 3}
    for n in sorted(notes, key=lambda n: (order.get(getattr(n, "kind", ""), 9), n.page if isinstance(n.page, int) else 99999, n.group)):
        ws.append([n.page, n.brand, n.name, n.group, "\n".join(n.changes) or ("(바뀐 것 없음)" if n.kind in ("card", "misc") else ""),
                   "\n".join(n.checks)])
        r = ws.max_row
        for c in range(1, len(cols) + 1):
            ws.cell(r, c).alignment = Alignment(wrap_text=True, vertical="top")
        if n.checks:
            ws.cell(r, 6).fill = yellow
    path = Path(path)
    for k in range(10):
        p = path if k == 0 else path.with_name(f"{path.stem}({k}){path.suffix}")
        try:
            wb.save(p)
            return p
        except PermissionError:      # 엑셀에서 열어 둔 경우
            continue
    raise PermissionError(f"{path.name} 을 저장할 수 없습니다 (엑셀에서 닫아 주세요)")


def save(path, doc):
    """원본을 .before-specs.json 으로 남기고, 임시 파일에 쓴 뒤 바꿔치기"""
    path = Path(path)
    bak = path.with_name(path.stem + ".before-specs.json")
    if bak.exists():          # 앞서 남긴 원본은 지우지 않음
        bak = path.with_name(f"{path.stem}.before-specs-{datetime.now():%Y%m%d-%H%M%S}.json")
    shutil.copyfile(path, bak)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return bak


def editor_running(port=8800):
    """편집기(editor_server.py)가 켜져 있는지 (link_photos.py 와 같게)"""
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


EDITOR_ON = "편집기가 켜져 있습니다. 편집기를 끄고(검은 창 닫기) 다시 실행해 주세요. (켜 둔 채면 편집기가 저장할 때 이 작업이 지워집니다)"


class Args(argparse.ArgumentParser):
    def error(self, message):   # 영어 오류 대신
        self.exit(2, "실행 방법이 맞지 않습니다. 예: python apply_specs.py --doc catalog.json   (설명: --help)\n")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = Args(description="홈페이지 스펙을 카탈로그 문서에 넣기")
    ap.add_argument("--doc", required=True, help="카탈로그 문서 (catalog.json)")
    ap.add_argument("--specs", default=str(BASE / "스펙"), help="스펙 폴더")
    ap.add_argument("--review", default=str(BASE / "스펙_검수.xlsx"), help="검수표")
    ap.add_argument("--no-review", action="store_true", help="검수표 없이 (고칠 내용 확인 안 함)")
    ap.add_argument("--dry-run", action="store_true", help="미리보기: 문서는 그대로, 결과표만")
    ap.add_argument("--brand", action="append", help="이 브랜드만 (여러 번 가능)")
    a = ap.parse_args(argv)

    doc_path = Path(a.doc)
    if not doc_path.is_file():
        print(f"문서를 찾을 수 없습니다: {doc_path}")
        return 1
    guard = not a.dry_run and doc_path.resolve() == (BASE / "catalog.json").resolve()
    if guard and editor_running():
        print(EDITOR_ON)
        return 1
    try:
        doc = catalog_doc.load_doc(doc_path)
    except Exception as e:  # noqa: BLE001
        print(f"문서를 읽지 못했습니다 ({doc_path.name}): {e}")
        return 1
    before = json.dumps(doc, ensure_ascii=False)
    specs = load_specs(a.specs, a.brand)
    if not specs:
        print("스펙 파일에서 제품을 못 찾았습니다.")
        return 1
    review = None
    if not a.no_review:
        try:
            review = Review(a.review)
        except Exception as e:  # noqa: BLE001
            print(f"검수표를 못 읽었습니다 ({a.review}): {e}\n검수표 없이 하려면 --no-review 를 붙이세요.")
            return 2
    shape = [(p.get("id"), (p.get("html") or "").count("<article"), (p.get("html") or "").count('class="mr"')) for p in doc["pages"]]
    notes, t = run(doc, specs, review)
    problems = catalog_doc.validate_doc(doc)
    for (pid, arts, mrs), p in zip(shape, doc["pages"]):     # 카드 수는 그대로, 기타 나이프 줄은 같거나 많게
        h = p.get("html") or ""
        if p.get("id") != pid or h.count("<article") != arts or h.count('class="mr"') < mrs:
            problems.append(f"{pid}: 카드·줄 수가 이상합니다")
    if problems or len(doc["pages"]) != len(shape):
        print("문서 검사에서 문제가 나와 저장하지 않았습니다: " + " / ".join(problems[:5]))
        return 3
    report = write_report(doc_path.parent / REPORT_NAME, notes)
    changed = json.dumps(doc, ensure_ascii=False) != before
    print("스펙 적용" + (" 미리보기 (문서는 안 바뀜)" if a.dry_run else ""))
    print(f"- 홈페이지 스펙 제품: {t['groups']}개 ({len({b for b, _, _ in specs})}개 브랜드)")
    print(f"- 바뀐 제품 칸: {t['cards_changed']}개")
    print(f"- 스펙 줄 채움(HRC·두께·재질): {t['kv']}칸 (글자가 길어 끝이 잘려 보이는 것 {t['cut']}칸)")
    print(f"- 표에 더한 줄: {t['rows']}줄, 더한 칸(두께 등): {t['cols']}개, 빈 칸 채움: {t['cells']}칸")
    print(f"- 품번 고침: {t['codes']}개, 날 길이 고침: {t['sizes']}개, 표에서 글자가 잘려 보일 칸: {t['tcut']}칸")
    print(f"- 숫돌·가위 등 2단 카드: 바뀐 카드 {t['gchanged']}개, 빈 줄 채움 {t['gfill']}칸, 줄 더함 {t['gadd']}줄, "
          f"모델 넘버 넣음 {t['gcode']}개, 방수 표시 넣음 {t['gbadge']}개, 줄 이름이 길어 겹칠 수 있는 것 {t['longlab']}개")
    print(f"- 값이 달라 안 바꾼 것: {t['conflicts']}개, 카탈로그에만 있는 줄: {t['extra_rows']}줄, 카드를 못 정한 줄: {t['unassigned']}개")
    print(f"- 건너뜀: 검수표에 고칠 내용 {t['pending']}개, 홈페이지 정보 없음 {t['nodata']}개")
    print(f"- 카탈로그에서 못 찾음: {t['notfound']}개")
    if a.dry_run:
        print(f"결과표: {report}")
        return 0
    if changed and guard and editor_running():      # 도는 사이에 편집기가 켜진 경우
        print("작업 중에 편집기가 켜져서 저장하지 않았습니다. " + EDITOR_ON)
        return 1
    if changed:
        bak = save(doc_path, doc)
        print(f"저장했습니다: {doc_path.name} (원래 것: {bak.name})")
    else:
        print("바뀐 것이 없어 문서는 그대로 둡니다.")
    print(f"결과표: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
