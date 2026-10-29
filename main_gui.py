import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import threading
import subprocess
import time
import webbrowser
import queue
from pathlib import Path

from src import settings
from src.desktop import LOG_FILE, focus_running_instance, setup_logging
from src.idlixHelper import IdlixHelper, logger, subtitle_filter
from src.images import ImageCache
from src.library import Library
from src.libraryScan import cache_artwork, scan_folder
from src.modernIdlix import ModernIdlix
from src.downloadQueue import (DownloadManager, retry, COMPLETED, FAILED, CANCELLED, DOWNLOADING)

MAX_PARALLEL_DOWNLOADS = 5
DEFAULT_PARALLEL_DOWNLOADS = 2
DEFAULT_DOWNLOAD_DIR = settings.DEFAULT_DOWNLOAD_DIR
SETTINGS_FILE = settings.SETTINGS_FILE
QUEUE_FILE = 'queue.json'

logger.configure(extra={"job": ""})  # "#N" job prefix is empty outside download workers


# ============================================================
# GUI LOGGER
# ============================================================
class GuiLogger:
    def __init__(self, textbox):
        self.textbox = textbox
        self.messages = queue.SimpleQueue()
        self.drain()

    def write(self, msg):
        self.messages.put(str(msg))

    def drain(self):
        while not self.messages.empty():
            self.textbox.configure(state='normal')
            self.textbox.insert(tk.END, self.messages.get())
            self.textbox.see(tk.END)
            self.textbox.configure(state='disabled')
        self.timer = self.textbox.after(100, self.drain)

    def stop(self):
        self.textbox.after_cancel(self.timer)

    def flush(self):
        pass


# ============================================================
# MAIN GUI
# ============================================================
class IdlixGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(settings.APP_NAME)
        self.root.geometry("1400x800")
        # A transparent 1x1 image replaces Tk's default feather icon.
        self.blank_icon = tk.PhotoImage(width=1, height=1)
        self.root.iconphoto(True, self.blank_icon)

        self.prefs = settings.load(SETTINGS_FILE, {})
        self.download_dir = Path(self.prefs.get('download_dir') or DEFAULT_DOWNLOAD_DIR)
        parallel = min(max(int(self.prefs.get('parallel', DEFAULT_PARALLEL_DOWNLOADS)), 1), MAX_PARALLEL_DOWNLOADS)

        self.library = Library(settings.CONFIG_DIR / 'library.db')
        self.images = ImageCache(settings.DATA_DIR / 'cache' / 'images')
        self.idlix = IdlixHelper(self.download_dir)
        # Browsing gets its own client: curl_cffi sessions must not be shared across threads.
        self.catalog = IdlixHelper(self.download_dir)
        self.catalog_lock = threading.Lock()
        self.ffplay_process = None
        self.busy = threading.Lock()
        self.closing = False
        # Worker threads never touch Tk directly; they queue callbacks for drain_ui.
        self.ui_calls = queue.SimpleQueue()
        self.changed_jobs = queue.SimpleQueue()
        self.request_token = 0
        self.results = {}
        self.episode_items = {}
        self.search_query = None
        self.search_page = 1
        self.search_total = 0
        self.series = None
        self.season_numbers = []
        self.root.protocol('WM_DELETE_WINDOW', self.close)

        # Main container
        main_frame = ttk.Frame(root, padding=10)
        main_frame.pack(fill="both", expand=True)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(0, weight=1)

        self.build_search_panel(main_frame)

        # RIGHT = controls + downloads + log
        right_panel = ttk.Frame(main_frame, padding=(10, 0))
        right_panel.grid(row=0, column=1, sticky="ns")

        ttk.Label(right_panel, text="Controls", font=("Arial", 16, "bold")).pack(anchor="w", pady=(0, 10))

        ttk.Button(right_panel, text="Add Downloads (URLs)", command=self.download_by_url).pack(fill="x", pady=4)
        ttk.Button(right_panel, text="Play by URL", command=self.play_by_url).pack(fill="x", pady=4)
        ttk.Button(right_panel, text="Stop Player", command=self.stop_player).pack(fill="x", pady=4)
        ttk.Button(right_panel, text="Clear Log", command=self.clear_log).pack(fill="x", pady=4)

        # Download folder
        folder = ttk.Frame(right_panel)
        folder.pack(fill="x", pady=(12, 0))
        ttk.Label(folder, text="Save to:").pack(side="left")
        ttk.Button(folder, text="Open", width=6, command=self.open_download_folder).pack(side="right")
        ttk.Button(folder, text="Change...", command=self.change_download_folder).pack(side="right", padx=4)
        self.folder_text = tk.StringVar(value=str(self.download_dir))
        ttk.Label(right_panel, textvariable=self.folder_text, foreground="#555",
                  wraplength=560).pack(anchor="w", pady=(2, 0))

        # Downloads queue
        header = ttk.Frame(right_panel)
        header.pack(fill="x", pady=(16, 5))
        ttk.Label(header, text="Downloads", font=("Arial", 14, "bold")).pack(side="left")
        self.parallel = tk.IntVar(value=parallel)
        ttk.Spinbox(header, from_=1, to=MAX_PARALLEL_DOWNLOADS, width=3, state="readonly",
                    textvariable=self.parallel, command=self.change_parallel).pack(side="right")
        ttk.Label(header, text="Parallel:").pack(side="right", padx=(0, 4))

        self.download_list = ttk.Treeview(right_panel, columns=("id", "title", "status", "progress"),
                                          show="headings", height=7, selectmode="extended")
        for column, text, width in (("id", "#", 35), ("title", "Title", 210),
                                    ("status", "Status", 85), ("progress", "Progress", 250)):
            self.download_list.heading(column, text=text, anchor="w")
            self.download_list.column(column, width=width, anchor="w", stretch=column == "progress")
        self.download_list.tag_configure(COMPLETED, foreground="#1b7f2a")
        self.download_list.tag_configure(FAILED, foreground="#c62828")
        self.download_list.tag_configure(CANCELLED, foreground="#888888")
        self.download_list.pack(fill="x")

        actions = ttk.Frame(right_panel)
        actions.pack(fill="x", pady=(4, 0))
        ttk.Button(actions, text="Cancel", command=self.cancel_selected).pack(side="left", expand=True, fill="x")
        ttk.Button(actions, text="Retry", command=self.retry_selected).pack(side="left", expand=True, fill="x", padx=4)
        ttk.Button(actions, text="Clear Finished", command=self.clear_finished).pack(side="left", expand=True, fill="x")

        self.downloads = DownloadManager(on_change=self.job_changed, limit=parallel,
                                         download_dir=self.download_dir,
                                         library=self.library, images=self.images)

        ttk.Label(right_panel, text="Log Output", font=("Arial", 14, "bold")).pack(anchor="w", pady=(16, 5))

        self.log_box = tk.Text(right_panel, height=14, state='disabled', bg="#111", fg="#0f0")
        self.log_box.pack(fill="both", expand=True)

        # Logger injection; "#N" marks which download a line belongs to. Other sinks (console,
        # log file) stay: under pythonw the log file is the only record outside this window.
        self.gui_logger = GuiLogger(self.log_box)
        logger.add(self.gui_logger, format="{time:HH:mm:ss} | {level} | {extra[job]}{message}")

        self.saved_queue = settings.load(QUEUE_FILE, [])
        self.restore_queue()
        self.drain_ui()
        self.show_latest()
        self.scan_library()

    # ============================================================
    # SEARCH PANEL (left)
    # ============================================================
    def build_search_panel(self, parent):
        left = ttk.Frame(parent)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)
        left.grid_rowconfigure(6, weight=1)

        ttk.Label(left, text="Find Movies & Series", font=("Arial", 16, "bold")).grid(row=0, column=0, sticky="w")

        bar = ttk.Frame(left)
        bar.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        self.query = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.query, font=("Arial", 11))
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _: self.search())
        entry.focus_set()
        ttk.Button(bar, text="Search", command=self.search).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Latest", command=self.show_latest).pack(side="left", padx=(6, 0))

        self.result_list = self.scrolled_tree(left, 2, (("title", "Title", 420), ("type", "Type", 80),
                                                        ("year", "Year", 60)), "browse")
        self.result_list.bind("<<TreeviewSelect>>", self.on_result_selected)

        footer = ttk.Frame(left)
        footer.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        self.results_info = tk.StringVar()
        ttk.Label(footer, textvariable=self.results_info).pack(side="left")
        self.more_button = ttk.Button(footer, text="More results", command=self.more_results, state="disabled")
        self.more_button.pack(side="right")

        detail = ttk.Frame(left)
        detail.grid(row=4, column=0, sticky="ew", pady=(14, 4))
        self.detail_title = tk.StringVar(value="Select a title above")
        ttk.Label(detail, textvariable=self.detail_title, font=("Arial", 13, "bold")).pack(side="left")
        self.season_choice = ttk.Combobox(detail, state="disabled", width=22)
        self.season_choice.pack(side="right")
        self.season_choice.bind("<<ComboboxSelected>>", lambda _: self.load_episodes())
        ttk.Label(detail, text="Season:").pack(side="right", padx=(0, 4))

        ttk.Label(left, text="Tip: Ctrl/Shift+click to pick several episodes.",
                  foreground="#666").grid(row=5, column=0, sticky="w")

        self.episode_list = self.scrolled_tree(left, 6, (("ep", "Ep", 45), ("title", "Title", 330),
                                                         ("aired", "Aired", 95), ("saved", "Saved", 90)),
                                               "extended")
        self.episode_list.tag_configure("novideo", foreground="#999999")

        buttons = ttk.Frame(left)
        buttons.grid(row=7, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(buttons, text="Select All", command=self.select_all_episodes).pack(side="left")
        ttk.Button(buttons, text="Play", command=self.play_selected).pack(side="right")
        ttk.Button(buttons, text="Download Selected", command=self.download_selected).pack(side="right", padx=6)

    @staticmethod
    def scrolled_tree(parent, row, columns, selectmode):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="nsew")
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings",
                            height=10, selectmode=selectmode)
        for column, text, width in columns:
            tree.heading(column, text=text, anchor="w")
            tree.column(column, width=width, anchor="w", stretch=column == "title")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        return tree

    def run_async(self, func, args, on_done):
        """Run a blocking helper call off the UI thread; drop the result if a newer request started."""
        token = self.request_token

        def task():
            try:
                with self.catalog_lock:
                    result = func(*args)
            except Exception as error:
                result = {"status": False, "message": str(error)}
            self.call_ui(lambda: token == self.request_token and on_done(result))

        threading.Thread(target=task, daemon=True).start()

    def show_latest(self):
        self.request_token += 1
        self.search_query = None
        self.results_info.set("Loading latest titles...")
        self.more_button.configure(state="disabled")
        self.run_async(retry, (self.catalog.get_home,), self.show_latest_results)

    def show_latest_results(self, home):
        if not home.get("status"):
            self.results_info.set("Could not load latest titles")
            logger.error(f"Failed to load latest titles: {home.get('message')}")
            return
        items = home["featured_movie"]
        self.fill_results(items, append=False)
        self.results_info.set(f"Latest on IDLIX: {len(items)} titles")

    def search(self):
        query = self.query.get().strip()
        if not query:
            return self.show_latest()
        self.request_token += 1
        self.search_query, self.search_page = query, 1
        self.results_info.set(f'Searching "{query}"...')
        self.more_button.configure(state="disabled")
        self.run_async(retry, (self.catalog.search, query, 1), lambda r: self.show_search_results(r, False))

    def more_results(self):
        self.request_token += 1
        self.search_page += 1
        self.more_button.configure(state="disabled")
        self.run_async(retry, (self.catalog.search, self.search_query, self.search_page),
                       lambda r: self.show_search_results(r, True))

    def show_search_results(self, result, append):
        if not result.get("status"):
            self.results_info.set("Search failed")
            logger.error(f"Search failed: {result.get('message')}")
            return
        self.search_total = result["total"]
        self.fill_results(result["results"], append)
        shown = len(self.results)
        self.results_info.set(f'{shown} of {self.search_total} results for "{self.search_query}"'
                              if shown else f'No results for "{self.search_query}"')
        self.more_button.configure(state="normal" if result["results"] and shown < self.search_total else "disabled")

    def fill_results(self, items, append):
        if not append:
            self.result_list.delete(*self.result_list.get_children())
            self.results.clear()
        labels = {"movie": "Movie", "series": "Series", "episode": "Episode"}
        for item in items:
            iid = str(len(self.results))
            self.results[iid] = item
            self.result_list.insert("", tk.END, iid=iid,
                                    values=(item["title"], labels.get(item["type"], item["type"]), item.get("year", "")))

    def on_result_selected(self, _event=None):
        selection = self.result_list.selection()
        if not selection:
            return
        item = self.results[selection[0]]
        self.request_token += 1
        self.series = None
        self.season_numbers = []
        self.episode_list.delete(*self.episode_list.get_children())
        self.episode_items.clear()
        self.season_choice.set("")
        self.season_choice.configure(state="disabled", values=())

        if item["type"] == "series":
            self.series = item
            self.detail_title.set(f"{item['title']} ({item.get('year') or '?'}) - loading seasons...")
            self.run_async(retry, (self.catalog.get_seasons, item["slug"]), self.show_seasons)
            return

        # A movie, or one episode from the Latest list: a single downloadable row.
        self.detail_title.set(item["title"])
        saved = self.saved_mark(item["title"]) if item["type"] == "movie" else ""
        self.episode_items["single"] = {"url": item["url"], "title": item["title"], "has_video": True,
                                        "check_saved": item["type"] == "movie"}
        self.episode_list.insert("", tk.END, iid="single", values=("", item["title"], item.get("year", ""), saved))
        self.episode_list.selection_set("single")

    def show_seasons(self, result):
        if not result.get("status") or not result["seasons"]:
            self.detail_title.set(f"{self.series['title']} - no seasons available")
            if not result.get("status"):
                logger.error(f"Could not load seasons: {result.get('message')}")
            return
        self.detail_title.set(result["title"])
        self.season_numbers = [number for number, _ in result["seasons"]]
        self.season_choice.configure(state="readonly", values=[
            f"Season {number} ({count} eps)" for number, count in result["seasons"]])
        self.season_choice.current(self.season_numbers.index(result["default"]))
        self.load_episodes()

    def load_episodes(self):
        if not self.series or self.season_choice.current() < 0:
            return
        self.request_token += 1
        season = self.season_numbers[self.season_choice.current()]
        self.episode_list.delete(*self.episode_list.get_children())
        self.episode_items.clear()
        self.episode_list.insert("", tk.END, iid="loading", values=("", "Loading episodes...", "", ""))
        self.run_async(retry, (self.catalog.get_episodes, self.series["slug"], season), self.show_episodes)

    def show_episodes(self, result):
        self.episode_list.delete(*self.episode_list.get_children())
        if not result.get("status"):
            logger.error(f"Could not load episodes: {result.get('message')}")
            return
        for episode in result["episodes"]:
            iid = str(episode["number"])
            self.episode_items[iid] = {**episode, "check_saved": True}
            saved = self.saved_mark(episode["title"]) if episode["has_video"] else "no video"
            self.episode_list.insert("", tk.END, iid=iid, tags=() if episode["has_video"] else ("novideo",),
                                     values=(episode["number"], episode["name"], episode["air_date"], saved))

    def saved_mark(self, title):
        return "✓ saved" if self.idlix.modern.output_path(title).exists() else ""

    def refresh_saved_marks(self):
        for iid, item in self.episode_items.items():
            if item.get("check_saved") and item["has_video"] and self.episode_list.exists(iid):
                self.episode_list.set(iid, "saved", self.saved_mark(item["title"]))

    def select_all_episodes(self):
        self.episode_list.selection_set([iid for iid, item in self.episode_items.items() if item["has_video"]])

    def selected_episodes(self):
        items = [self.episode_items[iid] for iid in self.episode_list.selection() if iid in self.episode_items]
        if not items:
            messagebox.showinfo("Nothing selected", "Select a movie or one or more episodes first.")
        return items

    def download_selected(self):
        items = self.selected_episodes()
        unavailable = [item["title"] for item in items if not item["has_video"]]
        for title in unavailable:
            logger.warning(f"No video available yet: {title}")
        self.queue_downloads([(item["url"], item["title"]) for item in items if item["has_video"]])

    def play_selected(self):
        items = self.selected_episodes()
        if items:
            self.play_movie(items[0]["url"])

    # ============================================================
    # URL BUTTON ACTIONS
    # ============================================================
    def download_by_url(self):
        popup = tk.Toplevel(self.root)
        popup.title("Add Downloads")
        popup.geometry("560x320")
        popup.transient(self.root)

        ttk.Label(popup, text="Paste one movie or episode URL per line:").pack(anchor="w", padx=10, pady=(10, 4))
        text = tk.Text(popup, height=12, wrap="none")
        text.pack(fill="both", expand=True, padx=10)
        text.focus_set()

        def add():
            urls = text.get("1.0", tk.END).split()
            popup.destroy()
            self.queue_downloads([(url, None) for url in urls])

        buttons = ttk.Frame(popup)
        buttons.pack(fill="x", padx=10, pady=10)
        ttk.Button(buttons, text="Cancel", command=popup.destroy).pack(side="right")
        ttk.Button(buttons, text="Add to Queue", command=add).pack(side="right", padx=6)
        popup.grab_set()

    def play_by_url(self):
        url = simpledialog.askstring("Play Movie", "Enter movie URL:")
        if url:
            self.play_movie(url.strip())

    # ============================================================
    # DOWNLOAD QUEUE
    # ============================================================
    def queue_downloads(self, items):
        """items: (url, title or None) pairs."""
        added = 0
        for url, title in dict.fromkeys((u.strip(), t) for u, t in items if u.strip()):
            if self.downloads.add(url, title):
                added += 1
            else:
                logger.warning(f"Already in the queue: {title or url}")
        if added:
            logger.info(f"Queued {added} download(s); running up to {self.downloads.limit} at a time.")

    def restore_queue(self):
        # Unfinished downloads from the last session start again (an HLS copy cannot resume).
        if self.saved_queue:
            self.queue_downloads([(url, title) for url, title in self.saved_queue])
            logger.info(f"Restored {len(self.saved_queue)} unfinished download(s) from the last session.")

    def save_queue(self):
        current = [list(job) for job in self.downloads.unfinished_jobs()]
        if current != self.saved_queue:
            self.saved_queue = current
            settings.save(QUEUE_FILE, current)

    def call_ui(self, func):
        self.ui_calls.put(func)

    def job_changed(self, job):
        # Called from worker threads; Tk is only touched by drain_ui on the main loop.
        self.changed_jobs.put(job)

    def drain_ui(self):
        while not self.ui_calls.empty():
            try:
                self.ui_calls.get()()
            except Exception as error:
                logger.error(f"UI update failed: {error}")
        latest = {}
        while not self.changed_jobs.empty():
            job = self.changed_jobs.get()
            latest[job.id] = job
        for job in latest.values():
            self.show_job(job)
        if latest and not self.closing:
            self.save_queue()
        if any(job.status == COMPLETED for job in latest.values()):
            self.refresh_saved_marks()
        self.drain_timer = self.root.after(150, self.drain_ui)

    def show_job(self, job):
        if job.id not in self.downloads.jobs:
            return  # cleared before this update was drawn
        progress = job.detail
        if job.status == DOWNLOADING and job.fraction is None and not progress:
            progress = "Downloading..."
        values = (job.id, job.title, job.status, progress)
        tags = (job.status,)
        row = str(job.id)
        if self.download_list.exists(row):
            self.download_list.item(row, values=values, tags=tags)
        else:
            self.download_list.insert("", tk.END, iid=row, values=values, tags=tags)

    def selected_jobs(self):
        return [int(row) for row in self.download_list.selection()]

    def change_parallel(self):
        self.downloads.set_limit(self.parallel.get())
        self.save_prefs()
        logger.info(f"Parallel downloads: {self.parallel.get()}")

    def cancel_selected(self):
        for job_id in self.selected_jobs():
            self.downloads.cancel(job_id)

    def retry_selected(self):
        for job_id in self.selected_jobs():
            if not self.downloads.retry_job(job_id):
                logger.warning(f"#{job_id} can only be retried after it failed or was cancelled.")

    def clear_finished(self):
        for job_id in self.downloads.clear_finished():
            if self.download_list.exists(str(job_id)):
                self.download_list.delete(str(job_id))

    # ============================================================
    # DOWNLOAD FOLDER
    # ============================================================
    def change_download_folder(self):
        folder = filedialog.askdirectory(parent=self.root, title="Save downloads to",
                                         initialdir=self.download_dir if self.download_dir.exists() else None)
        if not folder:
            return
        self.download_dir = Path(folder)
        self.downloads.download_dir = self.download_dir
        self.idlix.download_dir = self.catalog.download_dir = self.download_dir
        self.folder_text.set(str(self.download_dir))
        self.save_prefs()
        self.refresh_saved_marks()
        self.scan_library()
        message = f"New downloads will be saved to {self.download_dir}"
        if self.downloads.unfinished():
            message += " (downloads already running keep their folder)"
        logger.info(message)

    def scan_library(self):
        """In the background, forget deleted files and add videos already in the download folder."""
        folder = self.download_dir

        def task():
            client = ModernIdlix(folder)  # its own session: scanning must not block searches
            try:
                removed = self.library.prune_missing()
                matched, unmatched = scan_folder(self.library, client, folder, self.images)
                if removed or matched or unmatched:
                    logger.info(f"Library: added {matched + unmatched} video(s) from {folder}"
                                f"{f', {unmatched} without IDLIX details' if unmatched else ''}"
                                f"{f'; removed {removed} missing file(s)' if removed else ''}.")
                cache_artwork(self.library, self.images)
            except Exception as error:
                logger.warning(f"Library scan failed: {error}")
            finally:
                client.close()

        threading.Thread(target=task, daemon=True).start()

    def open_download_folder(self):
        self.download_dir.mkdir(parents=True, exist_ok=True)
        webbrowser.open(str(self.download_dir))

    def save_prefs(self):
        self.prefs.update(parallel=self.parallel.get(),
                          download_dir=None if self.download_dir == DEFAULT_DOWNLOAD_DIR else str(self.download_dir))
        settings.save(SETTINGS_FILE, self.prefs)

    # ============================================================
    # PLAY (same steps as the CLI)
    # ============================================================
    def play_movie(self, url: str):
        if not self.busy.acquire(blocking=False):
            logger.warning('Please wait for the current operation to finish.')
            return
        self.stop_player()

        def task():
            idlix = self.idlix

            # 1. get video data
            video_data = retry(idlix.get_video_data, url)
            if not video_data.get("status"):
                logger.error(f"Error getting video data: {video_data.get('message')}")
                return

            logger.info(
                f"Video ID: {video_data['video_id']} | Name: {video_data['video_name']}"
            )

            # 2. m3u8
            m3u8 = retry(idlix.get_m3u8_url)
            if not m3u8.get("status"):
                logger.error(f"Error getting M3U8 URL: {m3u8.get('message')}")
                return

            logger.info(f"Quality: {m3u8.get('quality', 'source')}")

            subtitle = idlix.get_subtitle()

            subtitle_file = subtitle["subtitle"] if subtitle.get("status") else None

            self.start_ffplay(idlix.m3u8_url, subtitle_file)

        def run():
            try:
                task()
            except Exception as error:
                logger.error(f'Operation failed: {error}')
            finally:
                self.busy.release()

        threading.Thread(target=run, daemon=True).start()

    # ============================================================
    # ffplay controls
    # ============================================================
    def start_ffplay(self, m3u8_url, subtitle=None):

        self.stop_player()

        args = ["ffplay", "-allowed_extensions", "ALL", "-extension_picky", "0",
                "-i", m3u8_url, "-window_title", self.idlix.video_name, "-loglevel", "error"]

        if subtitle:
            args += ["-vf", subtitle_filter(subtitle)]

        logger.info("Opening ffplay...")
        self.ffplay_process = subprocess.Popen(
            args, stderr=subprocess.PIPE, text=True, errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        player = self.ffplay_process

        def monitor():
            _, error = player.communicate()
            if player.returncode and self.ffplay_process is player:
                logger.error(f'Player exited with code {player.returncode}: {(error or "").strip()[-600:]}')

        threading.Thread(target=monitor, daemon=True).start()

    def stop_player(self):
        if self.ffplay_process and self.ffplay_process.poll() is None:
            try:
                player, self.ffplay_process = self.ffplay_process, None
                player.terminate()
                logger.info("ffplay terminated.")
            except:
                pass

    def clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete(1.0, tk.END)
        self.log_box.configure(state="disabled")

    def close(self):
        if self.busy.locked():
            logger.warning('Wait until the current operation finishes before closing.')
            return
        running = self.downloads.unfinished()
        if running and not messagebox.askyesno(
                "Downloads in progress",
                f"{running} download(s) are still queued or running.\n"
                "Quit anyway? They will start again from the beginning the next time you open the app."):
            return
        # Remember the queue before cancelling, which would otherwise mark every job finished.
        self.closing = True
        settings.save(QUEUE_FILE, [list(job) for job in self.downloads.unfinished_jobs()])
        self.downloads.cancel_all()
        self.stop_player()
        self.idlix.close()
        self.catalog.close()
        self.wait_for_downloads(time.monotonic() + 15)

    def wait_for_downloads(self, deadline):
        # Give workers time to stop ffmpeg and delete part files before the process exits.
        if self.downloads.unfinished() and time.monotonic() < deadline:
            self.root.after(200, self.wait_for_downloads, deadline)
        else:
            # Stop the repeating drain timers so Tk doesn't report them after the window is gone.
            self.root.after_cancel(self.drain_timer)
            self.gui_logger.stop()
            self.root.destroy()


# ============================================================
# RUN APP
# ============================================================
def main():
    setup_logging()
    if focus_running_instance():
        logger.info("Already running; focused the open window.")
        return
    try:
        root = tk.Tk()
        IdlixGUI(root)
        root.mainloop()
    except Exception:
        logger.exception("IDLIX Downloader crashed")
        messagebox.showerror(settings.APP_NAME, "IDLIX Downloader stopped because of an error.\n"
                                                f"Details: {LOG_FILE}")
        raise


if __name__ == "__main__":
    main()
