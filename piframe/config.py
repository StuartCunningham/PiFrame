import copy
import os
import uuid
import yaml

_DEFAULTS = {
    'display': {
        'mode': 'hdmi',
        'hdmi': {
            'width': 1920, 'height': 1080, 'fullscreen': True,
            'rotation': 0, 'background_color': [0, 0, 0], 'hide_cursor': True,
            'brightness': 1.0,
        },
        'eink': {'model': '7.3', 'rotation': 0, 'saturation': 0.5},
    },
    'slideshow': {
        'photo_dir': 'photos', 'interval': 60, 'shuffle': True,
        'transition': 'fade', 'fit_mode': 'fill', 'recursive': True,
        'supported_formats': ['jpg', 'jpeg', 'png', 'bmp', 'gif', 'webp'],
        'video': {
            'enabled': False,
            'volume': 50,
            'formats': ['mp4', 'mov', 'avi', 'mkv', 'webm', 'm4v'],
        },
    },
    'onedrive': {
        'enabled': False, 'client_id': '', 'folder_path': '/Pictures/PiFrame',
        'sync_subfolders': False, 'sync_interval': 3600,
        'delete_local_removed': False, 'token_file': '.piframe_token.json',
    },
    'fonts': {
        'global': 'dejavu-bold',
    },
    'overlays': {
        'clock': {
            'enabled': False, 'position': 'bottom-right',
            'time_format': '%-H:%M', 'show_date': True,
            'date_format': '%A, %-d %B', 'font_size': 52,
            'color': [255, 255, 255], 'shadow': True,
            'background': True, 'background_opacity': 120,
            'font': '',
        },
        'weather': {
            'enabled': False, 'api_key': '', 'location': '',
            'units': 'metric', 'position': 'bottom-left', 'show_icon': True,
            'show_humidity': False,
            'font_size': 40, 'color': [255, 255, 255], 'shadow': True,
            'background': True, 'background_opacity': 120,
            'update_interval': 1800, 'font': '',
        },
        'photo_info': {
            'enabled': False, 'show_filename': False, 'show_date_taken': True,
            'position': 'bottom-center', 'font_size': 30,
            'color': [220, 220, 220], 'shadow': True, 'background': False,
            'background_opacity': 120, 'font': '',
        },
    },
    'schedule': {
        'enabled': False, 'on_time': '07:00', 'off_time': '22:00',
        'off_action': 'blank',
    },
    'web': {
        'enabled': True, 'host': '0.0.0.0', 'port': 8080,
        'password': '', 'secret_key': 'change-me-please',
    },
}

# Fields stored in secrets.yaml instead of config.yaml
_SECRET_PATHS = (
    ('web', 'secret_key'),
    ('web', 'password'),
    ('overlays', 'weather', 'api_key'),
    ('overlays', 'weather', 'location'),
    ('onedrive', 'client_id'),
)


def _deep_merge(base, override):
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _get_nested(d, keys):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _set_nested(d, keys, value):
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def _del_nested(d, keys):
    for k in keys[:-1]:
        if not isinstance(d, dict) or k not in d:
            return
        d = d[k]
    if isinstance(d, dict):
        d.pop(keys[-1], None)


class Config:
    def __init__(self, path='config.yaml', secrets_path='secrets.yaml'):
        self._path = path
        self._secrets_path = secrets_path
        self._data = copy.deepcopy(_DEFAULTS)
        self.load()
        self._ensure_secret_key()

    def _ensure_secret_key(self):
        """Replace the shipped default secret_key with a random UUID on first run."""
        if self._data['web'].get('secret_key') == 'change-me-please':
            self._data['web']['secret_key'] = str(uuid.uuid4())
            secrets = {}
            for path in _SECRET_PATHS:
                val = _get_nested(self._data, path)
                if val is not None:
                    _set_nested(secrets, path, val)
            with open(self._secrets_path, 'w') as f:
                yaml.dump(secrets, f, default_flow_style=False, allow_unicode=True)

    def load(self):
        if os.path.exists(self._path):
            with open(self._path, 'r') as f:
                on_disk = yaml.safe_load(f) or {}
            self._data = _deep_merge(_DEFAULTS, on_disk)
        if os.path.exists(self._secrets_path):
            with open(self._secrets_path, 'r') as f:
                secrets_data = yaml.safe_load(f) or {}
            self._data = _deep_merge(self._data, secrets_data)

    def save(self):
        """Write non-secret settings to config.yaml."""
        data = copy.deepcopy(self._data)
        for path in _SECRET_PATHS:
            _del_nested(data, path)
        with open(self._path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    def save_secrets(self):
        """Write secret fields to secrets.yaml (only if the file already exists)."""
        if not os.path.exists(self._secrets_path):
            return
        secrets = {}
        for path in _SECRET_PATHS:
            val = _get_nested(self._data, path)
            if val is not None:
                _set_nested(secrets, path, val)
        with open(self._secrets_path, 'w') as f:
            yaml.dump(secrets, f, default_flow_style=False, allow_unicode=True)

    def get(self, *keys, default=None):
        node = self._data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def set(self, keys, value):
        """Set a nested key given a list of key segments."""
        node = self._data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value

    def update(self, partial: dict):
        """Deep-merge a partial config dict and persist to both files."""
        self._data = _deep_merge(self._data, partial)
        self.save()
        self.save_secrets()

    # Convenience accessors — return copies so callers can't mutate internal state
    @property
    def display(self): return copy.deepcopy(self._data['display'])
    @property
    def slideshow(self): return copy.deepcopy(self._data['slideshow'])
    @property
    def onedrive(self): return copy.deepcopy(self._data['onedrive'])
    @property
    def overlays(self): return copy.deepcopy(self._data['overlays'])
    @property
    def schedule(self): return copy.deepcopy(self._data['schedule'])
    @property
    def web(self): return copy.deepcopy(self._data['web'])
    @property
    def fonts(self): return copy.deepcopy(self._data.get('fonts', {}))

    def as_dict(self):
        return copy.deepcopy(self._data)
