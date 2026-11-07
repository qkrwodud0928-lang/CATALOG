"""신도 카탈로그 편집기 서버 (파이썬 표준 라이브러리만)

    python editor_server.py [--port 8800] [--doc catalog.json] [--open] [--no-pdf-open] [--publish-settings 파일]

127.0.0.1 에만 붙는다. 편집기(editor.html)·책 보기(viewer.html)와 저장·사진 올리기·PDF·홈페이지용 내보내기·홈페이지에 올리기를 맡는다.
"""
import argparse
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

import catalog_doc
import site_upload

BASE = Path(__file__).resolve().parent
MAX_UPLOAD = 30 * 1024 * 1024
MAX_DOC = 200 * 1024 * 1024
UPLOAD_EXTS = {"jpg", "jpeg", "png", "webp", "gif"}
OLD_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}  # 같은 이름의 옛 사진(확장자만 다른 것)은 백업으로
SLOT_RE = re.compile(r'(images|brands|logos|flags)/(?!\.)[^/\\:*?"<>|\x00-\x1f]{1,120}')
DENY_EXTS = {".py", ".pyc", ".pyw", ".xlsx", ".xlsm", ".xls", ".bat", ".cmd", ".ps1", ".tmp"}
DENY_DIRS = {"backups", "__pycache__"}  # 그리고 . 으로 시작하는 폴더·파일 (.omc, .claude …)
DENY_NAMES = {site_upload.SETTINGS_NAME, site_upload.MANIFEST_NAME}  # FTP 비밀번호·올린 기록
TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
         ".txt": "text/plain; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
         ".pdf": "application/pdf", ".ico": "image/x-icon", ".woff2": "font/woff2"}

LOCK = threading.Lock()  # 문서 읽기·저장·사진 올리기는 하나씩
JOB = threading.Lock()   # PDF·내보내기·홈페이지 올리기는 하나씩
CFG = {"doc": BASE / "catalog.json", "port": 8800, "open_results": True,
       "publish_settings": BASE / site_upload.SETTINGS_NAME}
PUB = {"state": "idle", "done": 0, "total": 0, "current": "", "message": "", "url": ""}  # 홈페이지 올리기 진행 상황
CLOUD = {"dir": None, "at": 0.0}  # OneDrive 백업 폴더, 마지막 백업 시각
CLOUD_EVERY = 600                 # 편집 중에는 10분에 한 번
CLOUD_LOCK = threading.Lock()
PHOTO_DIRS = ("images", "brands", "logos", "flags")


def backup_doc():
    """문서를 OneDrive 에 날짜별 한 파일로 (그날 마지막 모습). 60일 치만 둔다"""
    d = CLOUD["dir"]
    if not d:
        return
    try:
        d.mkdir(parents=True, exist_ok=True)
        with LOCK:
            data = CFG["doc"].read_bytes()
        dest = d / f"catalog-{datetime.now():%Y-%m-%d}.json"
        tmp = dest.with_name(f"{dest.name}.{threading.get_ident()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        for old in sorted(d.glob("catalog-*.json"))[:-60]:
            old.unlink(missing_ok=True)
    except OSError as e:
        log(f"OneDrive 백업 실패 (편집은 계속됩니다): {e}")


def cloud_backup():
    """문서 + 사진(새로 생기거나 바뀐 것만)을 OneDrive 로. 이미 하는 중이면 건너뜀"""
    if not CLOUD["dir"] or not CLOUD_LOCK.acquire(blocking=False):
        return
    try:
        backup_doc()
        for top in PHOTO_DIRS:
            for f in (BASE / top).rglob("*"):
                if not f.is_file() or f.suffix.lower() not in OLD_IMAGE_EXTS:
                    continue
                t, st = CLOUD["dir"] / "사진" / f.relative_to(BASE), f.stat()
                if t.exists() and t.stat().st_size == st.st_size and t.stat().st_mtime >= st.st_mtime:
                    continue
                t.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, t)
        CLOUD["at"] = time.time()
    except OSError as e:
        log(f"OneDrive 사진 백업 실패 (편집은 계속됩니다): {e}")
    finally:
        CLOUD_LOCK.release()


def backup_on_close():
    """검은 창을 닫거나 Ctrl+C 할 때 문서를 OneDrive 에 한 번 더 (Windows 는 창이 닫힐 때 몇 초를 준다)"""
    if os.name != "nt" or not CLOUD["dir"]:
        return
    import ctypes

    @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
    def handler(event):
        backup_doc()
        return 0  # 원래 하던 대로 끄기는 계속
    CLOUD["handler"] = handler  # 참조를 남겨야 콜백이 살아 있다
    ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)


def log(msg):
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True)


def run_publish(cfg):
    """홈페이지에 올리기 (뒤에서 돈다, JOB 을 쥔 채로 시작해서 끝나면 놓는다). 진행 상황은 PUB 에"""
    def progress(done, total, rel):
        PUB.update(done=done, total=total, current=rel,
                   message=f"홈페이지에 올리는 중… ({done}/{total})" if rel else "마무리하는 중…")

    state = "error"
    try:
        with LOCK:
            doc = catalog_doc.load_doc(CFG["doc"])
        res = catalog_doc.export_site(doc, BASE, BASE / "site")
        PUB.update(message="홈페이지 서버에 접속하는 중…")
        out = site_upload.publish(res["path"], cfg, CFG["publish_settings"].with_name(site_upload.MANIFEST_NAME), progress)
        msg = (f"다 올렸습니다. 새로 올린 파일 {out['uploaded']}개, 바뀌지 않아 건너뛴 파일 {out['skipped']}개."
               if out["uploaded"] else "바뀐 파일이 없습니다. 홈페이지는 이미 최신입니다.")
        if res["missing"]:
            msg += f" (파일이 없어 빠진 사진 등 {len(res['missing'])}개)"
        state = "done"
    except site_upload.PublishError as e:
        msg = str(e)
    except (ValueError, OSError) as e:
        msg = f"홈페이지용 파일을 만들지 못했습니다: {e}"
    except Exception as e:
        msg = f"올리지 못했습니다: {e!r}"
    finally:
        JOB.release()
    msg = site_upload.hide(msg, cfg["password"])
    PUB.update(state=state, current="", message=msg)
    log(f"홈페이지 올리기 {'끝' if state == 'done' else '실패'}: {msg}")


class Fail(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


def is_image(data):
    return (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:6] in (b"GIF87a", b"GIF89a")
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))


def save_upload(slot, ext, data):
    """사진 저장 → 쪽 html 에 넣을 src (URL 인코딩 + ?v=)"""
    if slot:
        rel = f"{slot}.{ext}"
        dest = BASE / rel
        if not dest.resolve().is_relative_to(BASE / slot.split("/")[0]):
            raise Fail(400, "사진 칸 이름이 올바르지 않습니다.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        stem = Path(slot).name.lower()
        stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
        for old in list(dest.parent.iterdir()):
            if old.is_file() and old.stem.lower() == stem and old.suffix.lower() in OLD_IMAGE_EXTS:
                keep = BASE / "backups" / Path(slot).parent / f"{old.stem}-{stamp}{old.suffix}"
                keep.parent.mkdir(parents=True, exist_ok=True)
                os.replace(old, keep)
    else:
        rel = f"images/uploads/up-{datetime.now():%Y%m%d-%H%M%S}{secrets.token_hex(2)}.{ext}"
        dest = BASE / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    return f"{quote(rel)}?v={dest.stat().st_mtime_ns // 1_000_000}"


class Handler(BaseHTTPRequestHandler):
    server_version = "SindoCatalog/1"

    def log_message(self, *args):  # 요청마다 찍지 않는다
        pass

    # ── 응답 ──
    def send(self, status, body, ctype, extra=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def reply(self, status, obj):
        self.send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def fail(self, status, msg):
        self.reply(status, {"ok": False, "error": msg})

    # ── GET ──
    def do_GET(self):
        try:
            path = urlsplit(self.path).path
            if path == "/":
                self.send(302, b"", "text/plain", [("Location", "/editor.html")])
            elif path == "/api/doc":
                with LOCK:
                    data = CFG["doc"].read_bytes()
                self.send(200, data, "application/json; charset=utf-8")
            elif path == "/catalog.js":
                with LOCK:
                    data = CFG["doc"].read_bytes()
                self.send(200, b"window.CATALOG_DATA = " + data + b";\n", "application/javascript; charset=utf-8")
            elif path == "/api/publish/status":
                self.reply(200, dict(PUB))
            else:
                self.static(path)
        except (ConnectionError, TimeoutError):
            pass
        except Exception as e:
            log(f"오류 GET {self.path[:80]}: {e!r}")
            self.fail(500, "파일을 읽지 못했습니다.")

    def static(self, path):
        try:
            rel = unquote(path, errors="strict")
        except UnicodeDecodeError:
            return self.fail(400, "주소가 잘못되었습니다.")
        parts = [p for p in rel.split("/") if p]
        if (any(c in rel for c in "\\:\x00") or any(p in (".", "..") or p[-1] in ". " for p in parts)):
            return self.fail(403, "열 수 없는 주소입니다.")
        target = BASE.joinpath(*parts).resolve()
        if not target.is_relative_to(BASE):
            return self.fail(403, "열 수 없는 주소입니다.")
        inside = target.relative_to(BASE).parts
        if (target.suffix.lower() in DENY_EXTS or target.name in DENY_NAMES or target == CFG["publish_settings"] or
                any(p.startswith(".") or p.lower() in DENY_DIRS for p in inside)):
            return self.fail(403, "열 수 없는 파일입니다.")
        if not target.is_file():
            return self.fail(404, "파일이 없습니다.")
        ctype = TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send(200, target.read_bytes(), ctype)

    # ── POST ──
    def same_origin(self):
        host = self.headers.get("Host", "")
        if host not in (f"127.0.0.1:{CFG['port']}", f"localhost:{CFG['port']}"):
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin == "http://" + host

    def body(self, limit, too_big):
        try:
            n = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise Fail(411, "보낸 내용의 길이를 알 수 없습니다.")
        if n > limit:
            raise Fail(413, too_big)  # 남은 내용은 do_POST 가 읽어 버린다
        self.body_read = True
        return self.rfile.read(max(n, 0))

    def drain(self):
        """안 읽은 내용을 읽어 버린다 (안 읽고 연결을 닫으면 윈도에서 브라우저가 답 대신 '연결 끊김'을 받는다)"""
        try:
            left = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        if left > 1024 ** 3:
            return
        while left > 0:
            chunk = self.rfile.read(min(left, 1 << 20))
            if not chunk:
                break
            left -= len(chunk)

    def do_POST(self):
        self.body_read = False
        try:
            if not self.same_origin():
                raise Fail(403, "다른 곳에서 온 요청은 받지 않습니다.")
            url = urlsplit(self.path)
            route = {"/api/save": self.api_save, "/api/upload": self.api_upload,
                     "/api/export": self.api_export, "/api/pdf": self.api_pdf,
                     "/api/publish": self.api_publish}.get(url.path)
            if not route:
                raise Fail(404, "없는 기능입니다.")
            status, obj, note = route(url)
        except Fail as e:
            status, obj, note = e.status, {"ok": False, "error": str(e)}, f"거절 {self.path[:60]}: {e}"
        except (ConnectionError, TimeoutError):
            return
        except Exception as e:
            status, obj = 500, {"ok": False, "error": f"처리하지 못했습니다: {e}"}
            note = f"오류 {self.path[:60]}: {e!r}"
        try:
            if not self.body_read:
                self.drain()
            self.reply(status, obj)
        except (ConnectionError, TimeoutError):
            return
        log(note)  # 응답을 보낸 뒤에 찍는다 (검은 창을 눌러 멈춰 있어도 편집기는 안 멈추게)

    def api_save(self, url):
        raw = self.body(MAX_DOC, "문서가 너무 큽니다.")
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise Fail(400, "문서 형식(JSON)이 잘못되었습니다.")
        problems = catalog_doc.validate_doc(doc)
        if problems:
            raise Fail(400, "저장하지 않았습니다: " + " / ".join(problems[:5]))
        with LOCK:
            catalog_doc.save_doc(CFG["doc"], doc, CFG["doc"].parent / "backups")
        if time.time() - CLOUD["at"] > CLOUD_EVERY:
            threading.Thread(target=cloud_backup, daemon=True).start()
        n = len(doc["pages"])
        return 200, {"ok": True, "savedAt": f"{datetime.now():%H:%M:%S}", "pages": n}, f"저장 {n}쪽"

    def api_upload(self, url):
        q = parse_qs(url.query, keep_blank_values=True)
        slot = q.get("slot", [""])[0].strip()
        ext = q.get("ext", [""])[0].strip().lower().lstrip(".")
        if ext not in UPLOAD_EXTS:
            raise Fail(400, "사진은 jpg, png, webp, gif 파일만 올릴 수 있습니다.")
        if slot and not SLOT_RE.fullmatch(slot):
            raise Fail(400, "사진 칸 이름이 올바르지 않습니다.")
        data = self.body(MAX_UPLOAD, "사진이 너무 큽니다 (30MB 까지).")
        if not is_image(data):
            raise Fail(400, "사진 파일이 아닙니다 (jpg, png, webp, gif).")
        with LOCK:
            src = save_upload(slot, ext, data)
        return 200, {"ok": True, "src": src}, f"사진 올림 {unquote(src.split('?')[0])}"

    def load(self):
        with LOCK:
            return catalog_doc.load_doc(CFG["doc"])

    def api_export(self, url):
        if not JOB.acquire(blocking=False):
            raise Fail(409, "다른 작업(PDF·내보내기)이 아직 진행 중입니다. 끝난 뒤 다시 눌러 주세요.")
        try:
            try:
                res = catalog_doc.export_site(self.load(), BASE, BASE / "site")
            except (ValueError, OSError) as e:
                raise Fail(500, f"내보내지 못했습니다: {e}")
        finally:
            JOB.release()
        if CFG["open_results"]:
            try:
                os.startfile(res["path"])
            except Exception:
                pass
        return 200, {"ok": True, **res}, f"내보내기 {res['files']}개 파일, 빠진 파일 {len(res['missing'])}개 → {res['path']}"

    def api_publish(self, url):
        """홈페이지에 올리기 시작 (저장은 편집기가 먼저 한다). 진행 상황은 GET /api/publish/status"""
        path = CFG["publish_settings"]
        raw = site_upload.read_settings(path)
        problem = None
        if raw is None:
            site_upload.write_template(path)
            problem = (f"처음 한 번은 설정이 필요합니다. '{path.name}' 파일을 만들었으니 메모장으로 열어 FTP 비밀번호를 적고"
                       f" 저장한 뒤 다시 눌러 주세요. (파일 위치: {path})")
        else:
            try:
                cfg = site_upload.check_settings(raw)
            except site_upload.PublishError as e:
                problem = f"{e} (설정 파일: {path})"
        if problem:
            if CFG["open_results"]:
                try:
                    os.startfile(path)
                except Exception:
                    pass
            raise Fail(400, problem)
        if not JOB.acquire(blocking=False):
            raise Fail(409, "다른 작업(PDF·내보내기·홈페이지 올리기)이 아직 진행 중입니다. 끝난 뒤 다시 눌러 주세요.")
        PUB.update(state="running", done=0, total=0, current="", message="홈페이지용 파일을 만드는 중…", url=cfg["url"])
        threading.Thread(target=run_publish, args=(cfg,), daemon=True).start()
        return 200, {"ok": True, "started": True}, f"홈페이지 올리기 시작 → {cfg['host']}{cfg['folder']}"

    def api_pdf(self, url):
        """인쇄소용 PDF (두 권 + 표지 그림이 있으면 표지) → 인쇄 폴더. ?marks=1 재단선, ?multiple=4 쪽 수를 4의 배수로"""
        if not JOB.acquire(blocking=False):
            raise Fail(409, "다른 작업(PDF·내보내기·홈페이지 올리기)이 아직 진행 중입니다. 끝난 뒤 다시 눌러 주세요.")
        q = parse_qs(url.query)
        try:
            log("인쇄용 PDF 만드는 중… (2~4분)")
            try:
                res = catalog_doc.make_print_pdfs(self.load(), BASE, BASE / "인쇄", marks=q.get("marks") == ["1"],
                                                  multiple=4 if q.get("multiple") == ["4"] else 2)
            except (RuntimeError, OSError) as e:
                raise Fail(500, str(e))
        finally:
            JOB.release()
        if CFG["open_results"]:
            try:
                os.startfile(res["path"])
            except Exception:
                pass
        return 200, {"ok": True, **res}, f"PDF {len(res['files'])}개 {res['pages']}쪽 → {res['path']}"


class Server(ThreadingHTTPServer):
    allow_reuse_address = False  # 윈도에서 True 면 이미 쓰는 포트에도 붙어 버린다
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # 다른 프로그램이 0.0.0.0 으로 쓰는 포트에도 겹쳐 붙지 않게
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        e = sys.exc_info()[1]
        if not isinstance(e, (ConnectionError, TimeoutError)):
            log(f"오류: {e!r}")


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="신도 카탈로그 편집기 서버")
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--doc", default=str(BASE / "catalog.json"))
    ap.add_argument("--open", action="store_true", help="켠 뒤 브라우저로 편집기 열기")
    ap.add_argument("--no-pdf-open", action="store_true", help="PDF·내보낸 폴더를 자동으로 열지 않기")
    ap.add_argument("--backup-dir", help="OneDrive 백업 폴더 (안 주면: 진짜 catalog.json 일 때만 OneDrive\신도카탈로그_백업)")
    ap.add_argument("--publish-settings", default=str(BASE / site_upload.SETTINGS_NAME),
                    help="홈페이지 올리기 설정 파일 (올린 기록도 같은 폴더에 둔다)")
    args = ap.parse_args()
    CFG["doc"] = Path(args.doc).resolve()
    CFG["open_results"] = not args.no_pdf_open
    CFG["publish_settings"] = Path(args.publish_settings).resolve()
    if not CFG["doc"].is_file():
        print(f"문서 파일이 없습니다: {CFG['doc']}")
        return 1
    one = os.environ.get("OneDrive")
    if args.backup_dir:
        CLOUD["dir"] = Path(args.backup_dir).resolve()
    elif CFG["doc"] == (BASE / "catalog.json").resolve() and one and Path(one).is_dir():
        CLOUD["dir"] = Path(one) / "신도카탈로그_백업"
    httpd = None
    for port in range(args.port, args.port + 11):
        try:
            httpd = Server(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if not httpd:
        print(f"포트 {args.port}~{args.port + 10} 이 모두 사용 중이라 켤 수 없습니다.")
        return 1
    CFG["port"] = port
    url = f"http://127.0.0.1:{port}/editor.html"
    print("신도 카탈로그 편집기가 켜졌습니다.")
    print(f"  편집기 주소: {url}")
    print(f"  책 보기 주소: http://127.0.0.1:{port}/viewer.html")
    print(f"  문서 파일:   {CFG['doc']}")
    print(f"  OneDrive 백업: {CLOUD['dir'] or '안 함'}")
    if CLOUD["dir"]:
        threading.Thread(target=cloud_backup, daemon=True).start()
        backup_on_close()
    print("이 검은 창을 닫으면 편집기가 꺼집니다. (편집 중에는 닫지 마세요)", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
