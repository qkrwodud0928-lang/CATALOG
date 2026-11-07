/* 신도 카탈로그 책 보기 (viewer.html)
   - 책: StPageFlip. 쪽마다 껍데기 div.leaf 를 두고, 지금 보는 쪽 앞뒤 4쪽에만 실제 쪽을 그린다.
   - 확대: 휠·두 손가락·두 번 누르기·버튼·키보드. 확대 중에는 #shield 가 포인터를 받아 끌기로 이동한다.
   - 검색: 처음 검색할 때 모든 쪽의 글자를 모아 둔다. 공백·하이픈·점을 빼고 비교 (TU-9003 = tu9003). */
(function () {
  'use strict';

  var R = window.CatalogRender;
  var doc = window.CATALOG_DATA;
  function $(s) { return document.querySelector(s); }
  var loading = $('#loading');

  function fail(msg) { loading.textContent = msg; loading.classList.add('vb-error'); }
  if (!R || !window.St) return fail('책 보기 파일(editor_assets 폴더)을 읽지 못했습니다. 폴더를 통째로 올렸는지 확인해 주세요.');
  if (!doc || !Array.isArray(doc.pages) || !doc.pages.length) {
    return fail('카탈로그 자료(catalog.js)를 읽지 못했습니다. catalog.js 파일이 이 화면과 같은 폴더에 있는지 확인해 주세요.');
  }

  var pages = doc.pages, N = pages.length;
  var nums = R.numberMap(doc);
  var NEAR = 4;            // 지금 쪽 앞뒤로 내용을 그려 둘 쪽 수
  var ZMAX = 4, ZSTEP = 1.4;
  var stage = $('#stage'), zoomer = $('#zoomer'), book = $('#book'), shield = $('#shield');
  var pnoBtn = $('#pnoBtn'), pnoInput = $('#pnoInput'), slider = $('#slider'), sliderLabel = $('#sliderLabel');
  var qInput = $('#q'), results = $('#results');
  slider.max = pnoInput.max = N;   // 첫 flip 이벤트(loadFromHTML 안)보다 먼저: 안 그러면 slider.value 가 1 로 잘린다
  var cur = 0;
  var z = 1, tx = 0, ty = 0;   // 확대 배율과 이동(px)
  var titles = [];
  function title(i) { return titles[i] || (titles[i] = R.pageTitle(pages[i])); }

  /* ── 쪽 껍데기와 필요한 쪽만 그리기 ── */
  var leaves = pages.map(function () { var d = document.createElement('div'); d.className = 'leaf'; return d; });
  var drawn = new Set();

  function drawAround(c, keep) {
    var lo = Math.max(0, c - NEAR), hi = Math.min(N - 1, c + NEAR + 1);   // +1: 펼친 면의 오른쪽 쪽
    if (!keep) drawn.forEach(function (i) { if (i < lo || i > hi) { leaves[i].textContent = ''; drawn.delete(i); } });
    for (var i = lo; i <= hi; i++) {
      if (drawn.has(i)) continue;
      leaves[i].appendChild(R.createPageElement(pages[i], i, nums));
      drawn.add(i);
    }
  }

  function hashPage() {
    var m = /p=(\d+)/.exec(location.hash);
    return m ? Math.max(0, Math.min(N - 1, parseInt(m[1], 10) - 1)) : 0;
  }

  var start = hashPage();
  drawAround(start);

  var pf = new St.PageFlip(book, {
    width: 794, height: 1123, size: 'stretch',
    minWidth: 280, maxWidth: 1200, minHeight: 400, maxHeight: 1700,
    showCover: true, usePortrait: true, drawShadow: true, maxShadowOpacity: 0.5, flippingTime: 700,
    showPageCorners: true, mobileScrollSupport: false, clickEventForward: true,
    autoSize: false,          // 책 크기를 가운데 영역(#book)에 맞춘다. true 면 폭 기준이라 세로가 화면을 넘친다
    disableFlipByClick: true, // 쪽 가운데를 눌러도 넘어가지 않음(두 번 눌러 확대와 겹치지 않게). 모서리 누르기·끌기·버튼으로 넘긴다
    startPage: start
  });

  function fitScale() { book.style.setProperty('--s', String(pf.getBoundsRect().pageWidth / R.PAGE_W_PX)); }

  function onPage(c) {
    cur = c;
    fitScale();
    drawAround(c);
    var two = pf.getOrientation() === 'landscape' && c > 0 && c < N - 1;
    pnoBtn.textContent = (c + 1) + (two ? '–' + (c + 2) : '') + ' / ' + N;
    slider.value = c + 1;
    sliderLabel.textContent = (c + 1) + '쪽 · ' + title(c);
    try { history.replaceState(null, '', '#p=' + (c + 1)); } catch (e) { /* file:// 등에서 막히면 무시 */ }
  }

  pf.on('flip', function (e) { onPage(e.data); });
  pf.on('init', function () { fitScale(); loading.hidden = true; });
  // 세로로 긴 화면(태블릿 세로 등)은 한 쪽씩 크게. StPageFlip 은 '책 폭 < 2×minWidth' 일 때만 한 쪽으로 보므로
  // 그때만 minWidth 를 올린다. StPageFlip 의 resize 처리보다 먼저 돌도록 loadFromHTML 앞에서 등록.
  function pickOrientation() { pf.getSettings().minWidth = book.clientWidth < book.clientHeight ? book.clientWidth / 2 + 1 : 280; }
  window.addEventListener('resize', pickOrientation);
  pickOrientation();
  pf.loadFromHTML(leaves);
  window.addEventListener('resize', function () { setZoom(1); fitScale(); });   // StPageFlip 의 resize 처리 뒤에 실행된다

  // StPageFlip 2.0.7 의 flipNext/flipPrev 는 고정 좌표(x:10, y:1)를 "누른 것"으로 넘긴다. disableFlipByClick 이면
  // 그 점이 책 모서리 안이어야 하는데, 책이 가운데 놓이면(위·옆 여백) 모서리 밖이 되어 이전/다음이 안 된다.
  // → 지금 책의 실제 모서리 점으로 넘기게 바꾼다 (버튼·키보드·스와이프·flip(i) 가 모두 이 두 함수를 거친다).
  var fc = pf.getFlipController();
  function cornerPoint(next, c) {
    var r = pf.getBoundsRect();
    return { x: next ? r.left + r.width - 10 : r.left + 10, y: c === 'bottom' ? r.top + r.height - 2 : r.top + 1 };
  }
  fc.flipNext = function (c) { fc.flip(cornerPoint(true, c)); };
  fc.flipPrev = function (c) { fc.flip(cornerPoint(false, c)); };

  /* ── 쪽 이동 ── */
  function go(i, animate) {
    i = Math.max(0, Math.min(N - 1, i | 0));
    setZoom(1);
    // 넘기는 중이면 먼저 끝낸다 (안 그러면 끝나는 순간 한 장 더 넘어가 엉뚱한 쪽이 된다)
    if (pf.getState() === 'flipping') pf.getRender().finishAnimation();
    drawAround(i, true);
    if (animate !== false && Math.abs(i - cur) <= 6) pf.flip(i);
    else pf.turnToPage(i);
    if (pf.getState() === 'read') drawAround(cur);   // 넘김 없이 끝났으면 더 그린 쪽을 정리
  }
  function next() { setZoom(1); pf.flipNext(); }
  function prev() { setZoom(1); pf.flipPrev(); }

  var tocIndex = pages.findIndex(function (p) { return p.kind === 'toc'; });
  if (tocIndex < 0) $('#tocBtn').hidden = true;

  /* ── 확대 ── */
  function bookBox() {   // 확대 전 화면(stage) 좌표에서 보이는 책의 사각형
    var r = pf.getBoundsRect(), portrait = pf.getOrientation() === 'portrait';
    // 한 쪽만 보이는 경우: 세로 화면, 펼침의 표지(오른쪽 반), 쪽 수가 짝수일 때 마지막 쪽(왼쪽 반)
    var right = portrait || cur === 0, left = !portrait && cur > 0 && cur === N - 1;
    return { x: book.offsetLeft + r.left + (right ? r.pageWidth : 0), y: book.offsetTop + r.top,
             w: right || left ? r.pageWidth : r.width, h: r.height };
  }
  function clampAxis(t, from, size, view) {   // 책이 화면보다 작으면 가운데, 크면 가장자리 밖으로 못 나가게
    if (size * z <= view) return view / 2 - (from + size / 2) * z;
    return Math.min(-from * z, Math.max(view - (from + size) * z, t));
  }
  function setZoom(nz, px, py, animate) {   // (px, py) = stage 안의 점. 이 점이 제자리에 남도록 확대
    nz = Math.min(ZMAX, Math.max(1, nz));
    if (px == null) { px = stage.clientWidth / 2; py = stage.clientHeight / 2; }
    tx = px - (px - tx) * nz / z;
    ty = py - (py - ty) * nz / z;
    z = nz;
    if (z < 1.01) { z = 1; tx = 0; ty = 0; }
    else {
      var b = bookBox();
      tx = clampAxis(tx, b.x, b.w, stage.clientWidth);
      ty = clampAxis(ty, b.y, b.h, stage.clientHeight);
    }
    zoomer.style.transition = animate ? 'transform .22s ease' : '';
    zoomer.style.transform = z === 1 ? '' : 'translate(' + tx + 'px,' + ty + 'px) scale(' + z + ')';
    shield.hidden = z === 1;
    stage.classList.toggle('vb-zoomed', z > 1);
  }
  function local(x, y) { var r = stage.getBoundingClientRect(); return [x - r.left, y - r.top]; }

  stage.addEventListener('wheel', function (e) {
    e.preventDefault();
    var dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
    var l = local(e.clientX, e.clientY);
    setZoom(z * Math.exp(-dy * 0.0015), l[0], l[1]);
  }, { passive: false });

  // StPageFlip 안쪽 값을 직접 건드린다(vendor 2.0.7 고정): 한 손가락으로 시작된 넘기기를 취소
  function cancelBookTouch() {
    var ui = pf.getUI();
    if (ui) ui.touchPoint = null;
    if (pf.isUserTouch) pf.userStop(pf.mousePosition, !pf.isUserMove);
  }

  // 링크·두 손가락은 StPageFlip 에 넘기지 않는다 (링크를 눌러도 책장이 같이 넘어가지 않게).
  // 링크는 linkAt(겹친 요소 아래까지 봄)으로 찾는다: 모서리 접힘(showPageCorners)이 링크를 덮고 있어도 링크로 친다.
  var downLink = null;
  stage.addEventListener('mousedown', function (e) {
    downLink = z === 1 ? linkAt(e.clientX, e.clientY) : null;
    if (downLink) e.stopPropagation();
  }, true);
  stage.addEventListener('touchstart', function (e) {
    var t = e.changedTouches[0];
    if (e.touches.length > 1 || (z === 1 && t && linkAt(t.clientX, t.clientY))) e.stopPropagation();
  }, true);
  // 확대 중에는 마우스 움직임으로 모서리가 접히지 않게. 링크·제품 위에서는 접힌 모서리를 거둔다(목차·색인 링크가 모서리 근처에 많다)
  window.addEventListener('mousemove', function (e) {
    if (z > 1) { e.stopPropagation(); return; }
    if (pf.isUserTouch || !(e.target instanceof Element) || !stage.contains(e.target)) return;
    if (!linkAt(e.clientX, e.clientY) && !prodAt(e.clientX, e.clientY)) return;
    e.stopPropagation();
    if (pf.getState() === 'fold_corner') fc.showCorner({ x: -1e4, y: -1e4 });   // 모서리 밖 점 = 접힘을 되돌림
  }, true);

  var pts = new Map(), pinch = null, lastTap = null, prodTimer = 0;
  function pinchInfo() {
    var a = Array.from(pts.values());
    return { d: Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y) || 1, x: (a[0].x + a[1].x) / 2, y: (a[0].y + a[1].y) / 2 };
  }

  stage.addEventListener('pointerdown', function (e) {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    // menu: 검색 결과가 열려 있었으면 이 누르기는 결과 닫기용 (제품을 열지 않는다)
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, moved: false, menu: !results.hidden });
    if (pts.size === 2) {
      cancelBookTouch();
      pinch = pinchInfo(); pinch.z = z;
      pts.forEach(function (p) { p.moved = true; });
    }
  }, true);

  window.addEventListener('pointermove', function (e) {
    var p = pts.get(e.pointerId);
    if (!p) return;
    var dx = e.clientX - p.x, dy = e.clientY - p.y;
    p.x = e.clientX; p.y = e.clientY;
    if (Math.hypot(p.x - p.sx, p.y - p.sy) > 8) p.moved = true;
    if (pinch && pts.size >= 2) {
      var now = pinchInfo(), l = local(now.x, now.y);
      tx += now.x - pinch.x; ty += now.y - pinch.y;    // 두 손가락 가운데가 움직인 만큼 옮기고
      pinch.x = now.x; pinch.y = now.y;
      setZoom(pinch.z * now.d / pinch.d, l[0], l[1]); // 벌린 만큼 확대
    } else if (z > 1 && pts.size === 1) {
      tx += dx; ty += dy;
      setZoom(z);
    }
  });

  function pointerEnd(e) {
    var p = pts.get(e.pointerId);
    if (!p) return;
    pts.delete(e.pointerId);
    if (pts.size < 2) pinch = null;
    if (e.type === 'pointerup' && !p.moved) tap(e, p.menu);
  }
  window.addEventListener('pointerup', pointerEnd);
  window.addEventListener('pointercancel', pointerEnd);

  function linkAt(x, y) {
    var els = document.elementsFromPoint(x, y);
    for (var i = 0; i < els.length; i++) { var a = els[i].closest('a[data-ref]'); if (a) return a; }
    return null;
  }
  function follow(a) { var n = nums.get(a.getAttribute('data-ref')); if (n) go(n - 1, true); }

  // 홈페이지 상품: 카드·줄의 data-prod(숫자만) → 신도 홈페이지 상품 화면. 다른 주소는 만들지 않는다
  function prodAt(x, y) {
    var els = document.elementsFromPoint(x, y);
    for (var i = 0; i < els.length; i++) {
      var c = els[i].closest('[data-prod]');
      if (c && book.contains(c)) return /^\d{1,10}$/.test(c.getAttribute('data-prod')) ? c : null;
    }
    return null;
  }
  function openProd(c) {
    window.open('https://sindoltd.com/product/detail.html?product_no=' + c.getAttribute('data-prod'), '_blank', 'noopener');
  }

  function tap(e, menu) {
    var a = linkAt(e.clientX, e.clientY);
    if (a && z === 1) { lastTap = null; return; }   // 원래 크기에서 링크는 click 에서 처리
    var c = !a && !menu && prodAt(e.clientX, e.clientY), at = cur, now = Date.now();
    // 제품을 누른 것이면 모서리 누르기로 쪽이 넘어가지 않게 (pointerup 이 책의 mouseup·touchend 보다 먼저 온다)
    if (c && z === 1) cancelBookTouch();
    clearTimeout(prodTimer);
    if (lastTap && now - lastTap.t < 350 && Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < 30) {
      lastTap = null;
      var l = local(e.clientX, e.clientY);
      setZoom(z > 1 ? 1 : 2, l[0], l[1], true);
      return;
    }
    lastTap = { t: now, x: e.clientX, y: e.clientY };
    if (a) { lastTap = null; follow(a); return; }   // 확대 중 링크 (막 아래에 있다)
    // 제품 카드: 두 번 누르기(확대)가 아닌지 잠깐 기다렸다가 연다. 그 사이 쪽이 넘어갔으면 열지 않는다
    if (c) prodTimer = setTimeout(function () { if (pf.getState() === 'read' && cur === at) openProd(c); }, 350);
  }

  // 원래 크기에서 링크 누르기. 누른 곳과 뗀 곳이 같은 링크일 때만 (책장을 끌다 링크 위에서 놓은 것은 아님)
  stage.addEventListener('click', function (e) {
    if (e.target === shield) return;   // 확대 중에는 tap() 이 처리
    var a = linkAt(e.clientX, e.clientY);
    if (a && a === downLink) { e.preventDefault(); follow(a); }
    downLink = null;
  });

  /* ── 위 막대 ── */
  function toggleFullscreen() {
    var d = document, el = d.documentElement, r;
    if (d.fullscreenElement || d.webkitFullscreenElement) r = (d.exitFullscreen || d.webkitExitFullscreen).call(d);
    else r = (el.requestFullscreen || el.webkitRequestFullscreen).call(el);
    if (r && r.catch) r.catch(function () {});
  }
  var fsBtn = $('#fsBtn');
  if (!(document.fullscreenEnabled || document.webkitFullscreenEnabled)) fsBtn.hidden = true;
  function fsLabel() { fsBtn.textContent = (document.fullscreenElement || document.webkitFullscreenElement) ? '전체화면 끝' : '전체화면'; }
  document.addEventListener('fullscreenchange', fsLabel);
  document.addEventListener('webkitfullscreenchange', fsLabel);

  var acts = {
    toc: function () { go(tocIndex); },
    first: function () { go(0); },
    prev: prev,
    next: next,
    last: function () { go(N - 1); },
    zin: function () { setZoom(z * ZSTEP, null, null, true); },
    zout: function () { setZoom(z / ZSTEP, null, null, true); },
    fit: function () { setZoom(1, null, null, true); },
    full: toggleFullscreen
  };
  $('#top').addEventListener('click', function (e) {
    var b = e.target.closest('[data-act]');
    if (b) acts[b.getAttribute('data-act')]();
  });

  // 쪽 번호를 누르면 입력칸으로 바뀐다
  function closePno() { pnoInput.hidden = true; pnoBtn.hidden = false; }
  pnoBtn.addEventListener('click', function () {
    pnoBtn.hidden = true; pnoInput.hidden = false;
    pnoInput.value = cur + 1; pnoInput.focus(); pnoInput.select();
  });
  pnoInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { var n = parseInt(pnoInput.value, 10); closePno(); if (n) go(n - 1); }
    else if (e.key === 'Escape') closePno();
  });
  pnoInput.addEventListener('blur', closePno);

  // 아래 쪽 이동 막대
  slider.addEventListener('input', function () { var i = slider.value - 1; sliderLabel.textContent = (i + 1) + '쪽 · ' + title(i); });
  slider.addEventListener('change', function () { go(slider.value - 1, false); });

  /* ── 키보드 ── */
  document.addEventListener('keydown', function (e) {
    var tag = e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || e.ctrlKey || e.metaKey || e.altKey) return;
    switch (e.key) {
      case 'ArrowRight': case 'PageDown': next(); break;
      case 'ArrowLeft': case 'PageUp': prev(); break;
      case 'Home': go(0); break;
      case 'End': go(N - 1); break;
      case '+': case '=': acts.zin(); break;
      case '-': case '_': acts.zout(); break;
      case '0': acts.fit(); break;
      case 'Escape': setZoom(1, null, null, true); closeResults(); break;
      default: return;
    }
    e.preventDefault();
  });
  window.addEventListener('hashchange', function () { go(hashPage()); });

  /* ── 검색 ── */
  var index = null, timer = 0;

  // 소문자로 바꾸고 공백·하이픈·점을 뺀 글자 + 원래 글자에서의 위치
  function norm(s) {
    var out = '', map = [];
    for (var i = 0; i < s.length; i++) {
      var c = s[i];
      if (/[\s.\-]/.test(c)) continue;
      var l = c.toLowerCase();
      out += l;
      for (var k = 0; k < l.length; k++) map.push(i);
    }
    return { s: out, map: map };
  }

  function search(q) {
    var qn = norm(String(q || '')).s;
    if (!qn) return [];
    if (!index) index = pages.map(function (p) { var t = R.pageText(p); return { text: t, n: norm(t) }; });
    var hits = [];
    index.forEach(function (it, i) {
      var pos = it.n.s.indexOf(qn);
      if (pos < 0) return;
      var a = it.n.map[pos], b = it.n.map[pos + qn.length - 1] + 1;
      hits.push({ page: i + 1, title: title(i),
        before: (a > 20 ? '…' : '') + it.text.slice(Math.max(0, a - 20), a),
        match: it.text.slice(a, b),
        after: it.text.slice(b, b + 20) + (b + 20 < it.text.length ? '…' : '') });
    });
    return hits;
  }

  function showResults(q) {
    var hits = search(q), E = R.esc, html;
    if (!hits.length) html = '<p class="vb-note">찾는 결과가 없습니다.</p>';
    else {
      html = '<p class="vb-note">' + hits.length + '쪽에서 찾았습니다</p>' + hits.slice(0, 50).map(function (h) {
        return '<button type="button" class="vb-hit" role="option" data-i="' + (h.page - 1) + '">' +
          '<span class="vb-hit-head"><b>' + h.page + '쪽</b>' + E(h.title) + '</span>' +
          '<span class="vb-hit-snip">' + E(h.before) + '<mark>' + E(h.match) + '</mark>' + E(h.after) + '</span></button>';
      }).join('');
      if (hits.length > 50) html += '<p class="vb-note">' + (hits.length - 50) + '개 더 — 검색어를 더 자세히 입력해 보세요</p>';
    }
    results.innerHTML = html;
    results.hidden = false;
  }
  function closeResults() { clearTimeout(timer); results.hidden = true; }

  qInput.addEventListener('input', function () {
    clearTimeout(timer);
    var v = qInput.value;
    if (!norm(v).s) { closeResults(); return; }
    if (!index) { results.innerHTML = '<p class="vb-note">찾는 중…</p>'; results.hidden = false; }
    timer = setTimeout(function () { showResults(v); }, 250);
  });
  qInput.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { closeResults(); qInput.blur(); }
    else if (e.key === 'Enter' && norm(qInput.value).s) {   // 250ms 를 기다리지 않고 지금 글자로 찾아 첫 결과로
      clearTimeout(timer); showResults(qInput.value);
      var f = results.querySelector('.vb-hit'); if (f) f.click();
    }
  });
  qInput.addEventListener('focus', function () { if (norm(qInput.value).s && results.innerHTML) results.hidden = false; });
  results.addEventListener('click', function (e) {
    var b = e.target.closest('.vb-hit');
    if (b) { closeResults(); qInput.blur(); go(parseInt(b.getAttribute('data-i'), 10)); }
  });
  document.addEventListener('pointerdown', function (e) { if (!e.target.closest('.vb-search')) closeResults(); });

  window.CatalogViewer = { go: go, search: search, pageFlip: pf };
})();
