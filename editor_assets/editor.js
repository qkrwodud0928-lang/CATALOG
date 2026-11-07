/* 신도 카탈로그 편집기 (editor.html)
   문서 구조는 render.js 머리 주석이 정본. 이 파일은 한 덩어리지만 기능별로 나눠 둔다:
   1 상수·틀   2 순수 함수(시험용으로 EditorInternals 에 내보냄)   3 상태·불러오기
   4 쪽 그리기(가상 스크롤)·번호·왼쪽 목록·보기 크기   5 직렬화·자동 저장·되돌리기
   6 글자 편집   7 쪽 다루기   8 사진 칸   9 표·제품 칸   10 글상자·자유 사진   11 PDF·내보내기·기타   12 시작 */
(function (global) {
  'use strict';
  var CR = global.CatalogRender;
  var PXMM = CR.PX_PER_MM;

  /* ───────────── 1 상수·틀 ───────────── */
  var EDIT_SEL = '.crumb, .ttl b, .ttl span, .band1 span, .band1 small, .band2, .w h4 > span, .w h4 small, .kv b, .kv span, ' +
    '.cert i, .t > b, .t > span, .g .top span, .g h4, .g .model b, .g .txt small, .mh b, .mb, .mr span, .story h3, .s-tag, ' +
    '.s-body, .s-series a > :not(.pref), .c-logo b, .c-logo small, .c-wine p, .c-wine small, .c-contact h5, ' +
    '.c-contact p, .c-url, .pf > span, .chip, .right > b';
  var MULTI_SEL = '.s-body, .c-wine p, .c-contact p, .ov-text-body';
  var SLOT_SEL = '[data-slot], .pic, .s-pic, .c-photo, .full-slot';
  var CARD_SEL = 'article.w, article.g';
  var SLOT_RE = /^(images|brands|logos|flags)\/[^/\\:*?"<>|]{1,120}$/;
  var PH = [['.ttl b', '제목'], ['.ttl span', '부제목'], ['.crumb', '분류'], ['.chip', '나라'], ['.badge', '배지'],
    ['.s-tag', '한 줄 소개'], ['.s-body', '소개 글'], ['.g .model b', '모델 넘버'], ['.w h4 small, .g .txt small', '참고 상품명'],
    ['.t > span, .mr span', ''], ['.kv span', '입력']];
  var NEW_TEXT = '글자를 입력하세요';
  var FOOTER = '<footer class="pf"><span>www.sindoltd.com</span><b class="pno"></b></footer>';
  var DEFAULT_HEAD = '<header class="ph"><p class="crumb"></p><p class="ttl"><b>제목을 입력하세요</b><span></span></p><div class="right"></div></header>';
  var IMAGE_HTML = '<div class="full-slot" data-slot=""><div class="noimg">눌러서 쪽 그림 넣기 (A4 세로 그림 · Canva에서 PNG로 내보낸 것)</div></div>';
  var KNIFE_CARD = '<article class="w"><h4><span><b>시리즈</b> 제품명</span><small></small></h4><div class="cols"><div class="specs">' +
    '<p class="kv"><b>HRC</b><span></span></p><p class="kv"><b>두께</b><span></span></p><p class="kv"><b>날 재질</b><span></span></p>' +
    '<p class="kv"><b>핸들 재질</b><span></span></p></div><div class="main"><div class="pic" data-slot=""><div class="noimg">눌러서 사진 넣기</div></div>' +
    '<div class="t" style="grid-template-columns:24mm 30mm 1fr"><b>핸들 색상</b><b>날 길이</b><b>모델 넘버</b><span></span><span></span>' +
    '<span class="code"></span></div></div></div></article>';
  function gridCard(n) {
    return '<article class="g"><p class="top"><span>' + (n < 10 ? '0' : '') + n + '</span><span class="badge"></span></p><div class="cols">' +
      '<div class="pic" data-slot=""><div class="noimg">눌러서 사진 넣기</div></div><div class="txt"><h4><b>브랜드</b> 제품명</h4>' +
      '<p class="model"><i>모델 넘버</i><b></b></p><p class="kv"><b>사이즈</b><span></span></p><p class="kv"><b>재질</b><span></span></p>' +
      '</div></div></article>';
  }

  /* ───────────── 2 순수 함수 ───────────── */
  // 그림을 불러오지 않는 문서: 화면에 안 그린 쪽을 고치거나 직렬화할 때 쓴다
  var INERT = document.implementation.createHTMLDocument('');
  function inertBox(html) { var d = INERT.createElement('div'); d.innerHTML = html || ''; return d; }
  function each(list, fn) { for (var i = 0; i < list.length; i++) fn(list[i], i); }
  function $$(root, sel) { return Array.prototype.slice.call(root.querySelectorAll(sel)); }

  /** 화면의 쪽(section) 또는 html 을 담은 상자 → 저장할 page.html
      .ov-layer·편집기 전용 요소(ed-only)를 빼고, ed-wrap 은 풀고, ed- class·contenteditable·data-ph 를 떼고, 번호를 비운다 */
  function serialize(root) {
    var c = INERT.importNode(root, true);
    each($$(c, ':scope > .ov-layer, .ed-only'), function (el) { el.remove(); });
    each($$(c, '.ed-wrap'), function (el) { while (el.firstChild) el.parentNode.insertBefore(el.firstChild, el); el.remove(); });
    each($$(c, '[class*="ed-"], a.broken'), function (el) {
      var keep = Array.prototype.filter.call(el.classList, function (x) { return x.indexOf('ed-') !== 0 && x !== 'broken'; });
      if (keep.length === el.classList.length) return;
      if (keep.length) el.className = keep.join(' '); else el.removeAttribute('class');
    });
    each($$(c, '[contenteditable], [data-ph]'), function (el) { el.removeAttribute('contenteditable'); el.removeAttribute('data-ph'); });
    CR.stripNumbers(c);
    return CR.sanitizeHTML(c.innerHTML);
  }

  function phFor(el) {
    for (var i = 0; i < PH.length; i++) if (el.matches(PH[i][0])) return PH[i][1];
    return '입력';
  }

  /** 고칠 수 있는 곳에 contenteditable·안내글을 붙인다 (여러 번 불러도 됨) */
  function decorate(root) {
    each(root.querySelectorAll('.s-series a'), function (a) {   // 링크 안의 맨 글자는 span 으로 감싸야 고칠 수 있다
      each(Array.prototype.slice.call(a.childNodes), function (n) {
        if (n.nodeType !== 3 || !n.nodeValue.trim()) return;
        var s = n.ownerDocument.createElement('span');
        s.className = 'ed-wrap';
        a.insertBefore(s, n);
        s.appendChild(n);
      });
    });
    each(root.querySelectorAll(EDIT_SEL), function (el) {
      if (el.hasAttribute('contenteditable') || el.closest('.ov-layer, .pno, .pref') || el.querySelector('img')) return;
      if (el.parentElement && el.parentElement.closest('[contenteditable]')) return;
      el.setAttribute('contenteditable', 'true');
      el.setAttribute('data-ph', phFor(el));
    });
  }

  /** 복제한 내용의 사진 칸 이름을 비운다 (새로 올린 사진이 원래 쪽 사진을 덮어쓰지 않게).
      홈페이지 상품 번호도 뗀다 (복제한 칸은 다른 제품이 되므로 엉뚱한 상품으로 가지 않게) */
  function freshSlots(root) {
    each(root.querySelectorAll('[data-slot]'), function (s) { s.setAttribute('data-slot', ''); });
    root.removeAttribute('data-prod');
    each(root.querySelectorAll('[data-prod]'), function (c) { c.removeAttribute('data-prod'); });
  }

  /** 새 쪽의 머리·탭·색: 앞 쪽을 본뜬다 (앞 쪽이 없거나 표지·그림 쪽이면 기본) */
  function headFrom(prev) {
    var def = { header: DEFAULT_HEAD, tab: '', style: '--c:#1f3c88' };
    if (!prev || prev.kind === 'cover' || prev.kind === 'image') return def;
    var box = inertBox(prev.html), h = box.querySelector('header.ph');
    if (!h) return def;
    var b = h.querySelector('.ttl b'), s = h.querySelector('.ttl span'), r = h.querySelector('.right');
    if (b) b.textContent = '제목을 입력하세요';
    if (s) s.textContent = '';
    if (r) r.innerHTML = '';
    var tab = box.querySelector(':scope > .tab');
    return { header: h.outerHTML, tab: tab ? tab.outerHTML : '', style: prev.style || def.style };
  }

  /** 새 쪽 객체. type: blank | knife | grid | image | dup,  prev: 바로 앞 쪽(없으면 null) */
  function makePage(doc, type, prev) {
    if (type === 'dup') return dupPage(doc, prev);
    var id = CR.newId(doc, 'pg');
    if (type === 'image') return { id: id, kind: 'image', cls: 'full', style: '', html: IMAGE_HTML, overlays: [] };
    var head = headFrom(prev), body = '';
    if (type === 'knife') body = KNIFE_CARD + KNIFE_CARD + KNIFE_CARD;
    if (type === 'grid') for (var r = 0; r < 4; r++) body += '<div class="grow">' + gridCard(r * 2 + 1) + gridCard(r * 2 + 2) + '</div>';
    return { id: id, kind: type === 'blank' ? 'blank' : 'content', cls: '', style: head.style,
      html: head.header + '<div class="body">' + body + '</div>' + FOOTER + head.tab, overlays: [] };
  }

  /** 쪽 복제: 새 id, 글상자 id 도 새로, 사진 칸 이름은 비움 */
  function dupPage(doc, src) {
    var box = inertBox(src.html);
    freshSlots(box);
    var p = { id: CR.newId(doc, 'pg'), kind: src.kind || 'content', cls: src.cls || '', style: src.style || '', html: box.innerHTML, overlays: [] };
    p.overlays = (src.overlays || []).map(function (o) { var c = JSON.parse(JSON.stringify(o)); c.id = CR.newId(doc, 'ov'); return c; });
    return p;
  }

  /** 문서 안에서 이 쪽을 가리키는 링크 수 (자기 쪽 제외) */
  function linkCount(doc, id) {
    var needle = 'data-ref="' + id + '"', n = 0;
    doc.pages.forEach(function (p) { if (p.id !== id) n += String(p.html).split(needle).length - 1; });
    return n;
  }

  // 표(.t): 열 수 = 머리 b 개수, 칸 = 머리 뒤 span 들
  function tableCols(t) { return t.querySelectorAll(':scope > b').length || 1; }
  function tableCells(t) { return $$(t, ':scope > span'); }
  /** 표 끝에 한 줄 추가. 새 칸 class 는 바로 위 줄과 같게. 새 칸들을 돌려준다 */
  function tableAddRow(t) {
    var cols = tableCols(t), cells = tableCells(t), made = [];
    for (var k = 0; k < cols; k++) {
      var s = t.ownerDocument.createElement('span'), ref = cells.length >= cols ? cells[cells.length - cols + k] : null;
      s.className = ref ? ref.className : '';
      t.appendChild(s);
      made.push(s);
    }
    return made;
  }
  /** 이 칸이 든 줄의 칸들 */
  function rowOf(t, cell) {
    var cols = tableCols(t), cells = tableCells(t), k = cells.indexOf(cell);
    if (k < 0) return [];
    var start = k - k % cols;
    return cells.slice(start, start + cols);
  }
  function tableRemoveRow(t, cell) {
    var row = rowOf(t, cell);
    row.forEach(function (c) { c.remove(); });
    return row.length > 0;
  }

  /** 제품 칸을 빼낸다 (.grow 가 비면 같이 지움) */
  function takeCard(card) {
    var g = card.parentElement;
    card.remove();
    if (g && g.classList.contains('grow') && !g.querySelector('article')) g.remove();
    return card;
  }
  /** body 맨 앞(atStart) 또는 맨 뒤에 제품 칸을 넣는다. 2단 칸은 1칸짜리 .grow 가 있으면 거기, 없으면 새 .grow */
  function putCard(body, card, atStart) {
    var target = body, ref = atStart ? body.firstChild : null;
    if (card.classList.contains('g')) {
      var grows = $$(body, ':scope > .grow'), g = grows.length ? grows[atStart ? 0 : grows.length - 1] : null;
      if (g && g.querySelectorAll(':scope > article').length === 1) { target = g; ref = atStart ? g.firstChild : null; }
      else {
        var ng = body.ownerDocument.createElement('div');
        ng.className = 'grow';
        body.insertBefore(ng, ref);
        target = ng; ref = null;
      }
    }
    target.insertBefore(card, ref);
    return card;
  }
  /** 제품 칸 복제 (바로 뒤에) */
  function dupCard(card) {
    var c = card.cloneNode(true), g = card.parentElement;
    freshSlots(c);
    if (card.classList.contains('g') && g && g.classList.contains('grow') && g.querySelectorAll(':scope > article').length > 1) {
      var ng = card.ownerDocument.createElement('div');
      ng.className = 'grow';
      ng.appendChild(c);
      g.parentNode.insertBefore(ng, g.nextSibling);
    } else card.parentNode.insertBefore(c, card.nextSibling);
    return c;
  }
  /** 쪽 끝에 빈 제품 칸 (쪽에 .g 가 있으면 2단 칸, 아니면 칼 칸) */
  function addCard(body) {
    var isG = !!body.querySelector('article.g'), box = inertBox(isG ? gridCard(body.querySelectorAll('article.g').length + 1) : KNIFE_CARD);
    var card = body.ownerDocument.importNode(box.firstChild, true);
    return putCard(body, card, false);
  }

  /** 되돌리기용 사진: 쪽 배열 얕은 사본 + meta */
  function snap(doc) { return { pages: doc.pages.slice(), meta: Object.assign({}, doc.meta) }; }
  function restoreSnap(doc, s) { doc.pages = s.pages.slice(); doc.meta = Object.assign({}, s.meta); }

  /* ───────────── 3 상태·불러오기 ───────────── */
  var doc = null, nums = new Map();
  var W = new Map();          // 쪽 id → 껍데기 {id, el, add, frame, no, sec, page, dirty}
  var order = [];             // 화면 순서의 껍데기
  var endAdd = null;          // 맨 끝 "+ 여기에 페이지 추가"
  var undoStack = [], redoStack = [], grouping = false;
  var ver = 0, savedVer = 0, saving = null, saveTimer = 0, retryTimer = 0, flushTimer = 0;
  var scaleMode = 'fit', scale = 1, cur = 0;
  var sel = null, editingOv = false, ovTimer = 0;   // 선택된 글상자·사진 {pid, oid}
  var stash = null;                                  // 안내글(.empty)을 비우고 입력 중인 칸 {el, html}
  var titleCache = new WeakMap(), textCache = new WeakMap(), ovf = new WeakMap();
  var io = null, stage, sheet, pagesEl, listEl;
  function $(id) { return document.getElementById(id); }

  function boot() {
    stage = $('ed-stage'); sheet = $('sheet'); pagesEl = $('pages'); listEl = $('list');
    fetch('api/doc', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(start)
      .catch(function (err) {
        fatal('편집기 프로그램이 꺼져 있습니다.', "'카탈로그 편집기' 아이콘을 두 번 눌러 켜 주세요.", err);
      });
  }

  function fatal(title, text, err) {
    var f = $('fatal');
    f.innerHTML = '<div><b>' + CR.esc(title) + '</b>' + CR.esc(text) + '</div>';
    f.hidden = false;
    if (err) console.error(err);
  }

  function start(d) {
    if (!d || !Array.isArray(d.pages) || !d.pages.length) {
      fatal('카탈로그 파일을 읽을 수 없습니다.', 'catalog.json 파일이 비었거나 망가졌습니다.');
      return;
    }
    doc = d;
    doc.meta = doc.meta || {};
    doc.pages.forEach(function (p) { if (!Array.isArray(p.overlays)) p.overlays = []; if (typeof p.html !== 'string') p.html = ''; });
    if (regenDerived()) ver++;          // 처음 열 때 목차·색인이 내용과 다르면 맞추고 저장
    endAdd = makeAdd();
    io = new IntersectionObserver(onIntersect, { root: stage, rootMargin: '1500px 0px 1500px 0px' });
    applyScale();
    sync();
    bindUI();
    if (ver) { setStatus('busy', '저장 중…'); saveTimer = setTimeout(save, 1500); } else setStatus('', '고친 것 없음');
    var go = /[#&]p=(\d+)/.exec(location.hash);
    if (go) scrollToIndex(Math.min(doc.pages.length, Math.max(1, +go[1])) - 1);
    updateCurrent(true);
    (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(function () { setTimeout(scanSoon, 300); });
  }

  /* ───────────── 4 쪽 그리기·번호·목록·보기 크기 ───────────── */
  var BAR = '<div class="ed-bar"><b class="ed-no"></b>' +
    '<button type="button" data-act="up" title="이 쪽을 앞으로">▲ 위로</button>' +
    '<button type="button" data-act="down" title="이 쪽을 뒤로">▼ 아래로</button>' +
    '<button type="button" data-act="dup" title="바로 뒤에 한 장 더">복제</button>' +
    '<button type="button" data-act="del" class="ed-danger">지우기</button><span class="ed-sep"></span>' +
    '<button type="button" data-act="text">+ 글상자</button>' +
    '<button type="button" data-act="photo">+ 사진</button>' +
    '<button type="button" data-act="card">+ 제품 칸</button></div>' +
    '<div class="ed-warn">⚠ 내용이 넘칩니다 — 입력을 마치면 넘친 제품 칸이 새 쪽으로 저절로 옮겨집니다 (칸 하나가 혼자 너무 길면 표 줄을 줄여 주세요)</div><div class="ed-frame"></div>';

  function makeAdd() {
    var d = document.createElement('div');
    d.className = 'ed-add';
    d.innerHTML = '<button type="button" data-act="add">+ 여기에 페이지 추가</button>';
    return d;
  }
  function makeWrap(id) {
    var el = document.createElement('div');
    el.className = 'ed-pg';
    el.setAttribute('data-id', id);
    el.innerHTML = BAR;
    var w = { id: id, el: el, add: makeAdd(), frame: el.lastChild, no: el.querySelector('.ed-no'), sec: null, page: null, dirty: false };
    el._w = w;
    W.set(id, w);
    io.observe(el);
    return w;
  }
  function wrapOf(node) {
    var el = node && (node.nodeType === 1 ? node : node.parentElement);
    el = el && el.closest('.ed-pg');
    return el ? el._w : null;
  }
  function indexOf(id) { var n = nums.get(id); return n ? n - 1 : -1; }

  /** 문서 순서대로 쪽 껍데기를 다시 늘어놓고 번호를 매긴다. 객체가 바뀐 쪽만 다시 그린다 */
  function sync() {
    nums = CR.numberMap(doc);
    var top = stage.scrollTop;          // 껍데기를 옮기기 전에 읽어 둔다
    var want = [], seen = new Set(), redrawn = [];
    order = doc.pages.map(function (p, i) {
      var w = W.get(p.id) || makeWrap(p.id);
      seen.add(p.id);
      want.push(w.add, w.el);
      w.no.textContent = (i + 1) + '쪽';
      if (w.sec) {
        if (w.page !== p) { renderInto(w, p, i); redrawn.push(w); } else CR.fillNumbers(w.sec, i, nums);
      }
      setWarn(w, ovf.get(p));
      return w;
    });
    want.push(endAdd);
    W.forEach(function (w, id) {
      if (seen.has(id)) return;
      io.unobserve(w.el); w.el.remove(); w.add.remove(); W.delete(id);
    });
    // 자리가 바뀐 껍데기만 옮긴다. 입력 중인 쪽을 떼었다 붙이면 커서가 빠지고 한글 조합이 끊긴다 (제목을 고치면 목차가 바뀌어 여기로 온다)
    var ref = pagesEl.firstChild;
    want.forEach(function (n) { if (n === ref) ref = ref.nextSibling; else pagesEl.insertBefore(n, ref); });
    stage.scrollTop = top;
    redrawn.forEach(checkOverflow);
    hideHoverTools();
    renderList();
    updateCurrent(true);
    updateUndoButtons();
  }

  function renderInto(w, p, i) {
    if (w.sec) w.sec.remove();
    var sec = CR.createPageElement(p, i, nums);
    decorate(sec);
    w.frame.appendChild(sec);
    w.sec = sec; w.page = p; w.dirty = false;
    w.el.classList.toggle('ed-auto', p.kind === 'toc' || p.kind === 'index');
    if (sel && sel.pid === p.id) markSelected();
  }
  function ensureRendered(w) {
    if (w.sec) return;
    var i = indexOf(w.id);
    renderInto(w, doc.pages[i], i);
    checkOverflow(w);
  }
  function unrender(w) {
    if (w.sec.contains(document.activeElement)) document.activeElement.blur();
    flush(w);
    if (sel && sel.pid === w.id) deselect();
    if ([cardTool(), tableTool(), slotTool(), rowTool()].some(function (t) { return t._t && w.sec.contains(t._t); })) hideHoverTools();
    w.sec.remove();
    w.sec = null; w.page = null; w.dirty = false;
  }
  function onIntersect(entries) {
    entries.forEach(function (e) {
      var w = e.target._w;
      if (!w || W.get(w.id) !== w) return;
      if (e.isIntersecting) ensureRendered(w);
      else if (w.sec) unrender(w);
    });
  }

  // 넘침 검사: 완성본(.final) 모양으로 잰다 (책·PDF 가 그 모양이므로)
  function overflows(sec) {
    var b = sec.querySelector(':scope > .body');
    return !!b && b.scrollHeight > b.clientHeight + 1;
  }
  // 화면 밖 재는 상자 (.final). 화면의 쪽을 직접 건드리면 입력 중인 칸이 잠깐 숨어 커서를 잃을 수 있어 사본을 잰다
  var mbox = null;
  function measureBox() {
    if (!mbox) { mbox = document.createElement('div'); mbox.className = 'ed-measure final'; document.body.appendChild(mbox); }
    return mbox;
  }
  function checkOverflow(w) {
    if (!w || !w.sec) return;
    var c = w.sec.cloneNode(true);
    measureBox().appendChild(c);
    var over = overflows(c);
    c.remove();
    ovf.set(w.page, over);
    setWarn(w, over);
  }
  function setWarn(w, over) {
    over = !!over;
    if (w.el.classList.contains('ed-over') === over) return;
    w.el.classList.toggle('ed-over', over);
    var li = listEl.querySelector('li[data-id="' + w.id + '"]');
    if (li) li.classList.toggle('warn', over);
  }
  // 화면에 안 그린 쪽도 쉬는 틈에 화면 밖에서 그려 넘침을 미리 잰다 (왼쪽 목록 ⚠ 용)
  var scanning = false, scanAgain = false;
  function scanSoon() {
    if (scanning) { scanAgain = true; return; }
    scanning = true;
    var box = measureBox(), i = 0;
    var later = global.requestIdleCallback || function (fn) { return setTimeout(fn, 30); };
    (function step() {
      var batch = [];
      while (i < doc.pages.length && batch.length < 12) {
        var p = doc.pages[i++];
        if (ovf.has(p)) continue;
        var sec = CR.createPageElement(p, i - 1, nums);
        box.appendChild(sec);
        batch.push([p, sec]);
      }
      batch.forEach(function (b) { ovf.set(b[0], overflows(b[1])); });
      box.textContent = '';
      batch.forEach(function (b) { var w = W.get(b[0].id); if (w && doc.pages[indexOf(w.id)] === b[0]) setWarn(w, ovf.get(b[0])); });
      if (i < doc.pages.length) { later(step); return; }
      scanning = false;
      if (scanAgain) { scanAgain = false; scanSoon(); }
    })();
  }

  // 왼쪽 목록
  function title(p) { var t = titleCache.get(p); if (t == null) { t = CR.pageTitle(p); titleCache.set(p, t); } return t; }
  function norm(s) { return String(s || '').toLowerCase().replace(/[\s\-.·]/g, ''); }
  function searchText(p) { var t = textCache.get(p); if (t == null) { t = norm(CR.pageText(p)); textCache.set(p, t); } return t; }
  function renderList() {
    var q = norm($('findInput').value), out = [];
    doc.pages.forEach(function (p, i) {
      if (q && norm(title(p)).indexOf(q) < 0 && searchText(p).indexOf(q) < 0) return;
      var cls = (ovf.get(p) ? 'warn ' : '') + (i === cur ? 'on' : '');
      out.push('<li data-id="' + CR.esc(p.id) + '"' + (cls ? ' class="' + cls.trim() + '"' : '') + '><b>' + (i + 1) + '</b><span>' +
        CR.esc(title(p)) + '</span><i title="내용이 넘칩니다">⚠</i></li>');
    });
    listEl.innerHTML = out.join('') || '<li class="ed-empty">찾는 쪽이 없습니다</li>';
  }

  /** 지금 보는 쪽 (화면 위쪽 30% 높이에 걸친 쪽) */
  function updateCurrent(force) {
    if (!order.length) return;
    var y = stage.scrollTop + stage.clientHeight * 0.3 - sheet.offsetTop, lo = 0, hi = order.length - 1;
    while (lo < hi) { var mid = (lo + hi + 1) >> 1; if (order[mid].el.offsetTop <= y) lo = mid; else hi = mid - 1; }
    if (lo === cur && !force) return;
    cur = lo;
    var old = listEl.querySelector('li.on');
    if (old) old.classList.remove('on');
    var li = listEl.querySelector('li[data-id="' + order[cur].id + '"]');
    if (!li) return;
    li.classList.add('on');
    if (li.offsetTop < listEl.scrollTop) listEl.scrollTop = li.offsetTop - 40;
    else if (li.offsetTop + li.offsetHeight > listEl.scrollTop + listEl.clientHeight) listEl.scrollTop = li.offsetTop - listEl.clientHeight + 60;
  }
  function scrollToIndex(i) {
    var w = order[Math.max(0, Math.min(order.length - 1, i))];
    if (w) stage.scrollTop = sheet.offsetTop + w.el.offsetTop - 10;
  }

  /** 보기 크기: 쪽을 원래 크기로 두고 transform: scale(s) (+ 액자 크기 210mm*s × 297mm*s) */
  function applyScale() {
    var s = scaleMode === 'fit' ? Math.min(1, (stage.clientWidth - 64 - 4) / CR.PAGE_W_PX) : Number(scaleMode);
    s = Math.max(0.2, Math.round(s * 1000) / 1000);
    if (s === scale && stage.style.getPropertyValue('--s')) return;
    var w = order[cur], off = w ? w.el.getBoundingClientRect().top : 0;
    scale = s;
    stage.style.setProperty('--s', String(s));
    if (w) stage.scrollTop += w.el.getBoundingClientRect().top - off;
    hideHoverTools();
    if (sel) showOvTool();
  }

  /* ───────────── 5 직렬화·자동 저장·되돌리기 ───────────── */
  /** 문서를 바꾸는 일은 모두 이 안에서: 바꾸기 전 모습을 되돌리기 목록에 쌓는다 */
  function change(fn) {
    if (grouping) { fn(); return; }
    var before = snap(doc);
    fn();
    pushUndo(before);
  }
  /** 여러 쪽을 한 번에 바꾸는 일을 되돌리기 한 번으로 묶는다 */
  function grouped(fn) {
    flushAll();
    var before = snap(doc);
    grouping = true;
    try { fn(); } finally { grouping = false; }
    var same = before.pages.length === doc.pages.length && before.pages.every(function (p, i) { return p === doc.pages[i]; });
    if (!same) pushUndo(before);
  }
  function pushUndo(before) {
    var regen = regenDerived();          // 목차·칼 색인도 같은 단계로 (되돌리면 같이 돌아감)
    undoStack.push(before);
    if (undoStack.length > 100) undoStack.shift();
    redoStack.length = 0;
    edited();
    if (regen) sync();
  }
  function edited() {
    ver++;
    setStatus('busy', '저장 중…');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 1500);
    updateUndoButtons();
  }
  function setPage(i, np) {
    doc.pages[i] = np;
    var w = W.get(np.id);
    if (w && w.sec) w.page = np;
  }

  /** 그려진 쪽의 고친 내용을 문서에 반영 */
  function flush(w) {
    if (!w || !w.sec || !w.dirty) return;
    w.dirty = false;
    var i = indexOf(w.id), p = doc.pages[i];
    if (!p) return;
    var html = serialize(w.sec);
    if (html !== p.html) change(function () { setPage(i, Object.assign({}, p, { html: html })); });
    checkOverflow(w);
    if (ovf.get(w.page)) wantFlow(w.id);
  }
  function flushAll() {
    clearTimeout(flushTimer);
    order.forEach(flush);
    commitOvText();
  }

  function undo() {
    flushAll();
    if (!undoStack.length) return;
    redoStack.push(snap(doc));
    restoreSnap(doc, undoStack.pop());
    afterRestore('되돌렸습니다');
  }
  function redo() {
    flushAll();
    if (!redoStack.length) return;
    undoStack.push(snap(doc));
    restoreSnap(doc, redoStack.pop());
    afterRestore('다시 했습니다');
  }
  function afterRestore(msg) {
    deselect();
    sync();
    scanSoon();
    edited();
    toast(msg);
  }
  function updateUndoButtons() {
    $('undoBtn').disabled = !undoStack.length;
    $('redoBtn').disabled = !redoStack.length;
  }

  function setStatus(kind, text, tip) {
    var s = $('status');
    s.className = 'ed-status' + (kind ? ' ' + kind : '');
    s.textContent = text;
    s.title = tip || '';
  }
  function postJSON(url, body) {
    return fetch(url, { method: 'POST', headers: body == null ? {} : { 'Content-Type': 'application/json' }, body: body == null ? null : body })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok || !j.ok) throw new Error(j.error || ('오류 ' + r.status));
          return j;
        });
      });
  }
  /** 저장 (끝나면 true). 저장 중에 또 고치면 끝난 뒤 한 번 더 */
  function save() {
    clearTimeout(saveTimer);
    clearTimeout(retryTimer);
    if (!doc) return Promise.resolve(false);
    flushAll();
    if (saving) return saving.then(function () { return save(); });
    if (ver === savedVer) return Promise.resolve(true);
    var v = ver;
    setStatus('busy', '저장 중…');
    saving = postJSON('api/save', JSON.stringify(doc)).then(function (j) {
      savedVer = v;
      return String(j.savedAt || '').slice(0, 5);
    }, function (err) { return err; }).then(function (r) {
      saving = null;
      if (r instanceof Error) {
        setStatus('bad', '저장 안 됨', r.message + ' — 5초 뒤에 다시 저장해 봅니다');
        retryTimer = setTimeout(save, 5000);
        return false;
      }
      if (ver !== savedVer) return save();
      setStatus('ok', '저장됨 ' + r);
      return true;
    });
    return saving;
  }

  /** 쪽 하나를 DOM 으로 고친다: 그려져 있으면 화면의 쪽을, 아니면 화면 밖 상자를 고친 뒤 문서에 반영 */
  function editPage(pid, fn) {
    var i = indexOf(pid);
    if (i < 0) { toast('그 쪽이 없어졌습니다', true); return false; }
    var w = W.get(pid);
    if (w && w.sec) { fn(w.sec, true); w.dirty = true; flush(w); return true; }
    var p = doc.pages[i], box = inertBox(p.html);
    fn(box, false);
    var html = serialize(box);
    if (html !== p.html) { change(function () { setPage(i, Object.assign({}, p, { html: html })); }); scanSoon(); wantFlow(pid); }
    return true;
  }

  /* ───────────── 6 글자 편집 ───────────── */
  function editHost(node) {
    var el = node && (node.nodeType === 1 ? node : node.parentElement);
    return el && el.closest ? el.closest('[contenteditable="true"]') : null;
  }
  function isMulti(host) { return host.matches(MULTI_SEL); }

  function onInput(e) {
    var host = editHost(e.target);
    if (!host) return;
    if (host.classList.contains('ov-text-body')) { clearTimeout(ovTimer); ovTimer = setTimeout(commitOvText, 600); placeOvTool(); return; }
    var w = wrapOf(host);
    if (!w) return;
    w.dirty = true;
    clearTimeout(flushTimer);
    flushTimer = setTimeout(flushAll, 600);
  }
  function onFocusIn(e) {
    var host = editHost(e.target);
    if (!host || host.classList.contains('ov-text-body')) return;
    if (host.classList.contains('empty')) {          // "한 줄 소개" 같은 흐린 안내글은 누르면 비운다
      stash = { el: host, html: host.innerHTML };
      host.innerHTML = '';
      host.classList.remove('empty');
      // 누른 곳(안내글)이 없어져 커서를 잃을 수 있으니, 클릭 처리가 끝난 뒤 커서를 칸 안에 다시 둔다
      setTimeout(function () {
        if (!host.isConnected || stash === null || stash.el !== host) return;
        if (document.activeElement !== host) host.focus();
        var s = global.getSelection();
        if (!s.rangeCount || !host.contains(s.getRangeAt(0).startContainer)) s.collapse(host, 0);
      }, 0);
    }
    if (host.matches('.t > span')) showRowTool(host);
  }
  function onFocusOut(e) {
    var host = editHost(e.target);
    if (!host) return;
    if (host.classList.contains('ov-text-body')) { stopEditOv(); return; }
    var w = wrapOf(host);
    if (stash && stash.el === host) {
      if (!host.textContent.trim()) { host.innerHTML = stash.html; host.classList.add('empty'); if (w) w.dirty = true; }
      stash = null;
    }
    hideT(rowTool());
    if (w) flush(w);
    setTimeout(runFlows, 0);
  }
  function onPaste(e) {
    var host = editHost(e.target);
    if (!host) return;
    e.preventDefault();                                // 붙여넣기는 글자만
    var text = ((e.clipboardData || global.clipboardData).getData('text/plain') || '').replace(/\r\n?/g, '\n');
    if (!isMulti(host)) { document.execCommand('insertText', false, text.replace(/\s*\n\s*/g, ' ').trim()); return; }
    text.split('\n').forEach(function (line, i) {      // 여러 줄은 Enter 와 같은 줄바꿈으로 (그냥 넣으면 줄마다 <div> 가 생긴다)
      if (i) document.execCommand('insertLineBreak');
      if (line) document.execCommand('insertText', false, line);
    });
  }
  function onKey(e) {
    if (e.isComposing || e.keyCode === 229) return;    // 한글 조합 중
    var t = e.target, host = editHost(t), field = /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName);
    var mod = e.ctrlKey || e.metaKey, k = (e.key || '').toLowerCase();
    if (mod && k === 's') { e.preventDefault(); save(); return; }
    if (mod && !e.altKey && (k === 'z' || k === 'y')) {
      if (host || field) return;                       // 글 입력 중에는 브라우저 기본 되돌리기
      e.preventDefault();
      if (k === 'y' || e.shiftKey) redo(); else undo();
      return;
    }
    if (document.querySelector('dialog[open]')) return;
    if (host) {
      if (e.key === 'Enter') {                         // 한 줄 칸: 입력 끝. 여러 줄 칸: Enter·Shift+Enter 모두 줄바꿈 한 번 (<div> 가 안 생기게)
        e.preventDefault();
        if (isMulti(host)) document.execCommand('insertLineBreak'); else host.blur();
      } else if (e.key === 'Escape') host.blur();
      return;
    }
    if (field || !sel) return;
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteOv(); }
    else if (e.key === 'Escape') deselect();
  }

  /* ───────────── 7 쪽 다루기 ───────────── */
  function structural(fn) {
    flushAll();
    deselect();
    change(fn);
    sync();
    scanSoon();
  }
  function pageAction(act, w) {
    if (!w) return;
    var i = indexOf(w.id);
    if (act === 'up' || act === 'down') movePage(i, act === 'up' ? -1 : 1);
    else if (act === 'dup') {
      structural(function () { doc.pages.splice(i + 1, 0, dupPage(doc, doc.pages[i])); });
      toast((i + 2) + '쪽에 복제했습니다');
    }
    else if (act === 'del') deletePage(i);
    else if (act === 'text') addTextBox(w);
    else if (act === 'photo') pickFile().then(function (f) { if (f) addPhoto(w.id, f); });
    else if (act === 'card') addCardToPage(w);
  }
  function movePage(i, d) {
    var j = i + d;
    if (j < 0 || j >= doc.pages.length) { toast(d < 0 ? '맨 앞 쪽입니다' : '맨 뒤 쪽입니다'); return; }
    var w = order[i], off = w.el.getBoundingClientRect().top;
    structural(function () { var p = doc.pages[i]; doc.pages[i] = doc.pages[j]; doc.pages[j] = p; });
    stage.scrollTop += w.el.getBoundingClientRect().top - off;   // 옮긴 쪽을 따라간다
    updateCurrent(true);
  }
  function deletePage(i) {
    flushAll();
    var p = doc.pages[i];
    if (!p) return;
    if (doc.pages.length <= 1) { toast('마지막 남은 쪽은 지울 수 없습니다', true); return; }
    var n = linkCount(doc, p.id);
    var msg = (i + 1) + '쪽 「' + title(p) + '」\n\n이 쪽을 지울까요? 되돌리기로 다시 살릴 수 있습니다.' +
      (n ? '\n\n목차/색인에서 이 쪽을 가리키는 링크가 ' + n + '개 있습니다. (지우면 그 링크 번호는 "?" 로 바뀝니다)' : '');
    if (global.confirm(msg)) removePage(i);
  }
  function removePage(i) {
    structural(function () { doc.pages.splice(i, 1); });
    toast((i + 1) + '쪽을 지웠습니다 — 되돌리기(Ctrl+Z)로 살릴 수 있습니다');
  }
  var addAt = 0;
  function openAdd(btn) {
    var next = btn.closest('.ed-add').nextElementSibling;
    addAt = next && next._w ? indexOf(next._w.id) : doc.pages.length;
    $('dupChoice').disabled = addAt === 0;
    $('addDlg').showModal();
  }
  function addPageAt(at, type) {
    flushAll();
    var prev = at > 0 ? doc.pages[at - 1] : null, p;
    if (type === 'dup' && !prev) return null;
    structural(function () { p = makePage(doc, type, prev); doc.pages.splice(at, 0, p); });
    scrollToIndex(at);
    toast((at + 1) + '쪽에 새 페이지를 넣었습니다. 뒤 쪽 번호는 저절로 바뀝니다');
    return p;
  }

  /* ───────────── 8 사진 칸 ───────────── */
  function pickFile() {
    return new Promise(function (res) {
      var inp = $('fileInput');
      inp.value = '';
      inp.onchange = function () { res((inp.files && inp.files[0]) || null); };
      inp.click();
    });
  }
  var MIME_EXT = { 'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/gif': 'gif' };
  function fileExt(f) {
    var m = /\.([a-z0-9]+)$/i.exec(f.name || ''), e = m ? m[1].toLowerCase() : (MIME_EXT[f.type] || '');
    if (e === 'jpeg' || e === 'jfif') e = 'jpg';
    return ['jpg', 'png', 'webp', 'gif'].indexOf(e) >= 0 ? e : '';
  }
  function loadImage(src) {
    return new Promise(function (res, rej) {
      var im = new Image();
      im.onload = function () { res(im); };
      im.onerror = function () { rej(new Error('그림 파일을 읽을 수 없습니다.')); };
      im.src = src;
    });
  }
  function hasAlpha(im) {
    var c = document.createElement('canvas'), k = Math.min(1, 256 / Math.max(im.naturalWidth, im.naturalHeight));
    c.width = Math.max(1, Math.round(im.naturalWidth * k)); c.height = Math.max(1, Math.round(im.naturalHeight * k));
    var g = c.getContext('2d');
    g.drawImage(im, 0, 0, c.width, c.height);
    var d = g.getImageData(0, 0, c.width, c.height).data;
    for (var i = 3; i < d.length; i += 4) if (d[i] < 250) return true;
    return false;
  }
  /** 큰 사진은 긴 변 2400px 이하 JPEG(0.88)로 줄인다 (투명 배경 png 는 png 로) */
  function prepareImage(file) {
    var ext = fileExt(file);
    if (!ext) return Promise.reject(new Error('jpg, png, webp, gif 사진만 넣을 수 있습니다.'));
    var url = URL.createObjectURL(file);
    return loadImage(url).then(function (im) {
      var w = im.naturalWidth, h = im.naturalHeight, k = 2400 / Math.max(w, h);
      if (ext === 'gif' || k >= 1) return { blob: file, ext: ext, w: w, h: h };
      var keepPng = ext === 'png' && hasAlpha(im), c = document.createElement('canvas');
      c.width = Math.round(w * k); c.height = Math.round(h * k);
      var g = c.getContext('2d');
      if (!keepPng) { g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height); }
      g.imageSmoothingQuality = 'high';
      g.drawImage(im, 0, 0, c.width, c.height);
      return new Promise(function (res, rej) {
        c.toBlob(function (b) {
          if (b) res({ blob: b, ext: keepPng ? 'png' : 'jpg', w: c.width, h: c.height }); else rej(new Error('사진을 줄이지 못했습니다.'));
        }, keepPng ? 'image/png' : 'image/jpeg', 0.88);
      });
    }).then(function (r) { URL.revokeObjectURL(url); return r; }, function (err) { URL.revokeObjectURL(url); throw err; });
  }
  function netErr(err) {
    if (err instanceof TypeError) return new Error('편집기 프로그램에 연결할 수 없습니다. 검은 창이 켜져 있는지 확인하세요.');
    return err;
  }
  /** 사진 올리기 → {src, w, h} */
  function upload(file, slot) {
    return prepareImage(file).then(function (r) {
      var q = 'api/upload?slot=' + encodeURIComponent(SLOT_RE.test(slot || '') ? slot : '') + '&ext=' + r.ext;
      return fetch(q, { method: 'POST', body: r.blob }).then(function (resp) {
        return resp.json().catch(function () { return {}; }).then(function (j) {
          if (!resp.ok || !j.ok || !j.src) throw new Error(j.error || '사진을 올리지 못했습니다.');
          return { src: j.src, w: r.w, h: r.h };
        });
      });
    }).catch(function (err) { throw netErr(err); });
  }
  function slotIndex(root, el) { return $$(root, SLOT_SEL).indexOf(el); }
  function slotFill(pid, k, fn) { return editPage(pid, function (root) { var s = $$(root, SLOT_SEL)[k]; if (s) fn(s); }); }
  function uploadToSlot(pid, k, slot, file) {
    toast('사진 올리는 중…');
    return upload(file, slot).then(function (r) {
      slotFill(pid, k, function (s) { s.innerHTML = '<img src="' + CR.esc(r.src) + '" alt="">'; });
      toast('사진을 넣었습니다');
    }).catch(function (err) { toast(err.message, true); });
  }
  function slotUpload(el, file) {
    var w = wrapOf(el);
    if (!w || !w.sec) return;
    var k = slotIndex(w.sec, el);
    if (k < 0) return;
    el.classList.add('ed-busy-slot');
    uploadToSlot(w.id, k, el.getAttribute('data-slot') || '', file).then(function () { el.classList.remove('ed-busy-slot'); });
  }
  function clearSlot(el) {
    var w = wrapOf(el);
    if (!w || !w.sec) return;
    var k = slotIndex(w.sec, el), full = el.classList.contains('full-slot');
    hideHoverTools();
    slotFill(w.id, k, function (s) {
      s.innerHTML = '<div class="noimg">' + (full ? '눌러서 쪽 그림 넣기 (A4 세로 그림 · Canva에서 PNG로 내보낸 것)' : '눌러서 사진 넣기') + '</div>';
    });
  }

  /* ───────────── 9 표·제품 칸 (떠 있는 도구막대) ───────────── */
  function cardTool() { return $('cardTool'); }
  function tableTool() { return $('tableTool'); }
  function rowTool() { return $('rowTool'); }
  function slotTool() { return $('slotTool'); }
  function hideT(t) { t.hidden = true; t._t = null; }
  // 홈페이지 번호를 입력하는 중이면 제품 칸 도구막대를 그대로 둔다 (마우스가 움직여도 입력 칸이 사라지거나 다른 칸으로 바뀌지 않게)
  // (칼 종류 고르기는 고르자마자 반영되므로 셈하지 않는다 — 고른 뒤에도 도구막대가 마우스를 따라가야 다음 칸에 잘못 고르지 않는다)
  function cardToolBusy() { return document.activeElement === $('cardProd'); }
  function hideHover() { [cardTool(), tableTool(), slotTool()].forEach(function (t) { if (t !== cardTool() || !cardToolBusy()) hideT(t); }); }
  function hideHoverTools() { hideHover(); hideT(rowTool()); }
  /** 도구막대를 대상 옆에 띄운다 (위치는 #sheet 기준이라 스크롤해도 따라간다) */
  function placeTool(tool, target, how) {
    if (!target) return;
    tool.hidden = false;
    var r = target.getBoundingClientRect(), base = sheet.getBoundingClientRect(), tw = tool.offsetWidth, th = tool.offsetHeight, x, y;
    if (how === 'tr') {                                                            // 안쪽 오른쪽 위
      x = r.right - tw - 3; y = r.top + 3;
      var h = target.querySelector('h4 > span') || target.querySelector('h4'), hr = null;
      if (h) { var rg = document.createRange(); rg.selectNodeContents(h); hr = rg.getBoundingClientRect(); }
      if (hr && hr.width && hr.right > x - 6 && hr.top < y + th && hr.bottom > y) y = r.top - th + 3;   // 제품 이름을 가리면 칸 바로 위로
    }
    else if (how === 'br') { x = r.right - tw; y = r.bottom - th / 2; }           // 오른쪽 아래
    else if (how === 'r') { x = r.right + 6; y = r.top + r.height / 2 - th / 2; } // 오른쪽 옆
    else if (how === 'tc') { x = r.left + r.width / 2 - tw / 2; y = r.top + 4; } // 안쪽 위 가운데
    else { x = r.left; y = r.top - th - 12; if (y < stage.getBoundingClientRect().top + 4) y = r.bottom + 10; } // 위
    tool.style.left = Math.round(x - base.left) + 'px';
    tool.style.top = Math.round(y - base.top) + 'px';
  }
  function showTool(tool, target, how) {
    if (!target) { if (!tool.hidden) hideT(tool); return; }
    if (tool._t === target && !tool.hidden) return;
    tool._t = target;
    placeTool(tool, target, how);
  }
  function onOver(e) {
    if (dragging) return;
    var t = e.target, inPage = !!t.closest('section.page') && !t.closest('.ov-layer');
    var card = inPage && t.closest(CARD_SEL);
    if (!cardToolBusy()) {
      if (card && cardTool()._t !== card) fillCardType(card);
      showTool(cardTool(), card, 'tr');
    }
    showTool(tableTool(), inPage && t.closest('.t'), 'br');
    var slot = inPage && t.closest(SLOT_SEL);
    showTool(slotTool(), slot && slot.querySelector('img') ? slot : null, 'tc');
  }
  function showRowTool(cell) {
    var row = rowOf(cell.parentElement, cell);
    if (!row.length) return;
    rowTool()._t = cell;
    placeTool(rowTool(), row[row.length - 1], 'r');
  }
  function onToolClick(e) {
    var b = e.target.closest('button[data-tool]');
    if (!b) return;
    var name = b.getAttribute('data-tool'), t = b.closest('.ed-tool')._t;
    if (name.indexOf('ov') === 0) { ovAction(name, b.getAttribute('data-v')); return; }
    if (cardToolBusy()) document.activeElement.blur();   // 입력 중인 홈페이지 번호를 먼저 반영
    if (!t || !t.isConnected) { hideHoverTools(); return; }
    var w = wrapOf(t);
    if (!w) return;
    if (name === 'cardDup') {
      hideHover();
      editPage(w.id, function () { dupCard(t); });
      toast('제품 칸을 복제했습니다');
    } else if (name === 'cardDel') {
      hideHover();
      editPage(w.id, function () { takeCard(t); });
      toast('제품 칸을 지웠습니다 — 되돌리기(Ctrl+Z)로 살릴 수 있습니다');
    } else if (name === 'cardNext' || name === 'cardPrev') {
      moveCard(t, name === 'cardNext' ? 1 : -1);
    } else if (name === 'rowAdd') {
      var cells = [];
      editPage(w.id, function () { cells = tableAddRow(t); decorate(t); });
      placeTool(tableTool(), t, 'br');
      if (cells[0]) cells[0].focus();
    } else if (name === 'rowDel') {
      var tb = t.parentElement;
      hideT(rowTool());
      editPage(w.id, function () { tableRemoveRow(tb, t); });
    } else if (name === 'slotChange') {
      pickFile().then(function (f) { if (f) slotUpload(t, f); });
    } else if (name === 'slotClear') clearSlot(t);
  }
  function pageHasBody(p) { return !!inertBox(p.html).querySelector(':scope > .body'); }
  /** 제품 칸을 다음 쪽 맨 앞(dir 1) / 앞 쪽 맨 뒤(dir -1)로 */
  function moveCard(card, dir) {
    var w = wrapOf(card), i = indexOf(w.id), j = i + dir, target = doc.pages[j];
    if (!target || !pageHasBody(target)) { toast((dir > 0 ? '다음' : '앞') + ' 쪽에는 제품 칸을 넣을 자리가 없습니다', true); return; }
    hideHoverTools();
    grouped(function () {
      editPage(w.id, function () { takeCard(card); });
      editPage(target.id, function (root) { putCard(root.querySelector(':scope > .body'), card, dir > 0); });
    });
    toast((j + 1) + '쪽 ' + (dir > 0 ? '맨 앞으로' : '맨 뒤로') + ' 옮겼습니다');
  }
  function addCardToPage(w) {
    ensureRendered(w);
    var body = w.sec.querySelector(':scope > .body'), card = null;
    if (!body) { toast('이 쪽에는 제품 칸을 넣을 수 없습니다', true); return; }
    editPage(w.id, function () { card = addCard(body); decorate(card); });
    if (card) toast('제품 칸을 쪽 끝에 넣었습니다');
  }

  /* ───────────── 10 글상자·자유 사진 (overlays) ───────────── */
  var dragging = false;
  function ovEl(s) {
    s = s || sel;
    var w = s && W.get(s.pid);
    return w && w.sec ? w.sec.querySelector('.ov[data-ov="' + CSS.escape(s.oid) + '"]') : null;
  }
  function ovModel(s) {
    s = s || sel;
    var p = s && doc.pages[indexOf(s.pid)];
    return p ? p.overlays.filter(function (o) { return o.id === s.oid; })[0] || null : null;
  }
  function select(pid, oid) {
    if (sel && sel.pid === pid && sel.oid === oid) { showOvTool(); return; }
    deselect();
    sel = { pid: pid, oid: oid };
    markSelected();
    showOvTool();
  }
  function markSelected() {
    var el = ovEl();
    if (!el) return;
    el.classList.add('ed-sel');
    if (!el.querySelector(':scope > .ed-h'))
      el.insertAdjacentHTML('beforeend', '<i class="ed-h ed-h-move" title="끌어서 옮기기"></i><i class="ed-h ed-h-size" title="끌어서 크기 바꾸기"></i>');
  }
  function deselect() {
    if (!sel) return;
    stopEditOv();
    var el = ovEl();
    if (el) { el.classList.remove('ed-sel'); each($$(el, ':scope > .ed-h'), function (h) { h.remove(); }); }
    sel = null;
    $('ovTool').hidden = true;
  }
  function showOvTool() {
    var tool = $('ovTool'), o = ovModel(), el = ovEl();
    if (!o || !el) { tool.hidden = true; return; }
    var text = o.type === 'text', st = o.style || {};
    tool.querySelector('.ed-ov-text').hidden = !text;
    if (text) {
      $('ovSize').textContent = (Number(st.size) || 12) + 'pt';
      $('ovBold').classList.toggle('on', !!st.bold);
      $('ovColor').value = /^#[0-9a-f]{6}$/i.test(st.color || '') ? st.color : '#1a1a1a';
      each(tool.querySelectorAll('[data-tool="ovAlign"]'), function (b) { b.classList.toggle('on', (st.align || 'left') === b.getAttribute('data-v')); });
      each(tool.querySelectorAll('[data-tool="ovBg"]'), function (b) { b.classList.toggle('on', (st.bg || '') === b.getAttribute('data-v')); });
    }
    placeTool(tool, el, 'above');
  }
  function placeOvTool() { if (sel && !$('ovTool').hidden) placeTool($('ovTool'), ovEl(), 'above'); }
  /** 글상자·사진 모델 고치기 (쪽 객체를 새로 만들고, 화면은 그 요소의 style 만 바꾼다) */
  function updateOv(s, patch) {
    var i = indexOf(s.pid), p = doc.pages[i], n = null;
    if (!p) return;
    change(function () {
      setPage(i, Object.assign({}, p, { overlays: p.overlays.map(function (o) {
        if (o.id !== s.oid) return o;
        n = Object.assign({}, o, patch);
        if (patch.style) n.style = Object.assign({}, o.style, patch.style);
        return n;
      }) }));
    });
    var el = ovEl(s);
    if (el && n) el.setAttribute('style', CR.overlayStyle(n));
    if (sel && sel.oid === s.oid) showOvTool();
  }
  function addOverlay(pid, make) {
    flushAll();
    var w = W.get(pid), i = indexOf(pid), o = null;
    if (!w || i < 0) return null;
    ensureRendered(w);
    var p = doc.pages[i];
    change(function () { o = make(CR.newId(doc, 'ov')); setPage(i, Object.assign({}, p, { overlays: p.overlays.concat([o]) })); });
    w.sec.querySelector(':scope > .ov-layer').insertAdjacentHTML('beforeend', CR.overlayHTML(o));
    select(pid, o.id);
    return o;
  }
  function addTextBox(w) {
    var o = addOverlay(w.id, function (id) {
      return { id: id, type: 'text', x: 60, y: 128, w: 90, h: 20, html: NEW_TEXT,
        style: { size: 12, color: '#1a1a1a', bold: false, align: 'left', bg: '' } };
    });
    if (o) startEditOv(true);
  }
  function addPhoto(pid, file) {
    toast('사진 올리는 중…');
    upload(file, '').then(function (r) {
      var w = 80, h = r.w ? Math.round(80 * r.h / r.w * 10) / 10 : 60;
      if (h > 260) { w = Math.round(w * 260 / h * 10) / 10; h = 260; }
      var o = addOverlay(pid, function (id) {
        return { id: id, type: 'image', x: Math.round((CR.PAGE_W_MM - w) / 2 * 10) / 10, y: Math.round((CR.PAGE_H_MM - h) / 2 * 10) / 10, w: w, h: h, src: r.src };
      });
      if (o) toast('사진을 넣었습니다. 끌어서 옮기고, 오른쪽 아래 동그라미로 크기를 바꾸세요');
    }).catch(function (err) { toast(err.message, true); });
  }
  function startEditOv(selectAll) {
    var el = ovEl(), o = ovModel();
    if (!el || !o || o.type !== 'text') return;
    var body = el.querySelector('.ov-text-body');
    if (!body) return;
    editingOv = true;
    el.classList.add('ed-editing');
    body.setAttribute('contenteditable', 'true');
    body.focus();
    if (selectAll || body.textContent === NEW_TEXT) {
      var r = document.createRange(), s = global.getSelection();
      r.selectNodeContents(body);
      s.removeAllRanges();
      s.addRange(r);
    }
  }
  function commitOvText() {
    clearTimeout(ovTimer);
    if (!editingOv || !sel) return;
    var el = ovEl(), o = ovModel(), body = el && el.querySelector('.ov-text-body');
    if (!body || !o) return;
    var html = CR.sanitizeHTML(body.innerHTML);
    if (html !== o.html) updateOv(sel, { html: html });
  }
  function stopEditOv() {
    if (!editingOv) return;
    commitOvText();
    editingOv = false;
    var el = ovEl(), b = el && el.querySelector('.ov-text-body');
    if (el) el.classList.remove('ed-editing');
    if (b) b.removeAttribute('contenteditable');
  }
  function deleteOv() {
    if (!sel) return;
    var s = sel, i = indexOf(s.pid), el = ovEl(s);
    editingOv = false;                                 // 지울 것이니 글은 반영하지 않는다
    deselect();
    var p = doc.pages[i];
    if (!p) return;
    change(function () { setPage(i, Object.assign({}, p, { overlays: p.overlays.filter(function (o) { return o.id !== s.oid; }) })); });
    if (el) el.remove();
    toast('지웠습니다 — 되돌리기(Ctrl+Z)로 살릴 수 있습니다');
  }
  function ovAction(name, v) {
    var o = ovModel();
    if (!o) return;
    if (name === 'ovDel') { deleteOv(); return; }
    var st = o.style || {};
    commitOvText();
    if (name === 'ovSmaller' || name === 'ovBigger')
      updateOv(sel, { style: { size: Math.max(6, Math.min(72, (Number(st.size) || 12) + (name === 'ovBigger' ? 1 : -1))) } });
    else if (name === 'ovBold') updateOv(sel, { style: { bold: !st.bold } });
    else if (name === 'ovAlign') updateOv(sel, { style: { align: v } });
    else if (name === 'ovBg') updateOv(sel, { style: { bg: v || '' } });
  }
  function onPointerDown(e) {
    if (e.button !== 0) return;
    var t = e.target;
    if (t.closest('.ed-tool')) return;
    var ovE = t.closest('.ed-pages .ov');
    if (!ovE) { if (sel) deselect(); return; }
    var w = wrapOf(ovE), oid = ovE.getAttribute('data-ov'), isH = t.classList.contains('ed-h');
    if (editingOv && sel && sel.oid === oid && !isH) return;     // 글 입력 중: 커서 움직이기
    var ae = document.activeElement;                              // 다른 칸에 입력 중이었으면 끝낸다 (Delete 가 그 칸에 가지 않게)
    if (ae && ae.isContentEditable && !ovE.contains(ae)) ae.blur();
    select(w.id, oid);
    e.preventDefault();
    startDrag(e, ovE, t.classList.contains('ed-h-size') ? 'size' : 'move');
  }
  function onDblClick(e) {
    var ov = e.target.closest('.ov-text');
    if (ov && sel && ov.getAttribute('data-ov') === sel.oid && !editingOv) startEditOv(false);
  }
  /** 끌어서 옮기기·크기 바꾸기. 화면 px → mm (배율 s 고려) */
  function startDrag(e, el, mode) {
    var o = ovModel();
    if (!o) return;
    var s = sel, sx = e.clientX, sy = e.clientY, k = 1 / (scale * PXMM), moved = false, now = {};
    var x0 = Number(o.x) || 0, y0 = Number(o.y) || 0, w0 = Number(o.w) || 50, hNow = el.offsetHeight / PXMM;
    var h0 = o.type === 'image' ? (Number(o.h) || 40) : (Number(o.h) || 10), ratio = o.type === 'image' ? h0 / w0 : 0;
    function r1(v) { return Math.round(v * 10) / 10; }
    function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
    function move(ev) {
      if (!moved && Math.abs(ev.clientX - sx) + Math.abs(ev.clientY - sy) < 4) return;
      if (!moved) { moved = true; dragging = true; $('ovTool').hidden = true; hideHover(); }
      var dx = (ev.clientX - sx) * k, dy = (ev.clientY - sy) * k;
      if (mode === 'move') {                             // 쪽 밖으로 다 나가지 않게 (5mm 는 남긴다)
        now.x = r1(clamp(x0 + dx, 5 - w0, CR.PAGE_W_MM - 5));
        now.y = r1(clamp(y0 + dy, 5 - hNow, CR.PAGE_H_MM - 5));
        el.style.left = now.x + 'mm'; el.style.top = now.y + 'mm';
      } else {
        now.w = r1(clamp(w0 + dx, 10, 400));
        if (ratio) { now.h = r1(now.w * ratio); el.style.height = now.h + 'mm'; }
        else { now.h = r1(Math.max(5, h0 + dy)); el.style.minHeight = now.h + 'mm'; }
        el.style.width = now.w + 'mm';
      }
    }
    function up() {
      global.removeEventListener('pointermove', move);
      global.removeEventListener('pointerup', up);
      global.removeEventListener('pointercancel', up);
      dragging = false;
      if (moved) updateOv(s, now); else showOvTool();
    }
    global.addEventListener('pointermove', move);
    global.addEventListener('pointerup', up);
    global.addEventListener('pointercancel', up);
  }

  /* ───────────── 11 PDF·내보내기·화면 틀 ───────────── */
  var toastTimer = 0;
  function toast(msg, bad) {
    var t = $('toast');
    t.textContent = msg;
    t.className = 'ed-toast' + (bad ? ' bad' : '');
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, bad ? 6000 : 2800);
  }
  function busy(text) { $('busyText').textContent = text || ''; $('busy').hidden = !text; }
  function runJob(url, text, report) {
    busy(text);
    save().then(function (ok) {
      if (!ok) throw new Error('먼저 저장해야 하는데 저장이 되지 않았습니다. 편집기 프로그램(검은 창)이 켜져 있는지 확인하세요.');
      return postJSON(url, null).catch(function (err) { throw netErr(err); });
    }).then(function (j) { busy(''); global.alert(report(j)); }, function (err) { busy(''); global.alert('실패했습니다.\n\n' + err.message); });
  }
  /** PDF 결과: {path, pages, files:[{name, pages}], notes:[…]} (예전 모양 {path, pages} 도 됨) */
  function reportPdf(j) {
    var files = Array.isArray(j.files) ? j.files : [], notes = Array.isArray(j.notes) ? j.notes : [];
    return 'PDF를 만들었습니다' + (j.pages ? ' (' + (files.length > 1 ? '모두 ' : '') + j.pages + '쪽)' : '') + '.\n\n' +
      (files.length ? files.map(function (f) { return '· ' + f.name + (f.pages ? ' — ' + f.pages + '쪽' : ''); }).join('\n') + '\n\n' : '') +
      (files.length ? '들어 있는 폴더: ' : '') + (j.path || '') +
      (notes.length ? '\n\n알아 둘 점:\n' + notes.map(function (n) { return '· ' + n; }).join('\n') : '');
  }
  /** 홈페이지에 올리기: 저장 → 묻기 → 시작 → 1초마다 진행 상황 → 결과 창 */
  function publish() {
    busy('저장하는 중…');
    save().then(function (ok) {
      busy('');
      if (!ok) throw new Error('먼저 저장해야 하는데 저장이 되지 않았습니다. 편집기 프로그램(검은 창)이 켜져 있는지 확인하세요.');
      if (!global.confirm('홈페이지에 올릴까요?\n\n지금 저장된 카탈로그로 홈페이지용 책을 만들어 홈페이지 서버에 올립니다.\n' +
        '홈페이지의 카탈로그가 지금 내용으로 바뀝니다. 사진이 많으면 몇 분 걸릴 수 있습니다.\n\n다 될 때까지 편집기와 검은 창을 닫지 마세요.')) return;
      busy('홈페이지에 올릴 준비 중…');
      return postJSON('api/publish', null).catch(function (err) { throw netErr(err); }).then(watchPublish).then(function (s) {
        busy('');
        $('pubMsg').textContent = s.message || '홈페이지의 카탈로그를 지금 내용으로 바꿨습니다.';
        $('pubUrl').textContent = s.url || '';
        $('pubOpen').hidden = !s.url;
        if (s.url) $('pubOpen').href = s.url;
        $('pubDlg').showModal();
      });
    }).catch(function (err) { busy(''); global.alert('홈페이지에 올리지 못했습니다.\n\n' + err.message); });
  }
  /** 올리는 중 상태를 1초마다 묻는다. 끝나면 상태를, 실패하면 서버가 준 까닭을 돌려준다 */
  function watchPublish() {
    return new Promise(function (res, rej) {
      var fails = 0, waits = 0;
      (function tick() {
        fetch('api/publish/status', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (s) {
          fails = 0;
          if (s.state === 'done') return res(s);
          if (s.state === 'error') return rej(new Error(s.message || s.error || '알 수 없는 문제로 멈췄습니다.'));
          if (s.state !== 'running' && ++waits > 10) return rej(new Error('올리기가 시작되지 않았습니다. 잠시 뒤 다시 눌러 주세요.'));
          busy(s.total ? '홈페이지에 올리는 중… ' + (s.done || 0) + ' / ' + s.total : (s.message || '홈페이지에 올리는 중…'));
          setTimeout(tick, 1000);
        }).catch(function () {
          if (++fails >= 5) return rej(new Error('편집기 프로그램에서 진행 상황을 받지 못했습니다. 검은 창이 켜져 있는지 확인하세요.'));
          setTimeout(tick, 1000);
        });
      })();
    });
  }
  function reportExport(j) {
    var m = j.missing || [];
    return '홈페이지용 폴더를 만들었습니다' + (j.files ? ' (파일 ' + j.files + '개)' : '') + '.\n\n' + (j.path || '') +
      '\n\n이 폴더 전체를 홈페이지 서버에 올리세요.' +
      (m.length ? '\n\n찾지 못한 사진 ' + m.length + '개: ' + m.slice(0, 5).join(', ') + (m.length > 5 ? ' …' : '') : '');
  }
  function openBook() {
    var url = 'viewer.html#p=' + (cur + 1), win = global.open('about:blank', '_blank');
    save().then(function (ok) {
      if (!ok) toast('저장이 안 되어 마지막으로 저장된 모습이 보입니다', true);
      if (win && !win.closed) win.location.href = url; else global.open(url, '_blank');
    });
  }
  function toggleSide(open) {
    document.body.classList.toggle('ed-side-off', !open);
    $('sideOpenBtn').hidden = open;
    applyScale();
  }
  function onPagesClick(e) {
    var t = e.target;
    if (t.closest('a') && t.closest('section.page')) e.preventDefault();   // 링크는 이동하지 않는다
    var b = t.closest('button[data-act]');
    if (b) {
      var act = b.getAttribute('data-act');
      if (act === 'add') openAdd(b); else pageAction(act, wrapOf(b));
      return;
    }
    if (t.closest('[contenteditable="true"], .ov-layer') || !t.closest('section.page')) return;
    var slot = t.closest(SLOT_SEL);
    if (slot) pickFile().then(function (f) { if (f) slotUpload(slot, f); });
  }
  function hasFiles(e) { var ty = e.dataTransfer && e.dataTransfer.types; return !!ty && Array.prototype.indexOf.call(ty, 'Files') >= 0; }
  function slotAt(node) {
    var el = node && (node.nodeType === 1 ? node : node.parentElement);
    if (!el || !el.closest('.ed-pages section.page') || el.closest('.ov-layer')) return null;
    return el.closest(SLOT_SEL);
  }
  var dropEl = null;
  function setDrop(el) {
    if (dropEl === el) return;
    if (dropEl) dropEl.classList.remove('ed-drop');
    dropEl = el;
    if (el) el.classList.add('ed-drop');
  }
  function onDragOver(e) {
    if (!hasFiles(e)) { if (editHost(e.target)) { e.preventDefault(); e.dataTransfer.dropEffect = 'none'; } return; }
    e.preventDefault();                                // 파일을 놓아도 브라우저가 그 파일로 넘어가지 않게
    var slot = slotAt(e.target);
    e.dataTransfer.dropEffect = slot ? 'copy' : 'none';
    setDrop(slot);
  }
  function onDrop(e) {
    if (!hasFiles(e)) { if (editHost(e.target)) e.preventDefault(); return; }
    e.preventDefault();
    var slot = slotAt(e.target), f = e.dataTransfer.files && e.dataTransfer.files[0];
    setDrop(null);
    if (!f) return;
    if (slot) slotUpload(slot, f); else toast('사진은 사진 칸 위에 놓아 주세요 (자유 사진은 쪽 위 [+ 사진])', true);
  }
  function onBeforeUnload(e) {
    flushAll();
    if (ver !== savedVer || saving) { save(); e.preventDefault(); e.returnValue = ''; return ''; }
  }
  function debounce(fn, ms) { var t = 0; return function () { clearTimeout(t); t = setTimeout(fn, ms); }; }

  /* ───────────── 11 목차·칼 색인 자동, 넘치면 새 쪽 ───────────── */
  var TITLE_PH = '제목을 입력하세요';
  var AUTO_COLOR = '#1f3c88';
  var infoCache = new WeakMap();
  function textOf(el) { return el ? el.textContent.replace(/\s+/g, ' ').trim() : ''; }
  /** 쪽 하나에서 목차·색인에 필요한 것만 뽑는다 (쪽 객체가 같으면 다시 읽지 않는다) */
  function pageInfo(p) {
    var f = infoCache.get(p);
    if (f) return f;
    var box = inertBox(p.html), crumb = box.querySelector('.crumb'), ch = '', en = '';
    if (crumb) {
      var c2 = crumb.cloneNode(true), sp = c2.querySelector('span');
      en = textOf(sp);
      if (sp) sp.remove();
      ch = textOf(c2);
    }
    var tb = box.querySelector('.ttl b'), title = '';
    if (tb) { var img = tb.querySelector('img'); title = img ? (img.getAttribute('alt') || '') : textOf(tb); }
    var names = title.replace(/\s*외$/, '').split(' · ').map(function (s) { return s.trim(); })
      .filter(function (n) { return n && n !== TITLE_PH; });
    each($$(box, '.body .band1 > span'), function (s) { var n = textOf(s); if (n && names.indexOf(n) < 0) names.push(n); });
    var m = /--c:\s*([^;]+)/.exec(p.style || '');
    f = { ch: ch, en: en, names: names, color: (m && CR.safeColor(m[1].trim())) || AUTO_COLOR,
      types: $$(box, '[data-type]').map(function (e) { return e.getAttribute('data-type') || ''; }),
      brand: p.kind === 'misc' ? '기타 나이프' : (names[0] || '') };
    infoCache.set(p, f);
    return f;
  }
  /** 목차 항목: 대분류(쪽 머리의 분류) → 그 안 제목(브랜드·종류)이 처음 나오는 쪽 */
  function tocEntries() {
    var out = [], seen = new Set(), chColor = {};
    doc.pages.forEach(function (p) {
      if (p.kind === 'cover' || p.kind === 'toc' || p.kind === 'image') return;
      var f = pageInfo(p);
      if (!f.ch) return;
      if (!seen.has(f.ch)) { seen.add(f.ch); chColor[f.ch] = f.color; out.push({ ch: true, text: f.ch, en: f.en, ref: p.id, color: f.color }); }
      f.names.forEach(function (n) {
        var k = f.ch + '\u0000' + n;
        if (!seen.has(k)) { seen.add(k); out.push({ ch: false, text: n, ref: p.id, color: chColor[f.ch] }); }
      });
    });
    return out;
  }
  /** 칼 색인 항목: 칼 종류 → 브랜드(또는 기타 나이프)가 처음 나오는 쪽 */
  function indexEntries() {
    var order = (doc.meta && doc.meta.knifeTypes) || [], first = new Map(), types = [];
    doc.pages.forEach(function (p, i) {
      if (p.kind !== 'content' && p.kind !== 'misc' && p.kind !== 'blank') return;
      var f = pageInfo(p);
      if (f.ch !== '칼' || !f.brand) return;
      f.types.forEach(function (t) {
        if (!t) return;
        var k = t + '\u0000' + f.brand;
        if (!first.has(k)) first.set(k, { type: t, brand: f.brand, ref: p.id, i: i });
        if (types.indexOf(t) < 0) types.push(t);
      });
    });
    var rank = function (t) { var r = order.indexOf(t); return r < 0 ? 1000 + types.indexOf(t) : r; };
    types.sort(function (a, b) { return rank(a) - rank(b); });
    var all = Array.from(first.values()), out = [];
    types.forEach(function (t) {
      var ents = all.filter(function (v) { return v.type === t; }).sort(function (a, b) { return a.i - b.i; });
      out.push({ ch: true, text: t, ref: ents[0].ref, color: AUTO_COLOR });
      ents.forEach(function (v) { out.push({ ch: false, text: v.brand, ref: v.ref, color: AUTO_COLOR }); });
    });
    return out;
  }
  /** 항목을 단(세로 줄)으로, 단을 쪽으로 (한 쪽에 3단, 단 높이 236mm) — 생성기 toc_columns 와 같은 규칙 */
  function tocPages(entries) {
    var cols = [], col = [], h = 0;
    entries.forEach(function (e) {
      var need = e.ch ? 11 + 5.5 : 5.5;
      if (h + need > 236 && col.length) { cols.push(col); col = []; h = 0; }
      col.push(e);
      h += e.ch ? 11 : 5.5;
    });
    cols.push(col);
    var pages = [];
    for (var i = 0; i < cols.length; i += 3) pages.push(cols.slice(i, i + 3));
    return pages;
  }
  function entryHTML(e) {
    return '<a class="' + (e.ch ? 'ch' : 'it') + '" data-ref="' + CR.esc(e.ref) + '" style="--c:' + (CR.safeColor(e.color) || AUTO_COLOR) + '">' +
      '<span>' + CR.esc(e.text) + (e.ch && e.en ? ' <em>' + CR.esc(e.en) + '</em>' : '') + '</span><b class="pref"></b></a>';
  }
  /** 목차(kind) 쪽들을 항목대로 다시 만든다. 쪽 수가 모자라면 마지막 쪽 뒤에 더하고, 남으면 뺀다. 바뀌면 true */
  function regenKind(kind, entries) {
    var at = [];
    doc.pages.forEach(function (p, i) { if (p.kind === kind) at.push(i); });
    if (!at.length) return false;
    var tpl = doc.pages[at[0]], changed = false;
    var fresh = tocPages(entries).map(function (cols, k) {
      var old = k < at.length ? doc.pages[at[k]] : null, box = inertBox((old || tpl).html), body = box.querySelector(':scope > .body');
      if (!body) return old;
      body.innerHTML = '<div class="toc">' + cols.map(function (col) { return '<div class="tcol">' + col.map(entryHTML).join('') + '</div>'; }).join('') + '</div>';
      var html = serialize(box);
      if (old && old.html === html) return old;
      changed = true;
      return old ? Object.assign({}, old, { html: html })
        : { id: CR.newId(doc, 'pg'), kind: kind, cls: tpl.cls || '', style: tpl.style || '', html: html, overlays: [] };
    }).filter(Boolean);
    if (fresh.length !== at.length) changed = true;
    if (!changed) return false;
    var out = [], k = 0, last = at[at.length - 1];
    doc.pages.forEach(function (p, i) {
      if (p.kind !== kind) { out.push(p); return; }
      if (k < fresh.length) out.push(fresh[k]);
      k++;
      if (i === last) while (k < fresh.length) out.push(fresh[k++]);
    });
    doc.pages = out;
    return true;
  }
  /** 목차·칼 색인을 문서 내용대로 맞춘다. 바뀌었으면 true (화면을 다시 맞춰야 함) */
  function regenDerived() {
    if (!doc) return false;
    var a = regenKind('toc', tocEntries());
    var b = regenKind('index', indexEntries());
    return a || b;
  }

  /** 쪽이 넘치면 끝에서부터 몇 덩어리(제품 칸·2단 줄·띠·표 줄)를 빼야 안 넘치는지. 넘치지 않거나 뺄 수 없으면 0 */
  function flowCount(p, i) {
    var sec = CR.createPageElement(p, i, nums), mb = measureBox();
    mb.appendChild(sec);
    try {
      var body = sec.querySelector(':scope > .body');
      if (!body || !overflows(sec)) return 0;
      var kids = $$(body, ':scope > *').filter(function (el) { return !el.classList.contains('mh'); }), k = 0;
      while (kids.length > 1 && overflows(sec)) { kids.pop().remove(); k++; }
      // 제목 띠(.band1 .band2 .mb)만 덩그러니 남지 않게
      while (kids.length > 1 && /(^|\s)(band1|band2|mb)(\s|$)/.test(kids[kids.length - 1].className)) { kids.pop().remove(); k++; }
      return k;
    } finally { mb.textContent = ''; }
  }
  /** 넘친 덩어리들을 바로 뒤 새 쪽으로 (머리·탭·색은 같게, 번호는 자동). 새 쪽도 넘치면 또 */
  function autoFlow(id) {
    var i0 = indexOf(id), p0 = doc.pages[i0];
    if (!p0 || p0.kind === 'toc' || p0.kind === 'index' || !flowCount(p0, i0)) return;
    var made = 0;
    change(function () {      // 되돌리기 한 단계 (Ctrl+Z 하면 새 쪽이 없어지고 원래대로)
      var curId = id, guard = 0;
      while (curId && guard++ < 40) {
        var i = indexOf(curId), p = doc.pages[i], k = flowCount(p, i);
        if (!k) break;
        var box = inertBox(p.html), body = box.querySelector(':scope > .body');
        var kids = $$(body, ':scope > *').filter(function (el) { return !el.classList.contains('mh'); });
        var moving = kids.slice(kids.length - k), nb = inertBox(p.html), nbody = nb.querySelector(':scope > .body');
        nbody.innerHTML = '';
        var head = body.querySelector(':scope > .mh');
        if (head && moving[0] && /(^|\s)(mb|mr)(\s|$)/.test(moving[0].className)) nbody.appendChild(head.cloneNode(true));
        moving.forEach(function (el) { nbody.appendChild(el); });
        var np = { id: CR.newId(doc, 'pg'), kind: p.kind, cls: p.cls || '', style: p.style || '', html: serialize(nb), overlays: [] };
        setPage(i, Object.assign({}, p, { html: serialize(box) }));
        doc.pages.splice(i + 1, 0, np);
        nums = CR.numberMap(doc);
        made++;
        curId = np.id;
      }
    });
    sync();
    scanSoon();
    toast('쪽이 넘쳐서 넘친 제품 칸을 새 쪽(' + (indexOf(id) + 2) + '쪽)으로 옮겼습니다' + (made > 1 ? ' — 새 쪽 ' + made + '장' : ''));
  }
  var flowPending = new Set();
  function wantFlow(id) { flowPending.add(id); setTimeout(runFlows, 0); }
  function runFlows() {
    flowPending.forEach(function (id) {
      var w = W.get(id), a = document.activeElement;
      if (w && w.sec && a && a !== document.body && w.sec.contains(a)) return;   // 입력 중이면 입력을 마친 뒤(focusout)에
      flowPending.delete(id);
      autoFlow(id);
    });
  }

  /** 제품 칸 도구막대의 '칼 종류' 고르기 (칼 쪽에서만) */
  function fillCardType(card) {
    var prod = card.getAttribute('data-prod') || '';
    $('cardProd').value = prod;
    setProdLink(prod);
    var w = wrapOf(card), p = w && doc.pages[indexOf(w.id)], wrap = $('cardTypeWrap'), selEl = $('cardType');
    var knife = !!p && pageInfo(p).ch === '칼';
    wrap.hidden = !knife;
    if (!knife) return;
    var cur = card.getAttribute('data-type') || '', list = ((doc.meta && doc.meta.knifeTypes) || []).slice();
    if (cur && list.indexOf(cur) < 0) list.push(cur);
    selEl.innerHTML = '<option value="">칼 종류 고르기</option>' + list.map(function (t) {
      return '<option value="' + CR.esc(t) + '">' + CR.esc(t) + '</option>';
    }).join('');
    selEl.value = cur;
    selEl.classList.toggle('ed-need', !cur);
  }
  function onCardType() {
    var t = cardTool()._t, v = this.value;
    if (!t || !t.isConnected) return;
    var w = wrapOf(t);
    if (!w) return;
    editPage(w.id, function () { if (v) t.setAttribute('data-type', v); else t.removeAttribute('data-type'); });
    this.classList.toggle('ed-need', !v);
    toast(v ? '칼 종류를 「' + v + '」(으)로 정했습니다 — 칼 색인에 저절로 들어갑니다' : '칼 종류를 지웠습니다');
  }

  /** 제품 칸의 홈페이지 상품 번호 (data-prod). 책 보기에서 제품을 누르면 이 번호의 상품 페이지가 열린다 */
  var PROD_URL = 'https://sindoltd.com/product/detail.html?product_no=';
  function setProdLink(v) { var a = $('cardProdOpen'); a.hidden = !v; a.href = v ? PROD_URL + v : '#'; }
  function onCardProd() {
    var t = cardTool()._t, v = this.value.replace(/\D/g, '');
    this.value = v;
    setProdLink(v);
    if (!t || !t.isConnected || (t.getAttribute('data-prod') || '') === v) return;
    var w = wrapOf(t);
    if (!w) return;
    editPage(w.id, function () { if (v) t.setAttribute('data-prod', v); else t.removeAttribute('data-prod'); });
    toast(v ? '홈페이지 상품 번호를 ' + v + '번으로 정했습니다' : '홈페이지 상품 번호를 지웠습니다');
  }

  function bindUI() {
    pagesEl.addEventListener('input', onInput);
    pagesEl.addEventListener('focusin', onFocusIn);
    pagesEl.addEventListener('focusout', onFocusOut);
    pagesEl.addEventListener('paste', onPaste);
    pagesEl.addEventListener('click', onPagesClick);
    pagesEl.addEventListener('dblclick', onDblClick);
    pagesEl.addEventListener('mouseover', onOver);
    sheet.addEventListener('mouseleave', hideHover);
    stage.addEventListener('pointerdown', onPointerDown);
    var ticking = false;
    stage.addEventListener('scroll', function () {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () { ticking = false; updateCurrent(); });
    }, { passive: true });
    var tl = $('toolLayer');
    tl.addEventListener('mousedown', function (e) { if (e.target.closest('button')) e.preventDefault(); });  // 입력 중인 칸의 커서를 지킨다
    tl.addEventListener('click', onToolClick);
    $('cardType').addEventListener('change', onCardType);
    $('cardProd').addEventListener('change', onCardProd);
    $('cardProd').addEventListener('input', function (e) { var v = this.value.replace(/\D/g, ''); if (!e.isComposing && v !== this.value) this.value = v; setProdLink(v); });
    $('cardProd').addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) this.blur(); });
    $('ovColor').addEventListener('input', function () { var el = ovEl(); if (el) el.style.color = this.value; });
    $('ovColor').addEventListener('change', function () { if (sel) updateOv(sel, { style: { color: this.value } }); });
    document.addEventListener('keydown', onKey);
    document.addEventListener('dragover', onDragOver);
    document.addEventListener('dragleave', function (e) { if (!e.relatedTarget) setDrop(null); });
    document.addEventListener('drop', onDrop);
    global.addEventListener('beforeunload', onBeforeUnload);
    document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'hidden') save(); });
    global.addEventListener('resize', debounce(function () { if (scaleMode === 'fit') applyScale(); }, 120));
    $('undoBtn').onclick = undo;
    $('redoBtn').onclick = redo;
    $('zoomSel').onchange = function () { scaleMode = this.value; applyScale(); this.blur(); };
    $('finalChk').onchange = function () { pagesEl.classList.toggle('final', this.checked); hideHoverTools(); };
    $('bookBtn').onclick = openBook;
    $('pdfBtn').onclick = function () { runJob('api/pdf', 'PDF 만드는 중… 두 권으로 나눠 만들어서 2~4분 걸립니다', reportPdf); };
    $('exportBtn').onclick = function () { runJob('api/export', '홈페이지용 폴더 만드는 중…', reportExport); };
    $('pubBtn').onclick = publish;
    $('pubOpen').onclick = function () { $('pubDlg').close(); };
    $('helpBtn').onclick = function () { $('helpDlg').showModal(); };
    $('sideBtn').onclick = function () { toggleSide(false); };
    $('sideOpenBtn').onclick = function () { toggleSide(true); };
    $('findInput').addEventListener('input', debounce(function () { renderList(); updateCurrent(true); }, 250));
    listEl.addEventListener('click', function (e) {
      var li = e.target.closest('li[data-id]');
      if (li) scrollToIndex(indexOf(li.getAttribute('data-id')));
    });
    $('addDlg').addEventListener('click', function (e) {
      var b = e.target.closest('button[data-type]');
      if (!b || b.disabled) return;
      $('addDlg').close();
      var type = b.getAttribute('data-type'), p = addPageAt(addAt, type);
      if (p && type === 'image') pickFile().then(function (f) { if (f) uploadToSlot(p.id, 0, '', f); });   // 바로 쪽 그림 고르기
    });
  }

  /* ───────────── 12 시작 ───────────── */
  global.EditorInternals = {
    serialize: serialize, decorate: decorate, makePage: makePage, dupPage: dupPage, headFrom: headFrom, linkCount: linkCount,
    tableAddRow: tableAddRow, tableRemoveRow: tableRemoveRow, rowOf: rowOf, takeCard: takeCard, putCard: putCard,
    dupCard: dupCard, addCard: addCard, freshSlots: freshSlots, snap: snap, restoreSnap: restoreSnap, inertBox: inertBox,
    app: {
      doc: function () { return doc; }, state: function () {
        return { cur: cur, scale: scale, undo: undoStack.length, redo: redoStack.length, ver: ver, savedVer: savedVer,
          rendered: order.filter(function (w) { return w.sec; }).map(function (w) { return indexOf(w.id) + 1; }), sel: sel };
      },
      wrap: function (id) { return W.get(id); }, sync: sync, flushAll: flushAll, undo: undo, redo: redo, save: save,
      scrollToIndex: scrollToIndex, editPage: editPage, addPageAt: addPageAt, removePage: removePage, movePage: movePage,
      moveCard: moveCard, addTextBox: addTextBox, select: select, deselect: deselect, updateOv: updateOv,
      setScale: function (m) { scaleMode = String(m); applyScale(); },
      regenDerived: regenDerived, tocEntries: tocEntries, indexEntries: indexEntries, autoFlow: autoFlow, flowCount: flowCount
    }
  };
  if (document.getElementById('ed-stage')) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  }
})(window);
