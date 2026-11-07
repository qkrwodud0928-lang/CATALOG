"""인쇄용 PDF 점검 (두 권·글꼴·재단 여유·목차 번호)

    python -X utf8 print_check.py [문서.json] [출력 폴더]

문서 "사본"으로 두 권을 출력 폴더(안 주면 임시 폴더)에 만들고 pymupdf 로 검사한다. 진짜 인쇄 폴더는 건드리지 않는다.
"""
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pymupdf

import catalog_doc as c

MM = 72 / 25.4


def words_lines(page, clip):
    """clip 안 낱말을 줄로 묶기 (가운데 높이가 3pt 안이면 같은 줄)"""
    lines = []
    for w in sorted(page.get_text("words", clip=clip), key=lambda w: (w[1] + w[3]) / 2):
        y = (w[1] + w[3]) / 2
        if lines and y - lines[-1][0] < 3:
            lines[-1][1].append(w)
        else:
            lines.append([y, [w]])
    return [sorted(ws, key=lambda w: w[0]) for _, ws in lines]


def toc_entries(page, number, n):
    """목차 쪽에서 (이름, 쪽 번호). 번호는 단 오른쪽 끝에 붙어 있다 (n단이 글 폭 186mm 를 나눠 가짐, 단 사이 7mm)"""
    left = (3 + (15 if number % 2 else 9)) * MM
    colw = (186 - 7 * (n - 1)) / n * MM
    rights = [left + k * (colw + 7 * MM) + colw for k in range(n)]
    out = []
    for ws in words_lines(page, pymupdf.Rect(0, 38 * MM, page.rect.width, page.rect.height - 15 * MM)):
        for w in ws:
            r = next((r for r in rights if abs(w[2] - r) < 1.5 * MM), None)
            if r is not None and w[4].isdigit():
                name = "".join(v[4] for v in ws if r - colw - 1 <= v[0] and v[2] < w[0])
                out.append((name, int(w[4])))
    return out


def norm(s):
    return re.sub(r"\s+", "", s).split("…")[0]


def check_pdf(path, sub, chapters):
    d = pymupdf.open(path)
    assert d.page_count == len(sub["pages"]) and d.page_count % 2 == 0, (path.name, d.page_count, len(sub["pages"]))
    fonts = {}
    for p in d:
        assert abs(p.rect.width - 216 * MM) <= 0.5 and abs(p.rect.height - 303 * MM) <= 0.5, (path.name, p.number, p.rect)
        for f in p.get_fonts():
            fonts[f[0]] = f
    for xref, ext, ftype, basefont, *_ in fonts.values():
        assert ftype != "Type3", (path.name, "Type3 글꼴", xref)
        assert ext != "n/a" and basefont, (path.name, "안 박힌 글꼴/이름 없음", xref, ext, basefont)
    # 쪽 머리 분류: 그 권의 분류(와 목차의 SINDO)만
    for p in d:
        crumb = " ".join(p.get_text("text", clip=pymupdf.Rect(0, 10 * MM, p.rect.width, 17 * MM)).split())
        if crumb:
            assert any(crumb.startswith(ch + " ") for ch in chapters | {"SINDO"}), (path.name, p.number + 1, crumb)
    # 목차 번호 → 그 쪽 머리(또는 그 쪽)에 항목 이름
    want = sum(len(re.findall(r'<a class="(?:ch|it)"', q["html"])) for q in sub["pages"] if q.get("kind") == "toc")
    got, in_head = [], 0
    for p in d:
        if "목차" in p.get_text("text", clip=pymupdf.Rect(0, 15 * MM, p.rect.width, 30 * MM)):
            got += toc_entries(p, p.number + 1, sub["pages"][p.number]["html"].count('class="tcol"'))
    assert len(got) == want, (path.name, "목차 항목 수", len(got), want)
    for name, n in got:
        t = d[n - 1]
        head = norm(t.get_text("text", clip=pymupdf.Rect(0, 0, t.rect.width, 38 * MM)))
        assert norm(name) in head or norm(name) in norm(t.get_text("text")), (path.name, name, n)
        in_head += norm(name) in head
    assert in_head >= 10, (path.name, "머리에서 찾은 목차 항목", in_head)
    return len(fonts), len(got), in_head, sorted({f[3].split("+")[-1] for f in fonts.values()})


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else c.BASE / "catalog.json"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(tempfile.mkdtemp(prefix="print_check_"))
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, out / "catalog_copy.json")
    doc = c.load_doc(out / "catalog_copy.json")

    # 목차 단 나누기 규칙 (editor.js tocPages 와 같음): 대분류 뒤 40개까지 한 단
    cols = c.toc_pages([(True, "a")] + [(False, "b")] * 41)
    assert [len(col) for col in cols[0]] == [41, 1], cols
    assert len(c.toc_pages([(False, "b")] * 43 * 3 + [(False, "b")])) == 2

    # 권 나누기: 본문 쪽은 한 권에만, 앞쪽(표지 등)은 두 권 모두, 다른 권으로 가는 번호는 '?' 가 아니게
    vols = c.split_volumes(doc)
    assert [v[0] for v in vols] == [v[0] for v in c.VOLUMES]
    seen = [q["id"] for _, _, sub in vols for q in sub["pages"] if q.get("kind") not in ("cover", "toc")]
    assert sorted(seen) == sorted(p["id"] for p in doc["pages"] if p.get("kind") not in ("cover", "toc")), "빠지거나 겹친 쪽"
    chapters = [{c.chapter_of(q) for q in sub["pages"]} - {""} for _, _, sub in vols]
    assert chapters[0] == {"칼"} and "칼" not in chapters[1], chapters
    for _, _, sub in vols:
        body = c.print_html(sub).split("<body", 1)[1]
        assert not re.search(r'class="[^"]*\bbroken\b', body) and '"pref">?<' not in body

    res = c.make_print_pdfs(doc, c.BASE, out)
    print("만든 파일:", res["files"], "\n안내:", res["notes"])
    vols = {name: (sub, ch) for (name, _, sub), ch in zip(c.split_volumes(doc), chapters)}
    for f in res["files"]:
        if f["name"] in vols:
            sub, ch = vols[f["name"]]
            sub = dict(sub, pages=sub["pages"] + [{}] * (-len(sub["pages"]) % 2))
            print(f["name"], f["pages"], "쪽 · 글꼴 %d개 · 목차 %d항목 (머리에서 %d개) · %s" % check_pdf(out / f["name"], sub, ch))

    # 표지: 가짜 작업 폴더에 그림을 두고 작은 문서로
    fake = out / "cover_base"
    (fake / c.COVER_DIR).mkdir(parents=True, exist_ok=True)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 216, 303), 0)
    for k, name in enumerate(("1권_앞표지", "1권_뒤표지", "2권_앞표지")):
        pix.clear_with(60 + 60 * k)
        pix.save(fake / c.COVER_DIR / f"{name}.png")
    # 편집기 서버의 api_pdf 로 (작업 폴더만 가짜로 바꿔서), 재단선 켜고 4의 배수로
    import editor_server as es
    from urllib.parse import urlsplit
    small = dict(doc, pages=doc["pages"][:4] + doc["pages"][-2:])
    es.BASE, es.CFG["open_results"] = fake, False
    status, res, _ = es.Handler.api_pdf(type("H", (), {"load": lambda self: small})(), urlsplit("/api/pdf?marks=1&multiple=4"))
    assert status == 200 and res["ok"] and res["path"] == str(fake / "인쇄") and res["pages"] == sum(f["pages"] for f in res["files"]), res
    v = pymupdf.open(fake / "인쇄" / c.VOLUMES[0][0])  # 재단선: 종이 사방 10mm 더
    assert abs(v[0].rect.width - 236 * MM) <= 0.5 and abs(v[0].rect.height - 323 * MM) <= 0.5, v[0].rect
    assert all(f[2] != "Type3" for p in v for f in p.get_fonts())
    names = [f["name"] for f in res["files"]]
    assert "인쇄용_1권_표지.pdf" in names and "인쇄용_2권_표지.pdf" not in names, names
    assert any("2권_뒤표지" in n for n in res["notes"]), res["notes"]
    assert (fake / c.COVER_DIR / "읽어보세요.txt").is_file()
    assert all(f["pages"] % 4 == 0 for f in res["files"] if "표지" not in f["name"]), res["files"]
    cv = pymupdf.open(fake / "인쇄" / "인쇄용_1권_표지.pdf")
    assert cv.page_count == 2 and all(abs(p.rect.width - 216 * MM) <= 0.5 and abs(p.rect.height - 303 * MM) <= 0.5 for p in cv)
    print("표지:", names, res["notes"])
    print("ok →", out)


if __name__ == "__main__":
    main()
