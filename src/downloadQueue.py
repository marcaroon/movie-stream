"""
Download queue: runs several IDLIX downloads side by side.

Each job gets its own IdlixHelper, because a helper keeps per-title state
(video id, stream URL, playback session). A job only starts while fewer than
`limit` jobs are running; the rest wait in FIFO order. A failed attempt is
retried automatically after a short pause before the job is marked Failed.
"""

import itertools
import threading
import time
from collections import deque

from loguru import logger

from src.idlixHelper import IdlixHelper

RETRY_LIMIT = 3
AUTO_RETRY_DELAYS = (15, 45)  # seconds before the 2nd and 3rd attempt

QUEUED = 'Queued'
PREPARING = 'Preparing'
DOWNLOADING = 'Downloading'
COMPLETED = 'Completed'
FAILED = 'Failed'
CANCELLED = 'Cancelled'
FINISHED = (COMPLETED, FAILED, CANCELLED)

_KEEP = object()


def retry(func, *args, **kwargs):
    result = None
    for _ in range(RETRY_LIMIT):
        result = func(*args, **kwargs)
        if result and result.get("status"):
            return result
        time.sleep(1)
    return result or {"status": False, "message": "Maximum retry reached (no response)"}


class Cancelled(Exception):
    pass


class DownloadJob:
    def __init__(self, job_id, url, title=None):
        self.id = job_id
        self.url = url
        self.title = title or url
        self.status = QUEUED
        self.fraction = 0.0  # None while the total size is unknown
        self.detail = ''
        self.helper = None
        self.cancelled = threading.Event()

    @property
    def cancel_requested(self):
        return self.cancelled.is_set()


class DownloadManager:
    def __init__(self, on_change, limit=2, download_dir='.', retry_delays=AUTO_RETRY_DELAYS,
                 library=None, images=None, account=None):
        # on_change(job) is called from worker threads; the GUI must hop to its own thread.
        self.on_change = on_change
        self.account = account  # IdlixAccount: signed-in downloads get the member quality
        self.library = library  # finished downloads are recorded here, with artwork cached in images
        self.images = images
        self.limit = limit
        self.download_dir = download_dir  # read when a job starts
        self.retry_delays = retry_delays
        self.jobs = {}
        self.pending = deque()
        self.active = 0
        self.lock = threading.Lock()
        self.ids = itertools.count(1)

    # ------------------------------------------------------------
    # Public API (safe to call from any thread)
    # ------------------------------------------------------------
    def add(self, url, title=None):
        """Queue a URL. Returns None when the same URL is already queued or running."""
        with self.lock:
            if any(job.url == url and job.status not in FINISHED for job in self.jobs.values()):
                return None
            job = DownloadJob(next(self.ids), url, title)
            self.jobs[job.id] = job
            self.pending.append(job)
        self.on_change(job)
        self._start_workers()
        return job

    def set_limit(self, limit):
        self.limit = max(1, int(limit))
        self._start_workers()

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.status in FINISHED:
                return
            job.cancelled.set()
            queued = job in self.pending
            if queued:
                self.pending.remove(job)
                job.status, job.detail = CANCELLED, ''
            helper = job.helper
        if queued:
            self.on_change(job)
            return
        if helper:
            helper.cancel()
        self._update(job, detail='Cancelling...')

    def cancel_all(self):
        for job_id in list(self.jobs):
            self.cancel(job_id)

    def retry_job(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.status not in (FAILED, CANCELLED):
                return False
            if any(other.url == job.url and other.status not in FINISHED for other in self.jobs.values()):
                return False
            job.status, job.fraction, job.detail = QUEUED, 0.0, ''
            job.cancelled = threading.Event()
            self.pending.append(job)
        self.on_change(job)
        self._start_workers()
        return True

    def clear_finished(self):
        """Forget finished jobs and return their ids."""
        with self.lock:
            done = [job_id for job_id, job in self.jobs.items() if job.status in FINISHED]
            for job_id in done:
                del self.jobs[job_id]
        return done

    def unfinished(self):
        return sum(job.status not in FINISHED for job in list(self.jobs.values()))

    def unfinished_jobs(self):
        """(url, title) of every queued or running job, in queue order, for saving across restarts."""
        return [(job.url, job.title) for job in list(self.jobs.values()) if job.status not in FINISHED]

    # ------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------
    def _start_workers(self):
        with self.lock:
            starting = []
            while self.pending and self.active < self.limit:
                starting.append(self.pending.popleft())
                self.active += 1
        for job in starting:
            threading.Thread(target=self._run, args=(job,), daemon=True).start()

    def _run(self, job):
        cancelled = job.cancelled  # a retried job gets a new event; keep this run's one
        with logger.contextualize(job=f'#{job.id} '):
            try:
                for attempt in range(len(self.retry_delays) + 1):
                    try:
                        note = self._attempt(job)
                        self._update(job, COMPLETED, 1.0, note)
                        return
                    except Exception as error:
                        if cancelled.is_set():
                            raise Cancelled() from error
                        if attempt == len(self.retry_delays):
                            raise
                        delay = self.retry_delays[attempt]
                        logger.warning(f'Attempt {attempt + 1} failed: {error}; retrying in {delay}s')
                        self._update(job, PREPARING, 0.0,
                                     f'Retrying in {delay}s ({attempt + 1}/{len(self.retry_delays)}): {error}')
                        if cancelled.wait(delay):
                            raise Cancelled()
            except Cancelled:
                self._update(job, CANCELLED, 0.0, '')
                logger.info(f'Cancelled: {job.title}')
            except Exception as error:
                self._update(job, FAILED, 0.0, str(error))
                logger.error(f'Download failed: {error}')
            finally:
                with self.lock:
                    self.active -= 1
                self._start_workers()

    def _attempt(self, job):
        # A fresh helper per attempt also means a fresh playback session.
        helper = IdlixHelper(self.download_dir, account=self.account)
        job.helper = helper
        try:
            return self._download(job, helper)
        finally:
            if job.helper is helper:
                job.helper = None
            helper.close()

    def _download(self, job, helper):
        self._check(job)

        self._update(job, PREPARING, 0.0, 'Fetching video info...')
        data = retry(helper.get_video_data, job.url)
        if not data.get('status'):
            raise ValueError(data.get('message'))
        job.title = data['video_name']
        self._check(job)

        # Re-queuing a finished title only fills in its missing subtitle.
        if helper.output_path().exists():
            logger.info(f'Video already downloaded, fetching subtitle only: {helper.output_path().name}')
            note, subtitle = self._subtitle(job, helper)
            self._record(helper, helper.output_path(), subtitle)
            return 'Already downloaded · ' + note

        self._update(job, detail='Getting stream...')
        stream = retry(helper.get_m3u8_url)
        if not stream.get('status'):
            raise ValueError(f"M3U8 URL: {stream.get('message')}")
        logger.info(f"Quality: {stream.get('quality', 'source')}")
        self._check(job)

        self._update(job, DOWNLOADING, 0.0, 'Starting download...')
        result = helper.download_m3u8(
            progress=lambda fraction, text: self._update(job, fraction=fraction, detail=text))
        if not result.get('status'):
            raise ValueError(result.get('message'))
        logger.success(f"Downloaded: {result['path']}")
        note, subtitle = self._subtitle(job, helper)
        self._record(helper, result['path'], subtitle)
        return 'Saved · ' + note

    def _subtitle(self, job, helper):
        """Save the subtitle next to the video; a missing subtitle never fails the job."""
        self._update(job, detail='Downloading subtitle...')
        subtitle = retry(helper.save_subtitle)
        if subtitle.get('status'):
            logger.success(f"Subtitle: {subtitle['subtitle']}" + (' (+ .srt)' if subtitle.get('srt') else ''))
            return 'subtitle saved', subtitle['subtitle']
        logger.warning(f"No subtitle: {subtitle.get('message')}")
        return 'no subtitle', None

    def _record(self, helper, path, subtitle):
        """Add the finished video to the library; a library problem never fails the download."""
        if not self.library:
            return
        try:
            info = helper.media_info()
            self.library.add_media(path, info, subtitle_path=subtitle)
            if self.images and info:
                self.images.prefetch(info)
        except Exception as error:
            logger.warning(f'Could not add to library: {error}')

    @staticmethod
    def _check(job):
        if job.cancel_requested:
            raise Cancelled()

    def _update(self, job, status=None, fraction=_KEEP, detail=None):
        if status:
            job.status = status
        if fraction is not _KEEP:
            job.fraction = fraction
        if detail is not None:
            job.detail = detail
        self.on_change(job)
