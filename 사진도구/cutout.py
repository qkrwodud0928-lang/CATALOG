"""상품 사진 → 배경 없는(투명) 그림. 칼은 한 자루만 골라 가로로 눕힌다 (손잡이 왼쪽, 칼끝 오른쪽).

    cutout(path, knife=True) -> (RGBA PIL 이미지, 정보 dict)
배경이 한 가지 색(흰색·회색·검정)일 때만 자신 있게 처리하고, 아니면 info["ok"]=False 로 알려 준다.
(누끼 2판 cutout2.py 가 흰 칼날을 놓칠 때 이 파일의 _bg·_mask·_parts 를 쓴다)
"""
import cv2
import numpy as np
from PIL import Image


def _bg(img):
    b = np.concatenate([img[:3].reshape(-1, 3), img[-3:].reshape(-1, 3), img[:, :3].reshape(-1, 3), img[:, -3:].reshape(-1, 3)])
    med = np.median(b, axis=0)
    spread = np.median(np.linalg.norm(b.astype(float) - med, axis=1))
    return med, spread


def _mask(img, med, tol):
    dist = np.linalg.norm(img.astype(np.float32) - med.astype(np.float32), axis=2)
    near = (dist < tol).astype(np.uint8)
    n, lab = cv2.connectedComponents(near, connectivity=4)
    edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    edge = edge[edge > 0]
    bg = np.isin(lab, edge)
    fg = (~bg).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return fg, dist


def _parts(fg, min_frac=0.004):
    n, lab, st, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    total = fg.size
    out = []
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < total * min_frac:
            continue
        ys, xs = np.nonzero(lab == i)
        (cx, cy), (w, h), ang = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        long, short = max(w, h), max(1.0, min(w, h))
        x, y, bw, bh = st[i, cv2.CC_STAT_LEFT], st[i, cv2.CC_STAT_TOP], st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
        H, W = fg.shape
        touch = (x <= 1) + (y <= 1) + (x + bw >= W - 1) + (y + bh >= H - 1)
        out.append({"id": i, "area": int(st[i, cv2.CC_STAT_AREA]), "long": long, "elong": long / short,
                    "rectness": st[i, cv2.CC_STAT_AREA] / max(1.0, w * h), "touch": int(touch), "rect": ((cx, cy), (w, h), ang)})
    return lab, out
