"""MarTube in its own window (web UI in WebView2, served from a loopback server)."""

import threading

import webview
from loguru import logger

from src import settings
from src.desktop import LOG_FILE, focus_running_instance, setup_logging
from src.idlixAccount import IdlixAccount
from src.idlixHelper import IdlixHelper
from src.images import ImageCache
from src.library import Library
from src.webapp.backend import Backend
from src.webapp.server import AppServer


class WindowApi:
    """Calls the page can make into the window itself (window.pywebview.api)."""

    def __init__(self):
        self.window = None

    def toggle_fullscreen(self):
        self.window.toggle_fullscreen()


def main():
    setup_logging()
    if focus_running_instance():
        logger.info('Already running; focused the open window.')
        return
    try:
        IdlixHelper.ensure_ffmpeg()
        library = Library(settings.CONFIG_DIR / 'library.db')
        images = ImageCache(settings.DATA_DIR / 'cache' / 'images')
        backend = Backend(library, images, account=IdlixAccount(settings.CONFIG_DIR))
        server = AppServer(backend).start()
    except Exception:
        logger.exception('MarTube could not start')
        raise

    api = WindowApi()
    window = webview.create_window(settings.APP_NAME, server.url, js_api=api, width=1360, height=860,
                                   min_size=(900, 600), background_color='#000000')
    api.window = window

    def choose_folder(current):
        chosen = window.create_file_dialog(webview.FileDialog.FOLDER, directory=current)
        return chosen[0] if chosen else None

    backend.choose_folder_dialog = choose_folder
    closing_confirmed = threading.Event()

    def on_closing():
        running = backend.downloads.unfinished()
        if running and not closing_confirmed.is_set():
            if not window.create_confirmation_dialog(
                    settings.APP_NAME,
                    f'{running} download(s) are still running or queued.\n'
                    'Quit now? They will start again from the beginning next time.'):
                return False
            closing_confirmed.set()
        backend.shutdown()
        return True

    def hide_title_bar_icon():
        # The app has no icon; Windows Forms would otherwise show a default one in the title bar.
        form = window.native
        try:
            from System import Action
            form.Invoke(Action(lambda: setattr(form, 'ShowIcon', False)))
        except Exception as error:
            logger.debug(f'Could not hide the title bar icon: {error}')

    window.events.closing += on_closing
    window.events.shown += hide_title_bar_icon
    backend.scan_library()
    backend.start_background_tasks()
    logger.info(f'{settings.APP_NAME} started; log file: {LOG_FILE}')
    webview.start(storage_path=str(settings.DATA_DIR / 'webview'), private_mode=False)
    server.stop()


if __name__ == '__main__':
    main()
