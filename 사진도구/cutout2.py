"""누끼 2판: 배경 지우기는 rembg(학습된 모델, 그림자도 배경으로 침), 칼은 한 자루만 가로로 눕히고 칼날이 아래로 오게.
거울 뒤집기는 안 함 (로고 글씨가 거꾸로 보이므로, 사용자 결정 2026-10-28) → 원래 손잡이가 오른쪽인 칼은 손잡이가 오른쪽에 남는다.

    cutout(path, knife=True) -> (RGBA PIL 이미지, 정보 dict)
"""
import cv2
import numpy as np
from PIL import Image
from rembg import new_session, remove

import cutout as old  # 옛 누끼 (바탕색 채우기) — 흰 칼날 대비

_SESSION = None


def _mask(rgb):
    global _SESSION
    if _SESSION is None:
        _SESSION = new_session("isnet-general-use")
    return np.array(remove(Image.fromarray(rgb), session=_SESSION, only_mask=True))


def _parts(solid):
    n, lab, st, _ = cv2.connectedComponentsWithStats(solid, connectivity=8)
    H, W = solid.shape
    out = []
    for i in range(1, n):
        area = st[i, cv2.CC_STAT_AREA]
        if area < solid.size * 0.003:
            continue
        ys, xs = np.nonzero(lab == i)
        (cx, cy), (w, h), _ = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        long, short = max(w, h), max(1.0, min(w, h))
        x, y, bw, bh = st[i, :4]
        touch = (x <= 1) + (y <= 1) + (x + bw >= W - 1) + (y + bh >= H - 1)
        out.append({"id": i, "area": int(area), "long": long, "elong": long / short,
                    "rectness": area / max(1.0, w * h), "touch": int(touch), "cy": cy, "cx": cx})
    return lab, out


def _axis_angle(m):
    """물건의 긴 축 각도(도). 이 각도만큼 돌리면 가로가 된다 (-90 ~ 90)"""
    ys, xs = np.nonzero(m)
    pts = np.column_stack([xs, ys]).astype(np.float64)
    pts -= pts.mean(axis=0)
    _, vecs = np.linalg.eigh(np.cov(pts.T))
    vx, vy = vecs[:, -1]
    a = np.degrees(np.arctan2(vy, vx))
    return (a + 90) % 180 - 90


def _rotate(rgba, ang):
    h0, w0 = rgba.shape[:2]
    M = cv2.getRotationMatrix2D((w0 / 2, h0 / 2), ang, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h0 * sin + w0 * cos) + 2, int(h0 * cos + w0 * sin) + 2
    M[0, 2] += nw / 2 - w0 / 2
    M[1, 2] += nh / 2 - h0 / 2
    return cv2.warpAffine(rgba, M, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


def _crop(rgba):
    ys, xs = np.nonzero(rgba[:, :, 3] > 8)
    return rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def handle_end(rgba):
    """가로로 누운 칼의 손잡이 쪽: 'left' / 'right' / None. 색(손잡이는 칼날보다 어둡거나 색이 있음)으로, 모르면 뭉툭한 끝"""
    a = rgba[:, :, 3] > 127
    L = a.shape[1]
    k = max(1, L // 4)
    hsv = cv2.cvtColor(np.ascontiguousarray(rgba[:, :, :3]), cv2.COLOR_RGB2HSV).astype(np.float32) / 255

    def score(sl):
        m = a[:, sl]
        return 0.0 if m.sum() < 20 else float(hsv[:, sl, 1][m].mean() + (1 - hsv[:, sl, 2][m].mean()))
    left, right = score(slice(0, k)), score(slice(L - k, L))
    if abs(left - right) > 0.06:
        return "right" if right > left else "left"
    e = max(2, L // 25)
    wl, wr = a[:, :e].sum() / e, a[:, -e:].sum() / e   # 칼끝은 뾰족하고 손잡이 끝은 뭉툭하다
    if max(wl, wr) > 1.5 * max(1.0, min(wl, wr)):
        return "left" if wl > wr else "right"
    return None


def edge_down(rgba):
    """칼날이 아래쪽인지: True / False / None(모름). 칼날 몸통은 손잡이 중심선에서 칼날 쪽으로 훨씬 더 나와 있다"""
    a = rgba[:, :, 3] > 127
    he = handle_end(rgba)
    if he is None:
        return None
    if he == "right":
        a = a[:, ::-1]
    L = a.shape[1]
    has = a.any(axis=0)
    T = np.where(has, a.argmax(axis=0), 0).astype(float)
    B = np.where(has, a.shape[0] - 1 - a[::-1].argmax(axis=0), 0).astype(float)
    h, bl = slice(int(L * .05), int(L * .25)), slice(int(L * .45), int(L * .75))
    y_h = ((T[h] + B[h]) / 2).mean()
    above, below = y_h - T[bl].mean(), B[bl].mean() - y_h
    if below > 1.3 * above:
        return True
    if above > 1.3 * below:
        return False
    return None


def cutout(path, knife=True, max_side=2400, prefer="long"):
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)   # 한글 경로도 읽히게
    if img is None:
        return None, {"ok": False, "why": "사진을 못 읽음"}
    h0, w0 = img.shape[:2]
    if max(h0, w0) > max_side:
        f = max_side / max(h0, w0)
        img = cv2.resize(img, (round(w0 * f), round(h0 * f)), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    alpha = _mask(rgb)
    solid = (alpha > 127).astype(np.uint8)
    lab, parts = _parts(solid)
    if not parts:
        return None, {"ok": False, "why": "물건을 못 찾음"}
    info = {"ok": True, "why": ""}
    if knife:
        blades = [p for p in parts if p["elong"] >= 2.6 and p["rectness"] < 0.86 and p["touch"] < 2]
        if prefer == "steel" and blades:                  # 칼과 칼집이 같이 찍힌 사진: 쇠(밝고 색 없음)가 가장 많은 것 = 칼
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            steel = (hsv[:, :, 1] < 40) & (hsv[:, :, 2] > 110)
            pick = max(blades, key=lambda p: steel[lab == p["id"]].mean())
        else:
            pick = max(blades, key=lambda p: p["long"]) if blades else None   # 여러 자루면 가장 긴 것
        # 흰 칼날이 흰 바탕에 묻히면 rembg가 칼날을 놓친다 → 옛 방식(바탕색 채우기)으로 찾은 칼이 더 길면 그걸 쓴다
        med, spread = old._bg(img)
        if spread <= 12 and prefer != "steel":
            fg, _ = old._mask(img, med, 22)
            lab2, parts2 = old._parts(fg)
            b2 = [p for p in parts2 if p["elong"] >= 2.6 and p["rectness"] < 0.86 and p["touch"] < 2]
            p2 = max(b2, key=lambda p: p["long"]) if b2 else None
            if p2 and (pick is None or pick["long"] < 0.85 * p2["long"] or pick["area"] < 0.6 * p2["area"]):
                m2 = (lab2 == p2["id"]).astype(np.uint8)
                cnts, _ = cv2.findContours(m2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                m2 = cv2.drawContours(np.zeros_like(m2), cnts, -1, 1, thickness=cv2.FILLED)
                lab, keep, alpha = m2, [{"id": 1}], cv2.GaussianBlur(m2.astype(np.float32) * 255, (3, 3), 0).astype(np.uint8)
                info["mask"] = "바탕색"
        if pick is None and "mask" not in info:
            return None, dict(info, ok=False, why="칼만 따로 못 찾음(상자·연출 사진)")
        if "mask" not in info:
            keep = [pick]
        info["n_knives"] = len(blades)
    else:
        big = max(p["area"] for p in parts)
        keep = [p for p in parts if p["area"] >= big * 0.03]
    m = np.isin(lab, [p["id"] for p in keep]).astype(np.uint8)
    near = cv2.dilate(m, np.ones((7, 7), np.uint8))       # 고른 물건 둘레의 부드러운 가장자리까지
    a = np.where(near > 0, alpha, 0).astype(np.uint8)
    rgba = np.dstack([rgb, a])
    if knife:
        ang = _axis_angle(m)
        rgba = _crop(_rotate(rgba, ang))
        # 거의 가로로 찍힌 사진은 찍힌 그대로 (상품 사진은 칼날이 아래 — 손잡이가 오른쪽이면 오른쪽 그대로, 사용자 결정).
        # 세워 찍은 사진만 칼날 몸통이 나온 쪽을 보고 칼날이 아래로 오게 (손잡이 위치는 따라감)
        if abs(ang) > 60:
            down = edge_down(rgba)
            turn = down is False or (down is None and handle_end(rgba) == "right")   # 모르면 손잡이 왼쪽 (옛 방식)
        else:
            turn = False
        if turn:
            rgba = np.ascontiguousarray(rgba[::-1, ::-1])  # 180도 돌리기 (거울 아님)
        info.update(angle=round(float(ang), 1), turned=turn)
    return Image.fromarray(_crop(rgba), "RGBA"), info
