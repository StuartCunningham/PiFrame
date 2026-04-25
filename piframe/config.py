import copy
import os
import yaml

_DEFAULTS = {
    'display': {
        'mode': 'hdmi',
        'hdmi': {
            'width': 1920, 'height': 1080, 'fullscreen': True,
            'rotation': 0, 'background_color': [0, 0, 0], 'hide_cursor': True,
        },
        'eink': {'model': '7.3', 'rotation': 0, 'saturation': 0.5},
    },
    'slideshow': {
        'photo_dir': 'photos', 'interval': 60, 'shuffle': True,
        'transition': 'fade', 'fit_mode': 'fill', 'recursive': True,
        'supported_formats': ['jpg', 'jpeg', 'png', 'bmp', 'gif', 'webp'],
    },
    'onedrive': {
        'enabled': False, 'client_id': '', 'folder_path': '/Pictures/PiFrame',
        'sync_subfolders': False, 'sync_interval': 3600,
        'delete_local_removed': False, 'token_file': '.piframe_token.json',
    },
    'overlays': {
        'clock': {
            'enabled': False, 'position': 'bottom-right',
            'time_format': '%-H:%M', 'show_date': True,
            'date_format': '%A, %-d %B', 'font_size': 52,
            'color': [255, 255, 255], 'shadow': True,
            'background': True, 'background_opacity': 120,
        },
        'weather': {
            'enabled': False, 'api_key': '', 'location': '',
            'units': 'metric', 'position': 'bottom-left', 'show_icon': True,
            'font_size': 40, 'color': [255, 255, 255], 'shadow': True,
            'background': True, 'background_opacity': 120,
            'update_interval': 1800,
        },
        'photo_info': {
            'enabled': False, 'show_filename': False, 'show_date_taken': True,
            'position': 'bottom-center', 'font_size': 30,
            'color': [220, 220, 220], 'shadow': True,
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


def _deep_merge(base, override):
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class Config:
    def __init__(self, path='config.yaml'):
        self._path = path
        self._data = copy.deepcopy(_DEFAULTS)
        self.load()

    def load(self):
        if os.path.exists(self._path):
            with open(self._path, 'r') as f:
                on_disk = yaml.safe_load(f) or {}
            self._data = _deep_merge(_DEFAULTS, on_disk)

    def save(self):
        with open(self._path, 'w') as f:
            yaml.dump(self._data, f, default_flow_style=False, allow_unicode=True)

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
        """Deep-merge a partial config dict and save."""
        self._data = _deep_merge(self._data, partial)
        self.save()

    # Convenience accessors
    @property
    def display(self): return self._data['display']
    @property
    def slideshow(self): return self._data['slideshow']
    @property
    def onedrive(self): return self._data['onedrive']
    @property
    def overlays(self): return self._data['overlays']
    @property
    def schedule(self): return self._data['schedule']
    @property
    def web(self): return self._data['web']

    def as_dict(self):
        return copy.deepcopy(self._data)
