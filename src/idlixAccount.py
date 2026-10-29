"""
The user's own IDLIX account. Signed-in playback sessions get the member
quality limit (1080p) instead of the guest one (720p).

IDLIX keeps its session in cookies (an access cookie and a rotating refresh
cookie). Only those cookies are kept, encrypted with Windows DPAPI so that only
this Windows user can read them; the password is sent once to IDLIX over HTTPS
and never stored or logged.
"""

import json
import os
import secrets
import threading
import time
from pathlib import Path

from curl_cffi import requests
from loguru import logger

from src.modernIdlix import BASE

CLIENT_VERSION = '1.7.1'  # the website's client version, sent on /api/auth/ requests
REFRESH_EVERY_SECONDS = 10 * 60
HEADERS = {'Origin': BASE.rstrip('/'), 'Referer': BASE, 'X-Client-Version': CLIENT_VERSION}


class AccountError(ValueError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class IdlixAccount:
    def __init__(self, folder, session_factory=None):
        self.path = Path(folder) / 'account.bin'
        self.session_factory = session_factory or (lambda: requests.Session(impersonate='chrome124', headers=HEADERS))
        self.lock = threading.RLock()
        self.cookies = []        # [{'name', 'value', 'domain', 'path', 'secure'}]
        self.user = None         # {'username', 'name'} for display
        self.fingerprint = None  # stable per install, like the website's device fingerprint
        self.refreshed_at = 0.0
        self.load()

    @property
    def signed_in(self):
        return bool(self.cookies)

    def status(self):
        with self.lock:
            return {'signed_in': self.signed_in, 'user': self.user}

    # ------------------------------------------------------------
    # Sign in / out
    # ------------------------------------------------------------
    def login(self, identifier, password, replace_sessions=False):
        identifier = (identifier or '').strip()
        if not identifier or not password:
            raise AccountError('Enter your IDLIX email or username and password.')
        session = self.session_factory()
        body = {'identifier': identifier, 'password': password}
        if replace_sessions:
            body['replaceExistingSessions'] = True
        response = session.post(BASE + 'api/auth/login', json=body, timeout=20,
                                headers={'X-Client-Fp': self.device_fingerprint()})
        if response.status_code != 200:
            raise login_error(response)
        cookies = export_cookies(session)
        if not cookies:
            raise AccountError('IDLIX accepted the sign-in but did not start a session.')
        user = read_user(session)
        with self.lock:
            self.cookies, self.user, self.refreshed_at = cookies, user, time.time()
            self.save()
        logger.info(f"Signed in to IDLIX as {user.get('username') or 'your account'}")
        return self.status()

    def logout(self):
        with self.lock:
            if self.cookies:
                try:
                    session = self.session_factory()
                    import_cookies(session, self.cookies)
                    session.post(BASE + 'api/auth/logout', json={'scope': 'local'}, timeout=15)
                except Exception as error:  # signing out locally must work offline too
                    logger.debug(f'IDLIX logout request failed: {error}')
            self.cookies, self.user = [], None
            self.save()
        logger.info('Signed out of IDLIX')
        return self.status()

    # ------------------------------------------------------------
    # Using the session
    # ------------------------------------------------------------
    def attach(self, session):
        """Give an HTTP session the current account cookies (renewing them when due)."""
        with self.lock:
            if not self.cookies:
                return False
            if time.time() - self.refreshed_at > REFRESH_EVERY_SECONDS:
                self.refresh()
            import_cookies(session, self.cookies)
            return bool(self.cookies)

    def refresh(self):
        """Renew the session cookies. Returns False once IDLIX has ended the session."""
        with self.lock:
            if not self.cookies:
                return False
            session = self.session_factory()
            import_cookies(session, self.cookies)
            try:
                response = session.post(BASE + 'api/auth/refresh?bootstrap=0', timeout=20)
            except Exception as error:
                logger.warning(f'Could not renew the IDLIX session: {error}')
                return True  # offline for now; keep the session and try again later
            if response.status_code == 200:
                self.cookies = merge_cookies(self.cookies, export_cookies(session))
                self.refreshed_at = time.time()
                self.save()
                return True
            if response.status_code in (401, 403):
                logger.warning('The IDLIX session ended; continuing as a guest')
                self.cookies, self.user = [], None
                self.save()
                return False
            logger.warning(f'IDLIX session renewal failed (HTTP {response.status_code}); will retry')
            return True

    # ------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------
    def device_fingerprint(self):
        with self.lock:
            if not self.fingerprint:
                self.fingerprint = secrets.token_hex(32)
                self.save()
            return self.fingerprint

    def load(self):
        try:
            data = json.loads(unprotect(self.path.read_bytes()))
        except FileNotFoundError:
            return
        except Exception as error:
            logger.warning(f'Ignoring unreadable IDLIX account data: {error}')
            return
        self.cookies = data.get('cookies') or []
        self.user = data.get('user')
        self.fingerprint = data.get('fingerprint')
        self.refreshed_at = float(data.get('refreshed_at') or 0)

    def save(self):
        data = json.dumps({'cookies': self.cookies, 'user': self.user, 'fingerprint': self.fingerprint,
                           'refreshed_at': self.refreshed_at}).encode()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_bytes(protect(data))
            os.replace(temporary, self.path)
        except OSError as error:
            logger.warning(f'Could not save the IDLIX session: {error}')


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def export_cookies(session):
    return [{'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path or '/', 'secure': bool(c.secure)}
            for c in session.cookies.jar if c.value]


def import_cookies(session, cookies):
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'], path=cookie['path'],
                            secure=cookie.get('secure', False))


def merge_cookies(old, new):
    """Renewed cookies replace their old versions; others are kept."""
    merged = {(c['name'], c['domain'], c['path']): c for c in old}
    merged.update({(c['name'], c['domain'], c['path']): c for c in new})
    return list(merged.values())


def read_user(session):
    user = {}
    try:
        response = session.get(BASE + 'api/auth/me', timeout=20)
        if response.status_code == 200:
            user = response.json().get('user') or {}
    except Exception:
        pass
    return {'username': user.get('username'), 'name': user.get('displayName') or user.get('name') or user.get('username')}


def login_error(response):
    try:
        data = response.json()
    except ValueError:
        data = {}
    code = data.get('code')
    detail = data.get('message') or data.get('error')
    if response.status_code == 409:
        return AccountError(detail or 'This account is already signed in on the maximum number of devices.',
                            code=code or 'SESSION_LIMIT')
    if response.status_code in (400, 401, 403):
        return AccountError(detail or 'The email/username or password is incorrect.', code=code)
    if response.status_code == 429:
        return AccountError('Too many sign-in attempts. Wait a moment and try again.', code=code)
    return AccountError(f'IDLIX sign-in failed (HTTP {response.status_code}){f": {detail}" if detail else ""}.', code=code)


# Windows DPAPI keeps the cookies readable only by this Windows user.
def _dpapi(data, decrypt):
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data, len(data))
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    result = Blob()
    crypt32 = ctypes.windll.crypt32
    ok = (crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(result)) if decrypt
          else crypt32.CryptProtectData(ctypes.byref(source), ctypes.c_wchar_p('MarTube'), None, None, None, 0x1,
                                        ctypes.byref(result)))
    if not ok:
        raise OSError('Windows could not ' + ('decrypt' if decrypt else 'encrypt') + ' the IDLIX session')
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def protect(data):
    return _dpapi(data, decrypt=False) if os.name == 'nt' else data


def unprotect(data):
    return _dpapi(data, decrypt=True) if os.name == 'nt' else data
