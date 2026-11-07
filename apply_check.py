"""apply_specs.py 자체 점검 (작은 가짜 문서로)

    python apply_check.py      → 끝에 '점검 통과' 가 나오면 됨
"""
import io
import json
import re
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_specs as A  # noqa: E402
from openpyxl import Workbook  # noqa: E402

KV = '<p class="kv"><b>HRC</b><span>{}</span></p><p class="kv"><b>두께</b><span></span></p>' \
     '<p class="kv"><b>날 재질</b><span></span></p><p class="kv"><b>핸들 재질</b><span></span></p>'


def card(gid, rows, hrc="", two=False, extra_kv=""):
    """칼 카드 html. rows = [(색, 날 길이, 품번)]"""
    def t(rs, w):
        return f'<div class="t" style="grid-template-columns:{w}"><b>핸들 색상</b><b>날 길이</b><b>모델 넘버</b>' + \
            "".join(f'<span class="">{c}</span><span class="">{s}</span><span class="code">{m}</span>' for c, s, m in rs) + "</div>"
    if two:
        h = -(-len(rows) // 2)
        tbl = '<div class="two">' + t(rows[:h], "16mm 18mm 1fr") + t(rows[h:], "16mm 18mm 1fr") + "</div>"
    else:
        tbl = t(rows, "24mm 30mm 1fr")
    return (f'<article class="w" data-type="규토·셰프나이프"><h4><span><b>시험</b> {gid}</span><small>원래 이름</small></h4>'
            f'<div class="cols"><div class="specs">{KV.format(hrc)}{extra_kv}</div><div class="main">'
            f'<div class="pic" data-slot="images/{gid}"><div class="noimg">이미지</div></div>{tbl}</div></div></article>')


def page(pid, body, kind="content"):
    return {"id": pid, "kind": kind, "cls": "", "style": "--c:#1f3c88", "overlays": [],
            "html": f'<header class="ph"><p class="crumb">칼 <span>Knives</span></p></header><div class="body">{body}</div>'
                    f'<footer class="pf"><span>www.sindoltd.com</span><b class="pno"></b></footer>'}


MISC = ('<div class="mh"><b>제품</b><b>종류</b><b>사이즈</b><b>품번</b></div><div class="mb">시험브랜드<small>일본</small></div>'
        '<div class="mr" data-type="데바"><span>데바 <small>[D]</small></span><span>데바</span><span>150 mm</span><span class="code">D-150</span></div>'
        '<div class="mr" data-type="데바"><span></span><span>데바</span><span></span><span class="code">D-165</span></div>'
        '<div class="mb">다른브랜드<small></small></div>'
        '<div class="mr" data-type="산토쿠"><span>산도쿠</span><span>산토쿠</span><span>165 mm</span><span class="code">S-1</span></div>')

KEEP = card("G9999", [("", "200 mm", "KEEP-1")])
SPECS = {
    "G9001": {"hrc": "58~59", "두께": "2mm", "날 재질": "강철", "핸들 재질": "나무",
              "사이즈": [["721TM", 210], ["724TM", 240], ["727TM", 270]]},
    "G9002": {"날 재질": "백지", "사이즈": [["", 210, "3mm"], ["", 240, "3.5mm"], ["", 270, "3.5mm"], ["", 300, "4mm"], ["", 330, "5mm"]]},
    "G9003": {"날 재질": "몰리브덴", "사이즈": [["HB-70", 180, "2mm"], ["TH-80", 200, "2.3mm"], ["TH-100", 255, "2.5mm"], ["ZZ-1", 999]]},
    "G9004": {"hrc": "60", "사이즈": [["X-1", 100]]},
    "G9005": {"날 재질": "스텐", "사이즈": [["D-150", 150], ["D-165", 165], ["D-180", 180]]},
    "G9006": {"메모": "홈페이지에서 못 찾음"},
    "G9007": {"날 재질": "검수 대기", "사이즈": [["P-1", 100]]},
    "G9008": {"날 재질": "없는 제품", "사이즈": [["NONE-1", 100]]},
    # 브랜드·사이즈 글이 똑같은 두 제품: G9010 줄만 직원이 두께 칸을 고치고 고칠 내용을 적음
    "G9009": {"두께": "2mm", "사이즈": [["Q-1", 100]]},
    "G9010": {"두께": "2mm", "사이즈": [["Q-1", 100]]},
    # 품번으로 짝지었는데 날 길이가 다름 → 바꾸고 '확인할 것' 에도 적음
    "G9011": {"사이즈": [["M904", 240], ["M906", 180]]},
}


def make_doc():
    return {"version": 1, "title": "시험", "meta": {"nextId": 10}, "pages": [
        page("pg-0001", card("G9001", [("", "", "721tm")]) + KEEP),
        page("pg-0002", card("G9002", [("", f"{n} mm", "") for n in (210, 240, 270, 300, 330)], two=True)),
        page("pg-0003", card("G9003-1", [("", "180 mm", "HB-70")]) + card("G9003-2", [("", "200 mm", "TH-80")])
             + card("G9004", [("", "100 mm", "X-1")], hrc="62") + card("G9007", [("", "100 mm", "P-1")])),
        page("pg-0004", MISC, "misc"),
        page("pg-0005", card("G9009", [("", "100 mm", "Q-1")]) + card("G9010", [("", "100 mm", "Q-1")])
             + card("G9011", [("", "180 mm", "M904"), ("", "240 mm", "M906")])),
    ]}


def make_review(path):
    wb = Workbook()
    ws = wb.active
    ws.append(["쪽", "브랜드", "제품 (카탈로그 이름)", "HRC", "두께", "날 재질", "핸들 재질", "사이즈 · 품번 (홈페이지)",
               "지금 카탈로그 표", "원산지", "메모", "홈페이지", "확인 (O 또는 고칠 내용)"])
    where = A.spec_review.cards(make_doc())          # 검수표를 만들 때와 같은 쪽·이름
    for gid, s in SPECS.items():
        ok = {"G9007": "240mm 아님", "G9001": "O", "G9010": "두께 3mm 임"}.get(gid)
        pg, name = where.get(gid, ("", "(카탈로그에서 못 찾음)"))[:2]
        ws.append([pg, "시험브랜드", name, s.get("hrc"), "3mm" if gid == "G9010" else s.get("두께"), s.get("날 재질"),
                   s.get("핸들 재질"), A.sizes_str(s), "", "", "", "", ok])
    wb.save(path)


def cards_of(doc):
    return {m.group(1): a for p in doc["pages"] for a in re.findall(r"<article.*?</article>", p["html"], re.S)
            for m in [re.search(r'data-slot="images/([^"]+)"', a)] if m}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "스펙").mkdir()
        (d / "스펙" / "시험브랜드.json").write_text(json.dumps({"_출처": "시험", **SPECS}, ensure_ascii=False), encoding="utf-8")
        make_review(d / "검수.xlsx")
        doc_path = d / "catalog.json"
        doc_path.write_text(json.dumps(make_doc(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        args = ["--doc", str(doc_path), "--specs", str(d / "스펙"), "--review", str(d / "검수.xlsx")]
        original = doc_path.read_bytes()

        # 1) 미리보기: 문서·백업은 그대로, 결과표만
        with redirect_stdout(io.StringIO()):
            assert A.main(args + ["--dry-run"]) == 0
        assert doc_path.read_bytes() == original, "미리보기인데 문서가 바뀜"
        assert not (d / "catalog.before-specs.json").exists()
        assert (d / A.REPORT_NAME).exists()

        # 2) 넣기
        out = io.StringIO()
        with redirect_stdout(out):
            assert A.main(args) == 0
        assert (d / "catalog.before-specs.json").read_bytes() == original, "원본 백업이 다름"
        doc = A.catalog_doc.load_doc(doc_path)
        assert A.catalog_doc.validate_doc(doc) == []
        c = cards_of(doc)
        # 사이즈마다 한 줄 + 홈페이지 품번 철자 + 스펙 줄
        assert "<span>58~59</span>" in c["G9001"] and "<span>강철</span>" in c["G9001"]
        assert re.findall(r'<span class="code">([^<]*)</span>', c["G9001"]) == ["721TM", "724TM", "727TM"]
        assert '<span class="">210 mm</span>' in c["G9001"] and "721tm" not in c["G9001"]
        assert KEEP in doc["pages"][0]["html"], "안 바뀐 카드는 글자 하나 안 바뀌어야 함"
        # 사이즈마다 다른 두께 → 표에 칸을 더하지 않고 왼쪽 두께 줄에 평균 '약 3.8mm' (3·3.5·3.5·4·5)
        g2 = c["G9002"]
        assert "<b>두께</b><b>" not in g2 and "<span>약 3.8mm</span>" in g2
        assert "<span>백지</span>" in g2
        # 쪼갠 그룹: 품번이 맞는 카드에만, 같은 계열(TH)은 TH 카드로, 모르는 줄(ZZ-1)은 안 넣음
        assert "TH-100" in c["G9003-2"] and "TH-100" not in c["G9003-1"]
        assert "ZZ-1" not in c["G9003-1"] + c["G9003-2"]
        assert "<span>약 2mm</span>" in c["G9003-1"]   # 두께는 늘 '약' 을 붙여 스펙 줄로
        # 다른 값은 안 바꿈
        assert "<span>62</span>" in c["G9004"] and "<span>60</span>" not in c["G9004"]
        # 검수표에 고칠 내용 → 건너뜀
        assert "검수 대기" not in c["G9007"]
        # 기타 나이프: 빈 사이즈 채움 + 없는 사이즈는 바로 뒤에 줄 더함 (이름 칸은 비움)
        misc = doc["pages"][3]["html"]
        assert '<span>데바</span><span>165 mm</span><span class="code">D-165</span></div>' \
               '<div class="mr" data-type="데바"><span></span><span>데바</span><span>180 mm</span><span class="code">D-180</span></div>' \
               '<div class="mb">다른브랜드' in misc
        # 결과표
        from openpyxl import load_workbook
        ws = load_workbook(d / A.REPORT_NAME).active
        rows = list(ws.iter_rows(values_only=True))
        assert rows[0] == ("쪽", "브랜드", "제품", "그룹", "바뀐 것", "확인할 것")
        text = json.dumps(rows, ensure_ascii=False, default=str)
        assert "G9007" in text and "검수표에 고칠 내용" in text
        assert "G9008" in text and "못 찾음" in text
        assert "G9006" in text and "메모만" in text
        assert "ZZ-1" in text and "HRC 다름" in text
        # 검수표: 값 칸을 고친 줄도 쪽·이름으로 찾아 건너뜀, 옆 제품은 넣음
        assert "<span>약 2mm</span>" in c["G9009"] and "약 2mm" not in c["G9010"]
        assert "두께 3mm 임" in text
        # 날 길이를 바꾼 것은 '확인할 것' 에도
        g11 = next(r for r in rows if r[3] == "G9011")
        assert "날 길이를 홈페이지대로 바꿈" in (g11[5] or "") and "M904 180 mm → 240 mm" in g11[4]
        assert re.findall(r'<span class="code">([^<]*)</span>', c["G9011"]) == ["M906", "M904"]

        # 3) 한 번 더 돌려도 그대로 (두 번 넣지 않음)
        once = doc_path.read_bytes()
        out = io.StringIO()
        with redirect_stdout(out):
            assert A.main(args) == 0
        assert doc_path.read_bytes() == once, "두 번째 실행에서 또 바뀜"
        assert "바뀐 것이 없어" in out.getvalue()

        # 4) 편집기가 켜져 있으면 catalog.json 에 안 넣음 (미리보기는 됨)
        base, running = A.BASE, A.editor_running
        A.BASE, A.editor_running = d, (lambda port=8800: True)
        try:
            doc_path.write_bytes(original)
            out = io.StringIO()
            with redirect_stdout(out):
                assert A.main(args) == 1
                assert A.main(args + ["--dry-run"]) == 0
            assert doc_path.read_bytes() == original and "편집기를 끄고" in out.getvalue()
        finally:
            A.BASE, A.editor_running = base, running

        # 5) 잘못 실행하면 한국어로 알림
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()) as o:
            try:
                A.main([])
                assert False
            except SystemExit as e:
                assert e.code == 2
            assert A.main(["--doc", str(d / "없음.json")]) == 1
        assert "실행 방법" in err.getvalue() and "찾을 수 없습니다" in o.getvalue()

    # 6) 쪼갠 그룹: 카드에 없는 품번(5.8450.20)이 같은 날 길이의 남의 줄을 가로채지 않음
    sr = [A.SRow(z, i) for i, z in enumerate([["5.8449.20", 200], ["5.8450.20", 200], ["5.8452.20", 200]])]
    parts, lost, guess = A.split_rows([[("5.8449.20", 200)], [("5.8452.20", 200)]], sr)
    assert [[s.code for s in x] for x in parts] == [["5.8449.20"], ["5.8452.20"]] and [s.code for s in lost] == ["5.8450.20"]
    parts, lost, guess = A.split_rows([[("5.8449.20", 200)], [("", 240)]], [A.SRow(["5.8449.20", 200], 0), A.SRow(["X-9", 240], 1)])
    assert [s.code for s in parts[1]] == ["X-9"] and guess == {1: "날 길이로"}

    # 7) 사이즈마다 다른 값: 표 칸은 그대로(핸들 색상·날 길이·모델 넘버), 왼쪽 줄로 모음 — 두께는 평균, 글자는 ' / ' 
    mat = {"날 재질": "몰리브덴 바나듐 AUS-8A 스테인리스", "핸들 재질": "적층 강화목 마이카르타", "hrc": "60"}
    sr = [A.SRow(["HPBE-5007R-ZRG-1205G-SPG2", 210, dict(mat, 두께="2mm")], 0),
          A.SRow(["ZRG-1205G-HPBE-5007R-XL", 240, dict(mat, 두께="2.5mm", hrc="62", **{"날 재질": "VG10 다마스커스 33층 스테인리스", "핸들 재질": "흑단 나무 손잡이"})], 1)]
    n = A.Note(1, "시험", "", "G9100")
    h = A.apply_wide(card("G9100", [("", "210 mm", "")]), sr, {}, n)
    heads = re.findall(r"<b>([^<]*)</b>", h.split('class="t"', 1)[1])[:4]
    assert heads[:3] == ["핸들 색상", "날 길이", "모델 넘버"], heads
    assert "<span>약 2.3mm</span>" in h and "<span>60 / 62</span>" in h, h
    assert "몰리브덴 바나듐 AUS-8A 스테인리스 / VG10 다마스커스 33층 스테인리스" in h
    print("점검 통과")


if __name__ == "__main__":
    main()
