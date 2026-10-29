"""Small JSON stores for GUI preferences and the unfinished download queue."""

import json
import os
from pathlib import Path

from loguru import logger

APP_NAME = 'MarTube'
CONFIG_DIR = Path(os.environ.get('APPDATA') or Path.home() / '.config') / 'IdlixDownloader'
# Machine-local, disposable data (logs, image cache) stays out of the roaming profile.
DATA_DIR = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.cache') / 'IdlixDownloader'
DEFAULT_DOWNLOAD_DIR = Path(__file__).resolve().parent.parent / 'Downloads'
SETTINGS_FILE = 'settings.json'
DEFAULT_PORT = 8765


def download_dir():
    """Folder chosen in the app, or the default download folder."""
    return Path(load(SETTINGS_FILE, {}).get('download_dir') or DEFAULT_DOWNLOAD_DIR)


def load(name, default):
    try:
        data = json.loads((CONFIG_DIR / name).read_text(encoding='utf-8'))
        return data if isinstance(data, type(default)) else default
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as error:
        logger.warning(f'Ignoring unreadable {name}: {error}')
        return default


def save(name, data):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # Write then rename, so a crash mid-write never leaves a half-written file.
        temporary = CONFIG_DIR / (name + '.tmp')
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, CONFIG_DIR / name)
    except OSError as error:
        logger.warning(f'Could not save {name}: {error}')
