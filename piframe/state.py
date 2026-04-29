"""Shared mutable state accessed by the slideshow, web app, and sync threads."""
import json
import os
import queue
import threading
from datetime import datetime


class State:
    def __init__(self):
        self._lock = threading.Lock()

        # Slideshow
        self._photo_list: list = []
        self._photo_index: int = 0
        self._current_photo: str = ''
        self._paused: bool = False
        self._command_queue: queue.Queue = queue.Queue(maxsize=4)

        # OneDrive
        self._sync_status: str = 'Never synced'
        self._last_sync: datetime | None = None
        self._syncing: bool = False
        self._onedrive_authenticated: bool = False
        self._auth_flow: dict | None = None   # device-flow info while pending

        # Weather cache
        self._weather_data: dict | None = None

    # ── Slideshow ─────────────────────────────────────────────────────────────

    @property
    def photo_list(self):
        with self._lock:
            return list(self._photo_list)

    @photo_list.setter
    def photo_list(self, value):
        with self._lock:
            self._photo_list = list(value)

    @property
    def photo_index(self):
        with self._lock:
            return self._photo_index

    @photo_index.setter
    def photo_index(self, value):
        with self._lock:
            self._photo_index = value

    @property
    def current_photo(self):
        with self._lock:
            return self._current_photo

    @current_photo.setter
    def current_photo(self, value):
        with self._lock:
            self._current_photo = value

    @property
    def paused(self):
        with self._lock:
            return self._paused

    @paused.setter
    def paused(self, value):
        with self._lock:
            self._paused = value

    def send_command(self, cmd: str):
        try:
            self._command_queue.put_nowait(cmd)
        except queue.Full:
            pass

    def pop_command(self) -> str | None:
        try:
            return self._command_queue.get_nowait()
        except queue.Empty:
            return None

    @property
    def total_photos(self):
        with self._lock:
            return len(self._photo_list)

    # ── OneDrive ──────────────────────────────────────────────────────────────

    @property
    def sync_status(self):
        with self._lock:
            return self._sync_status

    @sync_status.setter
    def sync_status(self, value):
        with self._lock:
            self._sync_status = value

    @property
    def last_sync(self):
        with self._lock:
            return self._last_sync

    @last_sync.setter
    def last_sync(self, value):
        with self._lock:
            self._last_sync = value

    @property
    def syncing(self):
        with self._lock:
            return self._syncing

    @syncing.setter
    def syncing(self, value):
        with self._lock:
            self._syncing = value

    @property
    def onedrive_authenticated(self):
        with self._lock:
            return self._onedrive_authenticated

    @onedrive_authenticated.setter
    def onedrive_authenticated(self, value):
        with self._lock:
            self._onedrive_authenticated = value

    @property
    def auth_flow(self):
        with self._lock:
            return self._auth_flow

    @auth_flow.setter
    def auth_flow(self, value):
        with self._lock:
            self._auth_flow = value

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str):
        """Atomically write resumable state to disk."""
        data = {'current_photo': self.current_photo}
        tmp = path + '.tmp'
        try:
            with open(tmp, 'w') as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except OSError:
            pass

    def load(self, path: str):
        """Restore state from a previous save if the file exists."""
        try:
            with open(path) as f:
                data = json.load(f)
            with self._lock:
                self._current_photo = data.get('current_photo', '')
        except (OSError, json.JSONDecodeError):
            pass

    # ── Weather ───────────────────────────────────────────────────────────────

    @property
    def weather_data(self):
        with self._lock:
            return self._weather_data

    @weather_data.setter
    def weather_data(self, value):
        with self._lock:
            self._weather_data = value
