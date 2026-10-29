"""
Helper Class for IDLIX Downloader & IDLIX Player CLI

Update  :   28-11-2025
Author  :   sandroputraa
"""

import os
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests
from loguru import logger
from vtt_to_srt.vtt_to_srt import ConvertFile

from src.modernIdlix import ModernIdlix

SITE_HOST = 'z2.idlixku.com'


class IdlixHelper:
    _ffmpeg_lock = threading.Lock()
    _ffmpeg_ready = False

    def __init__(self, download_dir='.', account=None):
        self.modern = ModernIdlix(download_dir, account=account)
        self.poster = None
        self.m3u8_url = None
        self.video_id = None
        self.video_name = None
        self.is_subtitle = None
        self.subtitle_file = None

        self.ensure_ffmpeg()

    @classmethod
    def ensure_ffmpeg(cls):
        # Every download job builds its own helper; only the first one sets up ffmpeg.
        with cls._ffmpeg_lock:
            if not cls._ffmpeg_ready:
                cls.setup_ffmpeg()
                cls._ffmpeg_ready = True

    @classmethod
    def setup_ffmpeg(cls):
        if os.name == 'nt':
            for executable in Path(__file__).resolve().parent.glob('ffmpeg/*/bin/ffmpeg.exe'):
                os.environ['PATH'] = str(executable.parent) + os.pathsep + os.environ.get('PATH', '')
                break
            if shutil.which('ffmpeg'):
                logger.info(f'FFMPEG Found: {shutil.which("ffmpeg")}')
            else:
                if not os.path.exists('ffmpeg-release-essentials.zip'):
                    cls.download_ffmpeg()
                logger.warning('FFMPEG not set in PATH, Trying set PATH')
                try:
                    with zipfile.ZipFile('ffmpeg-release-essentials.zip', 'r') as zip_ref:
                        zip_ref.extractall(
                            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg')
                        )
                    logger.success('Success Extracting ffmpeg')
                    path = ""
                    for _ in os.listdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg')):
                        if 'ffmpeg' in _:
                            logger.info(f'Found: {os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", _, "bin")}')
                            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", _, "bin")
                            break
                    else:
                        logger.error('FFMPEG not found, please install ffmpeg first before running this script')
                    if path:
                        os.environ['PATH'] = path + os.pathsep + os.environ.get('PATH', '')
                        logger.success('FFMPEG ready')
                except Exception as e:
                    print(f'Error: {e}')
        else:
            if not shutil.which('ffmpeg'):
                logger.error('FFMPEG not found, please install ffmpeg first before running this script')
                exit()

    @staticmethod
    def download_ffmpeg():
        try:
            logger.info('Downloading ffmpeg')
            content = requests.get(
                url='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',
                stream=True
            )
            with open("ffmpeg-release-essentials.zip", mode="wb") as file:
                for chunk in content.iter_content(chunk_size=1024):
                    print(
                        '\rDownloading: {} MB of {} MB'.format(
                            round(os.path.getsize('ffmpeg-release-essentials.zip') / 1024 / 1024, 2),
                            round(int(content.headers.get('Content-Length', 0)) / 1024 / 1024, 2)
                        ),
                        end=''
                    )
                    file.write(chunk)
            print()
            logger.success('Downloaded ffmpeg')
        except Exception as e:
            print(f'Error: {e}')

    @property
    def download_dir(self):
        return self.modern.download_dir

    @download_dir.setter
    def download_dir(self, folder):
        self.modern.download_dir = Path(folder)

    def get_home(self):
        try:
            return self.modern.home()
        except Exception as error_get_home:
            return {
                'status': False,
                'message': str(error_get_home)
            }

    def search(self, query, page=1):
        try:
            return self.modern.search(query, page)
        except Exception as error:
            return {'status': False, 'message': str(error)}

    def get_seasons(self, slug):
        try:
            return self.modern.seasons(slug)
        except Exception as error:
            return {'status': False, 'message': str(error)}

    def get_episodes(self, slug, season):
        try:
            return self.modern.episodes(slug, season)
        except Exception as error:
            return {'status': False, 'message': str(error)}

    def get_video_data(self, url):
        self.video_id = self.m3u8_url = None
        self.is_subtitle = False
        self.subtitle_file = None
        if not url:
            return {
                'status': False,
                'message': 'URL is required'
            }
        if urlparse(url).hostname != SITE_HOST:
            return {
                'status': False,
                'message': f'Use a movie or episode URL from https://{SITE_HOST}/'
            }
        try:
            data = self.modern.metadata(url)
            self.video_id, self.video_name, self.poster = data['video_id'], data['video_name'], data['poster']
            return data
        except Exception as error:
            return {'status': False, 'message': str(error)}

    def get_m3u8_url(self):
        try:
            result = self.modern.stream()
            self.m3u8_url = result['m3u8_url']
            return result
        except Exception as error:
            return {'status': False, 'message': str(error)}

    def download_m3u8(self, progress=None):
        try:
            return self.modern.download(progress)
        except Exception as error_download_m3u8:
            return {
                'status': False,
                'message': str(error_download_m3u8)
            }

    def output_path(self):
        """Where download_m3u8 saves the video of the loaded title."""
        return self.modern.output_path()

    def media_info(self):
        """Library metadata of the loaded title (see ModernIdlix.metadata)."""
        return self.modern.info

    def cancel(self):
        """Stop a running download."""
        self.modern.cancel()
        return True

    def close(self):
        self.modern.close()

    def get_subtitle(self, download=True):
        try:
            result = self.modern.subtitle(download)
            self.is_subtitle = result['status']
            self.subtitle_file = result.get('subtitle') if download else None
            return result
        except Exception as error_get_subtitle:
            return {
                'status': False,
                'message': str(error_get_subtitle)
            }

    def save_subtitle(self):
        """Download the subtitle next to the video, plus an .srt copy for players without WebVTT."""
        result = self.get_subtitle()
        if result.get('status') and result['subtitle'].endswith('.vtt'):
            try:
                self.convert_vtt_to_srt(result['subtitle'])
                result['srt'] = str(Path(result['subtitle']).with_suffix('.srt'))
            except Exception as error:
                logger.warning(f'Could not convert subtitle to SRT: {error}')
        return result

    def play_m3u8(self):
        try:
            args = ['ffplay', '-allowed_extensions', 'ALL', '-extension_picky', '0',
                    '-i', self.m3u8_url, '-window_title', self.video_name]
            if self.is_subtitle and self.subtitle_file:
                args += ['-vf', subtitle_filter(self.subtitle_file)]
            result = subprocess.run(args)
            return {'status': result.returncode == 0, 'message': f'Player exited with code {result.returncode}'}
        except Exception as error_play_m3u8:
            return {
                'status': False,
                'message': str(error_play_m3u8)
            }

    @staticmethod
    def convert_vtt_to_srt(vtt_file):
        convert_file = ConvertFile(vtt_file, "utf-8")
        convert_file.convert()


def subtitle_filter(path):
    """ffmpeg -vf value that burns in a subtitle file.

    ffmpeg unescapes the path twice: once as a filter option value, then as part of
    the filtergraph, so drive colons, quotes and brackets are escaped for both levels.
    """
    value = str(path).replace('\\', '/')
    for special in "\\':":
        value = value.replace(special, '\\' + special)
    for special in "\\'[],;":
        value = value.replace(special, '\\' + special)
    return 'subtitles=filename=' + value
