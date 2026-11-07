"""스펙/*.json (홈페이지에서 읽은 스펙) + catalog.json (지금 카탈로그) → 스펙_검수.xlsx

    python spec_review.py
"""
import json
import re
import sys
from html import unescape
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(__file__).resolve().parent
COLS = [("쪽", 6), ("브랜드", 12), ("제품 (카탈로그 이름)", 30), ("HRC", 9), ("두께", 10), ("날 재질", 24), ("핸들 재질", 24),
        ("사이즈 · 품번 (홈페이지)", 34), ("지금 카탈로그 표", 30), ("원산지", 8), ("메모", 44), ("홈페이지", 12), ("확인 (O 또는 고칠 내용)", 26)]
YELLOW = PatternFill("solid", fgColor="FFF2B3")
HEAD = PatternFill("solid", fgColor="1F3C88")


def text(h):
    return unescape(re.sub(r"<[^>]+>", " ", h)).split() and " ".join(unescape(re.sub(r"<[^>]+>", " ", h)).split())


def extra(v):
    """사이즈 줄의 세 번째 값: 두께 글자 또는 {항목: 값}"""
    if isinstance(v, dict):
        return "(" + ", ".join(f"{k} {x}" for k, x in v.items()) + ")"
    return f"(두께 {v})"


def cards(doc):
    """그룹ID → (쪽 번호, 카탈로그 이름, 지금 표 줄들)"""
    out = {}
    for n, p in enumerate(doc["pages"], 1):
        for m in re.finditer(r'<article class="[wg]".*?</article>', p["html"], re.S):
            a = m.group(0)
            gid = re.search(r'data-slot="images/(G[\w-]+)"', a)
            if not gid or gid.group(1) in out:
                continue
            name = re.search(r"<h4><span>(.*?)</span>", a) or re.search(r'<p class="top">(.*?)</p>', a)
            t = re.search(r'<div class="t"[^>]*>(.*?)</div>', a, re.S)
            t = t.group(1) if t else ""
            k = max(1, len(re.findall(r"<b>", t)))      # 표 칸 수 = 머리 칸 수
            spans = re.findall(r"<span[^>]*>(.*?)</span>", t)
            rows = [" ".join(x for x in (text(s) for s in spans[i:i + k]) if x) for i in range(0, len(spans), k)]
            out[gid.group(1)] = (n, text(name.group(1)) if name else "", " / ".join(r for r in rows if r))
    return out


def main():
    doc = json.load(open(BASE / "catalog.json", encoding="utf-8"))
    where = cards(doc)
    wb = Workbook()
    ws = wb.active
    ws.title = "스펙 검수"
    ws.append([c for c, _ in COLS])
    for i, (_, w) in enumerate(COLS, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
        ws.cell(1, i).font = Font(bold=True, color="FFFFFF")
        ws.cell(1, i).fill = HEAD
    ws.freeze_panes = "D2"
    n = 0
    items = [(f.stem, gid, s) for f in sorted((BASE / "스펙").glob("*.json"))
             for gid, s in json.load(open(f, encoding="utf-8")).items() if not gid.startswith("_")]
    items.sort(key=lambda x: (where.get(x[1], (99999,))[0], x[1]))
    for brand, gid, s in items:
            page, name, now = where.get(gid, ("", "(카탈로그에서 못 찾음)", ""))
            sizes = " / ".join(" ".join(x for x in (z[0], (f"{z[1]}mm" if isinstance(z[1], (int, float)) else str(z[1])) if z[1] else "", extra(z[2]) if len(z) > 2 else "") if x)
                               for z in s.get("사이즈", []))
            nos = s.get("상품번호", [])
            ws.append([page, brand, name, s.get("hrc", ""), s.get("두께", ""), s.get("날 재질", ""), s.get("핸들 재질", ""),
                       sizes, now, s.get("원산지", ""), s.get("메모", ""), "열기" if nos else "", ""])
            r = ws.max_row
            if nos:
                ws.cell(r, 12).hyperlink = f"https://sindoltd.com/product/detail.html?product_no={nos[0]}"
                ws.cell(r, 12).font = Font(color="0563C1", underline="single")
            if s.get("메모"):
                ws.cell(r, 11).fill = YELLOW
            if len(s.get("사이즈", [])) != len([x for x in now.split(" / ") if x]):
                ws.cell(r, 8).fill = YELLOW
            for c in range(1, len(COLS) + 1):
                ws.cell(r, c).alignment = Alignment(wrap_text=True, vertical="top")
            n += 1
    howto = wb.create_sheet("보는 법")
    for line in ["스펙 검수 목록 — 보는 법", "",
                 "1. 홈페이지 상품 상세 그림의 스펙 상자를 읽어서 정리한 것입니다. 가격은 넣지 않습니다.",
                 "2. 노란 칸만 보시면 됩니다: '사이즈 · 품번' 이 노란 것은 지금 카탈로그 표와 줄 수가 다른 것(홈페이지 기준으로 늘어남),",
                 "   '메모' 가 노란 것은 따로 알려 드릴 점이 있는 것입니다.",
                 "3. 맞으면 마지막 칸에 O, 틀리면 고칠 내용을 적어 주세요. 비워 두면 맞는 것으로 보고 카탈로그에 넣습니다.",
                 "4. '홈페이지' 칸의 '열기' 를 누르면 그 상품 페이지가 열립니다."]:
        howto.append([line])
    howto.column_dimensions["A"].width = 120
    out = BASE / "스펙_검수.xlsx"
    wb.save(out)
    print(f"{out.name}: {n}개 제품")


if __name__ == "__main__":
    main()
