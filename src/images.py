"""
Disk cache for poster, backdrop and episode images (served by TMDB).

Images are kept under the local app data folder so the library still shows
artwork offline. The cache is trimmed, oldest first, when it grows past its limit.
"""

import os
import re
import threading
from pathlib import Path

import requests
from loguru import logger

TMDB_IMAGES = 'https://image.tmdb.org/t/p/'
SIZES = ('w185', 'w342', 'w500', 'w780', 'w1280', 'original')
POSTER, BACKDROP, STILL = 'w342', 'w780', 'w500'


class ImageCache:
    def __init__(self, folder, limit_bytes=300 * 1024 * 1024):
        self.folder = Path(folder)
        self.limit_bytes = limit_bytes
        self.locks = {}
        self.locks_guard = threading.Lock()
        self.session = requests.Session()

    def path_for(self, image_path, size):
        name = (image_path or '').strip('/')
        if size not in SIZES or not re.fullmatch(r'[A-Za-z0-9_-]+\.(jpg|jpeg|png|webp)', name):
            return None
        return self.folder / f'{size}_{name}'

    def get(self, image_path, size=POSTER):
        """Local file for a TMDB image path such as '/abc.jpg', downloading it once; None if unavailable."""
        target = self.path_for(image_path, size)
        if target is None:
            return None
        with self.locks_guard:
            lock = self.locks.setdefault(target.name, threading.Lock())
        with lock:  # concurrent requests for one image download it once
            if target.exists():
                target.touch()  # most recently used survives trimming
                return target
            try:
                response = self.session.get(TMDB_IMAGES + size + '/' + image_path.strip('/'), timeout=15)
                response.raise_for_status()
                if not response.headers.get('Content-Type', '').startswith('image/'):
                    raise ValueError(f"not an image ({response.headers.get('Content-Type')})")
                self.folder.mkdir(parents=True, exist_ok=True)
                partial = target.with_suffix(target.suffix + '.part')
                partial.write_bytes(response.content)
                os.replace(partial, target)
            except Exception as error:
                logger.warning(f'Image {size}{image_path} unavailable: {error}')
                return None
        self.trim()
        return target

    def prefetch(self, info):
        """Cache the artwork of a title described by ModernIdlix.info."""
        parent = info.get('series') or info.get('movie') or {}
        self.get(parent.get('poster_path'), POSTER)
        self.get(parent.get('backdrop_path'), BACKDROP)
        if info.get('episode'):
            self.get(info['episode'].get('still_path'), STILL)

    def trim(self):
        files = [f for f in self.folder.glob('*') if f.is_file() and not f.name.endswith('.part')]
        total = sum(f.stat().st_size for f in files)
        if total <= self.limit_bytes:
            return
        # Drop least recently used files until 80% of the limit, leaving room to grow.
        for file in sorted(files, key=lambda f: f.stat().st_mtime):
            if total <= self.limit_bytes * 0.8:
                break
            total -= file.stat().st_size
            file.unlink(missing_ok=True)
