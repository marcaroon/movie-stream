"""
Local library: what has been downloaded, watch progress, the Watch Later list
and followed series with their new episodes.

Stored in SQLite so it works offline. Titles and episodes keep the IDLIX
metadata (overview, poster/backdrop/still image paths) needed to show the
library without a network connection.
"""

import sqlite3
import threading
import time
from pathlib import Path

SCHEMA_VERSION = 3
# Watching this much of a video (or reaching the last 2 minutes) marks it finished.
FINISHED_FRACTION = 0.92
FINISHED_REMAINING_SECONDS = 120

SCHEMA = '''
CREATE TABLE titles (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('movie', 'series')),
    slug TEXT,
    title TEXT NOT NULL,
    year TEXT,
    overview TEXT,
    poster_path TEXT,
    backdrop_path TEXT,
    runtime INTEGER,
    updated_at REAL NOT NULL
);
CREATE TABLE episodes (
    id TEXT PRIMARY KEY,
    series_id TEXT NOT NULL REFERENCES titles(id),
    season INTEGER NOT NULL,
    number INTEGER NOT NULL,
    name TEXT,
    overview TEXT,
    still_path TEXT,
    air_date TEXT,
    runtime INTEGER,
    UNIQUE (series_id, season, number)
);
CREATE TABLE media (
    id INTEGER PRIMARY KEY,
    url TEXT UNIQUE,                      -- IDLIX page; NULL for files that could not be matched
    title_id TEXT REFERENCES titles(id),
    episode_id TEXT REFERENCES episodes(id),
    display_title TEXT NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    subtitle_path TEXT,
    size_bytes INTEGER,
    added_at REAL NOT NULL
);
CREATE TABLE progress (
    url TEXT PRIMARY KEY,
    position REAL NOT NULL,
    duration REAL,
    finished INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE TABLE watch_later (
    url TEXT PRIMARY KEY,
    title_id TEXT REFERENCES titles(id),
    episode_id TEXT REFERENCES episodes(id),
    display_title TEXT NOT NULL,
    added_at REAL NOT NULL
);
'''

# SQL that upgrades a database from the previous version to this one.
MIGRATIONS = {
    # Progress remembers which title it belongs to, so streamed videos appear in Continue Watching.
    2: '''
        ALTER TABLE progress ADD COLUMN title_id TEXT REFERENCES titles(id);
        ALTER TABLE progress ADD COLUMN episode_id TEXT REFERENCES episodes(id);
        ALTER TABLE progress ADD COLUMN display_title TEXT;
    ''',
    # Followed series and the new episodes found for them.
    3: '''
        CREATE TABLE follows (
            series_id TEXT PRIMARY KEY REFERENCES titles(id),
            slug TEXT NOT NULL,
            last_season INTEGER NOT NULL DEFAULT 0,   -- newest available episode already known
            last_number INTEGER NOT NULL DEFAULT 0,
            auto_download INTEGER NOT NULL DEFAULT 0,
            checked_at REAL,
            added_at REAL NOT NULL
        );
        CREATE TABLE new_episodes (
            url TEXT PRIMARY KEY,
            series_id TEXT NOT NULL REFERENCES titles(id),
            season INTEGER NOT NULL,
            number INTEGER NOT NULL,
            name TEXT,
            still_path TEXT,
            found_at REAL NOT NULL,
            seen INTEGER NOT NULL DEFAULT 0
        );
    ''',
}

MEDIA_QUERY = '''
SELECT m.id, m.url, m.display_title, m.file_path, m.subtitle_path, m.size_bytes, m.added_at,
       t.id AS title_id, t.kind, t.slug, t.title, t.year, t.overview, t.poster_path, t.backdrop_path,
       e.season, e.number, e.name AS episode_name, e.still_path, e.overview AS episode_overview,
       p.position, p.duration, p.finished, p.updated_at AS watched_at
FROM media m
LEFT JOIN titles t ON t.id = m.title_id
LEFT JOIN episodes e ON e.id = m.episode_id
LEFT JOIN progress p ON p.url = m.url
'''


class Library:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection shared by GUI and download threads, serialised by a lock.
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock, self.db:
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA foreign_keys=ON')
            version = self.db.execute('PRAGMA user_version').fetchone()[0]
            if version == 0:
                self.db.executescript(SCHEMA)
                version = 1
            # Upgrade older databases step by step, keeping their data.
            for target in range(version + 1, SCHEMA_VERSION + 1):
                self.db.executescript(MIGRATIONS[target])
            self.db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    def close(self):
        with self.lock:
            self.db.close()

    # ------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------
    def save_info(self, info):
        """Store the movie/series (and episode) described by ModernIdlix.info; returns their ids."""
        with self.lock, self.db:
            parent = info.get('series') or info.get('movie')
            self.db.execute('''
                INSERT INTO titles (id, kind, slug, title, year, overview, poster_path, backdrop_path, runtime, updated_at)
                VALUES (:id, :kind, :slug, :title, :year, :overview, :poster_path, :backdrop_path, :runtime, :now)
                ON CONFLICT (id) DO UPDATE SET slug=excluded.slug, title=excluded.title, year=excluded.year,
                    overview=excluded.overview, poster_path=excluded.poster_path,
                    backdrop_path=excluded.backdrop_path, runtime=excluded.runtime, updated_at=excluded.updated_at
            ''', {**parent, 'now': time.time()})
            episode = info.get('episode')
            if episode:
                self.db.execute('''
                    INSERT INTO episodes (id, series_id, season, number, name, overview, still_path, air_date, runtime)
                    VALUES (:id, :series_id, :season, :number, :name, :overview, :still_path, :air_date, :runtime)
                    ON CONFLICT (id) DO UPDATE SET name=excluded.name, overview=excluded.overview,
                        still_path=excluded.still_path, air_date=excluded.air_date, runtime=excluded.runtime
                ''', {**episode, 'series_id': parent['id']})
            return parent['id'], episode['id'] if episode else None

    # ------------------------------------------------------------
    # Downloaded media
    # ------------------------------------------------------------
    def add_media(self, file_path, info=None, display_title=None, subtitle_path=None):
        """Record a downloaded video; info may be None for a file that could not be matched."""
        file_path = Path(file_path).resolve()
        with self.lock, self.db:
            title_id, episode_id = self.save_info(info) if info else (None, None)
            url = info['url'] if info else None
            if url:
                # The same title saved at a new location replaces its old record.
                self.db.execute('DELETE FROM media WHERE url = ? AND file_path != ?', (url, str(file_path)))
            self.db.execute('''
                INSERT INTO media (url, title_id, episode_id, display_title, file_path, subtitle_path, size_bytes, added_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (file_path) DO UPDATE SET url=excluded.url, title_id=excluded.title_id,
                    episode_id=excluded.episode_id, display_title=excluded.display_title,
                    subtitle_path=COALESCE(excluded.subtitle_path, media.subtitle_path),
                    size_bytes=excluded.size_bytes
            ''', (url, title_id, episode_id, display_title or (info and info['title']) or file_path.stem,
                  str(file_path), str(Path(subtitle_path).resolve()) if subtitle_path else None,
                  file_path.stat().st_size if file_path.exists() else None, time.time()))

    def media(self):
        """Every downloaded video, newest first, with metadata and watch progress."""
        with self.lock:
            return [dict(row) for row in self.db.execute(MEDIA_QUERY + ' ORDER BY m.added_at DESC')]

    def media_for_url(self, url):
        with self.lock:
            row = self.db.execute(MEDIA_QUERY + ' WHERE m.url = ?', (url,)).fetchone()
            return dict(row) if row else None

    def known_files(self):
        with self.lock:
            return {row[0] for row in self.db.execute('SELECT file_path FROM media')}

    def remove_media(self, media_id):
        with self.lock, self.db:
            self.db.execute('DELETE FROM media WHERE id = ?', (media_id,))

    def prune_missing(self):
        """Forget videos whose file was deleted or moved outside the app; returns how many."""
        with self.lock, self.db:
            gone = [row['id'] for row in self.db.execute('SELECT id, file_path FROM media')
                    if not Path(row['file_path']).exists()]
            self.db.executemany('DELETE FROM media WHERE id = ?', [(media_id,) for media_id in gone])
            return len(gone)

    # ------------------------------------------------------------
    # Watch progress
    # ------------------------------------------------------------
    def set_progress(self, url, position, duration=None, info=None):
        """Remember how far a video was watched; info (ModernIdlix.info) links it to its title."""
        finished = bool(duration) and (position >= duration * FINISHED_FRACTION
                                       or duration - position <= FINISHED_REMAINING_SECONDS)
        with self.lock, self.db:
            title_id, episode_id = self.save_info(info) if info else (None, None)
            self.db.execute('''
                INSERT INTO progress (url, position, duration, finished, updated_at, title_id, episode_id, display_title)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (url) DO UPDATE SET position=excluded.position,
                    duration=COALESCE(excluded.duration, progress.duration),
                    finished=excluded.finished, updated_at=excluded.updated_at,
                    title_id=COALESCE(excluded.title_id, progress.title_id),
                    episode_id=COALESCE(excluded.episode_id, progress.episode_id),
                    display_title=COALESCE(excluded.display_title, progress.display_title)
            ''', (url, position, duration, int(finished), time.time(), title_id, episode_id,
                  info['title'] if info else None))

    def progress(self, url):
        with self.lock:
            row = self.db.execute('SELECT * FROM progress WHERE url = ?', (url,)).fetchone()
            return dict(row) if row else None

    def continue_watching(self, limit=20):
        """Started but unfinished videos, most recently watched first, with their artwork."""
        with self.lock:
            return [dict(row) for row in self.db.execute('''
                SELECT p.url, p.position, p.duration, p.updated_at,
                       COALESCE(p.display_title, m.display_title, p.url) AS display_title,
                       t.kind, t.slug, t.title, t.poster_path, t.backdrop_path,
                       e.season, e.number, e.name AS episode_name, e.still_path, m.id AS media_id
                FROM progress p
                LEFT JOIN media m ON m.url = p.url
                LEFT JOIN titles t ON t.id = COALESCE(p.title_id, m.title_id)
                LEFT JOIN episodes e ON e.id = COALESCE(p.episode_id, m.episode_id)
                WHERE p.finished = 0 AND p.position > 0
                ORDER BY p.updated_at DESC LIMIT ?''', (limit,))]

    def states(self, urls):
        """{url: {'media_id', 'position', 'duration', 'finished'}} for the given page URLs."""
        urls = list(urls)
        if not urls:
            return {}
        marks = ','.join('?' * len(urls))
        with self.lock:
            states = {url: {'media_id': None, 'position': 0, 'duration': None, 'finished': False} for url in urls}
            for row in self.db.execute(f'SELECT id, url FROM media WHERE url IN ({marks})', urls):
                states[row['url']]['media_id'] = row['id']
            for row in self.db.execute(f'SELECT * FROM progress WHERE url IN ({marks})', urls):
                states[row['url']].update(position=row['position'], duration=row['duration'],
                                          finished=bool(row['finished']))
            return states

    def media_by_id(self, media_id):
        with self.lock:
            row = self.db.execute(MEDIA_QUERY + ' WHERE m.id = ?', (media_id,)).fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------
    # Watch Later
    # ------------------------------------------------------------
    def add_watch_later(self, info):
        with self.lock, self.db:
            title_id, episode_id = self.save_info(info)
            self.db.execute('''
                INSERT INTO watch_later (url, title_id, episode_id, display_title, added_at) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (url) DO NOTHING
            ''', (info['url'], title_id, episode_id, info['title'], time.time()))

    def remove_watch_later(self, url):
        with self.lock, self.db:
            self.db.execute('DELETE FROM watch_later WHERE url = ?', (url,))

    def watch_later(self):
        with self.lock:
            return [dict(row) for row in self.db.execute('''
                SELECT w.url, w.display_title, w.added_at, t.kind, t.slug, t.title, t.poster_path,
                       t.backdrop_path, e.season, e.number, e.name AS episode_name, e.still_path,
                       m.id AS media_id, m.file_path
                FROM watch_later w
                LEFT JOIN titles t ON t.id = w.title_id
                LEFT JOIN episodes e ON e.id = w.episode_id
                LEFT JOIN media m ON m.url = w.url
                ORDER BY w.added_at DESC''')]

    def in_watch_later(self, urls):
        urls = list(urls)
        if not urls:
            return set()
        with self.lock:
            rows = self.db.execute(f"SELECT url FROM watch_later WHERE url IN ({','.join('?' * len(urls))})", urls)
            return {row['url'] for row in rows}

    # ------------------------------------------------------------
    # Followed series
    # ------------------------------------------------------------
    def follow(self, series, latest):
        """Follow a series (title_info dict); episodes up to latest=(season, number) count as known."""
        with self.lock, self.db:
            self.save_info({'series': series})
            self.db.execute('''
                INSERT INTO follows (series_id, slug, last_season, last_number, checked_at, added_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (series_id) DO NOTHING
            ''', (series['id'], series['slug'], latest[0], latest[1], time.time(), time.time()))

    def unfollow(self, series_id):
        with self.lock, self.db:
            self.db.execute('DELETE FROM new_episodes WHERE series_id = ?', (series_id,))
            self.db.execute('DELETE FROM follows WHERE series_id = ?', (series_id,))

    def set_follow_auto(self, series_id, auto):
        with self.lock, self.db:
            self.db.execute('UPDATE follows SET auto_download = ? WHERE series_id = ?', (int(bool(auto)), series_id))

    def follows(self):
        """Followed series with artwork and how many new episodes are unseen."""
        with self.lock:
            return [dict(row) for row in self.db.execute('''
                SELECT f.series_id, f.slug, f.last_season, f.last_number, f.auto_download, f.checked_at,
                       t.title, t.year, t.poster_path, t.backdrop_path,
                       (SELECT COUNT(*) FROM new_episodes n WHERE n.series_id = f.series_id AND n.seen = 0) AS unseen
                FROM follows f JOIN titles t ON t.id = f.series_id
                ORDER BY unseen DESC, t.title''')]

    def following(self, series_id):
        with self.lock:
            row = self.db.execute('SELECT * FROM follows WHERE series_id = ?', (series_id,)).fetchone()
            return dict(row) if row else None

    def record_check(self, series_id, latest, found):
        """Store a follow check: the newest known episode and newly found ones (dicts from episodes())."""
        with self.lock, self.db:
            self.db.executemany('''
                INSERT INTO new_episodes (url, series_id, season, number, name, still_path, found_at)
                VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (url) DO NOTHING
            ''', [(e['url'], series_id, e['season'], e['number'], e.get('name'), e.get('still_path'), time.time())
                  for e in found])
            self.db.execute('UPDATE follows SET last_season = ?, last_number = ?, checked_at = ? WHERE series_id = ?',
                            (latest[0], latest[1], time.time(), series_id))

    def new_episodes(self, include_seen=False):
        with self.lock:
            return [dict(row) for row in self.db.execute(f'''
                SELECT n.url, n.season, n.number, n.name AS episode_name, n.still_path, n.found_at, n.seen,
                       t.id AS series_id, t.slug, t.title, t.poster_path, t.backdrop_path, m.id AS media_id
                FROM new_episodes n
                JOIN titles t ON t.id = n.series_id
                LEFT JOIN media m ON m.url = n.url
                {'' if include_seen else 'WHERE n.seen = 0'}
                ORDER BY n.found_at DESC, n.season DESC, n.number DESC''')]

    def mark_new_seen(self, series_id=None, url=None):
        with self.lock, self.db:
            if url:
                self.db.execute('UPDATE new_episodes SET seen = 1 WHERE url = ?', (url,))
            elif series_id:
                self.db.execute('UPDATE new_episodes SET seen = 1 WHERE series_id = ?', (series_id,))
            else:
                self.db.execute('UPDATE new_episodes SET seen = 1')

    # ------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------
    def watched_media(self, before=None):
        """Downloaded videos that were watched to the end (optionally, last watched before a time)."""
        rows = [m for m in self.media() if m['finished']]
        return [m for m in rows if before is None or (m['watched_at'] or 0) < before]
