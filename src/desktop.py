"""Desktop-app plumbing shared by the app windows: log file and single instance."""

import os

from loguru import logger

from src import settings

LOG_FILE = settings.DATA_DIR / 'logs' / 'idlix.log'


def setup_logging():
    # Started from a shortcut via pythonw there is no console, so keep a log file for diagnosis.
    logger.configure(extra={'job': ''})  # "#N" job prefix is empty outside download workers
    logger.add(LOG_FILE, rotation='1 MB', retention=5, encoding='utf-8', buffering=1,  # flush every line
               format='{time:YYYY-MM-DD HH:mm:ss} | {level} | {extra[job]}{message}')


def focus_running_instance():
    """Return True if the app is already open (and bring its window to the front)."""
    if os.name != 'nt':
        return False
    import ctypes
    kernel32, user32 = ctypes.windll.kernel32, ctypes.windll.user32
    # The handle lives as long as this process; Windows frees it on exit.
    focus_running_instance.mutex = kernel32.CreateMutexW(None, False, 'Local\\IdlixDownloader')
    if kernel32.GetLastError() != 183:  # ERROR_ALREADY_EXISTS
        return False
    window = user32.FindWindowW(None, settings.APP_NAME)
    if window:
        user32.ShowWindow(window, 9)  # SW_RESTORE
        user32.SetForegroundWindow(window)
    return True
