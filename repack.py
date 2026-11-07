"""쪽 줄이기 (2026-11): 칼 2단 · 같은 분류는 이어 붙여 쪽을 다시 나눈다. catalog.json 은 건드리지 않고 새 파일을 만든다.
    python repack.py --out 새파일.json [--doc catalog.json] [--story keep|half|drop]

- 칼 크기 표의 '핸들 색상' 칸(전부 비어 있음)을 뺀다 (2단 칸이 좁아서)
- 칼: 같은 브랜드의 시리즈는 이어 붙이고 시리즈가 바뀌는 자리마다 띠(band2)
- 그 밖의 분류: 같은 분류(쪽 머리 맨 위 글) 안에서는 종류·브랜드가 바뀌어도 이어 붙이고 종류마다 띠(band1), 브랜드마다 띠(band2)
- 브랜드 스토리 쪽: keep = 그대로 한 쪽, half = 그 브랜드 첫 쪽 위쪽 100mm 로, drop = 뺌
- 쪽 나누기는 헤드리스 크롬에서 편집기와 같은 넘침 검사(.body scrollHeight)로. 쪽 머리는 그 쪽 내용에 맞춰 다시 쓴다
- 다른 쪽을 가리키던 링크(data-ref)는 그 쪽 첫 제품이 간 쪽으로. 목차·칼 색인은 편집기가 열 때 다시 만든다
"""
import argparse
import html
import json
import re
import subprocess
import tempfile
from pathlib import Path

import catalog_doc as cd

BASE = Path(__file__).resolve().parent

JS = r"""
try { (function () {
const DOC = JSON.parse(document.getElementById('doc').textContent), STORY = document.getElementById('opt').textContent;
const P = DOC.pages, KNIFE = '칼';
const frag = h => { const t = document.createElement('template'); t.innerHTML = h; return t.content; };
const txt = el => el ? el.textContent.replace(/\s+/g, ' ').trim() : '';
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const isStory = p => p.html.indexOf('class="story') >= 0;

function stripHandle(root) {            // 칼 표: 2단 칸이 좁아서 '핸들 색상' 칸은 비었으면 빼고, 색 네모가 있으면 '색상' 으로 좁게
  root.querySelectorAll('article.w .t').forEach(t => {
    const heads = [...t.children].filter(e => e.tagName === 'B'), cells = [...t.children].filter(e => e.tagName !== 'B');
    if (heads.length !== 3 || txt(heads[0]) !== '핸들 색상') return;
    const col = cells.filter((c, k) => k % 3 === 0);
    if (col.some(c => c.innerHTML.trim())) {
      heads[0].textContent = '색상';
      t.setAttribute('style', 'grid-template-columns:9mm 15mm minmax(0,1fr)');
      return;
    }
    heads[0].remove(); col.forEach(c => c.remove());
    t.setAttribute('style', 'grid-template-columns:16mm minmax(0,1fr)');
  });
}
function info(p) {
  const f = frag(p.html), h = f.querySelector('header.ph'), crumb = h.querySelector('.crumb'), c2 = crumb.cloneNode(true);
  if (c2.querySelector('span')) c2.querySelector('span').remove();
  const tb = h.querySelector('.ttl b'), ts = h.querySelector('.ttl span'), right = h.querySelector('.right');
  stripHandle(f);
  const brand = txt(right && right.querySelector('b'));
  return { ch: txt(c2), chHTML: crumb.innerHTML, title: txt(tb), titleHTML: tb ? tb.innerHTML : '', span: ts ? ts.innerHTML : '',
    spanText: txt(ts), rightHTML: right ? right.innerHTML : '', brand: /^미분류/.test(brand) ? '' : brand,
    body: [...f.children].find(e => e.classList.contains('body')), tail: p.html.slice(p.html.lastIndexOf('<footer')), style: p.style || '', key: h.outerHTML, id: p.id };
}

// ── 1) 쪽 → 덩어리(묶음별 제품 칸·표 줄) 를 달리기(run) 로
const runs = [];     // {knife, items:[...]} 또는 {page}
const dropped = [];  // 빠진 스토리 쪽 id (링크를 다음 제품 쪽으로)
let cur = null, prevKey = null, title = null, sub = null, en = {};
P.forEach(p => {
  const content = p.kind === 'content' && p.html.indexOf('<header class="ph">') >= 0;
  if (!content || (isStory(p) && STORY === 'keep')) { runs.push({ page: p }); cur = null; prevKey = null; return; }
  const s = info(p), knife = s.ch === KNIFE, runKey = s.ch + '\u0000' + (knife ? s.title : '');
  if (!cur || cur.key !== runKey || cur.style !== s.style) { cur = { key: runKey, knife, style: s.style, items: [] }; runs.push(cur); prevKey = null; }
  if (isStory(p)) {
    if (STORY === 'drop') { dropped.push(p.id); return; }
    const sec = s.body.querySelector('section.story');
    sec.className = 'story half'; sec.setAttribute('style', 'height:100mm');
    cur.items.push({ html: sec.outerHTML, seg: s, title: s.title, sub: '', page: p.id, story: true });
    prevKey = null; return;
  }
  if (s.key !== prevKey) {              // 새 묶음: 머리글에서 종류(제목)·시리즈/브랜드
    const multi = s.title.indexOf(' · ') >= 0;
    title = multi ? null : s.title;
    if (!multi && !knife) en[title] = s.spanText.replace(/^_\s*/, '');
    sub = knife ? s.spanText.replace(/^_\s*/, '') : s.brand;
  }
  prevKey = s.key;
  [...s.body.children].forEach(el => {
    if (el.classList.contains('band1')) { title = txt(el.querySelector('span')); en[title] = txt(el.querySelector('small')); return; }
    if (el.classList.contains('band2')) { sub = txt(el); return; }
    cur.items.push({ html: el.outerHTML, seg: s, title: knife ? s.title : title, sub, page: p.id });
  });
});

// ── 2) 띠 다시 달기: 칼은 시리즈가 바뀔 때 band2, 그 밖은 종류가 바뀔 때 band1 · 브랜드가 바뀔 때 band2
runs.forEach(r => {
  if (!r.items) return;
  const out = []; let lt = null, ls = null;
  r.items.forEach(it => {
    if (it.story) { out.push(it); lt = it.title; ls = null; return; }
    if (!r.knife && it.title !== lt) {
      out.push({ band: 1, html: '<div class="band1"><span>' + esc(it.title || '') + '</span><small>' + esc(en[it.title] || '') + '</small></div>', seg: it.seg, title: it.title, sub: it.sub });
      ls = null;
    }
    if (it.sub && it.sub !== ls) out.push({ band: 2, html: '<div class="band2">' + esc(it.sub) + '</div>', seg: it.seg, title: it.title, sub: it.sub });
    lt = it.title; ls = it.sub; out.push(it);
  });
  r.items = out;
});

// ── 3) 쪽 나누기 (편집기 flowCount 와 같은 검사: .body 가 넘치면 마지막 덩어리를 다음 쪽으로, 띠만 남지 않게)
const body = document.querySelector('#mb .body');
const over = () => body.scrollHeight > body.clientHeight + 1;
function paginate(items) {
  const pages = []; let pg = [];
  body.innerHTML = '';
  items.forEach(it => {
    body.insertAdjacentHTML('beforeend', it.html);
    if (pg.length && over()) {
      const moved = [];
      while (pg.length > 1 && pg[pg.length - 1].band) moved.unshift(pg.pop());
      pages.push(pg); pg = moved;
      body.innerHTML = pg.map(x => x.html).join('') + it.html;
    }
    pg.push(it);
  });
  if (pg.length) pages.push(pg);
  return pages;
}

// ── 4) 쪽 머리: 그 쪽 내용대로
const uniq = a => a.filter((x, i) => x && a.indexOf(x) === i);
function build(pg, knife) {
  const s0 = pg.find(x => !x.band).seg, titles = uniq(pg.map(x => x.title)), subs = uniq(pg.map(x => x.sub));
  const allSub = subs.length === 1 && pg.every(x => x.sub === subs[0]);
  let b, span = '', right;
  if (knife) {
    b = s0.titleHTML; right = s0.rightHTML;
    if (allSub) { span = '_' + esc(subs[0]); if (pg[0].band === 2) pg = pg.slice(1); }
  } else {
    if (titles.length === 1) {
      const t = titles[0], same = pg.find(x => x.seg.title === t);
      b = same ? same.seg.titleHTML : esc(t); span = same ? same.seg.span : '_ ' + esc(en[t] || '');
      if (pg[0].band === 1) pg = pg.slice(1);
    } else b = esc(titles.join(' · '));
    const rights = uniq(pg.map(x => x.seg.rightHTML));
    right = pg.every(x => x.seg.rightHTML === pg[0].seg.rightHTML) ? pg[0].seg.rightHTML : '';
    if (right && allSub && pg[0].band === 2) pg = pg.slice(1);
  }
  const h = '<header class="ph"><p class="crumb">' + s0.chHTML + '</p><p class="ttl"><b>' + b + '</b><span>' + span + '</span></p><div class="right">' +
    right + '</div></header><div class="body">' + pg.map(x => x.html).join('') + '</div>' + s0.tail;
  return { pg, html: h, style: s0.style };
}

// ── 5) 새 쪽 목록 (id 는 되도록 옛 쪽 것을 다시 씀)
const used = new Set(), out = [], firstOf = {};
let nextId = Number(DOC.meta.nextId) || P.length + 1;
const allIds = new Set(P.map(p => p.id));
const newId = () => { let id; do { id = 'pg-' + String(nextId++).padStart(4, '0'); } while (allIds.has(id) || used.has(id)); return id; };
let pendingDrop = [];
runs.forEach(r => {
  if (r.page) { out.push(r.page); used.add(r.page.id); return; }
  const olds = uniq(r.items.map(x => x.page));
  paginate(r.items).forEach(pg => {
    const b = build(pg, r.knife), cand = [pg.find(x => !x.band).page, ...olds].find(id => !used.has(id)) || newId();
    used.add(cand);
    b.pg.forEach(x => { if (x.page && !(x.page in firstOf)) firstOf[x.page] = cand; });
    out.push({ id: cand, kind: 'content', cls: '', style: b.style, html: b.html, overlays: [] });
  });
});
// 빠진 스토리 쪽 → 바로 뒤 쪽
P.forEach((p, i) => { if (dropped.indexOf(p.id) >= 0) { const n = P.slice(i + 1).find(q => firstOf[q.id]); if (n) firstOf[p.id] = firstOf[n.id]; } });
const keep = new Set(out.map(p => p.id));
out.forEach(p => { p.html = p.html.replace(/data-ref="([^"]+)"/g, (m, id) => keep.has(id) || !firstOf[id] ? m : 'data-ref="' + firstOf[id] + '"'); });
// 온라인 책은 짝수 쪽: 뒤쪽 빈 쪽으로 맞춤
const bi = out.map(p => p.kind).lastIndexOf('blank');
if (out.length % 2 && bi >= 0 && !(out[bi].overlays || []).length) out.splice(bi, 1);
else if (out.length % 2) { const last = out[out.length - 1], blank = { id: newId(), kind: 'blank', cls: '', style: last.style || '', html: '', overlays: [] }; out.splice(out.length - 1, 0, blank); }
DOC.pages = out; DOC.meta.nextId = nextId;
document.body.innerHTML = '<pre id="out">' + esc(JSON.stringify(DOC)) + '</pre>';
})(); } catch (e) { document.body.innerHTML = '<pre id="err"></pre>'; document.getElementById('err').textContent = e.stack; }
"""


def repack(doc, story="keep", css=""):
    css = (BASE / "editor_assets" / "catalog.css").read_text(encoding="utf-8") + css
    js = lambda o: json.dumps(o, ensure_ascii=False).replace("</", "<\\/")
    page = ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            "<meta http-equiv=\"Content-Security-Policy\" content=\"img-src 'none'\">"   # 사진 칸 높이는 고정이라 사진은 안 읽음
            f"<style>{css}</style></head><body>"
            '<div id="mb" class="final"><section class="page"><header class="ph"></header><div class="body"></div></section></div>'
            f'<script type="application/json" id="doc">{js(doc)}</script><script type="text/plain" id="opt">{story}</script>'
            f"<script>{JS}</script></body></html>")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "repack.html"
        f.write_text(page, encoding="utf-8")
        r = subprocess.run([cd.find_browser(), "--headless=new", "--disable-gpu", f"--user-data-dir={Path(tmp) / 'p'}",
                            "--virtual-time-budget=5000", "--dump-dom", f.as_uri()], capture_output=True, timeout=900)
    dom = r.stdout.decode("utf-8", "replace")
    m = re.search(r'<body><pre id="out">(.*?)</pre>', dom, re.S)
    if not m:
        err = re.search(r'<pre id="err">(.*?)</pre>', dom, re.S)
        raise SystemExit("크롬에서 쪽 나누기를 못 했습니다:\n" + (html.unescape(err.group(1)) if err else r.stderr.decode("utf-8", "replace")[-2000:]))
    return json.loads(html.unescape(m.group(1)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default=str(BASE / "catalog.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--story", choices=("keep", "half", "drop"), default="keep")
    ap.add_argument("--css", help="catalog.css 뒤에 더해서 잴 css (미리 재 볼 때만)")
    a = ap.parse_args()
    doc = json.load(open(a.doc, encoding="utf-8"))
    n0 = len(doc["pages"])
    new = repack(doc, a.story, Path(a.css).read_text(encoding="utf-8") if a.css else "")
    Path(a.out).write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
    print(f"{n0}쪽 → {len(new['pages'])}쪽")
