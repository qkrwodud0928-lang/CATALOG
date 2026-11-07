"""신도 디지털 카탈로그 생성기.

사용법:  python build_catalog.py          → catalog.html
         python build_catalog.py --pdf    → catalog.html + catalog.pdf (크롬/엣지 필요)
         python build_catalog.py --editor → + 편집기 문서 catalog.json (이미 있으면 catalog.new.json, --force 로 덮어쓰기)

입력:    신도_카탈로그_데이터.xlsx
           '마스터' 시트   제품 (카탈로그 수록 Y/N, 스펙, 카탈로그 제품명)
           '브랜드' 시트   브랜드별 설정 (수록 N = 브랜드 통째로 제외, 스토리 페이지 N = 스토리 칸 없음,
                           한 줄 소개, 브랜드 스토리)
         images/그룹ID.jpg 또는 images/품번.jpg    제품 사진
         brands/브랜드명.jpg                        브랜드 스토리 칸에 넣을 사진
         logos/브랜드명.png                         브랜드 로고 (없으면 글자로 표시)
         flags/국가명.png                           국기 (없으면 글자로 표시)
         front/01.png, 02.png …                     표지·회사소개 등 앞 페이지 (Canva에서 내보낸 이미지)

구성:    대분류(용도) → 칼: 브랜드 → 시리즈 / 그 외: 종류 → 브랜드
"""
import html
import math
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from itertools import groupby
from pathlib import Path
from urllib.parse import quote

import openpyxl

BASE = Path(__file__).parent
XLSX = BASE / "신도_카탈로그_데이터.xlsx"
OUT = BASE / "catalog.html"

# ───────── 설정 ─────────
SHOW_ORIGINAL_NAME = True  # 회색 원본 상품명(입력 참고용). 완성본에선 False
SHOW_EMPTY_SPECS = True    # 아직 안 채운 스펙도 빈 칸으로 보여줌(틀 확인용). 완성본에선 False
NEW_PAGE_MIN_CARDS = 4     # 브랜드·시리즈·종류의 제품이 이 개수 이상이면 새 페이지에서 시작
NEW_PAGE_FILL = (1 / 3, 1 / 2)  # 단, 앞 페이지가 이만큼도 안 찼으면 이어서 놓는다 (중분류, 소분류)
FIRST_BRANDS = []                     # 맨 앞에 둘 브랜드 (비우면 전부 가나다순)
LAST_BRANDS = ["미분류(브랜드 없음)"]  # 맨 뒤에 둘 브랜드
VOLUME = "Volume_7"

# 대분류(용도): (이름, 영문, 엑셀 '제품군' 값, 레이아웃)  wide=칼처럼 긴 제품 1단 / grid=2단
CHAPTERS = [
    ("칼", "Knives", ["나이프"], "wide"),
    ("연마 및 보관", "Sharpening & Storage", ["연마·칼갈이", "칼 보관·케이스"], "grid"),
    ("가위", "Scissors", ["가위"], "grid"),
    ("조리도구", "Kitchen Tools",
     ["조리도구", "도마", "냄비·팬·주방기물", "주방기기", "안전·위생용품", "청소·위생", "미분류"], "grid"),
]
# 칼 제품(그룹)이 이 개수 이하인 브랜드는 브랜드 페이지 없이 칼 챕터 맨 뒤 '기타 나이프' 표에 한 줄씩
SMALL_BRAND_MAX = 5
SPLIT_MIXED_GROUPS = True  # 칼: 한 그룹에 같은 사이즈가 겹치면 품번 계열별로 제품을 나눈다
MISC = "기타 나이프"
CH_COLORS = ["#1f3c88", "#8c1d2f", "#2f6f4f", "#b8741a", "#5b3f8c", "#1f7a8c", "#8c5a1f", "#4a5568", "#a23b72"]

SECTION_EN = {
    "주방가위": "Kitchen Scissors", "가위(기타)": "Scissors", "재단·사무가위": "Tailor & Office Scissors",
    "게가위": "Crab Scissors", "분리형 주방가위": "Detachable Scissors",
    "숫돌": "Whetstones", "야스리·연마봉": "Honing Steels", "칼갈이·샤프너": "Knife Sharpeners",
    "다이아몬드 샤프너": "Diamond Sharpeners", "숫돌 받침대": "Stone Holders", "연마(기타)": "Sharpening",
    "전동 연마기": "Electric Sharpeners", "세라믹 샤프너": "Ceramic Sharpeners", "숫돌 평면잡이": "Flattening Stones",
    "칼가방": "Knife Bags", "나이프 가드·패드": "Blade Guards", "마그네틱 거치": "Magnetic Holders",
    "칼블럭·칼꽂이": "Knife Blocks", "칼집·사야": "Saya", "칼케이스": "Knife Cases", "칼 보관(기타)": "Storage",
    "도마(기타)": "Cutting Boards", "항균·시트 도마": "Antibacterial Boards", "도마 거치대·랙": "Board Racks",
    "나무 도마": "Wooden Boards", "도마 세트": "Board Sets", "PE 도마": "PE Boards", "TPU 도마": "TPU Boards",
    "조리도구(기타)": "Kitchen Tools", "채칼·슬라이서·강판": "Slicers & Graters",
    "뒤집개·스파츄라·헤라": "Turners & Spatulas", "온도계·저울·계측": "Thermometers & Scales",
    "제과·제빵 도구": "Baking Tools", "커트러리·서빙": "Cutlery & Serving", "밧드·볼·채반·망": "Pans, Bowls & Strainers",
    "집게·핀셋": "Tongs & Tweezers", "뷔페·서빙 용품": "Buffet & Serving", "국자·스푼·건지개": "Ladles & Spoons",
    "스쿠프·틀": "Scoops & Molds", "오프너·따개": "Openers", "보관·용기": "Containers",
    "랙·거치대·홀더": "Racks & Holders", "초밥·장식 용품": "Sushi & Garnish", "고기망치·연육": "Meat Tenderizers",
    "밀·그라인더": "Mills & Grinders", "생선 손질 도구": "Fish Tools", "부품·소모품": "Parts",
    "바베큐·꼬치": "BBQ & Skewers", "조각도·데코": "Carving & Deco", "거품기": "Whisks",
    "냄비·팬·포트": "Pots & Pans", "주방기기": "Kitchen Equipment",
    "안전장갑": "Safety Gloves", "앞치마": "Aprons", "위생 브러시": "Hygiene Brushes",
    "토시·보호대": "Sleeves & Guards", "소독기·살균": "Sterilizers", "청소·브러시": "Cleaning Brushes",
    "바·음료 용품": "Bar & Beverage", "받침·매트": "Trivets & Mats",
}
COLORS = {
    "블랙": "#111", "화이트": "#fff", "레드": "#d0342c", "블루": "#1f5fbf", "그린": "#1e8e4e", "옐로우": "#f2c200",
    "오렌지": "#f08a00", "그레이": "#8a8d91", "실버": "#c0c4c8", "골드": "#c9a227", "브라운": "#7a4a21",
    "핑크": "#f29bb7", "퍼플": "#7a3fa0", "아이보리": "#f3ead3", "네이비": "#1f2f5c", "우드": "#b98a52",
}

SPEC = "스펙:"
CERT, GRIT, FEATURE = SPEC + "인증", SPEC + "방수", "특징(강재·마감·핸들)"
TEMPLATE = {True: ["HRC", "두께", "날 재질", "핸들 재질"], False: ["재질", "무게"]}  # 빈 칸으로라도 보여줄 항목 (wide/grid)
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".svg")

# 치수(mm). CSS의 값과 짝을 이룸 — 바꾸면 CSS도 같이 바꿀 것 (표 줄 6mm, 칼 제품명 8mm+1mm, 스펙 줄 5.5mm)
BODY_H = 251                                                  # 297 - (위 8 + 머리 24 + 바닥글 8 + 아래 6)
BAND1_H, BAND2_H = 12, 8                                      # 띠 높이(아래 여백 포함)
W_PAD, W_TITLE, W_PIC, W_ROW, W_KV = 4.5, 9, 30, 6, 5.5         # 1단(칼) 카드 (W_PAD = 위아래 여백 + 아래 선)
G_TOP, G_PIC, G_TITLE, G_MODEL, G_KV, G_ORIG, G_PAD, G_ROW = 6, 36, 10, 6, 5, 4, 3, 6  # 2단 카드
# 칼 브랜드 스토리 칸: 제품이 NEW_PAGE_MIN_CARDS개 이상인 브랜드는 한 쪽 전체, 적은 브랜드는 위쪽 일부(아래에 제품이 이어짐)
STORY_FULL_H, STORY_HALF_H = BODY_H, 100
STORY_CHARS = {True: 750, False: 280}  # 칸에 들어가는 글자 수(대략). 넘으면 빌드할 때 알려줌


def esc(v):
    return html.escape(str(v).strip()) if v not in (None, "") else ""


# 칼 종류 → 카탈로그에 적을 이름. 상품명에 든 말과 브랜드 국가로 고른다 (Canva에서 쓰신 말투 기준)
ADJ = {"칼라", "다마스커스", "해머드", "혼야키", "혼야끼", "미즈혼야키", "경면", "하이브리드", "슈프림", "클래식", "프리미엄", "단조"}


def type_name(t, text, nation):
    jp = nation == "일본"

    def has(*ws):
        return any(w in text for w in ws)

    if t == "규토·셰프나이프":
        return "우도" if jp else ("식도" if nation == "한국" else "셰프 나이프")
    if t == "사시미(야나기바)":
        return "사시미"
    if t == "페티·과도":
        return "페어링 나이프" if has("페어링") else ("페티 나이프" if jp else "과도")
    if t == "뼈칼·보닝·창칼":
        for w, n in (("폴트리", "폴트리 나이프"), ("보닝", "보닝 나이프"), ("스티킹", "스티킹 나이프"), ("창칼", "창칼")):
            if has(w):
                return n
        return "창칼" if jp else "뼈칼"
    if t == "슬라이서·카빙":
        for w, n in (("살몬", "살몬 나이프"), ("연어", "살몬 나이프"), ("햄", "햄 슬라이서"), ("카빙", "카빙 나이프"),
                     ("슬라이싱", "슬라이싱 나이프"), ("스지히끼", "스지히끼")):
            if has(w):
                return n
        return "스지히끼" if jp else "슬라이싱 나이프"
    if t == "테이블·치즈 나이프":
        for w, n in (("스테이크", "스테이크 나이프"), ("치즈", "치즈 나이프"), ("토마토", "토마토 나이프"), ("버터", "버터 나이프")):
            if has(w):
                return n
        return "테이블 나이프"
    if t == "우스바·나키리":
        return "나키리 나이프" if has("나키리") else ("우수바" if has("우수바", "우스바") else "야채칼")
    if t == "정육·클리버":
        for w, n in (("도끼", "도끼칼"), ("클리버", "클리버 나이프"), ("클레버", "클리버 나이프"), ("부처", "부처 나이프"),
                     ("슬러터", "슬러터 나이프"), ("스티킹", "스티킹 나이프"), ("스키닝", "스키닝 나이프"), ("시메터", "시메터 나이프"),
                     ("갈비", "갈비칼"), ("냉장", "냉장칼")):
            if has(w):
                return n
        return "정육칼"
    if t == "분카·키리츠케":
        return "키리츠케" if has("키리츠케") else "분카 나이프"
    if t == "캠핑·아웃도어 나이프":
        return "낚시칼" if has("낚시") else "캠핑 나이프"
    if t == "굴칼·조개칼":
        return "조개칼" if has("조개") else "굴칼"
    return {"산토쿠": "산도쿠 나이프", "데바": "데바", "빵칼": "빵칼", "중식도": "중국칼", "필렛": "필레팅 나이프",
            "나이프 세트": "나이프 세트", "조각도": "조각도", "냉동칼": "냉동칼", "장어칼": "장어칼", "키즈 나이프": "키즈 나이프"}.get(t)


def auto_name(g, wide):
    """카탈로그 제품명이 비어 있을 때의 이름. (앞머리, 이름) — 앞머리는 시리즈(없으면 브랜드)."""
    parts = [x.strip(" /") for x in re.sub(r"\s*\[[^\]]*\]\s*$", "", g["그룹명"] or "").split(" / ")]
    parts = [x for x in parts if re.search(r"\w", x)]  # 빈 조각, '/' 찌꺼기 제거
    series, typ = g["라인/시리즈"], g["세부유형"]
    brand = "" if g["브랜드"] in LAST_BRANDS else g["브랜드"]
    rest = [x for x in parts if x != series and x != typ]
    name = None
    if wide:
        tn = type_name(typ, " ".join(parts) + " " + str(g["상품명(원본)"] or ""), g["브랜드 국가"])
        if tn:
            front = [x for x in rest if x in ADJ]
            back = [x for x in rest if x not in ADJ]
            back = [x for x in back if not any(w and w in tn for w in re.split(r"[\s·]+", x))]  # '살몬 나이프 (살몬)' 방지
            name = " ".join(front + [tn])
            if back:
                feat = " ".join(back)
                name += " " + feat if "(" in feat else f" ({feat})"
    if name is None:
        name = " ".join(rest) or (typ or "")
    return esc(series or brand), esc(name)


def index(folder):
    d = BASE / folder
    if not d.is_dir():
        return {}
    return {p.stem.lower(): quote(f"{folder}/{p.name}") for p in sorted(d.iterdir()) if p.suffix.lower() in IMG_EXTS}


IMAGES, LOGOS, FLAGS, STORIES = index("images"), index("logos"), index("flags"), index("brands")


def pick(idx, *names):
    keys = (re.sub(r'[\\/:*?"<>|]', "_", str(n)).strip().lower() for n in names if n)
    return next((idx[k] for k in keys if k in idx), None)


def code_of(r):
    return esc(r["모델코드(추출)"] or r["자체상품코드(원본)"])


def size_text(v):
    v = esc(v)
    return f"{v} mm" if re.fullmatch(r"[\d./ ]+", v) else v


def swatches(v):
    names = [n.strip() for n in esc(v).split("/") if n.strip()]
    if not names or not all(n in COLORS for n in names):
        return esc(v)
    return "".join(f'<i class="sw" style="background:{COLORS[n]}" title="{n}"></i>' for n in names)


# ───────── 데이터 ─────────
CODE = r"([A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9])"


def expand(first, c):
    """줄여 쓴 품번을 풀어 쓴다: 'SBK-95,105'의 105 → SBK-105, '5301T50, T51'의 T51 → 5301T51."""
    if len(c) >= len(first):
        return c
    if c.isdigit():
        return re.sub(r"\d+$", "", first) + c
    return first[:-len(c)] + c if len(c) <= 3 and first[-len(c)] == c[0] else c


IN_PAREN = r"\(\s*([A-Za-z0-9][A-Za-z0-9 .\-/]*?)\s*\)"  # 괄호 안 품번: (87404 21), (S-210.), (128-5637/7212UG)
INCH = r'(\d+(?:\.\d+)?)\s*(?:인치|"|”|″)'


def split_options(r, note):
    """사이즈가 여러 개 적힌 행(180/210/240)을 사이즈별 행으로 나눈다.

    품번은 근거가 있을 때만 짝짓는다: ① 상품명에 '품번(270mm)'·'270mm(품번)'·'8인치(품번)'·'품번_270mm'처럼
    적혀 있거나 ② 품번 개수가 사이즈 개수와 같을 때(엑셀 '모델코드(추출)'에 쉼표로 사이즈 순서대로 적으면 됨).
    근거가 없으면 첫 사이즈에만 넣고 나머지는 비워 둔다.
    """
    sizes = [s.strip() for s in str(r["사이즈(mm)"] or "").split("/") if s.strip()]
    if len(sizes) < 2 or not all(s.isdigit() for s in sizes):
        return [r]
    name = str(r["상품명(원본)"] or "")
    # 같은 제품의 인치 환산값이 같이 들어간 경우(10" 260mm → 254/260)는 mm로 적힌 쪽만 남긴다
    inch = [float(x) * 25.4 for x in re.findall(INCH, name)]

    def from_inch(s):
        return any(abs(int(s) - v) <= 1 for v in inch)

    sizes = [s for s in sizes
             if not (from_inch(s) and any(not from_inch(o) and abs(int(o) - int(s)) <= 13 for o in sizes))]
    merged = []
    for s in sizes:  # 178/180처럼 3mm 이내도 같은 사이즈로 본다(5mm 단위 쪽을 남김)
        if merged and abs(int(s) - int(merged[-1])) <= 3:
            merged[-1] = s if int(s) % 5 == 0 else merged[-1]
        else:
            merged.append(s)
    sizes = merged
    if len(sizes) < 2:
        return [dict(r, **{"사이즈(mm)": sizes[0]})]

    codes = [c.strip() for c in str(r["모델코드(추출)"] or r["자체상품코드(원본)"] or "").split(",") if c.strip()]
    codes = [c for c in codes if not re.fullmatch(r"\d{1,2}|\d+\s*m+|.*\dmm.*", c)]  # 10, 150m, MV240mm 같은 찌꺼기
    pairs = {}
    for c, s in re.findall(CODE + r"\s*\(\s*(\d{2,4})\s*mm\s*\)", name):   # 품번(270mm)
        pairs[s] = c
    for s, c in re.findall(r"(\d{2,4})\s*mm\s*" + IN_PAREN, name):          # 270mm(품번)
        pairs[s] = c
    for c, s in re.findall(r"([A-Za-z0-9.\-]+)_(\d{2,4})\s*mm", name):      # 품번_270mm
        pairs[s] = c
    for x, c in re.findall(INCH + r"\s*" + IN_PAREN, name):                 # 8인치(품번)
        s = next((s for s in sizes if abs(int(s) - float(x) * 25.4) <= 1), None)
        if s:
            pairs[s] = c
    pairs = {s: c for s, c in pairs.items() if re.search(r"\d", c) and not re.search(r"\d\s*(?:mm|cm)$", c)}
    if all(s in pairs for s in sizes):
        mapped = [pairs[s] for s in sizes]
    elif len(codes) == len(sizes):
        mapped = [codes[0]] + [expand(codes[0], c) for c in codes[1:]]
        if mapped != codes:
            note["풀어 쓴 품번"].append(f'{r["그룹ID"]} {", ".join(mapped)}')
    else:
        mapped = [pairs.get(s, "") for s in sizes]
        if not any(mapped):
            mapped[0] = codes[0] if codes else ""
        note["품번 빈칸"].append(r["그룹ID"])
    return [dict(r, **{"사이즈(mm)": s, "모델코드(추출)": c, "자체상품코드(원본)": None, "옵션묶음": None})
            for s, c in zip(sizes, mapped)]


def family(r):
    """품번 계열: TU-9003 → TU, 5.5203.18 → 5.5203, 129-40500 → 129, 01004 → 숫자(가까운 번호끼리 같은 계열)."""
    c = str(r["모델코드(추출)"] or r["자체상품코드(원본)"] or "").split(",")[0].strip()
    if not c:
        return None
    m = re.match(r"[A-Za-z]+", c) or re.match(r"\d\.\d{4}", c)
    if m:
        return m.group(0).upper()
    if c.isdigit():
        return int(c)
    return c.rsplit("-", 1)[0] if "-" in c else c


def split_group(items):
    """한 그룹에 같은 사이즈가 두 번 나오면 서로 다른 제품이 묶인 것(각마 우도 TU-/OVD- 등) → 품번 계열별로 나눈다.

    [(계열 이름, 품목들)]을 돌려준다. 나눌 근거(서로 다른 품번 계열)가 없으면 그대로 한 덩어리.
    """
    sizes = [str(r["사이즈(mm)"]) for r in items if r["사이즈(mm)"]]
    units = [list(u) for _, u in groupby(items, key=lambda r: r["No"])]  # 엑셀 한 줄에서 나온 사이즈들은 늘 같이
    if not SPLIT_MIXED_GROUPS or len(sizes) == len(set(sizes)) or len({family(u[0]) for u in units} - {None}) < 2:
        return [("", items)]
    subs = []
    for unit in units:
        key, usz = family(unit[0]), {str(r["사이즈(mm)"]) for r in unit}

        def fits(s):
            if s["sizes"] & usz:
                return False
            if key is None:  # 품번 없는 줄은 바로 앞 제품에 붙인다
                return s is subs[-1]
            if isinstance(key, int):
                return isinstance(s["key"], int) and abs(key - s["key"]) <= 9
            return key == s["key"]

        sub = next((s for s in subs if fits(s)), None)
        if sub is None:
            sub = dict(key=key, first=key, sizes=set(), items=[])
            subs.append(sub)
        sub["sizes"] |= usz
        sub["items"] += unit
        if isinstance(key, int):
            sub["key"] = key
    if len(subs) < 2:
        return [("", items)]
    label = lambda s: "" if s["first"] is None else code_of(s["items"][0]).split(",")[0] if isinstance(s["first"], int) \
        else str(s["first"])
    return [(label(s), s["items"]) for s in subs]


NOTE = {"풀어 쓴 품번": [], "품번 빈칸": []}  # 빌드 끝에 알려줄 것
KNIFE_TYPES = []  # 칼 종류 순서 (색인 순서). build() 가 채운다


def load_rows():
    wb = openpyxl.load_workbook(XLSX, read_only=True)
    it = wb["마스터"].iter_rows(values_only=True)
    header = list(next(it))
    rows = [dict(zip(header, r)) for r in it if r[0] is not None]
    specs = [h for h in header if h and str(h).startswith(SPEC)]
    # 수록 Y가 하나라도 있으면 Y만, 없으면 '판매중·진열' 전체. N은 항상 제외
    picked = [r for r in rows if r["카탈로그 수록"] == "Y"]
    if not picked:
        picked = [r for r in rows if r["상태"] == "판매중·진열" and r["카탈로그 수록"] != "N"]
    brands = {}  # '브랜드' 시트: 브랜드명 → 그 행. 시트에 없는 브랜드는 그냥 수록
    if "브랜드" in wb.sheetnames:
        it = wb["브랜드"].iter_rows(values_only=True)
        header = list(next(it))
        brands = {r[0]: dict(zip(header, r)) for r in it if r and r[0]}
    picked = [r for r in picked if brands.get(r["브랜드"], {}).get("수록") != "N"]
    for v in NOTE.values():
        v.clear()
    picked = [x for r in picked for x in split_options(r, NOTE)]
    return rows, picked, specs, brands


def build_cards(rows, picked, specs, brands=None):
    brands = brands or {}
    chap_of = {fam: i for i, c in enumerate(CHAPTERS) for fam in c[2]}
    first = lambda key: {v: i for i, v in enumerate(dict.fromkeys(r[key] for r in rows))}
    line_ord, type_ord, gid_ord = first("라인/시리즈"), first("세부유형"), first("그룹ID")
    type_cnt = Counter(r["세부유형"] for r in picked)

    def chapter(r):
        return chap_of.get(r["제품군"], len(CHAPTERS) - 1)

    knife_groups = {}
    for r in picked:
        if CHAPTERS[chapter(r)][3] == "wide":
            knife_groups.setdefault(r["브랜드"], set()).add(r["그룹ID"])
    small = {b for b, g in knife_groups.items() if len(g) <= SMALL_BRAND_MAX or not b or b in LAST_BRANDS}

    def brand_key(b):
        if b in FIRST_BRANDS:
            return (0, FIRST_BRANDS.index(b), "")
        if not b or b in LAST_BRANDS:
            return (2, 0, "")
        m = re.search(r"\(([가-힣]+)\)", b)  # MAC(맥) → '맥'으로 가나다순에 넣는다
        return (1, 0, m.group(1) if m else b)

    series_groups = {}
    for r in picked:
        if r["라인/시리즈"]:
            series_groups.setdefault((r["브랜드"], r["라인/시리즈"]), set()).add(r["그룹ID"])

    def line_key(r):  # 시리즈: '브랜드' 시트 '시리즈 순서'에 적힌 순 → 제품 많은 순. 시리즈 없는 제품은 맨 뒤
        v = r["라인/시리즈"]
        if v is None:
            return (1, 0, 0, 0)
        order = [x.strip() for x in str(brands.get(r["브랜드"], {}).get("시리즈 순서") or "").split(",") if x.strip()]
        return (0, order.index(v) if v in order else len(order), -len(series_groups.get((r["브랜드"], v), ())), line_ord[v])

    def sort_key(r):
        ci = chapter(r)
        fams = CHAPTERS[ci][2]
        if CHAPTERS[ci][3] == "wide":  # 브랜드 → 시리즈 → 칼 종류. 작은 브랜드는 맨 뒤(가나다)
            mid = (r["브랜드"] in small, brand_key(r["브랜드"]), line_key(r), type_ord[r["세부유형"]])
        else:  # 종류(품목 많은 순, '기타'는 뒤) → 브랜드 → 시리즈
            t = r["세부유형"]
            fam = fams.index(r["제품군"]) if r["제품군"] in fams else 99
            mid = ((fam, "기타" in (t or "기타"), -type_cnt[t], str(t)), brand_key(r["브랜드"]), line_key(r))
        return (ci, mid, gid_ord[r["그룹ID"]], r["No"])

    cards = []
    for gid, items in groupby(sorted(picked, key=sort_key), key=lambda r: r["그룹ID"]):
        items = list(items)
        ci = chapter(items[0])
        wide = CHAPTERS[ci][3] == "wide"
        parts = split_group(items) if wide else [("", items)]
        for k, (label, part) in enumerate(parts, 1):
            g = part[0]
            misc = wide and g["브랜드"] in small
            c = dict(ci=ci, wide=wide, gid=f"{gid}-{k}" if len(parts) > 1 else gid, items=part,
                     brand=g["브랜드"], nation=g["브랜드 국가"], misc=misc,
                     l1=MISC if misc else (g["브랜드"] if wide else g["세부유형"]) or "기타",
                     l2=g["라인/시리즈"] if wide else g["브랜드"])
            analyze(c, specs)
            fam = label or family(part[0])
            c["fam"] = code_of(part[0]).split(",")[0] if isinstance(fam, int) else (fam or "")
            color = str(brands.get(g["브랜드"], {}).get("색") or "").strip()
            c["color"] = color if re.fullmatch(r"#[0-9A-Fa-f]{6}", color) else None
            cards.append(c)
    # 같은 브랜드 안에서 이름이 같은 제품에만 품번 계열 꼬리표를 붙인다
    key = lambda c: (c["ci"], c["l1"], c["lead"], c["name"])
    seen = Counter(key(c) for c in cards if c["wide"])
    dup = [c for c in cards if c["wide"] and seen[key(c)] > 1]
    for c in dup:  # 1차: 품번 계열. 그래도 같으면 첫 품번
        c["tag"] = c["fam"] or code_of(c["items"][0]).split(",")[0]
    seen2 = Counter((key(c), c["tag"]) for c in dup)
    for c in dup:
        if seen2[(key(c), c["tag"])] > 1:
            c["tag"] = code_of(c["items"][0]).split(",")[0] or c["tag"]
        if c["tag"]:
            c["name"] += f' <small>[{esc(c["tag"])}]</small>'
    return cards


def analyze(c, specs):
    """카드에 들어갈 글·표·높이를 정한다. 그룹 안에서 값이 같으면 스펙 목록으로, 다르면 표의 열로."""
    items, wide = c["items"], c["wide"]
    g, n = items[0], len(c["items"])
    lines, varying = [], []
    for k in [s for s in specs if s not in (CERT, GRIT)] + [FEATURE]:
        label = k[len(SPEC):] if k.startswith(SPEC) else "특징"
        vals = {esc(r.get(k)) for r in items}
        if vals == {""}:
            if SHOW_EMPTY_SPECS and label in TEMPLATE[wide]:
                lines.append((label, ""))
        elif len(vals) == 1:
            lines.append((label, vals.pop()))
        else:
            varying.append((label, k))
    has_color = any(r["색상"] for r in items)
    cell = {"색": lambda r: swatches(r["색상"]), "길이": lambda r: size_text(r["사이즈(mm)"]), "코드": code_of}
    # 2단 카드 표에는 보여줄 게 있는 품목만 (중복 등록된 빈 품목은 빈 줄로 넣지 않음)
    shown = [r for r in items if r["사이즈(mm)"] or code_of(r) or r["색상"] or any(esc(r.get(k)) for _, k in varying)]
    shown = items if wide else (shown or items[:1])
    c["single"] = not wide and len(shown) == 1
    c["disp"] = shown[0]

    if wide:
        cols = [("핸들 색상", cell["색"]), ("날 길이", cell["길이"]), ("모델 넘버", cell["코드"])]
    elif not c["single"]:
        cols = [("모델 넘버", cell["코드"]), ("사이즈", cell["길이"])] + ([("색상", cell["색"])] if has_color else [])
    else:
        cols = []
        d = c["disp"]
        if has_color:
            lines.insert(0, ("색상", swatches(d["색상"])))
        if d["사이즈(mm)"] or SHOW_EMPTY_SPECS:
            lines.insert(0, ("사이즈", size_text(d["사이즈(mm)"])))
    if cols:
        cols += [(label, lambda r, k=k: esc(r.get(k))) for label, k in varying]
        if not SHOW_EMPTY_SPECS:  # 완성본에서는 전부 빈 열을 숨김
            cols = [(label, f) for label, f in cols if label == "모델 넘버" or any(f(r) for r in items)]
    c["cols"] = [label for label, _ in cols]
    c["rows"] = [[f(r) for _, f in cols] for r in shown] if cols else []
    c["img"] = pick(IMAGES, c["gid"], *[code_of(r).split(",")[0] for r in items])
    c["lines"] = lines
    # 사이즈가 많으면 표를 좌우 2단으로 (열이 늘거나 품번이 길면 좁아서 안 됨)
    c["two"] = wide and n > 4 and not varying and max(len(code_of(r)) for r in items) <= 14
    c["cert"] = [x.strip() for x in esc(g.get(CERT)).split(",") if x.strip()]
    c["badge"] = esc(g.get(GRIT)) if len({esc(r.get(GRIT)) for r in items}) == 1 else ""

    custom = next((r["카탈로그 제품명"] for r in items if r.get("카탈로그 제품명")), None)
    if custom:
        c["lead"], c["name"] = "", esc(custom)
    else:
        c["lead"], c["name"] = auto_name(g, wide)

    if wide:
        table_rows = math.ceil(n / 2) if c["two"] else n
        left = 1 + W_KV * len(lines) + (6 if c["cert"] else 0)
        right = W_PIC + 1 + W_ROW * (1 + table_rows)
        c["h"] = W_PAD + W_TITLE + max(left, right)
    else:
        text = G_TITLE + (G_MODEL if c["single"] else 0) + G_KV * len(lines) + (5 if c["cert"] else 0) \
            + (G_ORIG if SHOW_ORIGINAL_NAME else 0)
        c["h"] = G_TOP + max(G_PIC, text) + (0 if c["single"] else 1 + G_ROW * (1 + len(shown))) + G_PAD


# ───────── 페이지 나누기 ─────────
def story_of(c, count, brands):
    """칼 브랜드 c["l1"]의 스토리 칸(없으면 None). 페이지 안에서 카드처럼 한 자리를 차지한다."""
    info = brands.get(c["l1"], {})
    text = "".join(f"<p>{esc(p)}</p>" for p in str(info.get("브랜드 스토리") or "").split("\n") if p.strip())
    img = pick(STORIES, c["l1"])
    if c["misc"] or c["l1"] in LAST_BRANDS or info.get("스토리 페이지") == "N" or not (SHOW_EMPTY_SPECS or text or img):
        return None
    full = count >= NEW_PAGE_MIN_CARDS
    return dict(story=True, misc=False, full=full, h=STORY_FULL_H if full else STORY_HALF_H, text=text, img=img,
                tag=esc(info.get("한 줄 소개")), chars=len(str(info.get("브랜드 스토리") or "")),
                ci=c["ci"], wide=True, l1=c["l1"], l2=None, brand=c["brand"], nation=c["nation"])


def layout(items):
    """한 페이지에 놓인 것들(카드, 스토리 칸) → 블록 목록 [(종류, 내용, 높이mm)]."""
    blocks = [("story", c, c["h"]) for c in items if c.get("story")]
    cards = [c for c in items if not c.get("story")]
    if not cards:
        return blocks
    wide = cards[0]["wide"]
    many1 = len({c["l1"] for c in cards}) > 1
    many2 = wide and len({(c["l1"], c["l2"]) for c in cards}) > 1
    row, prev = [], None

    def flush():
        if row:
            blocks.append(("row", row[:], max(c["h"] for c in row)))
            row.clear()

    for c in cards:
        if c["misc"]:  # 기타 나이프: 열 제목(쪽마다 한 번) + 브랜드 줄(브랜드가 바뀔 때) + 품목 줄
            if not any(b[0] == "misc" for b in blocks):
                blocks.append(("misc-head", None, 7))
            new_brand = not prev or not prev["misc"] or prev["brand"] != c["brand"]
            blocks.append(("misc", (c, new_brand), (7 if new_brand else 0) + 6 * len(c["items"])))
            prev = c
            continue
        new1 = not prev or prev["l1"] != c["l1"]
        if many1 and new1 and not (blocks and blocks[-1][0] == "story"):  # 스토리 칸 바로 아래는 띠 생략
            flush()
            blocks.append(("band1", c, BAND1_H))
        # 시리즈 띠. 시리즈 없는 제품은 같은 브랜드의 시리즈 제품 뒤에 올 때만 '기타' 띠로 구분
        if many2 and (new1 or prev["l2"] != c["l2"]) and (c["l2"] or not new1):
            blocks.append(("band2", c, BAND2_H))
        if wide:
            blocks.append(("wide", c, c["h"]))
        else:
            row.append(c)
            if len(row) == 2:
                flush()
        prev = c
    flush()
    return blocks


def paginate(cards, brands):
    run1 = Counter((c["ci"], c["l1"]) for c in cards)
    run2 = Counter((c["ci"], c["l1"], c["l2"]) for c in cards)
    pages, prev = [], None
    for c in cards:
        k1, k2 = (c["ci"], c["l1"]), (c["ci"], c["l1"], c["l2"])
        p1, p2 = (prev and (prev["ci"], prev["l1"])), (prev and (prev["ci"], prev["l1"], prev["l2"]))
        story = story_of(c, run1[k1], brands) if c["wide"] and k1 != p1 else None
        fill = sum(b[2] for b in layout(pages[-1])) / BODY_H if pages else 1
        force = (not prev or prev["ci"] != c["ci"] or (c["misc"] and not prev["misc"])
                 or (k1 != p1 and run1[k1] >= NEW_PAGE_MIN_CARDS and fill > NEW_PAGE_FILL[0])
                 or (k2 != p2 and run2[k2] >= NEW_PAGE_MIN_CARDS and fill > NEW_PAGE_FILL[1]))
        if story:  # 스토리 칸이 있는 브랜드는 항상 새 쪽에서 시작
            pages.append([story])
            force = story["full"]
        if force or sum(b[2] for b in layout(pages[-1] + [c])) > BODY_H:
            pages.append([])
        pages[-1].append(c)
        prev = c
    return pages


# ───────── HTML ─────────
def picture(c):
    if c["img"]:
        return f'<img src="{c["img"]}" alt="">'
    return f'<div class="noimg">이미지 · images/{esc(c["gid"])}.jpg</div>'


def table(cols, rows, widths):
    head = "".join(f"<b>{esc(x)}</b>" for x in cols)
    body = "".join(f'<span class="{"code" + " long" * (len(v) > 22) if cols[j] == "모델 넘버" else ""}">{v}</span>'
                   for r in rows for j, v in enumerate(r))
    return f'<div class="t" style="grid-template-columns:{widths}">{head}{body}</div>'


def kv(lines):
    return "".join(f'<p class="kv"><b>{esc(k)}</b><span>{v}</span></p>' for k, v in lines)


def chips(c):
    return '<p class="cert">' + "".join(f"<i>{x}</i>" for x in c["cert"]) + "</p>" if c["cert"] else ""


def title(c):
    orig = f'<small>{esc(c["items"][0]["상품명(원본)"])}</small>' if SHOW_ORIGINAL_NAME else ""
    return f'<b>{c["lead"]}</b> {c["name"]}', orig


def render_wide(c):
    name, orig = title(c)
    width = {"핸들 색상": ("16mm", "24mm"), "날 길이": ("18mm", "30mm")}  # (좌우 2단일 때, 1단일 때)
    widths = " ".join(width.get(x, ("1fr", "1fr"))[not c["two"]] for x in c["cols"])
    if c["two"]:
        half = math.ceil(len(c["rows"]) / 2)
        tbl = '<div class="two">' + "".join(table(c["cols"], part, widths)
                                            for part in (c["rows"][:half], c["rows"][half:])) + "</div>"
    else:
        tbl = table(c["cols"], c["rows"], widths)
    return (f'<article class="w" data-type="{esc(c["items"][0]["세부유형"])}" style="height:{c["h"]}mm"><h4><span>{name}</span>{orig}</h4><div class="cols">'
            f'<div class="specs">{kv(c["lines"])}{chips(c)}</div>'
            f'<div class="main"><div class="pic" data-slot="images/{esc(c["gid"])}">{picture(c)}</div>{tbl}</div></div></article>')


def render_grid(c, num):
    name, orig = title(c)
    single = c["single"]
    code = code_of(c["disp"])
    model = f'<p class="model"><i>모델 넘버</i><b class="{"long" * (len(code) > 18)}">{code}</b></p>' if single else ""
    widths = " ".join({"모델 넘버": "1.4fr", "색상": "14mm"}.get(x, "1fr") for x in c["cols"])
    tbl = "" if single else table(c["cols"], c["rows"], widths)
    return (f'<article class="g" data-type="{esc(c["items"][0]["세부유형"])}"><p class="top"><span>{num:02d}</span><span class="badge">{c["badge"]}</span></p>'
            f'<div class="cols"><div class="pic" data-slot="images/{esc(c["gid"])}">{picture(c)}</div><div class="txt"><h4>{name}</h4>{model}'
            f'{kv(c["lines"])}{chips(c)}{orig}</div></div>{tbl}</article>')


def logo_of(brand):
    src = pick(LOGOS, brand)
    return f'<img class="logo" src="{src}" alt="{esc(brand)}">' if src else ""


def brand_mark(brand, nation, with_name):
    """머리글 오른쪽: (브랜드 로고 또는 이름) + 국기."""
    flag = pick(FLAGS, nation)
    out = (logo_of(brand) or f"<b>{esc(brand)}</b>") if with_name else ""
    if flag:
        out += f'<img class="flag" src="{flag}" alt="{esc(nation)}">'
    elif nation:
        out += f'<span class="chip">{esc(nation)}</span>'
    return out


def frame(no, ci, crumb, ttl, sub, right, body, color=None):
    color = color or (CH_COLORS[ci % len(CH_COLORS)] if ci is not None else "var(--navy)")
    tab = (f'<div class="tab" style="top:{30 + ci * 26}mm">{esc(CHAPTERS[ci][0])}</div>') if ci is not None else ""
    return (f'<section class="page" id="p{no}" style="--c:{color}"><header class="ph"><p class="crumb">{crumb}</p>'
            f'<p class="ttl"><b>{ttl}</b><span>{sub}</span></p><div class="right">{right}</div></header>'
            f'<div class="body">{body}</div><footer class="pf"><span>www.sindoltd.com</span><b>{no}</b></footer>'
            f'{tab}</section>')


def render_misc(c, new_brand):
    """기타 나이프 표의 한 제품: 브랜드 줄(필요할 때) + 품목마다 한 줄 (제품명 · 종류 · 사이즈 · 품번)."""
    g = c["items"][0]
    brand = "브랜드 미상" if not c["brand"] or c["brand"] in LAST_BRANDS else esc(c["brand"])
    head = f'<div class="mb">{brand}<small>{esc(c["nation"])}</small></div>' if new_brand else ""
    name = (f'<b>{c["lead"]}</b> ' if c["lead"] and c["lead"] != esc(c["brand"]) else "") + c["name"]
    rows = "".join(f'<div class="mr" data-type="{esc(g["세부유형"])}"><span>{name if i == 0 else ""}</span><span>{esc(g["세부유형"])}</span>'
                   f'<span>{size_text(r["사이즈(mm)"])}</span><span class="code">{code_of(r)}</span></div>'
                   for i, r in enumerate(c["items"]))
    return head + rows


def render_story(s, series):
    """브랜드 스토리 칸. series = [(시리즈 이름, 쪽)]"""
    pic = f'<img src="{s["img"]}" alt="">' if s["img"] else \
        f'<div class="noimg">브랜드 사진 · brands/{esc(s["l1"])}.jpg</div>'
    body = s["text"] or "<div class=\"noimg\">브랜드 스토리 · 엑셀 '브랜드' 시트의 '브랜드 스토리' 칸에 입력</div>"
    tag = s["tag"] or ("한 줄 소개" if SHOW_EMPTY_SPECS else "")
    links = "".join(f'<a href="#p{p}">{esc(name)}<b>{p}</b></a>' for name, p in series) if s["full"] else ""
    return (f'<section class="story {"full" if s["full"] else "half"}" style="height:{s["h"]}mm">'
            f'<div class="s-pic" data-slot="brands/{esc(s["l1"])}">{pic}</div><div class="s-txt">'
            f'<h3>{esc(s["l1"])}<small>{esc(s["nation"])}</small></h3><p class="s-tag{"" if s["tag"] else " empty"}">{tag}</p>'
            f'<div class="s-body{"" if s["text"] else " empty"}">{body}</div>'
            + (f'<p class="s-series"><i>시리즈</i>{links}</p>' if links else "") + "</div></section>")


def series_label(name):
    """'M 시리즈' 처럼 이미 '시리즈'로 끝나면 그대로, 아니면 ' 시리즈'를 붙인다."""
    name = str(name)
    return esc(name) if name.endswith("시리즈") else esc(name) + " 시리즈"


def render_page(no, items, series):
    cards = [c for c in items if not c.get("story")]
    c0 = items[0]
    ci, wide = c0["ci"], c0["wide"]
    name, en = CHAPTERS[ci][:2]
    l1s = list(dict.fromkeys(c["l1"] for c in items))
    l2s = list(dict.fromkeys(c["l2"] for c in cards))
    brands = list(dict.fromkeys(c["brand"] for c in items))
    ttl = esc(" · ".join(map(str, l1s[:3]))) + (" 외" if len(l1s) > 3 else "")
    if c0["misc"]:  # 기타 나이프 쪽
        sub, right = "_ Other Knives", ""
    elif wide:  # 칼: 브랜드가 제목. 로고가 있으면 글자 대신 로고
        ttl = (len(brands) == 1 and logo_of(brands[0])) or ttl
        sname = str(l2s[0] or "") if len(l1s) == 1 and len(l2s) == 1 else ""
        sub = "_" + series_label(sname) if sname else ""
        sub = sub if cards else "_ Brand Story"
    else:
        sub = "_ " + SECTION_EN[l1s[0]] if len(l1s) == 1 and l1s[0] in SECTION_EN else ""
    if not c0["misc"]:
        right = brand_mark(brands[0], c0["nation"], not wide) if len(brands) == 1 else ""

    body, num = [], 0
    for kind, x, h in layout(items):
        if kind == "story":
            body.append(render_story(x, series.get((x["ci"], x["l1"]), [])))
        elif kind == "misc-head":
            body.append('<div class="mh"><b>제품</b><b>종류</b><b>사이즈</b><b>품번</b></div>')
        elif kind == "misc":
            body.append(render_misc(*x))
        elif kind == "band1":
            note = esc(x["nation"]) if wide else SECTION_EN.get(x["l1"], "")
            body.append(f'<div class="band1"><span>{esc(x["l1"])}</span><small>{note}</small></div>')
        elif kind == "band2":
            body.append(f'<div class="band2">{series_label(x["l2"]) if x["l2"] else "기타"}</div>')
        elif kind == "wide":
            body.append(render_wide(x))
        else:
            cells = []
            for c in x:
                num += 1
                cells.append(render_grid(c, num))
            body.append(f'<div class="grow" style="height:{h}mm">{"".join(cells)}</div>')
    return frame(no, ci, f"{esc(name)} <span>{en}</span>", ttl, sub, right, "".join(body),
                 c0.get("color") if len(brands) == 1 else None)


def toc_columns(entries):
    """목차 항목 [(장 제목인가, 글, 쪽)] → 페이지별 3단."""
    cols, col, h = [], [], 0
    for e in entries:
        need = 11 + 5.5 if e[0] else 5.5  # 장 제목은 첫 항목과 같이 다음 단으로
        if h + need > 236:
            cols.append(col)
            col, h = [], 0
        col.append(e)
        h += 11 if e[0] else 5.5
    cols.append(col)
    return [cols[i:i + 3] for i in range(0, len(cols), 3)]


def render_toc(no, cols, ci=None, crumb="SINDO <span>Kitchenware Wholesale</span>", ttl="목차", sub="_ Contents"):
    """목차 꼴 페이지. 칼 종류별 색인도 같은 꼴로 만든다."""
    out = []
    for col in cols:
        items = "".join(
            f'<a class="{"ch" if ch else "it"}" href="#p{p}" style="--c:{color}"><span>{text}</span><b>{p}</b></a>'
            for ch, text, p, color in col)
        out.append(f'<div class="tcol">{items}</div>')
    return frame(no, ci, crumb, ttl, sub, "", f'<div class="toc">{"".join(out)}</div>')


def render_front():
    files = sorted((BASE / "front").glob("*")) if (BASE / "front").is_dir() else []
    files = [f for f in files if f.suffix.lower() in IMG_EXTS]
    if files:
        return [f'<section class="page full"><img src="{quote("front/" + f.name)}" alt=""></section>' for f in files]
    cover = pick(IMAGES, "cover")
    photo = f'<img src="{cover}" alt="">' if cover else '<div class="noimg">표지 사진 · images/cover.jpg</div>'
    return [
        '<section class="page cover">'
        f'<div class="c-photo" data-slot="images/cover">{photo}</div><div class="c-gray"></div>'
        '<div class="c-logo"><b>SINDO</b><small>Kitchenware Wholesale</small></div>'
        f'<div class="c-wine"><p>Kitchenware<br>Wholesale</p><small><b>{VOLUME}</b> product catalogue</small></div>'
        '<div class="c-contact"><h5>오시는 길 <span>Contact Us</span></h5>'
        "<p><b>ADDRESS</b>서울시 중구 난계로 205-1 신도빌딩<br>205-1, Nangye-ro, Jung-gu, Seoul, Republic of Korea</p>"
        "<p><b>TEL</b>02-2252-2733</p><p><b>MAIL</b>sindoltd@naver.com</p></div>"
        '<div class="c-url">www.sindoltd.com</div></section>'
    ]


CSS = """
:root{--navy:#1f3c88;--wine:#8c1d2f;--ink:#1a1a1a;--gray:#777;--line:#d5d8de;--red:#d0342c;--amber:#b8741a}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Noto Sans KR","Pretendard","Malgun Gothic","맑은 고딕",sans-serif;color:var(--ink);
 background:#e9ebf0;font-size:8.5pt;line-height:1.3}
.page{width:210mm;height:297mm;margin:6mm auto;padding:8mm 12mm 6mm;background:#fff;box-shadow:0 1px 6px #0003;
 position:relative;overflow:hidden;--c:var(--navy)}
.ph{height:24mm;position:relative}
.crumb{height:5mm;line-height:5mm;font-size:7.5pt;color:var(--gray)}.crumb span{margin-left:1mm;font-size:7pt}
.ttl{height:12mm;line-height:12mm;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:60mm}
.ttl b{font-size:19pt}.ttl span{font-size:10pt;color:#444;margin-left:2.5mm}
.ph::after{content:"";position:absolute;left:0;right:0;top:18mm;height:1.6mm;background:var(--c)}
.right{position:absolute;right:0;top:2mm;height:14mm;display:flex;align-items:center;gap:3mm;font-size:12pt}
.right .logo{max-height:13mm;max-width:45mm}.right .flag{height:9mm;border:1px solid var(--line)}
.chip{border:1px solid var(--line);border-radius:1mm;padding:.8mm 2.5mm;font-size:8pt;color:#444}
.body{height:251mm;overflow:hidden}
.pf{height:8mm;display:flex;justify-content:space-between;align-items:flex-end;font-size:7.5pt;color:var(--gray)}
.pf b{font-size:11pt;color:var(--ink);line-height:1}
.tab{position:absolute;right:0;width:6mm;height:24mm;background:var(--c);color:#fff;font-size:7pt;
 writing-mode:vertical-rl;text-align:center;line-height:6mm;border-radius:1.5mm 0 0 1.5mm;overflow:hidden}
.band1{height:9mm;margin-bottom:3mm;background:var(--c);color:#fff;font-size:11pt;font-weight:700;line-height:9mm;
 padding:0 3mm;display:flex;justify-content:space-between;overflow:hidden}
.band1 small{font-weight:400;font-size:8pt;opacity:.85}
.band2{height:6mm;margin-bottom:2mm;border-left:1.2mm solid var(--c);padding-left:2mm;font-size:9.5pt;
 font-weight:700;line-height:6mm;color:var(--c);background:#f3f5f9;overflow:hidden}
h4 b{color:var(--c)}
.pic img{width:100%;height:100%;object-fit:contain;display:block}
.noimg{height:100%;border:1px dashed #c5c8cf;color:#a5a9b3;font-size:6.5pt;display:flex;align-items:center;
 justify-content:center;text-align:center}
.kv{display:flex;gap:2mm;white-space:nowrap;overflow:hidden}
.kv span{overflow:hidden;text-overflow:ellipsis;color:#333}
.cert{display:flex;gap:1mm;overflow:hidden}
.cert i{font-style:normal;font-size:6.5pt;font-weight:700;border:1px solid #555;border-radius:.8mm;padding:0 1.2mm;
 line-height:3.6mm;height:4mm;white-space:nowrap}
.t{display:grid;grid-auto-rows:6mm;font-size:8pt}
.t>*{height:6mm;line-height:6mm;text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
 border-bottom:1px solid var(--line);padding:0 .8mm}
.t>b{border-bottom-color:#222}.t .code{font-weight:700}
.t .long,.g .model .long{font-size:6.5pt;letter-spacing:-.02em}
.sw{display:inline-block;width:3mm;height:3mm;border:1px solid #888;margin:0 .3mm;vertical-align:middle}
small{font-weight:400;color:#aaa;font-size:6.5pt}
/* 1단 카드 (칼) */
.w{padding:2mm 0;border-bottom:1px solid var(--line);overflow:hidden}/* 높이 = 글·표 + 4.5mm */
.w h4{height:8mm;line-height:8mm;margin-bottom:1mm;font-size:11pt;border-bottom:1px solid #222;display:flex;gap:4mm;
 justify-content:space-between;white-space:nowrap;overflow:hidden}
.w h4 span{flex:none;max-width:120mm;overflow:hidden;text-overflow:ellipsis}
.w h4 small{overflow:hidden;text-overflow:ellipsis}
.w .cols{display:flex;gap:4mm}
.w .specs{flex:0 0 60mm;width:60mm;padding-top:1mm}
.w .kv{height:5.5mm;line-height:5.5mm}.w .kv b{flex:0 0 17mm}
.w .cert{height:6mm;align-items:center}
.w .main{flex:1;min-width:0}
.w .pic{height:25mm;padding:1mm 0;margin-bottom:1mm}
.two{display:flex;gap:4mm}.two .t{flex:1;min-width:0}
/* 2단 카드 */
.grow{display:flex;gap:6mm;overflow:hidden}
.g{flex:0 0 90mm;width:90mm;border-top:1px solid #222;overflow:hidden}
.g .top{height:6mm;line-height:6mm;display:flex;justify-content:space-between;font-size:8.5pt}
.badge{color:var(--amber);font-weight:700}
.g .cols{display:flex;gap:3mm}
.g .pic{flex:0 0 36mm;width:36mm;height:36mm}
.g .txt{flex:1;min-width:0}
.g h4{height:10mm;line-height:5mm;font-size:9pt;overflow:hidden}
.g .model{height:6mm;line-height:6mm;border-top:1px solid var(--line);white-space:nowrap;overflow:hidden;
 text-overflow:ellipsis}
.g .model i{font-style:normal;color:var(--red);margin-right:2mm}.g .model b{font-size:9pt}
.g .kv{height:5mm;line-height:5mm;font-size:7.5pt}.g .kv b{flex:0 0 11mm;font-weight:400;color:var(--gray)}
.g .cert{height:5mm;align-items:center}
.g .txt small{display:block;height:4mm;line-height:4mm;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.g .t{margin-top:1mm}
/* 기타 나이프 표: 열 제목 6mm, 브랜드 줄 6mm, 품목 줄 5mm */
.mh,.mr{display:grid;grid-template-columns:1fr 34mm 24mm 36mm;font-size:8pt}
.mh{height:7mm;line-height:7mm;font-weight:700;border-bottom:1px solid #222}
.mh b,.mr span{padding:0 1.5mm;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mb{height:7mm;line-height:6.5mm;padding-left:2mm;font-weight:700;color:var(--c);background:#f3f5f9;overflow:hidden}
.mb small{margin-left:2mm;color:var(--gray)}
.mr span{height:6mm;line-height:6mm;border-bottom:1px solid var(--line)}
.mr .code{font-weight:700}
/* 브랜드 스토리 칸: full = 한 쪽 전체(251mm), half = 위쪽 100mm */
.story{overflow:hidden;padding-bottom:6mm}
.s-pic img{width:100%;height:100%;object-fit:cover;display:block}
.story h3{height:12mm;line-height:12mm;font-size:20pt;color:var(--c);white-space:nowrap;overflow:hidden}
.story h3 small{font-size:9pt;color:var(--gray);margin-left:3mm}
.s-tag{height:7mm;line-height:7mm;margin-bottom:4mm;font-size:11pt;font-weight:700;border-bottom:1px solid #222;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.s-tag.empty{color:#b5b8c0;font-weight:400}
.s-body{font-size:9.5pt;line-height:1.75;overflow:hidden;text-align:justify}
.s-body p{margin-bottom:2.5mm}
.s-series{height:16mm;margin-top:4mm;padding-top:2mm;border-top:1px solid var(--line);overflow:hidden;line-height:6mm}
.s-series i{font-style:normal;font-weight:700;color:var(--c);margin-right:3mm}
.s-series a{color:inherit;text-decoration:none;margin-right:4mm;white-space:nowrap}
.s-series b{font-weight:400;color:var(--gray);margin-left:1mm;font-size:7.5pt}
.full .s-pic{height:100mm;margin-bottom:6mm}
.full .s-body{height:96mm;columns:2;column-gap:8mm}
.full .s-body.empty{columns:auto}
.half{display:flex;gap:6mm}
.half .s-pic{flex:0 0 70mm;width:70mm;height:90mm}
.half .s-txt{flex:1;min-width:0}
.half .s-body{height:66mm}
/* 목차 */
.toc{display:flex;gap:7mm;height:100%}.tcol{flex:1;min-width:0}
.toc a{display:flex;justify-content:space-between;gap:2mm;color:inherit;text-decoration:none;white-space:nowrap;
 overflow:hidden}
.toc a span{overflow:hidden;text-overflow:ellipsis}
.toc .ch{height:8mm;line-height:8mm;margin-top:3mm;font-size:10pt;font-weight:700;color:var(--c);
 border-bottom:.5mm solid var(--c)}
.toc .ch em{font-style:normal;font-weight:400;font-size:6.5pt;margin-left:.5mm}
.ttl .logo{max-height:11mm;max-width:70mm;vertical-align:middle}
.toc .it{height:5.5mm;line-height:5.5mm;border-bottom:1px dotted var(--line)}.toc .it b{font-weight:400;color:var(--gray)}
/* 표지 · 앞 페이지 */
.full{padding:0}.full img{width:100%;height:100%;object-fit:cover;display:block}
.cover{padding:0}
.cover>*{position:absolute}
.c-photo{inset:0 0 110mm 0;background:#eef0f3}.c-photo img{width:100%;height:100%;object-fit:cover}
.c-gray{left:10mm;top:0;width:75mm;height:112mm;background:#4a4f57e0}
.c-logo{right:14mm;top:16mm;text-align:right;color:var(--navy)}
.c-logo b{display:block;font-size:30pt;letter-spacing:.12em;line-height:1}
.c-logo small{font-size:9pt;color:var(--navy);font-weight:700}
.c-wine{left:10mm;top:112mm;width:75mm;height:92mm;background:var(--wine);color:#fff;padding:36mm 8mm 0;text-align:center}
.c-wine p{font-size:19pt;line-height:1.35}
.c-wine small{position:absolute;left:3mm;bottom:3mm;color:#fff;font-size:8.5pt}.c-wine small b{font-size:12pt}
.c-contact{right:14mm;bottom:18mm;width:88mm;font-size:8pt}
.c-contact h5{font-size:10pt;border-bottom:1px solid #222;border-right:1px solid #222;padding-bottom:1.5mm;margin-bottom:2.5mm}
.c-contact h5 span{margin-left:4mm}
.c-contact p{position:relative;padding-left:20mm;margin-bottom:1.5mm}
.c-contact p b{position:absolute;left:0;font-size:9pt}
.c-url{left:10mm;bottom:0;width:75mm;height:22mm;background:var(--navy);color:#fff;font-size:14pt;text-align:center;
 line-height:22mm}
.page:nth-of-type(even) .tab{right:auto;left:0;border-radius:0 1.5mm 1.5mm 0}
.page:nth-of-type(even) .pf{flex-direction:row-reverse}
@page{size:A4;margin:0}
@media print{
 body{background:#fff;zoom:1!important}
 .page{margin:0;box-shadow:none;break-after:page}
}
"""

# 화면 폭이 좁으면(휴대폰 등) 페이지를 줄여서 보여준다
JS = "function fit(){document.body.style.zoom=Math.min(1,innerWidth/830)}fit();addEventListener('resize',fit)"


def build():
    rows, picked, specs, brands = load_rows()
    cards = build_cards(rows, picked, specs, brands)
    pages = paginate(cards, brands)
    assert sum(len(c.get("items", [])) for p in pages for c in p) == len(picked), "일부 품목이 누락됨"
    assert all(sum(b[2] for b in layout(p)) <= BODY_H or len(p) == 1 for p in pages), "페이지 높이 초과"

    front = render_front()
    n_knife = sum(p[0]["ci"] == 0 for p in pages)  # 칼 쪽은 맨 앞에 몰려 있다. 그 뒤에 종류별 색인 쪽이 들어간다

    # 칼 종류별 찾아보기: 종류(마스터에 나온 순) → 브랜드(또는 기타 나이프)와 처음 나오는 쪽
    type_order = {t: i for i, t in enumerate(dict.fromkeys(r["세부유형"] for r in rows))}
    KNIFE_TYPES[:] = [t for t in type_order if any(c["wide"] and c["items"][0]["세부유형"] == t for c in cards)]
    idx = {}
    for i, p in enumerate(pages[:n_knife]):
        for c in p:
            if not c.get("story"):
                idx.setdefault((c["items"][0]["세부유형"] or "기타", c["l1"]), i)
    index_entries = []
    for t in sorted({t for t, _ in idx}, key=lambda t: type_order.get(t, 999)):
        ents = sorted(((b, i) for (tt, b), i in idx.items() if tt == t), key=lambda x: x[1])
        index_entries.append((True, esc(t), ents[0][1], CH_COLORS[0]))
        index_entries += [(False, esc(b), i, CH_COLORS[0]) for b, i in ents]
    n_index = len(toc_columns(index_entries))

    entries, seen, where = [], set(), {}  # 목차: 대분류와 그 아래 브랜드(칼)·종류(그 외)가 처음 나오는 쪽
    for i, p in enumerate(pages):
        if i == n_knife:
            entries.append((False, "칼 종류별 찾아보기", None, CH_COLORS[0]))  # None = 색인 첫 쪽
        for c in p:
            color = CH_COLORS[c["ci"] % len(CH_COLORS)]
            name, en = CHAPTERS[c["ci"]][:2]
            for key, ch, text in ((c["ci"], True, f"{esc(name)} <em>{en}</em>"), ((c["ci"], c["l1"]), False, esc(c["l1"]))):
                if key not in seen:
                    seen.add(key)
                    entries.append((ch, text, i, color))
            where.setdefault((c["ci"], c["l1"], c["l2"]), i)
    n_toc = len(toc_columns(entries))
    first = len(front) + n_toc + 1  # 본문 첫 쪽 번호

    def page_no(i):  # 상대 쪽(pages 순서) → 실제 쪽 번호. 색인 쪽만큼 뒤 대분류가 밀린다
        if i is None:
            return first + n_knife
        return first + i + (n_index if i >= n_knife else 0)

    entries = [(ch, text, page_no(i), color) for ch, text, i, color in entries]
    entries = [(ch, text, first + n_knife if text == "칼 종류별 찾아보기" else p, color) for ch, text, p, color in entries]
    index_entries = [(ch, text, page_no(i), color) for ch, text, i, color in index_entries]
    series = {}  # 스토리 칸의 시리즈 목록: (대분류, 브랜드) → [(시리즈, 쪽)]
    for (ci, l1, l2), i in where.items():
        if l2:
            series.setdefault((ci, l1), []).append((l2, page_no(i)))

    out = front[:]
    out += [render_toc(len(front) + 1 + i, cols) for i, cols in enumerate(toc_columns(entries))]
    out += [render_page(page_no(i), p, series) for i, p in enumerate(pages[:n_knife])]
    out += [render_toc(first + n_knife + j, cols, 0, "칼 <span>Knives</span>", "칼 종류별 찾아보기", "_ Knife Index")
            for j, cols in enumerate(toc_columns(index_entries))]
    out += [render_page(page_no(i), p, series) for i, p in enumerate(pages) if i >= n_knife]
    OUT.write_text(
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700&display=swap">'
        f"<title>SINDO 제품 카탈로그</title><style>{CSS}</style></head><body>"
        f'{"".join(out)}<script>{JS}</script></body></html>',
        encoding="utf-8",
    )
    stories = [c for p in pages for c in p if c.get("story")]
    tall = [c["gid"] for p in pages for c in p if len(p) == 1 and not c.get("story") and c["h"] > BODY_H]
    misc = [c for c in cards if c["misc"]]
    print(f"{OUT.name} 생성: {len(out)}쪽 (앞 {len(front)} + 목차 {n_toc} + 본문 {len(pages)} + 칼 색인 {n_index}), "
          f"제품 {len(cards)}개 / 품목 {len(picked)}개, 사진 {sum(bool(c['img']) for c in cards)}개")
    print(f"기타 나이프: 브랜드 {len({c['brand'] for c in misc})}개 {len(misc)}제품 (칼 제품 {SMALL_BRAND_MAX}개 이하 브랜드) / "
          f"브랜드 페이지 {len({c['l1'] for c in cards if c['wide'] and not c['misc']})}개")
    print(f"브랜드 스토리 칸 {len(stories)}개 (한 쪽 전체 {sum(s['full'] for s in stories)}개, "
          f"글 있음 {sum(bool(s['text']) for s in stories)}개) / 제외한 브랜드: "
          + (", ".join(b for b, d in brands.items() if d.get("수록") == "N") or "없음"))
    wordy = [f'{s["l1"]}({s["chars"]}자, 칸은 약 {STORY_CHARS[s["full"]]}자)' for s in stories
             if s["chars"] > STORY_CHARS[s["full"]]]
    if wordy:
        print("스토리가 길어 잘릴 수 있는 브랜드:", ", ".join(wordy))
    if tall:
        print("한 쪽에 다 안 들어가는 제품(사이즈가 너무 많음):", ", ".join(tall))
    blank = list(dict.fromkeys(NOTE["품번 빈칸"]))
    if blank:
        print(f"사이즈별로 나눴지만 품번을 다 못 채운 제품 {len(blank)}개 (엑셀 '모델코드(추출)'에 사이즈 순서대로 "
              f"쉼표로 적으면 채워짐): {', '.join(blank[:12])}{' …' if len(blank) > 12 else ''}")
    if NOTE["풀어 쓴 품번"]:
        print(f"줄여 쓴 품번을 풀어 쓴 제품 {len(NOTE['풀어 쓴 품번'])}개 (확인 필요): " + " / ".join(NOTE["풀어 쓴 품번"][:12]))
    long = list(dict.fromkeys(c["gid"] for c in cards for r in c["items"] if len(code_of(r)) > 34))
    if long:
        print("품번이 길어 잘리는 제품(엑셀 '모델코드(추출)' 정리 필요):", ", ".join(long))
    return out


# ───────── 편집기용 내보내기 (--editor) ─────────
EDITOR_JSON = BASE / "catalog.json"
EDITOR_CSS = BASE / "editor_assets" / "catalog.css"
SECTION = re.compile(r'^<section class="([^"]*)"(?: id="p(\d+)")?(?: style="([^"]*)")?>(.*)</section>$', re.S)
REF = re.compile(r'<a ([^>]*?)href="#p(\d+)"([^>]*)>(.*?)<b>\d+</b></a>', re.S)

# 편집기·책 보기에서 더 쓰는 규칙 (catalog.css 끝에 붙는다)
EDITOR_CSS_EXTRA = """
/* ── 편집기·책 보기 공용 ── */
.page{margin:0;box-shadow:none}
.page a[data-ref]{cursor:pointer}
.page a[data-ref].broken b{color:var(--red)}
.ov-layer{position:absolute;inset:0;pointer-events:none;z-index:5}
.ov{position:absolute;pointer-events:auto;box-sizing:border-box}
.ov-text{line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--ink)}
.ov-image img{width:100%;height:100%;object-fit:contain;display:block}
.page.full .pic,.page.full .full-slot{position:absolute;inset:0}
.page.full .full-slot img{width:100%;height:100%;object-fit:cover;display:block}
/* 완성본(책 보기·PDF): 참고용 원본 상품명과 빈 스펙 줄은 숨긴다 */
.final .w h4 small,.final .g .txt small{visibility:hidden}
.final .kv:has(> span:empty){display:none}
.final .noimg{border-color:#e3e5ea;color:transparent}
"""


def editor_css():
    """catalog.css: 생성기 CSS에서 화면용(body·여백) 규칙을 빼고, 짝수 쪽 규칙을 class(.even)로 바꾼다."""
    css = CSS.replace(".page:nth-of-type(even)", ".page.even")
    return css + EDITOR_CSS_EXTRA


def editor_doc(out):
    """build() 가 만든 쪽 html 목록 → 편집기 문서(dict)."""
    pages = []
    for n, sec in enumerate(out, 1):
        m = SECTION.match(sec.strip())
        assert m, f"{n}쪽을 읽지 못했습니다"
        cls, no, style, inner = m.groups()
        assert no is None or int(no) == n, f"{n}쪽 번호가 맞지 않습니다 ({no})"
        inner = inner.replace(f'<footer class="pf"><span>www.sindoltd.com</span><b>{n}</b></footer>',
                              '<footer class="pf"><span>www.sindoltd.com</span><b class="pno"></b></footer>')
        inner = REF.sub(lambda r: f'<a {r.group(1)}data-ref="pg-{int(r.group(2)):04d}"{r.group(3)}>'
                                  f'{r.group(4)}<b class="pref"></b></a>', inner)
        inner = re.sub(r'<(article class="w"(?: data-type="[^"]*")?|div class="grow") style="height:[\d.]+mm">', r"<\1>", inner)
        extra = cls.replace("page", "", 1).strip()
        ttl = re.search(r'<p class="ttl"><b>(.*?)</b><span>(.*?)</span>', inner, re.S)
        if "cover" in extra or "full" in extra:
            kind = "cover" if n == 1 else "image"
        elif ttl and ttl.group(1) == "목차":
            kind = "toc"
        elif ttl and ttl.group(1) == "칼 종류별 찾아보기":
            kind = "index"
        elif ttl and "Other Knives" in ttl.group(2):
            kind = "misc"
        else:
            kind = "content"
        pages.append({"id": f"pg-{n:04d}", "kind": kind, "cls": extra, "style": style or "",
                      "html": inner, "overlays": []})
    left = [p["id"] for p in pages if "#p" in p["html"] or "id=\"p" in p["html"]]
    assert not left, f"쪽 번호 링크가 남은 쪽: {left[:5]}"
    return {"version": 1, "title": "SINDO 제품 카탈로그",
            "meta": {"nextId": len(pages) + 1, "knifeTypes": KNIFE_TYPES[:]}, "pages": pages}


def export_editor(out, force=False):
    import json
    EDITOR_CSS.parent.mkdir(exist_ok=True)
    EDITOR_CSS.write_text(editor_css(), encoding="utf-8")
    doc = editor_doc(out)
    target = EDITOR_JSON
    if target.exists() and not force:
        target = BASE / "catalog.new.json"
        print(f"catalog.json 이 이미 있어서(편집기에서 고친 내용 보호) {target.name} 로 저장했습니다. "
              "편집한 내용을 버리고 엑셀 기준으로 새로 시작하려면 --editor --force")
    target.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{target.name} 생성: {len(doc['pages'])}쪽 / {EDITOR_CSS.relative_to(BASE)} 갱신")


def make_pdf():
    exe = next((p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if Path(p).exists()), None)
    if not exe:
        sys.exit("크롬/엣지를 찾지 못했습니다. catalog.html을 브라우저에서 열어 인쇄 → PDF로 저장하세요.")
    pdf = OUT.with_suffix(".pdf")
    started = time.time()
    # 전용 프로필 폴더를 줘야 이미 떠 있는 크롬에 붙지 않는다. 그래도 종료를 안 하면 5분 뒤 끝낸다
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        try:
            subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                            f"--user-data-dir={profile}", f"--print-to-pdf={pdf}", OUT.as_uri()],
                           check=True, capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            pass
    if not pdf.exists() or pdf.stat().st_mtime < started:
        sys.exit("PDF를 만들지 못했습니다. catalog.html을 브라우저에서 열어 인쇄 → PDF로 저장하세요.")
    print(f"{pdf.name} 생성")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    out = build()
    if "--pdf" in sys.argv:
        make_pdf()
    if "--editor" in sys.argv:
        export_editor(out, force="--force" in sys.argv)
