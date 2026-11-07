"""검은 바탕 칼 사진 누끼 (사카이 타카유키 등): 밝은 칼만 남기고 검은 바탕은 투명하게, 칼은 가로로.
python darkcut.py <칸들...> → dark/<칸>.webp + dark_sheet.jpg (확인용)"""
import sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cutout2 as c2  # noqa: E402
CAT = Path(r"C:\Users\박재영\CATALOG")


def darkcut(path):
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    dark = rgb.max(axis=2) < 30                           # 흰 바탕 + 상자 라벨 옆에 검은 네모가 있는 사진: 검은 네모만 남김
    cols, rows = np.nonzero(dark.mean(axis=0) > .5)[0], np.nonzero(dark.mean(axis=1) > .5)[0]
    if len(cols) and len(rows):
        rgb = np.ascontiguousarray(rgb[rows.min():rows.max() + 1, cols.min():cols.max() + 1])
    H, W = rgb.shape[:2]
    lit = (rgb.max(axis=2) > 38).astype(np.uint8)
    k = max(5, int(max(H, W) * .02)) | 1                 # 검은 손잡이 고리(물소뿔) 틈을 메울 만큼
    m = cv2.morphologyEx(lit, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    lab, parts = c2._parts(m)
    blades = [p for p in parts if p["elong"] >= 2.0 and p["touch"] < 2]   # 데바는 날이 넓어 2.0까지
    if not blades:
        return None
    pick = max(blades, key=lambda p: p["long"])
    one = (lab == pick["id"]).astype(np.uint8)
    cnts, _ = cv2.findContours(one, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    one = cv2.drawContours(np.zeros_like(one), cnts, -1, 1, thickness=cv2.FILLED)
    alpha = cv2.GaussianBlur(one.astype(np.float32) * 255, (3, 3), 0).astype(np.uint8)
    rgba = np.dstack([rgb, alpha])
    ang = c2._axis_angle(one)
    rgba = c2._crop(c2._rotate(rgba, ang))
    if abs(ang) > 60:
        down = c2.edge_down(rgba)
        if down is False or (down is None and c2.handle_end(rgba) == "right"):
            rgba = np.ascontiguousarray(rgba[::-1, ::-1])
    return Image.fromarray(c2._crop(rgba), "RGBA")


if __name__ == "__main__":
    out = HERE / "dark"
    out.mkdir(exist_ok=True)
    slots = sys.argv[1:]
    font = ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf", 14)
    sheet = Image.new("RGB", (900, 110 * len(slots)), "white")
    dr = ImageDraw.Draw(sheet)
    for i, s in enumerate(slots):
        src = next((p for p in (CAT / "backups" / "images" / "검수전" / f"{s}.jpg", CAT / "images" / f"{s}.jpg") if p.exists()), None)
        im = darkcut(src) if src else None
        dr.text((4, i * 110 + 2), s + ("" if im else "  (못 땀)"), font=font, fill=(200, 0, 0))
        if im is None:
            continue
        im.save(out / f"{s}.webp", "WEBP", quality=90, method=4)
        t = im.copy()
        t.thumbnail((880, 85))
        sheet.paste(t, (10, i * 110 + 20), t)
    sheet.save(HERE / "dark_sheet.jpg", quality=82)
    print("done")
