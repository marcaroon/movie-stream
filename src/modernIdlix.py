"""Client for the current IDLIX API and its guest playback sessions."""

import re
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import m3u8
from curl_cffi import requests
from loguru import logger


BASE = 'https://z2.idlixku.com/'


def safe_name(title):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title).strip(' .')[:160]
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', name, re.I):
        name = '_' + name
    return name or 'video'


def clock(seconds):
    seconds = int(max(0, seconds))
    return f'{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'


def signed_url(url, master):
    """Carry the issued session token to child playlists and CDN segments."""
    parts = urlsplit(urljoin(master, url))
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('Invalid media URL from server')
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    token = dict(parse_qsl(urlsplit(master).query)).get('t')
    if token:
        query['t'] = token
    return urlunsplit(parts._replace(query=urlencode(query)))


def episode_title(series, season, number, name):
    """Display name of an episode; also the base of its video and subtitle file names."""
    return f'{series} S{season}E{number} - {name}'


def title_info(item, kind):
    """The parts of an IDLIX movie/series record the local library keeps."""
    date = item.get('releaseDate') or item.get('firstAirDate') or ''
    return {'id': item['id'], 'kind': kind, 'slug': item.get('slug'), 'title': item['title'],
            'year': date[:4], 'overview': item.get('overview'), 'poster_path': item.get('posterPath'),
            'backdrop_path': item.get('backdropPath'), 'logo_path': item.get('logoPath'),
            'runtime': item.get('runtime')}


def catalog_item(entry):
    """Normalise a homepage or search entry into a poster card; None for unsupported kinds."""
    item = entry.get('content', entry)
    kind = entry.get('contentType') or item.get('contentType')
    if kind == 'movie':
        return {'type': 'movie', 'id': item['id'], 'slug': item['slug'], 'title': item['title'],
                'year': (item.get('releaseDate') or '')[:4], 'poster_path': item.get('posterPath'),
                'backdrop_path': item.get('backdropPath'), 'logo_path': item.get('logoPath'),
                'overview': item.get('overview'), 'url': BASE + f"movie/{item['slug']}"}
    if kind in ('tv_series', 'series'):
        return {'type': 'series', 'id': item['id'], 'slug': item['slug'], 'title': item['title'],
                'year': (item.get('firstAirDate') or '')[:4], 'poster_path': item.get('posterPath'),
                'backdrop_path': item.get('backdropPath'), 'logo_path': item.get('logoPath'),
                'overview': item.get('overview'), 'url': None}
    if kind == 'episode' and item.get('series') and item.get('season'):
        series, season, number = item['series'], item['season']['seasonNumber'], item['episodeNumber']
        return {'type': 'episode', 'id': item['id'], 'slug': series['slug'],
                'title': f"{series['title']} S{season}E{number}", 'episode_name': item.get('name'),
                'year': (series.get('firstAirDate') or '')[:4], 'poster_path': series.get('posterPath'),
                'still_path': item.get('stillPath'), 'season': season, 'number': number,
                'url': BASE + f"series/{series['slug']}/season/{season}/episode/{number}"}
    return None


def season_list(series):
    """[(season number, episode count)] of a series record and the season to show first."""
    seasons = sorted((s['seasonNumber'], s.get('episodeCount') or 0) for s in series.get('seasons', []))
    default = series.get('defaultSeason')
    default = default.get('seasonNumber') if isinstance(default, dict) else default
    numbers = [number for number, _ in seasons]
    return {'seasons': seasons, 'default': default if default in numbers else (numbers[0] if numbers else None)}


class ModernIdlix:
    def __init__(self, download_dir='.', account=None):
        self.request = requests.Session(impersonate='chrome124', headers={
            'Origin': BASE.rstrip('/'), 'Referer': BASE,
        })
        self.download_dir = Path(download_dir)
        self.account = account  # IdlixAccount: when signed in, playback gets the member quality
        self.content_id = None
        self.content_type = None
        self.title = None
        self.source = None
        self.claim = None
        self.proxy = None
        self.process = None
        self.cancelled = False
        self.info = None  # library metadata of the loaded title
        self.lock = threading.RLock()

    def api(self, path, body=None):
        method = self.request.get if body is None else self.request.post
        signed_in = bool(self.account and self.account.attach(self.request))
        response = method(BASE + 'api/' + path, timeout=20,
                          **({'json': body} if body is not None else {}))
        if response.status_code == 401 and signed_in and self.account.refresh():
            # The access cookie expired early: renew it once and repeat the request.
            self.account.attach(self.request)
            response = method(BASE + 'api/' + path, timeout=20,
                              **({'json': body} if body is not None else {}))
        if response.status_code != 200:
            try:
                detail = response.json().get('message') or response.json().get('error')
            except ValueError:
                detail = 'Server did not return JSON'
            raise ValueError(f'IDLIX HTTP {response.status_code}: {detail}')
        return response.json()

    def home(self):
        data = self.api('homepage')
        items = []
        seen = set()
        for module in data.get('above', []) + data.get('below', []):
            if module['type'] not in ('featured', 'latest_movies', 'latest_episodes'):
                continue
            for entry in module.get('data', []):
                item = entry.get('content', entry)
                kind = entry.get('contentType')
                if kind == 'movie':
                    path = f"movie/{item['slug']}"
                    title = item['title']
                    date = item.get('releaseDate') or ''
                    poster = item.get('posterPath')
                elif kind == 'episode':
                    series = item['series']
                    season, episode = item['season']['seasonNumber'], item['episodeNumber']
                    path = f"series/{series['slug']}/season/{season}/episode/{episode}"
                    title = f"{series['title']} S{season}E{episode}"
                    date = series.get('firstAirDate') or ''
                    poster = series.get('posterPath')
                else:
                    continue  # Series landing pages require an episode choice.
                if path in seen:
                    continue
                seen.add(path)
                items.append({'url': BASE + path, 'title': title, 'year': date[:4],
                              'type': kind, 'poster': self.image_url(poster)})
        if not items:
            raise ValueError('No playable titles found in the homepage response')
        return {'status': True, 'featured_movie': items}

    def search(self, query, page=1):
        data = self.api('search?' + urlencode({'q': query, 'page': page}))
        items = [item for item in map(catalog_item, data.get('results', [])) if item and item['type'] != 'episode']
        return {'status': True, 'results': items, 'total': data.get('total', len(items))}

    def browse(self):
        """Homepage rows (Featured, Trending, Recently Added ...) as {'title', 'items'} lists."""
        data = self.api('homepage')
        rows = []
        for module in data.get('above', []) + data.get('below', []):
            items, seen = [], set()
            for item in map(catalog_item, module.get('data') or []):
                key = (item and (item['type'], item['slug'], item.get('season'), item.get('number')))
                if item and key not in seen:
                    seen.add(key)
                    items.append(item)
            if items and module.get('title'):
                rows.append({'title': module['title'], 'items': items})
        if not rows:
            raise ValueError('The IDLIX homepage returned no titles')
        return {'status': True, 'rows': rows}

    def details(self, kind, slug):
        """Movie or series page: metadata, genres and (for series) its seasons."""
        if kind == 'movie':
            data = self.api(f'movies/{slug}')
            item = data.get('movie', data)
            info = {**title_info(item, 'movie'), 'url': BASE + f'movie/{slug}', 'has_video': bool(item.get('hasVideo'))}
        elif kind == 'series':
            item = self.api(f'series/{slug}')
            info = {**title_info(item, 'series'), **season_list(item)}
        else:
            raise ValueError(f'Unknown title type: {kind}')
        info.update(genres=[g['name'] for g in item.get('genres') or [] if isinstance(g, dict) and g.get('name')],
                    rating=item.get('voteAverage'), tagline=item.get('tagline'))
        return {'status': True, **info}

    def seasons(self, slug):
        data = self.api(f'series/{slug}')
        return {'status': True, 'title': data['title'], **season_list(data)}

    def episodes(self, slug, season):
        data = self.api(f'series/{slug}/season/{season}')
        series = data['series']['title']
        episodes = []
        for item in sorted(data['season'].get('episodes', []), key=lambda e: e['episodeNumber']):
            number = item['episodeNumber']
            episodes.append({
                'number': number, 'name': item.get('name') or f'Episode {number}',
                'air_date': (item.get('airDate') or '')[:10],
                'has_video': bool(item.get('hasVideo')) and item.get('isPublished', True),
                'url': BASE + f'series/{slug}/season/{season}/episode/{number}',
                'title': episode_title(series, season, number, item.get('name') or f'Episode {number}'),
                'id': item.get('id'), 'overview': item.get('overview'), 'still_path': item.get('stillPath'),
                'runtime': item.get('runtime'),
            })
        return {'status': True, 'series': series, 'episodes': episodes}

    @staticmethod
    def image_url(path):
        return urljoin('https://image.tmdb.org/t/p/w500/', (path or '').lstrip('/')) if path else ''

    def metadata(self, url):
        self.close()
        self.content_id = self.content_type = self.title = self.source = self.claim = self.info = None
        self.cancelled = False
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.netloc != 'z2.idlixku.com':
            raise ValueError('Use an HTTPS movie or episode URL from z2.idlixku.com')
        episode = re.fullmatch(r'/series/([\w-]+)/season/([1-9]\d*)/episode/([1-9]\d*)/?', parts.path)
        movie = re.fullmatch(r'/movie/([\w-]+)/?', parts.path)
        if episode:
            slug, season, number = episode.groups()
            data = self.api(f'series/{slug}/season/{season}/episode/{number}')
            item = data['episode']
            title = episode_title(data['series']['title'], season, number, item['name'])
            poster = data['series'].get('posterPath')
            kind = 'episode'
            self.info = {'kind': 'episode', 'url': url, 'title': title,
                         'series': title_info(data['series'], 'series'),
                         'episode': {'id': item['id'], 'season': int(season), 'number': int(number),
                                     'name': item.get('name'), 'overview': item.get('overview'),
                                     'still_path': item.get('stillPath'), 'air_date': item.get('airDate'),
                                     'runtime': item.get('runtime')}}
        elif movie:
            data = self.api(f'movies/{movie[1]}')
            item = data.get('movie', data)
            title, poster, kind = item['title'], item.get('posterPath'), 'movie'
            self.info = {'kind': 'movie', 'url': url, 'title': title, 'movie': title_info(item, 'movie')}
        else:
            raise ValueError('Use a movie URL or a complete /season/1/episode/3 URL, not a series landing page')
        if not item.get('hasVideo'):
            raise ValueError('This title has no available video on IDLIX')
        self.content_id, self.content_type, self.title = item['id'], kind, title
        return {'status': True, 'video_id': self.content_id, 'video_name': title,
                'poster': self.image_url(poster)}

    def playback(self):
        with self.lock:
            if not self.content_id:
                raise ValueError('Load a movie or episode first')
            data = self.api(f'watch/play-info/{self.content_type}/{self.content_id}')
            for _ in range(12):
                if data.get('kind') != 'gate':
                    break
                delay = max(0, (data['unlockAt'] - data['serverNow']) / 1000)
                if delay > 60:
                    raise ValueError('Server requested a wait longer than 60 seconds; try again later')
                logger.info(f'Waiting {delay:.0f}s for the IDLIX playback session...')
                time.sleep(delay + 0.2)
                data = self.api('watch/session/claim', {'gateToken': data['gateToken']})
            if data.get('kind') != 'pentos':
                raise ValueError('IDLIX did not provide a supported playback session')
            self.claim = data
            logger.info(f"Playback session: {data.get('viewerTier', 'unknown')} tier, up to {data.get('maxHeight')}p")
            self.redeem()

    def redeem(self):
        target = urlsplit(self.claim['redeemUrl'])
        if target.scheme != 'https' or target.username or target.password:
            raise ValueError('Invalid playback endpoint')
        response = self.request.post(self.claim['redeemUrl'], json={
            'claim': self.claim['claim'], 'mode': 'browser',
        }, timeout=20)
        if response.status_code != 200:
            raise ValueError(f'Playback server HTTP {response.status_code}')
        source = response.json()
        if source.get('code') != 'ok' or not source.get('url'):
            raise ValueError('Playback server did not return a stream')
        signed_url(source['url'], source['url'])
        self.source = source
        # TTL uses a monotonic clock, independent of the computer's date/time.
        self.refresh_at = time.monotonic() + max(1, source['ttlSeconds'] - 60)

    def current_source(self):
        with self.lock:
            if self.source is None:
                self.playback()
            elif time.monotonic() >= self.refresh_at:
                self.claim = self.api('watch/session/refresh-claim', {
                    'renewalToken': self.claim['renewalToken'],
                })
                self.redeem()
            return self.source

    def stream(self):
        self.current_source()
        if self.proxy is None:
            self.proxy = MediaProxy(self)
        self.proxy.duration = 0
        self.proxy.playlist(None)
        url = self.proxy.master_url
        return {'status': True, 'm3u8_url': url, 'variant_playlist': [],
                'is_variant_playlist': False, 'quality': self.proxy.quality}

    def subtitle(self, download=True):
        source = self.current_source()
        subtitles = source.get('subtitles') or []
        if not subtitles:
            return {'status': False, 'message': 'Subtitle not available'}
        track = next((s for s in subtitles if s['lang'] == 'id'), subtitles[0])
        url = signed_url(track['path'], source['url'])
        if not download:
            return {'status': True, 'subtitle': url}
        response = self.request.get(url, timeout=20)
        response.raise_for_status()
        extension = '.vtt' if response.text.lstrip('\ufeff').startswith('WEBVTT') else '.srt'
        path = self.output_path().with_suffix(extension)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return {'status': True, 'subtitle': str(path)}

    def output_path(self, title=None):
        return self.download_dir / (safe_name(title or self.title) + '.mp4')

    def download(self, progress=None):
        url = self.stream()['m3u8_url']
        path = self.output_path()
        if path.exists():
            raise ValueError(f'File already exists: {path.name}')
        partial = path.with_suffix('.part.mp4')
        if partial.exists():
            raise ValueError(f'An unfinished download already exists: {partial.name}')
        if self.cancelled:
            raise ValueError('Download cancelled')
        self.download_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f'Downloading video and audio to {path.name} ...')
        process = self.process = subprocess.Popen([
            'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
            '-progress', 'pipe:1', '-nostats',
            '-allowed_extensions', 'ALL', '-extension_picky', '0',
            '-i', url, '-map', '0:v:0', '-map', '0:a:0?', '-c', 'copy',
            '-movflags', '+faststart', str(partial),
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            if self.cancelled:  # cancel() arrived while ffmpeg was starting
                process.terminate()
            # Drain stderr separately so a chatty ffmpeg cannot block the progress pipe.
            errors = []
            reader = threading.Thread(target=lambda: errors.append(process.stderr.read()), daemon=True)
            reader.start()
            stats = {}
            for line in process.stdout:
                key, _, value = line.strip().partition('=')
                stats[key] = value
                if key == 'progress' and progress:
                    progress(*self.describe_progress(stats))
            process.wait()
            reader.join(timeout=5)
            if self.cancelled:
                raise ValueError('Download cancelled')
            if process.returncode:
                detail = ''.join(errors).strip()[-300:]
                raise ValueError(f'FFmpeg failed (exit {process.returncode}): {detail}')
            partial.rename(path)
        except BaseException:
            # A copied HLS stream cannot be resumed, and a leftover part file would block a retry.
            process.kill()
            process.wait()
            partial.unlink(missing_ok=True)
            raise
        finally:
            self.process = None
        return {'status': True, 'path': str(path.resolve())}

    def cancel(self):
        self.cancelled = True
        process = self.process
        if process and process.poll() is None:
            process.terminate()

    def describe_progress(self, stats):
        """Turn ffmpeg -progress fields into (fraction or None, status text)."""
        try:
            done = int(stats.get('out_time_us', '')) / 1_000_000
        except ValueError:
            done = 0
        try:
            size = int(stats.get('total_size', '')) / 1024 / 1024
        except ValueError:
            size = 0
        try:
            speed = float(stats.get('speed', '').rstrip('x'))
        except ValueError:
            speed = 0
        total = self.proxy.duration if self.proxy else 0
        parts = [f'{size:.1f} MB']
        if total:
            fraction = min(done / total, 1.0)
            parts.insert(0, f'{fraction * 100:.1f}%')
            parts.append(f'{clock(done)} / {clock(total)}')
            if speed > 0:
                parts.append(f'{speed:.1f}x · ETA {clock((total - done) / speed)}')
        else:
            fraction = None
            parts.append(clock(done))
        return fraction, ' · '.join(parts)

    def close(self):
        if self.proxy:
            self.proxy.close()
            self.proxy = None


class MediaProxy:
    """Loopback HLS adapter: preserve audio, apply guest quality, renew tokens."""

    def __init__(self, client):
        self.client = client
        self.urls = {}
        self.routes = {}
        self.lock = threading.Lock()
        self.prefix = '/' + uuid.uuid4().hex
        self.quality = 'source'
        self.duration = 0
        # The app's player page (another loopback port) may read this proxy; nothing else may.
        self.allowed_origins = set()
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def end_headers(self):
                origin = self.headers.get('Origin')
                if origin and origin in proxy.allowed_origins:
                    self.send_header('Access-Control-Allow-Origin', origin)
                    self.send_header('Vary', 'Origin')
                super().end_headers()

            def do_GET(self):
                try:
                    if self.path == proxy.prefix + '/master.m3u8':
                        data = proxy.playlist(None)
                    elif self.path in proxy.routes:
                        url, playlist = proxy.routes[self.path]
                        if playlist:
                            data = proxy.playlist(url)
                        else:
                            source = client.current_source()
                            self.send_response(302)
                            self.send_header('Location', signed_url(url, source['url']))
                            self.end_headers()
                            return
                    else:
                        self.send_error(404)
                        return
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as error:
                    logger.error(f'Media request failed: {type(error).__name__}')
                    self.send_error(502, 'Unable to load media from IDLIX')

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.master_url = self.origin + self.prefix + '/master.m3u8'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def route(self, url, playlist):
        key = (url, playlist)
        with self.lock:
            if key not in self.urls:
                path = f'{self.prefix}/{len(self.urls)}' + ('.m3u8' if playlist else '.mp4')
                self.urls[key] = self.origin + path
                self.routes[path] = key
            return self.urls[key]

    def playlist(self, url):
        source = self.client.current_source()
        remote = signed_url(url or source['url'], source['url'])
        response = self.client.request.get(remote, timeout=20)
        response.raise_for_status()
        if not response.text.lstrip().startswith('#EXTM3U'):
            raise ValueError('Expected an HLS playlist')
        parsed = m3u8.loads(response.text, uri=remote)
        if parsed.is_variant:
            if not parsed.playlists:
                raise ValueError('IDLIX returned no video streams for this title')
            limit = self.client.claim.get('maxHeight')
            # Some masters list variants without a RESOLUTION; the server already decided which
            # variants this session may see, so only a stated height above the limit rules one out.
            candidates = [p for p in parsed.playlists if not limit or not p.stream_info.resolution
                          or p.stream_info.resolution[1] <= limit]
            # Keep the audio group and choose the best quality allowed; if every labelled variant is
            # above the limit, take the smallest rather than failing (IDLIX enforces the limit anyway).
            chosen = (max(candidates, key=lambda p: p.stream_info.bandwidth or 0) if candidates
                      else min(parsed.playlists, key=lambda p: p.stream_info.bandwidth or 0))
            if chosen.stream_info.resolution:
                self.quality = '{}x{}'.format(*chosen.stream_info.resolution)
            parsed.playlists[:] = [chosen]
            for media in parsed.media:
                if media.uri:
                    media.uri = self.route(urljoin(remote, media.uri), True)
            chosen.uri = self.route(urljoin(remote, chosen.uri), True)
        else:
            # Video and audio playlists cover the same runtime; keep the longest.
            self.duration = max(self.duration, sum(s.duration or 0 for s in parsed.segments))
            for segment in parsed.segments:
                segment.uri = self.route(urljoin(remote, segment.uri), False)
                if segment.init_section:
                    original = segment.init_section.uri
                    if not original.startswith(self.origin + '/'):
                        segment.init_section.uri = self.route(urljoin(remote, original), False)
            for key in parsed.keys:
                if key and key.uri:
                    key.uri = self.route(urljoin(remote, key.uri), False)
        return parsed.dumps().encode('utf-8')

    def close(self):
        self.server.shutdown()
        self.server.server_close()
