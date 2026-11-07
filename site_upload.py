"""홈페이지(Cafe24 쇼핑몰)에 카탈로그 올리기 — FTP, 파이썬 표준 라이브러리만. editor_server.py 가 부른다.

설정은 '홈페이지_올리기_설정.txt' ('이름 = 값' 줄). 비밀번호는 로그·화면·오류 글·내보낸 폴더 어디에도 내보내지 않는다.
올린 파일은 '홈페이지_올리기_기록.json' 에 남겨 다음에는 바뀐 것만 올린다 (한 파일마다 저장 → 끊겨도 이어서).
서버의 파일은 지우지 않는다 (바꿔 올릴 파일의 옛것만 바꿔치기).
"""
import ftplib
import hashlib
import json
import os
import posixpath
import re
import socket
import ssl
import time
from pathlib import Path

SETTINGS_NAME = "홈페이지_올리기_설정.txt"
MANIFEST_NAME = "홈페이지_올리기_기록.json"  # 설정 파일과 같은 폴더에 둔다
LAST = ("catalog.js", "index.html")  # 맨 끝에 (중간에 끊겨도 손님은 옛 책을 온전히 본다)
SKIP = {".sindo-site", "올리는 법.txt"}  # 내보내기 표시·손으로 올리는 법은 홈페이지에 필요 없다
TIMEOUT = 30
TRIES = 3
TLS = {"자동": "auto", "예": "yes", "아니오": "no", "아니요": "no"}

TEMPLATE = """\
# ─────────────────────────────────────────────
#  홈페이지에 올리기 설정  (신도 카탈로그 편집기)
# ─────────────────────────────────────────────
# 편집기의 [홈페이지에 올리기] 버튼이 이 파일을 읽어 Cafe24 쇼핑몰 서버에 카탈로그를 올립니다.
# 고칠 곳은 '=' 오른쪽뿐입니다. '#' 으로 시작하는 줄은 설명이라 읽지 않습니다.
# 다 적었으면 저장(Ctrl+S)하고, 편집기에서 버튼을 다시 누르세요.
#
# ※ 비밀번호가 들어가는 파일입니다. 메일·메신저로 다른 사람에게 보내지 마세요.
#   (편집기는 이 파일을 홈페이지에 올리지 않고, 화면이나 기록에도 비밀번호를 보여 주지 않습니다)

# 1) 주소 — FTP 서버 주소. Cafe24 쇼핑몰은 '쇼핑몰아이디.ftp.cafe24.com' 입니다. 보통 고칠 필요 없습니다.
주소 = sindoltd.ftp.cafe24.com

# 2) 포트 — 21 그대로 두세요. (3822 는 SFTP 용이라 이 기능에서는 쓸 수 없습니다)
포트 = 21

# 3) 아이디 — Cafe24 쇼핑몰 아이디(대표 관리자 아이디)입니다.
아이디 = sindoltd

# 4) 비밀번호 — FTP 비밀번호를 '=' 뒤에 적으세요.
#    모르면 Cafe24 관리자 화면의 FTP 정보에서 새로 정할 수 있습니다. (처음 쓰는 쇼핑몰은 먼저 새로 정해야 합니다)
#    ※ 여러 번 틀리면 한동안 접속이 막힐 수 있습니다.
비밀번호 =

# 5) 올릴_폴더 — 서버 안에서 카탈로그를 넣을 폴더입니다. 없으면 자동으로 만듭니다.
#    Cafe24 쇼핑몰은 /web/upload 아래에 올린 파일이 홈페이지에 공개됩니다.
#    이 폴더 밖의 파일은 건드리지 않고, 서버의 파일을 지우지도 않습니다.
올릴_폴더 = /web/upload/catalog

# 6) 홈페이지_주소 — 다 올린 뒤 손님이 카탈로그를 여는 주소입니다. 다 올리면 편집기가 이 주소를 보여 줍니다.
#    위 '올릴_폴더'를 바꾸면 이 주소의 /web/upload/catalog 부분도 똑같이 바꾸세요.
홈페이지_주소 = https://sindoltd.com/web/upload/catalog/index.html

# 7) 보안연결 — 자동 / 예 / 아니오 중 하나. 잘 모르면 '자동' 그대로 두세요.
#    자동: 암호화 연결이 되면 암호화해서 보내고, 안 되면 보통 방식으로 보냅니다.
#    예: 암호화 연결로만 보냅니다 (서버가 못 하면 멈춥니다).   아니오: 보통 방식으로만 보냅니다.
보안연결 = 자동

# 참고: 한 번 올린 파일은 '홈페이지_올리기_기록.json' 에 적어 두고, 다음에는 바뀐 파일만 올립니다.
#       서버에서 파일이 지워졌거나 전부 다시 올리고 싶으면 그 기록 파일을 지운 뒤 버튼을 누르세요.
"""


class PublishError(Exception):
    """사용자에게 그대로 보여 줄 한국어 오류"""


def hide(text, secret):
    """글 속 비밀번호를 **** 로 (어떤 경로로도 새지 않게 마지막에 한 번 더)"""
    return str(text).replace(secret, "****") if secret else str(text)


# ── 설정 ──

def write_template(path):
    Path(path).write_text(TEMPLATE, encoding="utf-8")


def read_settings(path):
    """설정 파일 → {이름: 값}. 파일이 없으면 None"""
    p = Path(path)
    if not p.is_file():
        return None
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:  # 메모장에서 'ANSI' 로 저장한 경우
        text = raw.decode("cp949", errors="replace")
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)  # 비밀번호에 = 가 있어도 된다
            out[k.strip()] = v.strip()
    return out


def check_settings(raw):
    """읽은 설정 → 쓸 값. 잘못되면 무엇을 고칠지 알려 주는 PublishError"""
    host = re.sub(r"^(s?ftps?://)", "", raw.get("주소", ""), flags=re.I).strip("/ ")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
        raise PublishError("설정 파일의 '주소'를 확인해 주세요. (예: sindoltd.ftp.cafe24.com)")
    try:
        port = int(raw.get("포트") or 21)
    except ValueError:
        raise PublishError("설정 파일의 '포트'는 숫자로 적어 주세요. (보통 21)")
    if port in (22, 3822):
        raise PublishError("포트 22·3822 는 SFTP 용이라 쓸 수 없습니다. 설정 파일의 '포트'를 21 로 적어 주세요.")
    if not 0 < port < 65536:
        raise PublishError("설정 파일의 '포트'가 잘못되었습니다. (보통 21)")
    user, password = raw.get("아이디", ""), raw.get("비밀번호", "")
    if not user:
        raise PublishError("설정 파일에 '아이디'를 적어 주세요.")
    if not password:
        raise PublishError("설정 파일에 FTP '비밀번호'를 적고 저장한 뒤 다시 눌러 주세요.")
    parts = [p for p in raw.get("올릴_폴더", "").replace("\\", "/").split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        raise PublishError("설정 파일의 '올릴_폴더'를 확인해 주세요. (예: /web/upload/catalog)")
    tls = TLS.get(raw.get("보안연결") or "자동")
    if not tls:
        raise PublishError("설정 파일의 '보안연결'은 자동, 예, 아니오 중 하나로 적어 주세요.")
    url = raw.get("홈페이지_주소", "")
    return {"host": host, "port": port, "user": user, "password": password, "folder": "/" + "/".join(parts),
            "url": url if re.match(r"https?://", url) else "", "tls": tls}


# ── 올리기 ──

def site_files(site_dir):
    """올릴 파일 (site 기준 / 경로). catalog.js·index.html 은 맨 끝"""
    site_dir = Path(site_dir)
    rels = sorted(f.relative_to(site_dir).as_posix() for f in site_dir.rglob("*") if f.is_file())
    rels = [r for r in rels if r not in SKIP and not any(p.startswith(".") for p in r.split("/"))]
    return [r for r in rels if r not in LAST] + [r for r in LAST if r in rels]


def fingerprint(path):
    data = Path(path).read_bytes()
    return {"size": len(data), "sha1": hashlib.sha1(data).hexdigest()}


def load_manifest(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_manifest(path, data):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    os.replace(tmp, path)


def net_message(e, tls=False):
    if isinstance(e, socket.gaierror):
        return "홈페이지 서버를 찾지 못했습니다. 설정 파일의 '주소'가 맞는지, 인터넷이 연결되어 있는지 확인해 주세요."
    if isinstance(e, TimeoutError):
        return "홈페이지 서버가 응답하지 않습니다 (시간 초과). 인터넷 연결을 확인하고 잠시 뒤 다시 눌러 주세요."
    if isinstance(e, ConnectionRefusedError):
        return "홈페이지 서버에 연결하지 못했습니다. 설정 파일의 '주소'와 '포트'(보통 21), 인터넷 연결을 확인해 주세요."
    if isinstance(e, ftplib.error_temp):
        return f"홈페이지 서버가 지금 받아 주지 않습니다. 잠시 뒤 다시 눌러 주세요. (서버 답: {e})"
    return ("홈페이지 서버와 연결이 끊겼습니다. 인터넷 연결을 확인하고 다시 눌러 주세요."
            + (" 계속 안 되면 설정 파일의 '보안연결'을 '아니오'로 바꿔 보세요." if tls else "")
            + " (이미 올린 파일은 다시 올리지 않습니다)")


class FTPS(ftplib.FTP_TLS):
    """파일을 보내는 연결도 처음 암호화 연결을 이어 쓴다 (vsftpd·ProFTPD 는 이렇게 안 하면 막는다)"""

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
        return conn, size


def connect(cfg):
    """접속 + 로그인. 로그인 실패는 바로 PublishError (다시 시도하면 서버가 막는다), 네트워크 문제는 OSError 그대로"""
    ftp = None
    if cfg["tls"] != "no":
        ftp = FTPS(timeout=TIMEOUT, context=ssl.create_default_context(), encoding="utf-8")
        try:
            ftp.connect(cfg["host"], cfg["port"])
            ftp.auth()
        except (ftplib.error_perm, ssl.SSLError) as e:
            close(ftp)  # QUIT 까지 (서버에 접속을 남겨 두지 않게)
            if cfg["tls"] == "yes":
                raise PublishError("이 서버는 보안 연결(암호화)을 할 수 없습니다. 설정 파일의 '보안연결'을 '자동'으로 바꿔 주세요."
                                   f" (서버 답: {e})")
            ftp = None  # 자동: 보통 방식으로
    if ftp is None:
        ftp = ftplib.FTP(timeout=TIMEOUT, encoding="utf-8")
        ftp.connect(cfg["host"], cfg["port"])
    try:
        ftp.login(cfg["user"], cfg["password"])
    except ftplib.error_perm:
        ftp.close()
        raise PublishError("홈페이지 서버에 로그인하지 못했습니다. 설정 파일의 '아이디'와 '비밀번호'를 확인해 주세요."
                           " (여러 번 틀리면 한동안 접속이 막힐 수 있으니, 확인한 뒤에 다시 눌러 주세요)")
    if isinstance(ftp, ftplib.FTP_TLS):
        ftp.prot_p()  # 파일 내용도 암호화
    ftp.set_pasv(True)
    try:
        ftp.sendcmd("OPTS UTF8 ON")  # 한글 파일 이름
    except ftplib.Error:
        pass
    return ftp


def close(ftp):
    if ftp:
        try:
            ftp.quit()
        except (OSError, EOFError, ftplib.Error):
            ftp.close()


def make_dirs(ftp, path, made):
    cur = ""
    for part in path.strip("/").split("/"):
        cur += "/" + part
        if cur not in made:
            try:
                ftp.mkd(cur)
            except ftplib.error_perm:
                pass  # 이미 있다 (권한이 없으면 파일 올릴 때 걸린다)
            made.add(cur)


def put(ftp, local, remote):
    """임시 이름으로 올린 뒤 이름 바꾸기 (올리는 도중에 손님이 반쪽 파일을 받지 않게)"""
    if getattr(ftp, "no_rename", False):  # 이름 바꾸기가 안 되는 서버: 바로 덮어쓴다
        with open(local, "rb") as f:
            ftp.storbinary("STOR " + remote, f)
        return
    folder, name = posixpath.split(remote)
    stem, ext = posixpath.splitext(name)
    tmp = posixpath.join(folder, f"{stem}.uploading{ext}")  # 확장자는 그대로 (Cafe24 는 확장자로 거른다)
    with open(local, "rb") as f:
        ftp.storbinary("STOR " + tmp, f)
    try:
        ftp.rename(tmp, remote)
    except ftplib.error_perm:  # 이름 바꾸기가 안 되면 옛 파일 위에 바로 덮어쓰고 (옛 파일은 지우지 않는다)
        ftp.no_rename = True
        put(ftp, local, remote)
        try:
            ftp.delete(tmp)  # 우리가 만든 임시 파일만 치운다
        except ftplib.error_perm:
            pass


def publish(site_dir, cfg, manifest_path, progress=lambda done, total, rel: None):
    """site 폴더를 서버의 올릴_폴더로 (바뀐 파일만) → {"uploaded", "skipped"}"""
    site_dir = Path(site_dir)
    book = load_manifest(manifest_path)
    sent = book.setdefault(f"{cfg['host'].lower()}:{cfg['port']}{cfg['folder']}", {})
    files = site_files(site_dir)
    todo = []
    for rel in files:
        fp = fingerprint(site_dir / rel)
        if sent.get(rel) != fp:
            todo.append((rel, fp))
    ftp, made = None, set()
    try:
        for i, (rel, fp) in enumerate([("", None)] + todo):  # 맨 앞 "" = 접속·폴더 확인만 (바뀐 게 없어도 설정을 확인)
            if rel:
                progress(i - 1, len(todo), rel)
            for attempt in range(1, TRIES + 1):
                try:
                    if ftp is None:
                        ftp = connect(cfg)
                    remote = posixpath.join(cfg["folder"], rel) if rel else cfg["folder"] + "/"
                    make_dirs(ftp, posixpath.dirname(remote), made)
                    if rel:
                        put(ftp, site_dir / rel, remote)
                    break
                except ftplib.error_perm as e:
                    if str(e)[:3] in ("452", "552"):
                        raise PublishError("홈페이지 서버의 저장 공간이 모자랍니다. Cafe24 관리자에서 FTP 용량을 확인해 주세요.")
                    raise PublishError(f"홈페이지 서버에 '{rel or cfg['folder']}' 을(를) 올릴 수 없습니다. 설정 파일의 '올릴_폴더'가 맞는지,"
                                       f" 그 폴더에 올릴 권한이 있는지 확인해 주세요. (서버 답: {e})")
                except (OSError, EOFError, ftplib.Error) as e:  # 네트워크·서버 잠깐 문제: 다시 접속해서 다시
                    if ftp:
                        ftp.close()  # 끊긴 연결에 QUIT 를 보내면 시간 초과까지 기다리게 된다
                    ftp = None
                    if attempt == TRIES:
                        raise PublishError(net_message(e, cfg["tls"] != "no") + (f" (멈춘 파일: {rel})" if rel else ""))
                    time.sleep(attempt)
            if rel:
                sent[rel] = fp
                save_manifest(manifest_path, book)  # ponytail: 파일마다 기록 전체를 다시 쓴다 (수천 개면 느려짐 → 그때 줄 단위 기록으로)
        progress(len(todo), len(todo), "")
    finally:
        close(ftp)
    return {"uploaded": len(todo), "skipped": len(files) - len(todo)}
