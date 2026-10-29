"""
Everything the app window can ask for, independent of HTTP: browsing IDLIX,
the download queue, the local library, followed series, storage and preparing
videos for the player.
"""

import os
import shutil
import threading
import time
import webbrowser
from pathlib import Path

from loguru import logger

from src import settings
from src.downloadQueue import FINISHED, DownloadManager
from src.libraryScan import cache_artwork, scan_folder
from src.modernIdlix import ModernIdlix

QUEUE_FILE = 'queue.json'
MAX_PARALLEL_DOWNLOADS = 5
DEFAULT_PARALLEL_DOWNLOADS = 2
BROWSE_CACHE_SECONDS = 600
RESUME_AFTER_SECONDS = 30
STREAM_ATTEMPTS = 2  # a fresh playback session once more after a network timeout
FOLLOW_CHECK_DELAY = 20  # seconds after start, so the first screen loads first
FOLLOW_CHECK_INTERVAL = 3 * 3600
DELETE_AFTER_CHOICES = (0, 1, 3, 7, 14, 30)  # days; 0 = never delete watched videos
DEFAULT_PREFS = {'auto_next_download': False, 'delete_watched_after_days': 0}
DELETABLE_SUFFIXES = {'.mp4', '.vtt', '.srt'}


def series_record(details):
    """The library's title fields from a details() result."""
    return {key: details.get(key) for key in
            ('id', 'kind', 'slug', 'title', 'year', 'overview', 'poster_path', 'backdrop_path', 'runtime')}


class Backend:
    def __init__(self, library, images, client_factory=ModernIdlix, account=None):
        self.account = account  # the user's IDLIX sign-in (member quality), or None
        self.library = library
        self.images = images
        self.client_factory = client_factory
        self.prefs = settings.load(settings.SETTINGS_FILE, {})
        self.download_dir = Path(self.prefs.get('download_dir') or self.adopt_library_folder(library)
                                 or settings.DEFAULT_DOWNLOAD_DIR)
        parallel = min(max(int(self.prefs.get('parallel', DEFAULT_PARALLEL_DOWNLOADS)), 1), MAX_PARALLEL_DOWNLOADS)
        self.origins = set()  # addresses of the app page, allowed to read the stream proxy
        self.choose_folder_dialog = None  # set by the window: (current folder) -> chosen folder or None

        # curl_cffi sessions are not thread-safe: browsing shares one client under a lock,
        # and the video being streamed has its own.
        self.catalog = self.new_client(self.download_dir)
        self.catalog_lock = threading.Lock()
        self.browse_cache = (0, None)
        self.stream_client = None
        self.stream_lock = threading.Lock()
        self.playing = {}  # page URL -> library info, so progress links streamed videos to their title

        self.closing = False
        self.queue_changed = threading.Event()
        self.downloads = DownloadManager(on_change=lambda job: self.queue_changed.set(), limit=parallel,
                                         download_dir=self.download_dir, library=library, images=images,
                                         account=account)
        self.restore_queue()
        threading.Thread(target=self.save_queue_loop, daemon=True).start()
        self.stop_checks = threading.Event()

    def start_background_tasks(self):
        """Follow checks and clean-up of watched videos, now and then every few hours."""
        def loop():
            if self.stop_checks.wait(FOLLOW_CHECK_DELAY):
                return
            while True:
                try:
                    self.check_follows()
                    self.delete_expired_watched()
                except Exception as error:
                    logger.warning(f'Background check failed: {error}')
                if self.stop_checks.wait(FOLLOW_CHECK_INTERVAL):
                    return

        threading.Thread(target=loop, daemon=True).start()

    def pref(self, name):
        return self.prefs.get(name, DEFAULT_PREFS[name])

    def adopt_library_folder(self, library):
        """With no folder chosen yet, keep saving where the library's videos already are.

        This keeps an existing collection in one place if the default folder ever changes.
        The choice is saved explicitly.
        """
        folders = {}
        for media in library.media():
            folder = Path(media['file_path']).parent
            if folder.is_dir():
                folders[folder] = folders.get(folder, 0) + 1
        if not folders:
            return None
        folder = max(folders, key=folders.get)
        self.prefs['download_dir'] = str(folder)
        settings.save(settings.SETTINGS_FILE, self.prefs)
        logger.info(f'Download folder: {folder} (where the library videos are)')
        return folder

    # ------------------------------------------------------------
    # Browsing
    # ------------------------------------------------------------
    def catalog_call(self, method, *args, attempts=3):
        """Call the shared browsing client, retrying briefly when the network hiccups."""
        with self.catalog_lock:
            for attempt in range(attempts):
                try:
                    return getattr(self.catalog, method)(*args)
                except Exception:
                    if attempt == attempts - 1:
                        raise
                    time.sleep(0.5 * (attempt + 1))

    def home(self):
        cached_at, rows = self.browse_cache
        error = None
        if rows is None or time.monotonic() - cached_at > BROWSE_CACHE_SECONDS:
            try:
                rows = self.catalog_call('browse')['rows']
                self.browse_cache = (time.monotonic(), rows)
            except Exception as error_browse:
                error = str(error_browse)
                rows = rows or []
        return {'continue': self.library.continue_watching(), 'downloaded': self.library.media()[:20],
                'new_episodes': self.library.new_episodes(), 'watch_later': self.library.watch_later(),
                'rows': rows, 'error': error}

    def search(self, query, page=1):
        return self.catalog_call('search', query, page)

    def title(self, kind, slug):
        details = self.catalog_call('details', kind, slug)
        if kind == 'movie':
            details['state'] = self.states([details['url']])[details['url']]
        else:
            follow = self.library.following(details['id'])
            details['following'] = bool(follow)
            details['auto_download'] = bool(follow and follow['auto_download'])
        return details

    def season(self, slug, number):
        result = self.catalog_call('episodes', slug, number)
        states = self.states([episode['url'] for episode in result['episodes']])
        for episode in result['episodes']:
            episode['state'] = states[episode['url']]
        return result

    def states(self, urls):
        """Library and queue status of page URLs: downloaded file, watch progress, active job."""
        states = self.library.states(urls)
        later = self.library.in_watch_later(urls)
        jobs = {}
        for job in list(self.downloads.jobs.values()):  # later jobs win
            jobs[job.url] = job
        for url, state in states.items():
            job = jobs.get(url)
            state['job'] = self.job_dict(job) if job and job.status not in FINISHED else None
            state['watch_later'] = url in later
        return states

    def catalog_info(self, url):
        """Library metadata (ModernIdlix.info) of a movie or episode page."""
        with self.catalog_lock:  # metadata() replaces the client's loaded title
            self.catalog.metadata(url)
            return self.catalog.info

    def new_client(self, folder):
        return self.client_factory(folder, account=self.account)

    @staticmethod
    def session_quality(client):
        """What the playback session allows, and the best the title offers (for a sign-in hint)."""
        claim = client.claim or {}
        ladder = [height for height in claim.get('qualityLadder') or [] if isinstance(height, int)]
        return {'tier': claim.get('viewerTier'), 'max_height': claim.get('maxHeight'),
                'best_height': max(ladder) if ladder else None}

    # ------------------------------------------------------------
    # IDLIX account
    # ------------------------------------------------------------
    def account_view(self):
        if not self.account:
            return {'available': False, 'signed_in': False, 'user': None}
        return {'available': True, **self.account.status()}

    def sign_in(self, identifier, password, replace_sessions=False):
        if not self.account:
            raise ValueError('Accounts are not available')
        try:
            return {'available': True, **self.account.login(identifier, password, bool(replace_sessions))}
        except ValueError as error:
            # Wrong password etc. is the user's to fix, not a server failure.
            raise UserError(str(error), getattr(error, 'code', None)) from None

    def sign_out(self):
        if not self.account:
            raise ValueError('Accounts are not available')
        return {'available': True, **self.account.logout()}

    def status(self):
        """Counters for the navigation badges."""
        return {'downloads_active': self.downloads.unfinished(),
                'new_episodes': len(self.library.new_episodes())}

    # ------------------------------------------------------------
    # Watch Later and followed series
    # ------------------------------------------------------------
    def set_watch_later(self, url, add):
        if add:
            self.library.add_watch_later(self.catalog_info(url))
        else:
            self.library.remove_watch_later(url)
        return {'watch_later': bool(add)}

    def set_follow(self, slug, follow):
        details = self.catalog_call('details', 'series', slug)
        if follow:
            # Episodes out today count as known: only later ones are "new".
            available = self.available_episodes(slug, details['seasons'])
            latest = max(((e['season'], e['number']) for e in available), default=(0, 0))
            self.library.follow(series_record(details), latest)
            logger.info(f"Following {details['title']}")
        else:
            self.library.unfollow(details['id'])
        return {'following': bool(follow)}

    def set_follow_auto(self, slug, auto):
        details = self.catalog_call('details', 'series', slug)
        self.library.set_follow_auto(details['id'], auto)
        return {'auto_download': bool(auto)}

    def available_episodes(self, slug, seasons):
        """Episodes with a video in the newest two seasons (new episodes only appear there)."""
        episodes = []
        for number, _count in seasons[-2:]:
            for episode in self.catalog_call('episodes', slug, number)['episodes']:
                if episode['has_video']:
                    episodes.append({**episode, 'season': number})
        return episodes

    def check_follows(self):
        """Look for new episodes of followed series; queue them where auto-download is on."""
        found = 0
        for follow in self.library.follows():
            try:
                details = self.catalog_call('details', 'series', follow['slug'])
                available = self.available_episodes(follow['slug'], details['seasons'])
            except Exception as error:
                logger.warning(f"Could not check {follow['title']}: {error}")
                continue
            known = (follow['last_season'], follow['last_number'])
            new = [e for e in available if (e['season'], e['number']) > known]
            latest = max([(e['season'], e['number']) for e in available] + [known])
            self.library.record_check(follow['series_id'], latest, new)
            if new:
                found += len(new)
                logger.info(f"{details['title']}: {len(new)} new episode(s)")
                if follow['auto_download']:
                    self.queue([{'url': e['url'], 'title': e['title']} for e in new
                                if not self.library.media_for_url(e['url'])])
        return {'found': found}

    def mark_new_seen(self, series_id=None):
        self.library.mark_new_seen(series_id=series_id)
        return {'ok': True}

    def library_view(self):
        return {'watch_later': self.library.watch_later(), 'follows': self.library.follows(),
                'new_episodes': self.library.new_episodes(), 'storage': self.storage_view(),
                'prefs': {name: self.pref(name) for name in DEFAULT_PREFS},
                'delete_choices': DELETE_AFTER_CHOICES}

    def set_prefs(self, auto_next_download=None, delete_watched_after_days=None):
        if auto_next_download is not None:
            self.prefs['auto_next_download'] = bool(auto_next_download)
        if delete_watched_after_days is not None:
            if int(delete_watched_after_days) not in DELETE_AFTER_CHOICES:
                raise ValueError('Unsupported clean-up period')
            self.prefs['delete_watched_after_days'] = int(delete_watched_after_days)
        settings.save(settings.SETTINGS_FILE, self.prefs)
        return {name: self.pref(name) for name in DEFAULT_PREFS}

    # ------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------
    def storage_view(self):
        items = self.library.media()
        folder = self.download_dir
        while not folder.exists() and folder != folder.parent:
            folder = folder.parent  # the download folder may not exist yet
        usage = shutil.disk_usage(folder)
        return {'items': items, 'folder': str(self.download_dir),
                'used': sum(m['size_bytes'] or 0 for m in items),
                'watched': sum(m['size_bytes'] or 0 for m in items if m['finished']),
                'free': usage.free, 'disk_total': usage.total}

    def delete_media(self, media_id):
        """Delete a downloaded video and its subtitles from disk and the library."""
        media = self.library.media_by_id(media_id)
        if not media:
            raise FileNotFoundError('This video is no longer in the library')
        if media['url'] and any(job.url == media['url'] and job.status not in FINISHED
                                for job in list(self.downloads.jobs.values())):
            raise ValueError('This video is still downloading')
        video = Path(media['file_path'])
        # Only the files this app writes: the video and the subtitles named after it.
        targets = {video, video.with_suffix('.vtt'), video.with_suffix('.srt')}
        if media['subtitle_path']:
            targets.add(Path(media['subtitle_path']))
        freed = 0
        for target in targets:
            if target.suffix.lower() in DELETABLE_SUFFIXES and target.parent == video.parent and target.is_file():
                size = target.stat().st_size
                try:
                    target.unlink()
                except PermissionError:
                    raise ValueError('The video is open in a player; close it and try again')
                freed += size
        self.library.remove_media(media_id)
        logger.info(f"Deleted {media['display_title']} ({freed / 2**20:.0f} MB)")
        return {'deleted': media['display_title'], 'freed': freed}

    def delete_watched(self, before=None):
        deleted = freed = 0
        for media in self.library.watched_media(before):
            try:
                freed += self.delete_media(media['id'])['freed']
                deleted += 1
            except (ValueError, OSError) as error:
                logger.warning(f"Kept {media['display_title']}: {error}")
        return {'deleted': deleted, 'freed': freed}

    def delete_expired_watched(self):
        days = self.pref('delete_watched_after_days')
        if days:
            result = self.delete_watched(before=time.time() - days * 86400)
            if result['deleted']:
                logger.info(f"Clean-up: deleted {result['deleted']} video(s) watched over {days} day(s) ago")

    # ------------------------------------------------------------
    # Downloads
    # ------------------------------------------------------------
    @staticmethod
    def job_dict(job):
        return {'id': job.id, 'url': job.url, 'title': job.title, 'status': job.status,
                'fraction': job.fraction, 'detail': job.detail}

    def downloads_view(self):
        return {'jobs': [self.job_dict(job) for job in list(self.downloads.jobs.values())],
                'parallel': self.downloads.limit, 'folder': str(self.download_dir),
                'library': self.library.media()}

    def queue(self, items):
        added = skipped = 0
        for item in items:
            url = (item.get('url') or '').strip()
            if url and self.downloads.add(url, item.get('title')):
                added += 1
            else:
                skipped += 1
        if added:
            logger.info(f'Queued {added} download(s); running up to {self.downloads.limit} at a time.')
        return {'added': added, 'skipped': skipped}

    def cancel(self, job_id):
        self.downloads.cancel(job_id)
        return {'ok': True}

    def retry_job(self, job_id):
        return {'ok': self.downloads.retry_job(job_id)}

    def clear_finished(self):
        return {'cleared': len(self.downloads.clear_finished())}

    def set_parallel(self, value):
        self.downloads.set_limit(min(max(int(value), 1), MAX_PARALLEL_DOWNLOADS))
        self.save_prefs()
        return {'parallel': self.downloads.limit}

    def choose_folder(self):
        if not self.choose_folder_dialog:
            raise ValueError('Folder picker is only available in the app window')
        folder = self.choose_folder_dialog(str(self.download_dir))
        return self.set_folder(folder) if folder else {'folder': str(self.download_dir)}

    def set_folder(self, folder):
        """Save new downloads to folder (absolute path), creating it if needed."""
        folder = Path(str(folder or '').strip().strip('"'))
        if not folder.is_absolute():
            raise ValueError('Use a full folder path, for example D:\\Videos\\MarTube')
        folder.mkdir(parents=True, exist_ok=True)
        self.download_dir = folder
        self.downloads.download_dir = self.download_dir
        self.catalog.download_dir = self.download_dir
        self.save_prefs()
        self.scan_library()
        logger.info(f'New downloads will be saved to {self.download_dir}')
        return {'folder': str(self.download_dir)}

    def open_folder(self):
        self.download_dir.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            os.startfile(self.download_dir)
        else:
            webbrowser.open(self.download_dir.as_uri())
        return {'ok': True}

    def save_prefs(self):
        self.prefs.update(parallel=self.downloads.limit,
                          download_dir=None if self.download_dir == settings.DEFAULT_DOWNLOAD_DIR
                          else str(self.download_dir))
        settings.save(settings.SETTINGS_FILE, self.prefs)

    def restore_queue(self):
        # Unfinished downloads from the last session start again (an HLS copy cannot resume).
        saved = settings.load(QUEUE_FILE, [])
        for url, title in saved:
            self.downloads.add(url, title)
        if saved:
            logger.info(f'Restored {len(saved)} unfinished download(s) from the last session.')

    def save_queue_loop(self):
        saved = None
        while True:
            self.queue_changed.wait()
            self.queue_changed.clear()
            if self.closing:
                return
            current = [list(job) for job in self.downloads.unfinished_jobs()]
            if current != saved:
                settings.save(QUEUE_FILE, current)
                saved = current
            time.sleep(1)  # coalesce bursts of progress updates

    def scan_library(self):
        """In the background, forget deleted files and add videos already in the download folder."""
        folder = self.download_dir

        def task():
            client = self.new_client(folder)
            try:
                removed = self.library.prune_missing()
                matched, unmatched = scan_folder(self.library, client, folder, self.images)
                if removed or matched or unmatched:
                    logger.info(f'Library: added {matched + unmatched} video(s) from {folder}; '
                                f'removed {removed} missing file(s).')
                cache_artwork(self.library, self.images)
            except Exception as error:
                logger.warning(f'Library scan failed: {error}')
            finally:
                client.close()

        threading.Thread(target=task, daemon=True).start()

    # ------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------
    def play(self, url=None, media_id=None):
        """Where the player gets the video: the downloaded file if there is one, else an HLS stream."""
        media = self.library.media_by_id(media_id) if media_id else self.library.media_for_url(url)
        if media_id and not media:
            raise FileNotFoundError('This video is no longer in the library')
        if media and Path(media['file_path']).exists():
            # Files without an IDLIX page keep their progress under a library key.
            url = media['url'] or f"media:{media['id']}"
            progress = self.library.progress(url)
            return {'kind': 'local', 'url': url, 'src': f"/media/{media['id']}",
                    'subtitle': f"/subtitle/local/{media['id']}" if media['subtitle_path'] else None,
                    'title': media['display_title'], 'series': media['title'] if media['kind'] == 'series' else None,
                    'resume': self.resume_position(progress),
                    'next': self.next_episode(media['slug'], media['season'], media['number'])
                    if media['kind'] == 'series' else None}

        url = url or (media and media['url'])
        self.library.mark_new_seen(url=url)
        if not url:
            raise FileNotFoundError('The video file is missing and it has no IDLIX page to stream from')
        with self.stream_lock:
            for attempt in range(STREAM_ATTEMPTS):
                if self.stream_client:
                    self.stream_client.close()
                client = self.stream_client = self.new_client(self.download_dir)
                try:
                    client.metadata(url)
                    stream = client.stream()
                    break
                except Exception as error:
                    if attempt == STREAM_ATTEMPTS - 1:
                        raise
                    logger.warning(f'Preparing the stream failed ({error}); trying once more')
            client.proxy.allowed_origins = set(self.origins)
            info = client.info
        self.playing[url] = info
        episode = info.get('episode')
        has_subtitle = bool((client.source or {}).get('subtitles'))
        return {'kind': 'stream', 'url': url, 'src': stream['m3u8_url'],
                'subtitle': '/subtitle/stream' if has_subtitle else None,
                'title': info['title'], 'series': info['series']['title'] if episode else None,
                'quality': stream.get('quality'), 'resume': self.resume_position(self.library.progress(url)),
                **self.session_quality(client),
                'next': self.next_episode(info['series']['slug'], episode['season'], episode['number'])
                if episode else None}

    @staticmethod
    def resume_position(progress):
        if progress and not progress['finished'] and progress['position'] > RESUME_AFTER_SECONDS:
            return progress['position']
        return 0

    def next_episode(self, slug, season, number):
        """The episode after season/number (or the first of the next season), if it has a video."""
        if not slug:
            return None
        try:
            for candidate_season, after in ((season, number), (season + 1, 0)):
                episodes = self.catalog_call('episodes', slug, candidate_season)['episodes']
                upcoming = [e for e in episodes if e['number'] > after and e['has_video']]
                if upcoming:
                    nxt = upcoming[0]
                    return {'url': nxt['url'], 'title': f"S{candidate_season}E{nxt['number']} · {nxt['name']}",
                            'file_title': nxt['title']}
        except Exception as error:
            logger.debug(f'No next episode for {slug} S{season}E{number}: {error}')
        return None

    def stream_subtitle(self):
        """Subtitle of the video being streamed, as WebVTT text."""
        with self.stream_lock:
            client = self.stream_client
            if not client:
                raise ValueError('Nothing is streaming')
            url = client.subtitle(download=False)['subtitle']
            response = client.request.get(url, timeout=20)
            response.raise_for_status()
            return as_webvtt(response.text)

    def local_subtitle(self, media_id):
        media = self.library.media_by_id(media_id)
        if not media or not media['subtitle_path']:
            raise FileNotFoundError('No subtitle for this video')
        return as_webvtt(Path(media['subtitle_path']).read_text(encoding='utf-8-sig', errors='replace'))

    def save_progress(self, url, position, duration):
        was_finished = (self.library.progress(url) or {}).get('finished')
        self.library.set_progress(url, float(position), float(duration) if duration else None,
                                  info=self.playing.get(url))
        if not was_finished and self.library.progress(url)['finished']:
            threading.Thread(target=self.on_finished, args=(url,), daemon=True).start()
        return {'ok': True}

    def episode_of(self, url):
        """(series slug, season, number) of an episode page, from the player or the library."""
        info = self.playing.get(url)
        if info and info.get('episode'):
            return info['series']['slug'], info['episode']['season'], info['episode']['number']
        media = self.library.media_for_url(url)
        if media and media['kind'] == 'series' and media['season']:
            return media['slug'], media['season'], media['number']
        return None

    def on_finished(self, url):
        """A video was watched to the end: tidy Watch Later and download the next episode if wanted."""
        self.library.remove_watch_later(url)
        self.library.mark_new_seen(url=url)
        episode = self.episode_of(url)
        if not (episode and self.pref('auto_next_download')):
            return
        upcoming = self.next_episode(*episode)
        if upcoming and not self.library.media_for_url(upcoming['url']):
            logger.info(f"Auto-download: next episode {upcoming['title']}")
            self.queue([{'url': upcoming['url'], 'title': upcoming.get('file_title')}])

    # ------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------
    def shutdown(self, wait_seconds=15):
        """Remember unfinished downloads, stop them and close network sessions."""
        self.closing = True
        self.stop_checks.set()
        self.queue_changed.set()
        settings.save(QUEUE_FILE, [list(job) for job in self.downloads.unfinished_jobs()])
        self.downloads.cancel_all()
        deadline = time.monotonic() + wait_seconds
        while self.downloads.unfinished() and time.monotonic() < deadline:
            time.sleep(0.2)  # let workers stop ffmpeg and delete part files
        for client in (self.stream_client, self.catalog):
            if client:
                client.close()


class UserError(ValueError):
    """A problem the user can fix (shown as-is, with an optional machine-readable code)."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def as_webvtt(text):
    """Browsers only accept WebVTT subtitles; convert SRT timestamps and add the header."""
    text = text.lstrip('﻿')
    if text.lstrip().startswith('WEBVTT'):
        return text
    lines = []
    for line in text.replace('\r\n', '\n').split('\n'):
        if '-->' in line:
            line = line.replace(',', '.')
        lines.append(line)
    return 'WEBVTT\n\n' + '\n'.join(lines)
