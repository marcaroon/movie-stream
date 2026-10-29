"""
Loopback HTTP server behind the app: the web UI, a JSON API, artwork,
downloaded videos (with Range support for seeking) and subtitles.

Only this computer's own app page may use it. It listens on 127.0.0.1,
rejects other Host names (DNS rebinding), and requires a session cookie that
is handed out once through the URL the launcher or window opens. The cookie is
SameSite=Strict, so other websites in a browser cannot make requests with it.
"""

import hmac
import json
import mimetypes
import re
import secrets
import sys
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from loguru import logger

from src import settings
from src.webapp.backend import UserError

STATIC_DIR = Path(__file__).resolve().parent / 'static'
COOKIE = 'idlix_session'
CHUNK = 256 * 1024
LOGIN_SECONDS = 365 * 86400
LOCKED_PAGE = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>MarTube</title>
<body style="margin:0;background:#000;color:#f5f5f7;font:17px/1.47 -apple-system,'Segoe UI Variable',
'Segoe UI',sans-serif;display:grid;place-items:center;height:100vh;letter-spacing:-.01em">
<div style="max-width:420px;text-align:center;padding:24px"><h1 style="font-size:34px;letter-spacing:-.03em;
margin:0 0 8px">MarTube</h1><p style="color:rgba(235,235,245,.6);margin:0">Open MarTube from its shortcut on the
Desktop or Start menu to sign this browser in.</p></div></body></html>'''.encode()

mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('font/woff2', '.woff2')


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # The player drops connections all the time (seeking, closing); that is not an error.
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


class AppServer:
    def __init__(self, backend, static_dir=STATIC_DIR, port=0, token=None, remember_login=False):
        """port 0 picks a free port. A fixed token and remember_login keep a browser logged in
        across restarts (browser mode); the default is a one-run login for the app window."""
        self.backend = backend
        self.static_dir = Path(static_dir).resolve()
        self.token = token or secrets.token_urlsafe(32)
        self.remember_login = remember_login
        self.on_quit = None  # set when the page may stop the server (browser mode)
        self.routes = []
        self.add_routes()
        server = self

        class Handler(RequestHandler):
            app = server

        self.httpd = QuietServer(('127.0.0.1', port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_port
        self.host = f'127.0.0.1:{self.port}'
        self.hosts = {self.host, f'localhost:{self.port}'}
        self.origin = 'http://' + self.host
        backend.origins = {'http://' + host for host in self.hosts}

    @property
    def url(self):
        """What the window opens first; it trades the token for the session cookie."""
        return f'{self.origin}/?token={self.token}'

    def start(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def route(self, method, pattern, handler):
        self.routes.append((method, re.compile(pattern + '$'), handler))

    def add_routes(self):
        b = self.backend
        self.route('GET', r'/api/home', lambda r, m: b.home())
        self.route('GET', r'/api/search', lambda r, m: b.search(r.query('q'), int(r.query('page', '1'))))
        self.route('GET', r'/api/title/(movie|series)/([\w-]+)', lambda r, m: b.title(m[1], m[2]))
        self.route('GET', r'/api/season/([\w-]+)/(\d+)', lambda r, m: b.season(m[1], int(m[2])))
        self.route('GET', r'/api/downloads', lambda r, m: b.downloads_view())
        self.route('POST', r'/api/downloads', lambda r, m: b.queue(r.json().get('items') or []))
        self.route('POST', r'/api/downloads/(\d+)/cancel', lambda r, m: b.cancel(int(m[1])))
        self.route('POST', r'/api/downloads/(\d+)/retry', lambda r, m: b.retry_job(int(m[1])))
        self.route('POST', r'/api/downloads/clear', lambda r, m: b.clear_finished())
        self.route('POST', r'/api/settings', lambda r, m: b.set_parallel(r.json()['parallel']))
        self.route('POST', r'/api/folder/choose', lambda r, m: b.choose_folder())
        self.route('POST', r'/api/folder/set', lambda r, m: b.set_folder(r.json().get('folder')))
        self.route('POST', r'/api/folder/open', lambda r, m: b.open_folder())
        self.route('POST', r'/api/play', lambda r, m: b.play(r.json().get('url'), r.json().get('media_id')))
        self.route('GET', r'/api/status', lambda r, m: b.status())
        self.route('GET', r'/api/library', lambda r, m: b.library_view())
        self.route('POST', r'/api/watch-later', lambda r, m: b.set_watch_later(r.json()['url'], r.json()['add']))
        self.route('POST', r'/api/follow/([\w-]+)', lambda r, m: b.set_follow(m[1], r.json()['follow']))
        self.route('POST', r'/api/follow/([\w-]+)/auto', lambda r, m: b.set_follow_auto(m[1], r.json()['auto']))
        self.route('POST', r'/api/follows/check', lambda r, m: b.check_follows())
        self.route('POST', r'/api/new-episodes/seen', lambda r, m: b.mark_new_seen(r.json().get('series_id')))
        self.route('POST', r'/api/prefs', lambda r, m: b.set_prefs(**{
            k: r.json().get(k) for k in ('auto_next_download', 'delete_watched_after_days')}))
        self.route('POST', r'/api/media/(\d+)/delete', lambda r, m: b.delete_media(int(m[1])))
        self.route('POST', r'/api/storage/delete-watched', lambda r, m: b.delete_watched())
        self.route('POST', r'/api/progress', lambda r, m: b.save_progress(**{
            k: r.json().get(k) for k in ('url', 'position', 'duration')}))
        self.route('GET', r'/api/server', lambda r, m: {'can_quit': self.on_quit is not None})
        self.route('GET', r'/api/account', lambda r, m: b.account_view())
        self.route('POST', r'/api/account/sign-in', lambda r, m: b.sign_in(**{
            k: r.json().get(k) for k in ('identifier', 'password', 'replace_sessions')}))
        self.route('POST', r'/api/account/sign-out', lambda r, m: b.sign_out())
        self.route('POST', r'/api/quit', lambda r, m: self.quit())

    def quit(self):
        if not self.on_quit:
            raise HttpError(404, 'Not available')
        # Answer first; the shutdown (waiting for downloads to stop) runs afterwards.
        threading.Timer(0.3, self.on_quit).start()
        return {'ok': True}


class RequestHandler(BaseHTTPRequestHandler):
    app = None  # set by AppServer
    protocol_version = 'HTTP/1.1'

    # ------------------------------------------------------------
    # Request helpers
    # ------------------------------------------------------------
    def query(self, name, default=''):
        return parse_qs(urlsplit(self.path).query).get(name, [default])[0]

    def json(self):
        return json.loads(self.body or b'{}')

    def authorised(self):
        cookie = SimpleCookie(self.headers.get('Cookie', ''))
        value = cookie[COOKIE].value if COOKIE in cookie else ''
        return hmac.compare_digest(value, self.app.token)

    # ------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------
    def do_GET(self):
        self.handle_request('GET')

    def do_POST(self):
        self.handle_request('POST')

    def handle_request(self, method):
        path = urlsplit(self.path).path
        # One handler serves every request of a keep-alive connection: always consume this
        # request's body first, or leftover bytes would corrupt the next request line.
        self.body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        try:
            if self.headers.get('Host') not in self.app.hosts:
                raise HttpError(403, 'Unexpected host')
            if method == 'GET' and path == '/api/ping':  # lets the launcher find a running server
                return self.send_json({'app': settings.APP_NAME})
            if method == 'GET' and path == '/' and hmac.compare_digest(self.query('token'), self.app.token):
                return self.send_login()
            if not self.authorised():
                if method == 'GET' and path in ('/', '/index.html'):
                    return self.send_body(LOCKED_PAGE, 'text/html; charset=utf-8', 403)
                raise HttpError(403, 'Open MarTube from its shortcut')
            if method == 'GET' and path in ('/', '/index.html'):
                return self.send_index()
            if method == 'GET' and path.startswith('/static/'):
                return self.send_static(path[len('/static/'):])
            if method == 'GET' and (match := re.fullmatch(r'/img/(\w+)/([\w.-]+)', path)):
                return self.send_image(match[1], match[2])
            if method == 'GET' and (match := re.fullmatch(r'/media/(\d+)', path)):
                return self.send_media(int(match[1]))
            if method == 'GET' and (match := re.fullmatch(r'/subtitle/local/(\d+)', path)):
                return self.send_body(self.app.backend.local_subtitle(int(match[1])).encode(), 'text/vtt')
            if method == 'GET' and path == '/subtitle/stream':
                return self.send_body(self.app.backend.stream_subtitle().encode(), 'text/vtt')
            for route_method, pattern, handler in self.app.routes:
                if route_method == method and (match := pattern.match(path)):
                    return self.send_json(handler(self, match))
            raise HttpError(404, 'Not found')
        except HttpError as error:
            self.send_json({'error': str(error)}, error.status)
        except UserError as error:
            self.send_json({'error': str(error), 'code': error.code}, 400)
        except (ConnectionError, BrokenPipeError):
            pass
        except FileNotFoundError as error:
            self.send_json({'error': str(error)}, 404)
        except Exception as error:
            logger.warning(f'{method} {path} failed: {error}')
            self.send_json({'error': str(error)}, 502)

    # ------------------------------------------------------------
    # Responses
    # ------------------------------------------------------------
    def send_body(self, body, content_type, status=200, headers=()):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_body(body, 'application/json; charset=utf-8', status, [('Cache-Control', 'no-store')])

    def send_index(self):
        self.send_body((self.app.static_dir / 'index.html').read_bytes(), 'text/html; charset=utf-8',
                       headers=[('Cache-Control', 'no-store')])

    def send_login(self):
        """Trade the token for the session cookie, then reload without the token in the address bar."""
        lifetime = f'; Max-Age={LOGIN_SECONDS}' if self.app.remember_login else ''
        self.send_body(b'', 'text/plain', 303, [
            ('Location', '/'), ('Cache-Control', 'no-store'),
            ('Set-Cookie', f'{COOKIE}={self.app.token}; Path=/; HttpOnly; SameSite=Strict{lifetime}')])

    def send_static(self, relative):
        target = (self.app.static_dir / relative).resolve()
        if self.app.static_dir not in target.parents or not target.is_file():
            raise HttpError(404, 'Not found')
        kind = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        self.send_body(target.read_bytes(), kind, headers=[('Cache-Control', 'no-cache')])

    def send_image(self, size, name):
        image = self.app.backend.images.get('/' + name, size)
        if not image:
            raise HttpError(404, 'Image unavailable')
        kind = mimetypes.guess_type(image.name)[0] or 'image/jpeg'
        self.send_body(image.read_bytes(), kind, headers=[('Cache-Control', 'max-age=604800')])

    def send_media(self, media_id):
        """Stream a downloaded video, honouring Range requests so the player can seek."""
        media = self.app.backend.library.media_by_id(media_id)
        path = Path(media['file_path']) if media else None
        if not path or not path.is_file():
            raise HttpError(404, 'Video file not found')
        size = path.stat().st_size
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', self.headers.get('Range', '').strip())
        if match and (match[1] or match[2]):
            if match[1]:
                start, end = int(match[1]), int(match[2]) if match[2] else size - 1
            else:  # suffix range: the last N bytes
                start, end = max(0, size - int(match[2])), size - 1
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            status = 206
        else:
            start, end, status = 0, size - 1, 200
        self.send_response(status)
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'video/mp4')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as video:
            video.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = video.read(min(CHUNK, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def log_message(self, *_):
        pass
