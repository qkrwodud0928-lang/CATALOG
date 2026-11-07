"""link_photos.py 점검 (인터넷 안 씀). python -X utf8 link_check.py → '모두 통과'"""
import io
import json
import tempfile
from pathlib import Path

from PIL import Image

import link_photos as L

# 1) 사진 주소: 파일 이름·경로·전체 주소
B = "https://sindoltd.com/web/product/big/"
assert L.photo_url("202301/a b.jpg") == B + "202301/a%20b.jpg"
assert L.photo_url("product/big/202301/a.jpg") == B + "202301/a.jpg"
assert L.photo_url("/web/product/big/x.jpg") == B + "x.jpg"
assert L.photo_url("https://sindoltd.com/web/product/big/x.jpg") == B + "x.jpg"
assert L.photo_url("") is None

# 2) 엑셀 + 사이트맵 표로 알려진 카드 (글레스텐 M·K 시리즈 우도)
rows = L.load_rows()
nos, _ = L.product_numbers(rows, [])
groups = {}
for r in sorted(rows, key=lambda r: r["No"]):
    groups.setdefault(r["그룹ID"], []).append(r)
card = lambda slot, code: L.page_items(
    f'<article class="w"><h4><span>우도</span></h4><div class="pic" data-slot="{slot}"><div class="noimg">x</div></div>'
    f'<span class="code">{code}</span></article>')[0]
assert L.card_product(card("images/G0585", "721tm"), groups, nos) == (4052, "G0585")
assert L.card_product(card("images/G0584", "721tk"), groups, nos) == (4051, "G0584")
# 나뉜 카드(-1)는 카드의 품번 행만: G0002 의 TU 줄 → TU-9003 상품
assert L.card_product(card("images/G0002-1", "TU-9003"), groups, nos) == (3804, "G0002")

# 3) Cafe24 내보내기 파일이 있으면 그것이 먼저 (자체 상품코드로 맞춤, 사진은 이미지등록(상세))
ex = [["상품번호", "상품명", "자체상품코드", "이미지등록(상세)"],
      {"상품번호": "9999", "상품명": "아무개", "자체상품코드": "721TM", "이미지등록(상세)": "202601/m.jpg"}]
nos2, hints = L.product_numbers(rows, ex)
assert L.card_product(card("images/G0585", "721tm"), groups, nos2) == (9999, "G0585")
assert hints[9999] == B + "202601/m.jpg"

# 4) 사진이 있는 칸은 절대 안 바꾸고, 빈 칸만 채운다 (가짜로 받기)
with tempfile.TemporaryDirectory() as tmp:
    doc_path = Path(tmp) / "catalog.json"
    full = '<img src="images/G0584.jpg?v=1" alt="">'
    h = (f'<article class="w"><div class="pic" data-slot="images/G0584">{full}</div><span class="code">721tk</span></article>'
         '<article class="g"><div class="pic" data-slot="images/G0585"><div class="noimg">빈 칸</div></div><span class="code">721tm</span></article>')
    doc_path.write_text(json.dumps({"pages": [{"id": "pg-0001", "kind": "content", "html": h, "overlays": []}]}), encoding="utf-8")
    asked = []

    def fake(no, hint, dest, web):
        asked.append(no)
        buf = io.BytesIO()
        Image.new("RGBA", (2400, 1200), (255, 0, 0, 0)).save(buf, "PNG")
        L.save_jpeg(buf.getvalue(), dest)
        return True

    st, report = L.run(doc_path, True, True, rows=rows, export=[], fetch=fake, log=lambda *a: None)
    out = json.loads(doc_path.read_text(encoding="utf-8"))["pages"][0]["html"]
    assert asked == [4052], asked  # 사진 있는 칸은 받으러 가지도 않는다
    assert full in out
    assert '<img src="images/G0585.jpg?v=' in out and "noimg" not in out
    assert 'data-prod="4051"' in out and 'data-prod="4052"' in out
    im = Image.open(Path(tmp) / "images" / "G0585.jpg")
    assert im.format == "JPEG" and im.mode == "RGB" and max(im.size) == 1200 and im.getpixel((5, 5))[0] > 250
    assert (Path(tmp) / "사진_링크_확인.xlsx").is_file() and list((Path(tmp) / "backups").glob("catalog-*.json"))
    # 두 번째 실행: 바뀔 것이 없으면 그대로
    st, _ = L.run(doc_path, True, True, rows=rows, export=[], fetch=fake, log=lambda *a: None)
    assert st["linked"] == 0 and st["added"] == 0 and asked == [4052]

    # 5) 편집기에서 사진을 빼고(파일은 남음) 번호를 7777 로 직접 고친 카드
    #    → 남은 파일은 다시 쓰지 않고 backups 로, 사진은 7777 것으로 새로 받고, 번호는 그대로 (확인 표에 '다름')
    h = ('<article class="g" data-prod="7777"><div class="pic" data-slot="images/G0585"><div class="noimg">빈 칸</div></div>'
         '<span class="code">721tm</span></article>')
    doc_path.write_text(json.dumps({"pages": [{"id": "pg-0001", "kind": "content", "html": h, "overlays": []}]}), encoding="utf-8")
    Image.new("RGB", (10, 10), (0, 0, 255)).save(Path(tmp) / "images" / "G0585.jpg")
    asked.clear()
    st, report = L.run(doc_path, True, True, rows=rows, export=[], fetch=fake, log=lambda *a: None)
    out = json.loads(doc_path.read_text(encoding="utf-8"))["pages"][0]["html"]
    assert asked == [7777] and st["added"] == 1 and st["linked"] == 0, (asked, st)
    assert 'data-prod="7777"' in out and '<img src="images/G0585.jpg?v=' in out
    assert Image.open(Path(tmp) / "images" / "G0585.jpg").getpixel((5, 5))[0] > 250  # 새로 받은 것 (파란 옛 파일 아님)
    old = list((Path(tmp) / "backups" / "images").glob("G0585-*.jpg"))
    assert len(old) == 1 and Image.open(old[0]).getpixel((5, 5))[0] < 10  # 옛 파일은 backups 에
    assert any("7777" in r[-1] and "4052" in r[-1] for r in report), report
    # --relink 일 때만 찾은 번호로 바꾼다
    st, _ = L.run(doc_path, True, True, rows=rows, export=[], fetch=fake, log=lambda *a: None, relink=True)
    out = json.loads(doc_path.read_text(encoding="utf-8"))["pages"][0]["html"]
    assert st["linked"] == 1 and 'data-prod="4052"' in out and asked == [7777]

# 6) 기타 나이프 줄: 제 그룹(G2840 제로 커트러리)에 번호가 없으면 짧은 품번 3400·3000 으로
#    다른 제품(3354 숫돌)에 잇지 않고, 다음 줄로 번지지도 않는다. 맞는 줄은 그대로 잇고 빈 품번 줄로 이어진다
mr = lambda name, code: (f'<div class="mr" data-type="테이블·치즈 나이프"><span>{name}</span><span>테이블·치즈 나이프</span>'
                         f'<span></span><span class="code">{code}</span></div>')
items = L.page_items('<div class="mb">브랜드 미상<small></small></div>'
                     + mr("제로 커트러리 스테이크 포크·나이프", "3400, 3400.7210.0117, 3400.7204S.2115")
                     + mr("", "3000, 3000.7110MP.011, 3000.7190MP.012") + mr("쿠프나이프", "SN48604-SD") + mr("", ""))
got = L.row_products(items, L.code_index(rows), nos)
assert [got[id(it)] for it in items] == [None, None, 3989, 3989], [got[id(it)] for it in items]
# 같은 품번이 두 브랜드에 있으면 쪽의 브랜드 것 (3015: 관경차 G0570, 사카이 타카유키 G0162)
items = L.page_items('<div class="mb">관경차<small></small></div>' + mr("x", "3015"))
assert L.row_products(items, L.code_index(rows), nos)[id(items[0])] == 3852

print("모두 통과")
