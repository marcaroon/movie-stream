"""Add videos already sitting in the download folder to the library by matching their names on IDLIX."""

import re
from pathlib import Path

from loguru import logger

from src.images import BACKDROP, POSTER, STILL
from src.modernIdlix import BASE, safe_name

# Episode files are named by episode_title(): "<series> S<season>E<number> - <name>"
EPISODE_FILE = re.compile(r'^(?P<series>.+) S(?P<season>\d+)E(?P<number>\d+) - (?P<name>.+)$')


def identify(client, stem):
    """IDLIX metadata (ModernIdlix.info) for a video file name, or None when nothing matches exactly."""
    episode = EPISODE_FILE.match(stem)
    name = episode['series'] if episode else stem
    # safe_name() turned characters such as ':' into '_'; search with spaces instead.
    for item in client.search(re.sub(r'[_\s]+', ' ', name).strip())['results']:
        if safe_name(item['title']) != name:
            continue
        if episode and item['type'] == 'series':
            url = BASE + f"series/{item['slug']}/season/{int(episode['season'])}/episode/{int(episode['number'])}"
        elif not episode and item['type'] == 'movie':
            url = item['url']
        else:
            continue
        try:
            client.metadata(url)
        except Exception as error:
            logger.debug(f'{url}: {error}')
            continue
        if safe_name(client.info['title']) == stem:
            return client.info
    return None


def cache_artwork(library, images):
    """Download any poster, backdrop or episode image of library videos that is not cached yet."""
    for item in library.media():
        images.get(item['poster_path'], POSTER)
        images.get(item['backdrop_path'], BACKDROP)
        images.get(item['still_path'], STILL)


def scan_folder(library, client, folder, images=None):
    """Add unknown .mp4 files in folder to the library; returns (matched, unmatched) counts."""
    known = library.known_files()
    matched = unmatched = 0
    for video in sorted(Path(folder).glob('*.mp4')):
        if video.name.endswith('.part.mp4') or str(video.resolve()) in known:
            continue
        subtitle = next((p for p in (video.with_suffix('.vtt'), video.with_suffix('.srt')) if p.exists()), None)
        try:
            info = identify(client, video.stem)
        except Exception as error:
            logger.warning(f'Could not look up {video.name}: {error}')
            info = None
        library.add_media(video, info, subtitle_path=subtitle)
        if info:
            matched += 1
            if images:
                images.prefetch(info)
        else:
            unmatched += 1
            logger.info(f'Added without IDLIX details (no exact match): {video.name}')
    return matched, unmatched
