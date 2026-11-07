/* 신도 카탈로그 공용 렌더러 — editor.js 와 viewer.js 가 같이 쓴다. (편집하지 말 것: 두 화면의 약속)

   문서(catalog.json) 구조
   {
     version: 1,
     title: "SINDO 제품 카탈로그",
     meta: { nextId: 382 },                 // 새 페이지·글상자 id 를 만들 때 쓰는 번호
     pages: [
       {
         id: "pg-0001",                      // 바뀌지 않는 이름. 목차·색인은 이 id 로 쪽을 가리킨다
         kind: "cover" | "toc" | "index" | "content" | "misc" | "blank" | "image",
         cls: "cover",                       // section.page 에 더 붙는 class (없으면 "")
         style: "--c:#1f3c88",               // section.page 의 style (챕터 색)
         html: "<header class=ph>…</header><div class=body>…</div><footer class=pf>…<b class=pno></b></footer>…",
         overlays: [                         // 자유 배치 글상자·사진 (좌표는 mm, 쪽 왼쪽 위 기준)
           { id: "ov-12", type: "text",  x: 20, y: 40, w: 80, h: 20, html: "글자",
             style: { size: 12, color: "#1a1a1a", bold: false, align: "left", bg: "" } },
           { id: "ov-13", type: "image", x: 20, y: 80, w: 60, h: 40, src: "images/uploads/ov-13.jpg" }
         ]
       }
     ]
   }

   html 안의 약속
   - <b class="pno"></b>            : 그 쪽의 번호가 들어갈 자리 (쪽 순서로 자동)
   - <a data-ref="pg-0123">…<b class="pref"></b></a> : 다른 쪽을 가리키는 링크. 번호는 자동, 지워진 쪽이면 "?"
   - data-slot="images/G0002-1"     : 사진 칸. 사진을 올리면 이 이름으로 저장된다 (비어 있으면 images/uploads/…)
   - 저장할 때 .pno / .pref 안의 숫자는 비운다 (stripNumbers)
*/
(function (global) {
  'use strict';

  var PX_PER_MM = 96 / 25.4;
  var PAGE_W_MM = 210;
  var PAGE_H_MM = 297;
  var KIND_LABEL = { cover: '표지', toc: '목차', index: '칼 종류별 찾아보기', misc: '기타 나이프', blank: '새 페이지', image: '그림 페이지' };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /** id → 쪽 번호(1부터) */
  function numberMap(doc) {
    var m = new Map();
    doc.pages.forEach(function (p, i) { m.set(p.id, i + 1); });
    return m;
  }

  function num(v, d) { v = Number(v); return isFinite(v) ? v : d; }
  // style 속성에 그대로 들어가므로 색·정렬 값은 정해진 꼴만 받는다
  function color(v) { v = String(v || '').trim(); return /^(#[0-9a-fA-F]{3,8}|rgba?\([\d\s.,%]+\)|transparent)$/.test(v) ? v : ''; }
  function align(v) { return ['left', 'center', 'right', 'justify'].indexOf(v) >= 0 ? v : ''; }

  function overlayStyle(o) {
    var s = 'left:' + num(o.x, 0) + 'mm;top:' + num(o.y, 0) + 'mm;width:' + num(o.w, 50) + 'mm;';
    if (o.type === 'image') return s + 'height:' + num(o.h, 40) + 'mm;';
    var st = o.style || {};
    s += 'min-height:' + num(o.h, 10) + 'mm;font-size:' + num(st.size, 12) + 'pt;';
    if (color(st.color)) s += 'color:' + color(st.color) + ';';
    if (st.bold) s += 'font-weight:700;';
    if (align(st.align)) s += 'text-align:' + align(st.align) + ';';
    if (color(st.bg)) s += 'background:' + color(st.bg) + ';';
    return s;
  }

  function overlayHTML(o) {
    var cls = 'ov ov-' + (o.type === 'image' ? 'image' : 'text');
    var inner = o.type === 'image'
      ? '<img src="' + esc(o.src || '') + '" alt="" draggable="false">'
      : '<div class="ov-text-body">' + (o.html || '') + '</div>';
    return '<div class="' + cls + '" data-ov="' + esc(o.id) + '" style="' + overlayStyle(o) + '">' + inner + '</div>';
  }

  /** 쪽 번호·링크 번호·짝수/홀수 표시를 채운다 (DOM 을 다시 만들지 않고 번호만 갱신할 때도 쓴다) */
  function fillNumbers(sec, index, nums) {
    var n = index + 1;
    sec.classList.toggle('even', n % 2 === 0);
    sec.classList.toggle('odd', n % 2 === 1);
    var pnos = sec.querySelectorAll('.pno');
    for (var i = 0; i < pnos.length; i++) pnos[i].textContent = String(n);
    var refs = sec.querySelectorAll('a[data-ref]');
    for (var j = 0; j < refs.length; j++) {
      var a = refs[j];
      var t = nums.get(a.getAttribute('data-ref'));
      var b = a.querySelector('.pref');
      if (b) b.textContent = t ? String(t) : '?';
      a.classList.toggle('broken', !t);
    }
  }

  /** 문서의 한 쪽 → section.page 요소 */
  function createPageElement(page, index, nums) {
    var sec = document.createElement('section');
    sec.className = ('page ' + (page.cls || '')).trim();
    if (page.style) sec.setAttribute('style', page.style);
    sec.setAttribute('data-id', page.id);
    sec.setAttribute('data-kind', page.kind || 'content');
    sec.innerHTML = (page.html || '') +
      '<div class="ov-layer">' + (page.overlays || []).map(overlayHTML).join('') + '</div>';
    fillNumbers(sec, index, nums);
    return sec;
  }

  /** 저장 전에 자동으로 채운 번호를 비운다 */
  function stripNumbers(root) {
    var els = root.querySelectorAll('.pno, .pref');
    for (var i = 0; i < els.length; i++) els[i].textContent = '';
  }

  var inert = null;
  function parse(html) {
    if (!inert) inert = new DOMParser();
    return inert.parseFromString('<!doctype html><body>' + (html || ''), 'text/html').body;
  }

  /** 쪽 제목 (목록·검색 결과에 쓰는 짧은 이름) */
  function pageTitle(page) {
    if (KIND_LABEL[page.kind] && page.kind !== 'blank') return KIND_LABEL[page.kind];
    var body = parse(page.html);
    var t = body.querySelector('.ttl b');
    var s = body.querySelector('.ttl span');
    var text = ((t ? t.textContent : '') + ' ' + (s ? s.textContent : '')).replace(/\s+/g, ' ').trim();
    if (!text) { var img = t && t.querySelector('img'); if (img) text = img.getAttribute('alt') || ''; }
    return text || KIND_LABEL[page.kind] || '페이지';
  }

  /** 검색용 글자 (쪽 본문 + 자유 글상자) */
  function pageText(page) {
    var parts = [parse(page.html).textContent];
    (page.overlays || []).forEach(function (o) { if (o.type === 'text') parts.push(parse(o.html).textContent); });
    return parts.join(' ').replace(/\s+/g, ' ').trim();
  }

  /** 붙여넣기·편집으로 들어온 html 에서 위험한 것 제거 (script, on* 속성, javascript: 주소 등) */
  function sanitizeHTML(html) {
    var body = parse(html);
    var bad = body.querySelectorAll('script, iframe, object, embed, link, meta, style, form, input, textarea, button, select');
    for (var i = 0; i < bad.length; i++) bad[i].remove();
    var all = body.querySelectorAll('*');
    for (var j = 0; j < all.length; j++) {
      var el = all[j];
      for (var k = el.attributes.length - 1; k >= 0; k--) {
        var name = el.attributes[k].name.toLowerCase();
        var val = el.attributes[k].value;
        if (name.indexOf('on') === 0) el.removeAttribute(el.attributes[k].name);
        else if ((name === 'href' || name === 'src') && /^\s*(javascript|vbscript|data:text)/i.test(val)) el.removeAttribute(el.attributes[k].name);
      }
    }
    return body.innerHTML;
  }

  /** 새 id 만들기: prefix-번호 (문서 meta.nextId 를 1 올린다) */
  function newId(doc, prefix) {
    doc.meta = doc.meta || {};
    var n = num(doc.meta.nextId, doc.pages.length + 1);
    var used = new Set(doc.pages.map(function (p) { return p.id; }));
    doc.pages.forEach(function (p) { (p.overlays || []).forEach(function (o) { used.add(o.id); }); });
    var id;
    do { id = prefix + '-' + String(n++).padStart(4, '0'); } while (used.has(id));
    doc.meta.nextId = n;
    return id;
  }

  global.CatalogRender = {
    PX_PER_MM: PX_PER_MM,
    PAGE_W_MM: PAGE_W_MM,
    PAGE_H_MM: PAGE_H_MM,
    PAGE_W_PX: PAGE_W_MM * PX_PER_MM,
    PAGE_H_PX: PAGE_H_MM * PX_PER_MM,
    KIND_LABEL: KIND_LABEL,
    esc: esc,
    safeColor: color,
    safeAlign: align,
    numberMap: numberMap,
    overlayHTML: overlayHTML,
    overlayStyle: overlayStyle,
    createPageElement: createPageElement,
    fillNumbers: fillNumbers,
    stripNumbers: stripNumbers,
    pageTitle: pageTitle,
    pageText: pageText,
    sanitizeHTML: sanitizeHTML,
    newId: newId
  };
})(window);
