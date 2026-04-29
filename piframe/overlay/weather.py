"""Weather overlay — fetches from OpenWeatherMap and renders onto the image."""
import threading
import time
import requests
from PIL import Image

from ._base import get_font, parse_color, draw_text_with_bg

# Map OWM icon codes to simple unicode symbols (fallback when icon disabled)
_ICON_MAP = {
    '01': '☀',   # ☀ sun
    '02': '⛅',   # ⛅ sun behind cloud
    '03': '☁',   # ☁ cloud
    '04': '☁',   # ☁ cloud
    '09': '☂',   # ☂ rain/umbrella
    '10': '☂',   # ☂ light rain
    '11': '⚡',   # ⚡ thunderstorm
    '13': '❄',   # ❄ snowflake
    '50': '≈',   # ≈ mist/fog
}


class WeatherOverlay:
    def __init__(self, config, state):
        self._config = config
        self._state = state
        self._last_fetch = 0
        self._lock = threading.Lock()
        self._cached: dict | None = None

    def draw(self, image: Image.Image) -> Image.Image:
        cfg = self._config.overlays['weather']
        self._maybe_refresh(cfg)

        data = self._state.weather_data
        if not data:
            return image

        units = cfg.get('units', 'metric')
        degree = '°C' if units == 'metric' else '°F'
        temp = round(data.get('temp', 0))
        desc = data.get('description', '').capitalize()
        icon_code = data.get('icon', '01')[:2]

        parts = [f"{_ICON_MAP.get(icon_code, '')} {temp}{degree}  {desc}".strip()]
        if cfg.get('show_humidity') and 'humidity' in data:
            parts[0] += f"  💧{data['humidity']}%"
        line = parts[0]

        family = cfg.get('font') or self._config.get('fonts', 'global', default='dejavu-bold')
        font = get_font(cfg['font_size'], family)
        color = parse_color(cfg['color'])

        return draw_text_with_bg(
            image, [line], [font], color,
            position=cfg['position'],
            shadow=cfg.get('shadow', True),
            bg=cfg.get('background', True),
            bg_opacity=cfg.get('background_opacity', 120),
        )

    def _maybe_refresh(self, cfg):
        interval = cfg.get('update_interval', 1800)
        now = time.time()
        with self._lock:
            if now - self._last_fetch < interval:
                return
            if not cfg.get('api_key') or not cfg.get('location'):
                return
            self._last_fetch = now
        threading.Thread(target=self._fetch, args=(cfg,), daemon=True).start()

    def _fetch(self, cfg):
        try:
            location = cfg['location']
            units = cfg.get('units', 'metric')
            key = cfg['api_key']

            if ',' in location and all(
                p.strip().replace('.', '').replace('-', '').isdigit()
                for p in location.split(',')
            ):
                lat, lon = [p.strip() for p in location.split(',')]
                url = (
                    f"https://api.openweathermap.org/data/2.5/weather"
                    f"?lat={lat}&lon={lon}&units={units}&appid={key}"
                )
            else:
                url = (
                    f"https://api.openweathermap.org/data/2.5/weather"
                    f"?q={location}&units={units}&appid={key}"
                )

            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            self._state.weather_data = {
                'temp': data['main']['temp'],
                'description': data['weather'][0]['description'],
                'icon': data['weather'][0]['icon'],
                'humidity': data['main']['humidity'],
                'city': data.get('name', ''),
            }
        except Exception:
            pass  # Keep stale data on failure
