"""
MarTube in the browser: starts the local server when it is not running
yet, then opens http://127.0.0.1:<port> (default 8765) in the default browser.

The desktop shortcut runs it with .venv\\Scripts\\pythonw.exe, so no console
window appears. The server keeps running (and downloading) after the browser
tab is closed; stop it from the Downloads page.

    pythonw launcher.py               start if needed, open the browser
    pythonw launcher.py --no-browser  start if needed, nothing else
"""

import argparse
import json
import secrets
import threading
import urllib.request
import webbrowser

from loguru import logger

from src import settings
from src.desktop import LOG_FILE, focus_running_instance, setup_logging
from src.idlixAccount import IdlixAccount
from src.idlixHelper import IdlixHelper
from src.images import ImageCache
from src.library import Library
from src.webapp.backend import Backend
from src.webapp.server import AppServer

TOKEN_FILE = settings.DATA_DIR / 'login.token'


def login_token():
    """A token kept across runs, so a browser stays logged in after the server restarts."""
    try:
        token = TOKEN_FILE.read_text(encoding='utf-8').strip()
        if len(token) >= 32:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token, encoding='utf-8')
    return token


def server_running(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/ping', timeout=2) as response:
            return json.load(response).get('app') == settings.APP_NAME
    except (OSError, ValueError):
        return False


def show_message(text):
    """A plain Windows message box: under pythonw there is no console to print to."""
    logger.warning(text)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, settings.APP_NAME, 0x30)  # MB_ICONWARNING
    except (AttributeError, OSError):
        print(text)


def main():
    parser = argparse.ArgumentParser(description='Start MarTube and open it in the browser.')
    parser.add_argument('--no-browser', action='store_true', help='only make sure the server is running')
    args = parser.parse_args()

    setup_logging()
    port = int(settings.load(settings.SETTINGS_FILE, {}).get('port') or settings.DEFAULT_PORT)
    token = login_token()
    address = f'http://127.0.0.1:{port}/'
    login_url = f'{address}?token={token}'

    if server_running(port):
        if not args.no_browser:
            webbrowser.open(login_url)
        return
    if focus_running_instance():
        show_message('MarTube is already open in another window. Close that window first, '
                     'then use the shortcut again.')
        return

    try:
        IdlixHelper.ensure_ffmpeg()
        backend = Backend(Library(settings.CONFIG_DIR / 'library.db'),
                          ImageCache(settings.DATA_DIR / 'cache' / 'images'),
                          account=IdlixAccount(settings.CONFIG_DIR))
        server = AppServer(backend, port=port, token=token, remember_login=True).start()
    except OSError as error:
        show_message(f'Port {port} is used by another program, so MarTube cannot start.\n'
                     f'Change "port" in {settings.CONFIG_DIR / settings.SETTINGS_FILE} and try again.\n\n{error}')
        return
    except Exception:
        logger.exception('MarTube could not start')
        show_message(f'MarTube could not start. Details: {LOG_FILE}')
        return

    stopped = threading.Event()

    def stop():
        logger.info('Stopping the server (requested from the page)')
        backend.shutdown()
        stopped.set()

    server.on_quit = stop
    backend.scan_library()
    backend.start_background_tasks()
    logger.info(f'{settings.APP_NAME} server running at {address}')
    if not args.no_browser:
        webbrowser.open(login_url)
    stopped.wait()
    server.stop()


if __name__ == '__main__':
    main()
