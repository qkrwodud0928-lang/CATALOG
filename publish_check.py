"""홈페이지에 올리기 시험 — 이 컴퓨터에 진짜 FTP 서버(pyftpdlib)를 띄우고 editor_server 의 /api/publish 를 끝까지 돌려 본다.

    python -X utf8 publish_check.py [시험에 쓸 catalog.json]

pyftpdlib 가 없으면 실제 FTP 시험은 건너뛴다. 따로 설치한 폴더는 환경 변수 PUBLISH_PYLIB 로 알려 준다.
진짜 catalog.json·사진·설정 파일은 건드리지 않는다 (임시 폴더에 복사해서 돌린다). 포트: FTP 2121, 편집기 8822.
"""
import json
import logging
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if os.environ.get("PUBLISH_PYLIB"):
    sys.path.insert(0, os.environ["PUBLISH_PYLIB"])
import site_upload as su  # noqa: E402

PW = "S3cret=pw#한글"   # 이 글자가 로그·응답·올린 파일 어디에도 나오면 안 된다
WRONG = "Wrong-pw-777"


def expect_error(raw, word):
    try:
        su.check_settings(raw)
    except su.PublishError as e:
        assert word in str(e), (word, str(e))
        return
    raise AssertionError(f"오류가 나야 함: {raw}")


def unit():
    d = Path(tempfile.mkdtemp(prefix="publish_unit_"))
    try:
        p = d / "s.txt"
        p.write_bytes("﻿# 설명\n주소 = ftp://Example.com/ \n아이디=u\n비밀번호 = a=b#c \n올릴_폴더 = web\\upload\\x/\n".encode("utf-8"))
        raw = su.read_settings(p)
        assert raw["비밀번호"] == "a=b#c", raw
        c = su.check_settings(raw)
        assert (c["host"], c["port"], c["folder"], c["tls"], c["url"]) == ("Example.com", 21, "/web/upload/x", "auto", ""), c
        expect_error({**raw, "포트": "3822"}, "SFTP")
        expect_error({**raw, "비밀번호": ""}, "비밀번호")
        expect_error({**raw, "올릴_폴더": "/a/../b"}, "올릴_폴더")
        expect_error({**raw, "올릴_폴더": "/"}, "올릴_폴더")
        expect_error({**raw, "보안연결": "몰라"}, "보안연결")
        expect_error({**raw, "주소": "쇼핑몰아이디.ftp.cafe24.com"}, "주소")
        assert su.read_settings(d / "없음.txt") is None
        su.write_template(d / "t.txt")
        t = su.read_settings(d / "t.txt")
        assert set(t) == {"주소", "포트", "아이디", "비밀번호", "올릴_폴더", "홈페이지_주소", "보안연결"}, t
        expect_error(t, "비밀번호")  # 틀은 비밀번호만 비어 있다
        assert su.check_settings({**t, "비밀번호": "x"})["url"].startswith("https://")
        site = d / "site"
        for rel in ("index.html", "catalog.js", "a/b.js", "z.css", ".sindo-site", "올리는 법.txt"):
            (site / rel).parent.mkdir(parents=True, exist_ok=True)
            (site / rel).write_text("x", encoding="utf-8")
        assert su.site_files(site) == ["a/b.js", "z.css", "catalog.js", "index.html"], su.site_files(site)
        assert su.hide("a PW b", "PW") == "a **** b" and su.hide("a", "") == "a"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def tls_reuse():
    """vsftpd·ProFTPD 처럼 '파일 연결도 처음 암호화를 이어 써야' 받아 주는 작은 FTPS 서버에 올려 본다 (표준 라이브러리만)"""
    exe = shutil.which("openssl") or next((p for p in (r"C:\Program Files\Git\usr\bin\openssl.exe",) if Path(p).is_file()), None)
    if not exe:
        print("openssl 이 없어 암호화(FTPS) 시험은 건너뜁니다.")
        return
    d = Path(tempfile.mkdtemp(prefix="publish_tls_"))
    old_env = os.environ.get("SSL_CERT_FILE")
    try:
        subprocess.run([exe, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost", "-keyout", str(d / "k.pem"), "-out", str(d / "c.pem")],
                       check=True, capture_output=True)
        os.environ["SSL_CERT_FILE"] = str(d / "c.pem")  # 시험용 인증서를 믿게 (이 프로세스 안에서만)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(d / "c.pem", d / "k.pem")
        log, got = [], {}

        def client(sock):
            pasv = None
            say = lambda s: sock.sendall((s + "\r\n").encode())  # noqa: E731
            say("220 hi")
            while True:
                line = b""
                while not line.endswith(b"\n"):
                    ch = sock.recv(1)
                    if not ch:
                        return
                    line += ch
                cmd, _, arg = line.decode().strip().partition(" ")
                cmd = cmd.upper()
                if cmd == "AUTH":
                    say("234 ok")
                    sock = ctx.wrap_socket(sock, server_side=True)
                elif cmd == "PASV":
                    pasv = socket.create_server(("127.0.0.1", 0))
                    p = pasv.getsockname()[1]
                    say(f"227 Passive (127,0,0,1,{p >> 8},{p & 255})")
                elif cmd == "STOR":
                    say("150 go")
                    data = ctx.wrap_socket(pasv.accept()[0], server_side=True)
                    log.append(data.session_reused)
                    if not data.session_reused:  # vsftpd require_ssl_reuse=YES 처럼
                        data.close()
                        say("522 SSL session reuse required")
                        continue
                    buf = b""
                    while chunk := data.recv(65536):
                        buf += chunk
                    data.unwrap()
                    data.close()
                    got[arg] = buf
                    say("226 done")
                elif cmd == "MKD":
                    say("550 exists")
                elif cmd == "QUIT":
                    return say("221 bye")
                else:  # USER PASS PBSZ PROT TYPE OPTS RNFR RNTO
                    say({"USER": "331 pw", "PASS": "230 in", "RNFR": "350 ok"}.get(cmd, "250 ok"))

        lst = socket.create_server(("127.0.0.1", 0))
        threading.Thread(target=lambda: [threading.Thread(target=client, args=(lst.accept()[0],), daemon=True).start()
                                         for _ in iter(int, 1)], daemon=True).start()
        (d / "site").mkdir()
        (d / "site/index.html").write_bytes(b"tls ok")
        cfg = su.check_settings({"주소": "localhost", "포트": str(lst.getsockname()[1]), "아이디": "a", "비밀번호": "pw",
                                 "올릴_폴더": "/web/upload/catalog", "보안연결": "자동"})
        assert su.publish(d / "site", cfg, d / "m.json") == {"uploaded": 1, "skipped": 0}, log
        assert log == [True] and got == {"/web/upload/catalog/index.uploading.html": b"tls ok"}, (log, got)
    finally:
        if old_env is None:
            os.environ.pop("SSL_CERT_FILE", None)
        else:
            os.environ["SSL_CERT_FILE"] = old_env
        shutil.rmtree(d, ignore_errors=True)


class Editor:
    def __init__(self, app, doc, settings):
        self.lines, self.bodies = [], []
        self.proc = subprocess.Popen(
            [sys.executable, "-X", "utf8", str(app / "editor_server.py"), "--doc", str(doc), "--port", "8822",
             "--no-pdf-open", "--publish-settings", str(settings)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        threading.Thread(target=lambda: self.lines.extend(self.proc.stdout), daemon=True).start()
        for _ in range(600):  # 이 컴퓨터는 파이썬이 켜질 때 암호 모듈(_hashlib)을 읽는 데만 몇 초 걸린다
            m = re.search(r"편집기 주소: (http://127\.0\.0\.1:\d+)/", "".join(self.lines))
            if m:
                self.url = m.group(1)
                return
            time.sleep(0.1)
        self.proc.kill()
        raise AssertionError("편집기 서버가 켜지지 않았습니다: " + "".join(self.lines))

    def call(self, method, path, origin=None):
        req = urllib.request.Request(self.url + path, method=method, data=b"" if method == "POST" else None)
        req.add_header("Origin", origin or self.url)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                status, body = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read()
        self.bodies.append(body)
        return status, body

    def publish(self):
        status, body = self.call("POST", "/api/publish")
        return status, json.loads(body)

    def wait(self):
        for _ in range(600):
            st = json.loads(self.call("GET", "/api/publish/status")[1])
            if st["state"] in ("done", "error"):
                return st
            time.sleep(0.2)
        raise AssertionError("올리기가 끝나지 않았습니다")


def main():
    unit()
    tls_reuse()
    try:
        from pyftpdlib.authorizers import DummyAuthorizer
        from pyftpdlib.handlers import FTPHandler
        from pyftpdlib.servers import ThreadedFTPServer
    except ImportError:
        print("pyftpdlib 가 없어 실제 FTP 시험은 건너뜁니다. "
              "(pip install --target <폴더> pyftpdlib 로 설치한 뒤 환경 변수 PUBLISH_PYLIB=<폴더> 로 다시 실행)")
        print("ok (설정 읽기 시험만)")
        return 0
    logging.basicConfig(level=logging.WARNING)

    tmp = Path(tempfile.mkdtemp(prefix="publish_check_"))
    app, root, conf = tmp / "app", tmp / "ftp", tmp / "conf"
    for d in (app, root, conf, tmp / "doc", tmp / "ftp2"):
        d.mkdir()
    for f in ("editor_server.py", "catalog_doc.py", "site_upload.py", "viewer.html"):
        shutil.copy(HERE / f, app / f)
    shutil.copytree(HERE / "editor_assets", app / "editor_assets")
    doc = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "catalog.json").read_text(encoding="utf-8-sig"))
    doc["pages"][0]["html"] += ('<img src="images/zz-test.jpg?v=1" alt="">'
                                '<img src="brands/%ED%85%8C%EC%8A%A4%ED%8A%B8%20%EC%82%AC%EC%A7%84.jpg" alt="">')
    (tmp / "doc" / "catalog.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    for rel, data in (("images/zz-test.jpg", b"\xff\xd8\xff\xe0one"), ("brands/테스트 사진.jpg", b"\xff\xd8\xff\xe0two")):
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / rel).write_bytes(data)

    auth = DummyAuthorizer()
    auth.add_user("tester", PW, str(root), perm="elradfmwMT")
    auth.add_user("norename", PW, str(tmp / "ftp2"), perm="elradmwMT")  # 이름 바꾸기(f)만 못 하는 서버
    handler = type("H", (FTPHandler,), {"authorizer": auth, "auth_failed_timeout": 0.5})
    ftpd = ThreadedFTPServer(("127.0.0.1", 2121), handler)
    threading.Thread(target=ftpd.serve_forever, kwargs={"handle_exit": False}, daemon=True).start()

    settings = conf / su.SETTINGS_NAME
    try:
        ed = Editor(app, tmp / "doc" / "catalog.json", settings)
    except BaseException:
        ftpd.close_all()
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    def write(**kw):
        v = {"주소": "127.0.0.1", "포트": "2121", "아이디": "tester", "비밀번호": PW, "올릴_폴더": "/web/upload/catalog",
             "홈페이지_주소": "http://example.test/web/upload/catalog/index.html", "보안연결": "자동", **kw}
        settings.write_text("# 시험\n" + "".join(f"{k} = {x}\n" for k, x in v.items()), encoding="utf-8")

    try:
        # 설정 파일이 없으면: 틀을 만들고 400
        status, r = ed.publish()
        assert status == 400 and "설정" in r["error"], (status, r)
        assert settings.read_text(encoding="utf-8") == su.TEMPLATE
        status, r = ed.publish()  # 틀 그대로(비밀번호 빈칸)
        assert status == 400 and "비밀번호" in r["error"], (status, r)

        # 설정·기록 파일은 편집기 주소로 열 수 없다
        (app / su.SETTINGS_NAME).write_text(f"비밀번호 = {PW}\n", encoding="utf-8")
        (app / su.MANIFEST_NAME).write_text("{}", encoding="utf-8")
        for name in (su.SETTINGS_NAME, su.MANIFEST_NAME):
            assert ed.call("GET", "/" + quote(name))[0] in (403, 404), name
        assert ed.call("GET", "/" + quote(su.SETTINGS_NAME.upper()))[0] in (403, 404)
        assert ed.call("GET", "/viewer.html")[0] == 200
        assert ed.call("POST", "/api/publish", origin="http://evil.example")[0] == 403

        # 비밀번호가 틀리면: 한국어 로그인 오류. 도는 동안 또 누르면 409
        write(비밀번호=WRONG)
        assert ed.publish() == (200, {"ok": True, "started": True})
        status, r = ed.publish()
        assert status == 409, (status, r)
        st = ed.wait()
        assert st["state"] == "error" and "아이디" in st["message"] and "비밀번호" in st["message"], st

        # 보안연결 = 예 인데 서버가 암호화를 못 하면: 오류
        write(보안연결="예")
        ed.publish()
        st = ed.wait()
        assert st["state"] == "error" and "보안 연결" in st["message"], st

        # 서버가 없으면: 연결 오류 (세 번 해 보고)
        write(포트="2")
        ed.publish()
        st = ed.wait()
        assert st["state"] == "error" and "연결하지 못했습니다" in st["message"], st

        # 처음 올리기 (자동 → 암호화 못 하는 서버라 보통 방식으로)
        write()
        assert ed.publish()[0] == 200
        st = ed.wait()
        assert st["state"] == "done" and st["url"] == "http://example.test/web/upload/catalog/index.html", st
        remote, site = root / "web/upload/catalog", app / "site"
        want = su.site_files(site)
        got = sorted(f.relative_to(remote).as_posix() for f in remote.rglob("*") if f.is_file())
        assert sorted(want) == got, (want, got)
        assert {"index.html", "catalog.js", "images/zz-test.jpg", "brands/테스트 사진.jpg",
                "editor_assets/vendor/page-flip.browser.js"} <= set(got), got
        assert st["total"] == st["done"] == len(want), st
        for rel in want:
            assert (remote / rel).read_bytes() == (site / rel).read_bytes(), rel
        times = sorted(want, key=lambda rel: (remote / rel).stat().st_mtime_ns)
        assert times[-1] == "index.html", times[-3:]

        # 다시 올리면: 바뀐 게 없으니 0개
        ed.publish()
        st = ed.wait()
        assert st["state"] == "done" and st["total"] == 0 and "최신" in st["message"], st

        # 사진 하나를 바꾸면: 그것만 (서버의 옛 파일을 바꿔치기)
        (app / "images/zz-test.jpg").write_bytes(b"\xff\xd8\xff\xe0changed")
        ed.publish()
        st = ed.wait()
        assert st["state"] == "done" and st["total"] == 1, st
        assert (remote / "images/zz-test.jpg").read_bytes() == b"\xff\xd8\xff\xe0changed"
        assert not [f for f in remote.rglob("*") if ".uploading" in f.name]
        book = json.loads((conf / su.MANIFEST_NAME).read_text(encoding="utf-8"))
        assert list(book) == ["127.0.0.1:2121/web/upload/catalog"], list(book)

        # 이름 바꾸기가 안 되는 서버: 옛 파일을 지우지 않고 바로 덮어쓴다 (임시 파일은 치운다)
        live, site2 = tmp / "ftp2/web/upload/catalog", tmp / "site2"
        for rel in ("index.html", "a/b.js"):
            for base, text in ((live, "OLD"), (site2, "NEW " + rel)):
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_text(text, encoding="utf-8")
        (site2 / "c.css").write_text("NEW c.css", encoding="utf-8")
        cfg = su.check_settings({"주소": "127.0.0.1", "포트": "2121", "아이디": "norename", "비밀번호": PW,
                                 "올릴_폴더": "/web/upload/catalog", "보안연결": "아니오"})
        assert su.publish(site2, cfg, tmp / "m2.json") == {"uploaded": 3, "skipped": 0}
        got = {f.relative_to(live).as_posix(): f.read_text(encoding="utf-8") for f in live.rglob("*") if f.is_file()}
        assert got == {r: "NEW " + r for r in ("index.html", "a/b.js", "c.css")}, got

        # 비밀번호는 어디에도 없다
        time.sleep(0.3)
        out = "".join(ed.lines)
        for secret in (PW, WRONG):
            assert secret not in out, out
            assert not [b for b in ed.bodies if secret.encode() in b]
            for f in list(site.rglob("*")) + list(remote.rglob("*")):
                assert not f.is_file() or secret.encode() not in f.read_bytes(), f
        print("ok — 서버 기록:")
        print(out)
    finally:
        ed.proc.terminate()
        ed.proc.wait(10)
        ftpd.close_all()
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
