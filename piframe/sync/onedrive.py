"""OneDrive photo sync via Microsoft Graph API (device-code OAuth2 flow)."""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import msal
import requests

GRAPH_BASE = 'https://graph.microsoft.com/v1.0'
SCOPES = ['Files.Read', 'offline_access']
IMAGE_MIMES = {'image/jpeg', 'image/png', 'image/gif', 'image/bmp',
               'image/webp', 'image/tiff'}
_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'}


class OneDriveSync:
    def __init__(self, config, state):
        self._config = config
        self._state = state
        self._token_cache = msal.SerializableTokenCache()
        self._app: msal.PublicClientApplication | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._load_cache()

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _get_app(self) -> msal.PublicClientApplication:
        if self._app is None:
            self._app = msal.PublicClientApplication(
                self._config.onedrive['client_id'],
                token_cache=self._token_cache,
            )
        return self._app

    def _load_cache(self):
        path = self._config.onedrive.get('token_file', '.piframe_token.json')
        if os.path.exists(path):
            with open(path) as f:
                self._token_cache.deserialize(f.read())
            self._state.onedrive_authenticated = self._get_token() is not None

    def _save_cache(self):
        if self._token_cache.has_state_changed:
            path = self._config.onedrive.get('token_file', '.piframe_token.json')
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(self._token_cache.serialize())

    def _get_token(self) -> str | None:
        app = self._get_app()
        accounts = app.get_accounts()
        if not accounts:
            return None
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and 'access_token' in result:
            self._save_cache()
            return result['access_token']
        return None

    def start_device_flow(self) -> dict:
        """Initiate device-code flow. Returns dict with user_code and verification_uri."""
        if not self._config.onedrive.get('client_id'):
            raise ValueError('No client_id configured in onedrive settings.')
        flow = self._get_app().initiate_device_flow(scopes=SCOPES)
        self._state.auth_flow = flow
        return flow

    def poll_device_flow(self) -> bool:
        """Poll for token after user has authenticated. Returns True on success."""
        flow = self._state.auth_flow
        if not flow:
            return False
        result = self._get_app().acquire_token_by_device_flow(flow)
        if 'access_token' in result:
            self._save_cache()
            self._state.onedrive_authenticated = True
            self._state.auth_flow = None
            return True
        return False

    def revoke(self):
        """Sign out — delete cached token."""
        path = self._config.onedrive.get('token_file', '.piframe_token.json')
        if os.path.exists(path):
            os.remove(path)
        self._token_cache = msal.SerializableTokenCache()
        self._app = None
        self._state.onedrive_authenticated = False

    # ── Sync ──────────────────────────────────────────────────────────────────

    def sync(self):
        """Download new/changed photos from OneDrive. Blocking."""
        if self._state.syncing:
            return
        self._state.syncing = True
        self._state.sync_status = 'Syncing…'

        token = self._get_token()
        if not token:
            self._state.sync_status = 'Not authenticated'
            self._state.syncing = False
            return

        headers = {'Authorization': f'Bearer {token}'}
        folder = self._config.onedrive['folder_path'].rstrip('/')
        photo_dir = Path(self._config.slideshow['photo_dir'])
        photo_dir.mkdir(parents=True, exist_ok=True)

        try:
            synced = self._sync_folder(headers, folder, photo_dir)
            self._state.sync_status = f'OK — {synced} new file(s)'
            self._state.last_sync = datetime.now()
        except requests.HTTPError as exc:
            self._state.sync_status = f'HTTP {exc.response.status_code}'
        except Exception as exc:
            self._state.sync_status = f'Error: {exc}'
        finally:
            self._state.syncing = False

    def _sync_folder(self, headers, folder_path: str, local_dir: Path,
                     depth: int = 0) -> int:
        synced = 0
        remote_names: set[str] = set()
        url = f"{GRAPH_BASE}/me/drive/root:{folder_path}:/children"

        while url:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get('value', []):
                if 'folder' in item and self._config.onedrive.get('sync_subfolders') and depth == 0:
                    sub_path = f"{folder_path}/{item['name']}"
                    sub_dir = local_dir / item['name']
                    sub_dir.mkdir(exist_ok=True)
                    synced += self._sync_folder(headers, sub_path, sub_dir, depth + 1)
                    continue

                if 'file' not in item:
                    continue
                if item['file'].get('mimeType') not in IMAGE_MIMES:
                    continue

                name = item['name']
                remote_names.add(name)
                local_path = local_dir / name
                remote_size = item.get('size', -1)

                if local_path.exists() and local_path.stat().st_size == remote_size:
                    continue

                dl_url = item.get('@microsoft.graph.downloadUrl')
                if dl_url:
                    tmp_path = local_path.with_suffix(local_path.suffix + '.tmp')
                    r = requests.get(dl_url, stream=True, timeout=60)
                    r.raise_for_status()
                    with open(tmp_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            f.write(chunk)
                    os.replace(tmp_path, local_path)
                    synced += 1

            url = data.get('@odata.nextLink')

        if self._config.onedrive.get('delete_local_removed'):
            for f in local_dir.iterdir():
                if f.is_file() and f.suffix.lower() in _IMAGE_EXTS and f.name not in remote_names:
                    f.unlink()

        return synced

    # ── Background thread ─────────────────────────────────────────────────────

    def start_background(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop_background(self):
        self._stop.set()

    def _run(self):
        interval = self._config.onedrive.get('sync_interval', 3600)
        # Initial sync shortly after start
        time.sleep(10)
        while not self._stop.is_set():
            if self._state.onedrive_authenticated:
                self.sync()
            self._stop.wait(interval)
