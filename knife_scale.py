"""칼 사진 크기를 칼 길이에 맞게 (사용자 요청 2026-10-28: 페티는 작게, 규토는 크게 — 적당히 차이)

    python knife_scale.py --doc catalog.json            넣기 (편집기가 꺼져 있을 때)
    python knife_scale.py --doc catalog.json --dry-run  미리보기

칼 카드(.w)의 누끼 사진 칸에 style="--kw:NN%" 를 단다 (catalog.css: .w .pic img{width:var(--kw)}).
사진 칸에 달아 두므로 편집기에서 사진을 바꿔도 크기는 남는다. 연출 사진(jpg)은 칸 폭 그대로.
날 길이(표의 mm 중 가장 긴 것) + 손잡이 어림값 = 전체 길이 → 칸 폭에 대한 비율. 차이를 조금 줄이려고 0.75 제곱.
"""
import argparse
import json
import re
import sys
from pathlib import Path

REF_MM = 450          # 이 길이(날 300 + 손잡이 150) 이상이면 칸 폭 가득
MIN_W, DEFAULT_W = 42, 80


def handle_mm(blade):
    return min(150, max(90, 0.35 * blade + 60))


def width_pct(blade):
    if not blade:
        return DEFAULT_W
    total = blade + handle_mm(blade)
    return round(min(100, max(MIN_W, 100 * (total / REF_MM) ** 0.75)))


def blade_mm(card):
    t = re.search(r'<div class="t".*?</div>', card, re.S)
    nums = [int(n) for n in re.findall(r'(\d{2,3})\s*mm', t.group(0) if t else "")]
    if not nums:
        h = re.search(r"<h4>.*?</h4>", card, re.S)
        nums = [int(n) for n in re.findall(r'(\d{2,3})\s*mm', h.group(0) if h else "", re.I)]
    nums = [n for n in nums if 50 <= n <= 450]
    return max(nums) if nums else None


def scale_card(card):
    pic = re.search(r'<div class="pic"[^>]*>', card)
    if not pic:
        return card
    tag = re.sub(r'\s*style="[^"]*"', "", pic.group(0))
    if re.search(r'<img src="[^"]+\.webp', card):
        tag = tag[:-1] + f' style="--kw:{width_pct(blade_mm(card))}%">'
    return card[:pic.start()] + tag + card[pic.end():]


def apply(doc):
    n = 0
    for p in doc["pages"]:
        new = re.sub(r'<article class="w[" ].*?</article>', lambda m: scale_card(m.group(0)), p["html"], flags=re.S)
        n += new != p["html"]
        p["html"] = new
    return n


def demo():
    assert width_pct(65) == 45 and width_pct(300) == 100 and width_pct(None) == DEFAULT_W
    assert width_pct(65) < width_pct(150) < width_pct(210) < width_pct(270)
    c = ('<article class="w"><h4>x</h4><div class="main"><div class="pic" data-slot="images/A"><img src="images/A.webp?v=1" alt="">'
         '</div><div class="t"><b>날 길이</b><span>180 mm</span><span>240 mm</span></div></div></article>')
    assert 'style="--kw:%d%%"' % width_pct(240) in scale_card(c)
    assert scale_card(scale_card(c)) == scale_card(c)
    assert "--kw" not in scale_card(c.replace(".webp", ".jpg"))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    demo()
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default="catalog.json")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    path = Path(a.doc)
    doc = json.load(open(path, encoding="utf-8"))
    n = apply(doc)
    print(f"칼 사진 크기 맞춘 쪽: {n}쪽 (페티 65mm → {width_pct(65)}%, 규토 210mm → {width_pct(210)}%, 300mm → {width_pct(300)}%)")
    if not a.dry_run:
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        print("저장했습니다:", path.name)
