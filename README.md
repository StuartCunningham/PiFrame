# PiFrame

A self-hosted digital photo frame for Raspberry Pi. Displays photos and videos in a fullscreen slideshow, with a browser-based control panel for managing content and settings.

Supports HDMI monitors and Inky Impression e-ink displays. Runs as a systemd service and resumes where it left off after a reboot.

---

## Features

- Fullscreen slideshow with fade or cut transitions
- **Video support** — plays mp4, mov, mkv, avi, webm via mpv; per-clip volume, framing (fill/letterbox/stretch), pan and zoom
- **Library browser** — thumbnail grid organised by folder; click any file to edit its settings without touching config files
- **Overlays** — clock (with 5 quick presets), weather (OpenWeatherMap), photo info (EXIF date + filename)
- **Fonts** — global font family setting with per-overlay overrides; 10 named families included
- **OneDrive sync** — pull photos automatically from a OneDrive folder
- **Schedule** — turn the display on/off at set times (blank screen or HDMI power-off)
- Per-file metadata sidecars — skip, duration, fit mode, caption, video framing — saved as `.json` files beside each photo/video
- State persists across restarts: resumes at the last displayed file
- Thumbnail cache — instant library page loads after the first visit

---

## Hardware

| Component | Notes |
|-----------|-------|
| Raspberry Pi 3B+ / 4 / 5 | Pi 4 or 5 recommended for video |
| HDMI display | Any resolution; 1080p default |
| Inky Impression (optional) | 5.7″ or 7.3″ e-ink; HDMI and e-ink are mutually exclusive |
| SD card | 16 GB+ |

---

## Installation

```bash
git clone https://github.com/youruser/PiFrame.git
cd PiFrame
bash setup.sh
```

The script will:

1. Install system packages (`python3`, `pygame`, `mpv`, `ffmpeg`, DejaVu + Free fonts, etc.)
2. Create a Python virtual environment and install Python dependencies
3. Generate `secrets.yaml` with a random session key and optional web UI password
4. Optionally install and enable the systemd service
5. Optionally enable desktop auto-login (required for HDMI mode)
6. Disable screen blanking
7. Optionally add passwordless `sudo` rules for the web UI's Restart and Reboot buttons

### Manual run (no service)

```bash
source venv/bin/activate
python run.py
```

---

## Configuration

Settings are split across two files in the project root:

| File | Purpose | Git-tracked |
|------|---------|-------------|
| `config.yaml` | All non-secret settings | Yes |
| `secrets.yaml` | API keys, passwords, session key | No (gitignored) |

Most settings can be changed through the web UI. Direct YAML editing is also fine — the service picks up changes on the next photo advance or after a restart.

### config.yaml reference

```yaml
display:
  mode: hdmi          # hdmi | eink
  hdmi:
    width: 1920
    height: 1080
    fullscreen: true
    rotation: 0       # 0 | 90 | 180 | 270
    background_color: [0, 0, 0]
    hide_cursor: true
    brightness: 1.0   # software brightness via xrandr (X11 only)
  eink:
    model: '7.3'      # '7.3' | '5.7'
    rotation: 0       # 0 | 180
    saturation: 0.5

fonts:
  global: dejavu-bold   # key from the font table below

slideshow:
  photo_dir: photos     # relative or absolute path
  interval: 60          # seconds per photo
  shuffle: true
  transition: fade      # fade | cut
  fit_mode: fill        # fill | fit | stretch | center
  recursive: true       # include sub-folders
  supported_formats: [jpg, jpeg, png, bmp, gif, webp]
  video:
    enabled: false
    volume: 50          # 0–100
    formats: [mp4, mov, avi, mkv, webm, m4v]

overlays:
  clock:
    enabled: true
    position: bottom-right   # see positions below
    time_format: '%-H:%M'
    show_date: true
    date_format: '%A, %-d %B'
    font_size: 52
    font: ''                 # empty = use fonts.global
    color: [255, 255, 255]
    shadow: true
    background: true
    background_opacity: 120  # 0–255
  weather:
    enabled: false
    position: bottom-left
    font_size: 40
    font: ''
    color: [255, 255, 255]
    shadow: true
    background: false
    background_opacity: 120
    units: imperial      # metric | imperial
    update_interval: 1800
  photo_info:
    enabled: false
    position: bottom-center
    font_size: 30
    font: ''
    color: [220, 220, 220]
    shadow: true
    show_date_taken: true
    show_filename: false

schedule:
  enabled: false
  on_time: '07:00'
  off_time: '22:00'
  off_action: blank    # blank | off  (off = HDMI power-off via vcgencmd)

web:
  enabled: true
  host: 0.0.0.0
  port: 8080
```

**Overlay positions:** `top-left`, `top-center`, `top-right`, `bottom-left`, `bottom-center`, `bottom-right`

### secrets.yaml reference

```yaml
web:
  password: ''          # blank = no login required
  secret_key: 'random hex string — do not share'
overlays:
  weather:
    api_key: 'your OpenWeatherMap key'
onedrive:
  client_id: 'your Azure app (client) ID'
```

---

## Web UI

Access at `http://<pi-ip>:8080` from any browser on your network.

### Dashboard

Live status: current photo/video, index, play/pause state. Controls: previous, play/pause, next, rescan. OneDrive sync status and trigger.

### Library

Browse all photos and videos in the configured folder, organised by sub-folder. Click any thumbnail to open the editor panel.

**Photo editor:**
- Skip this file
- Fit mode override (fill, fit, stretch, center)
- Duration override (seconds)
- Caption text, position, font size

**Video editor:**
- Skip this file
- Per-clip volume override
- Framing: Fill (crop) / Letterbox / Stretch
- Pan X / Pan Y sliders (−1 to +1) — available in Fill mode
- Zoom slider (−1 to +1)
- Live framing preview showing the video content relative to the display frame

Settings are saved as a `.json` sidecar file next to each photo/video.

### Settings

Tabs: Slideshow, Display, Schedule, Overlays, OneDrive, System.

**Overlays tab** includes a global font selector at the top, then per-overlay font overrides. The Clock card has five quick presets (Minimal, Standard, Bold, Elegant, Matrix) that pre-fill the form fields.

The active tab is remembered across saves.

---

## Fonts

Ten named font families are available. Set `fonts.global` for a sitewide default; override per overlay with the `font` key.

| Key | Family |
|-----|--------|
| `dejavu-bold` | DejaVu Sans Bold *(default)* |
| `dejavu` | DejaVu Sans |
| `dejavu-serif-bold` | DejaVu Serif Bold |
| `dejavu-serif` | DejaVu Serif |
| `dejavu-mono-bold` | DejaVu Mono Bold |
| `dejavu-mono` | DejaVu Mono |
| `freesans-bold` | Free Sans Bold |
| `freesans` | Free Sans |
| `freeserif-bold` | Free Serif Bold |
| `freeserif` | Free Serif |

Fonts not present on disk are skipped gracefully, falling back to the next available family.

---

## Videos

Enable videos in **Settings → Slideshow → Enable videos**. `mpv` and `ffmpeg` must be installed (both are included in the setup script).

Videos play fullscreen via mpv and are mixed into the slideshow with photos. When a video ends, the slideshow advances normally. Pressing Next during playback skips to the next file immediately.

**Global settings** (Settings → Slideshow):
- Enable/disable videos
- Global volume (0–100)

**Per-clip settings** (Library → select video):
- Volume override
- Framing mode: Fill (crop to cover), Letterbox (bars), Stretch
- Pan X / Pan Y: shift the crop window (Fill mode only)
- Zoom: additional scale factor

**Supported formats:** mp4, mov, avi, mkv, webm, m4v

---

## Per-file metadata (JSON sidecars)

PiFrame stores per-file settings in a `.json` file with the same name as the media file:

```
photos/
  holiday.jpg
  holiday.json     ← sidecar
  2024/
    beach.mp4
    beach.json
```

**Photo fields:**

| Key | Type | Description |
|-----|------|-------------|
| `skip` | bool | Exclude from slideshow |
| `duration` | int | Display time in seconds (overrides global interval) |
| `fit_mode` | string | `fill` \| `fit` \| `stretch` \| `center` |
| `caption` | string | Overlay text |
| `caption_position` | string | Position key (e.g. `bottom-center`) |
| `caption_font_size` | int | Caption font size |

**Video fields:**

| Key | Type | Description |
|-----|------|-------------|
| `skip` | bool | Exclude from slideshow |
| `volume` | int | 0–100 (overrides global video volume) |
| `video_fit` | string | `fill` \| `fit` \| `stretch` |
| `video_pan_x` | float | −1.0 to 1.0; shifts crop left/right (fill only) |
| `video_pan_y` | float | −1.0 to 1.0; shifts crop up/down (fill only) |
| `video_zoom` | float | −1.0 to 1.0; additional zoom |

---

## OneDrive sync

1. Register an app at [portal.azure.com](https://portal.azure.com) — add a Mobile/Desktop redirect URI of `https://login.microsoftonline.com/common/oauth2/nativeclient` and enable the `Files.Read` scope.
2. Copy the Application (client) ID to **Settings → OneDrive → Azure App ID**, or into `secrets.yaml` as `onedrive.client_id`.
3. Go to **OneDrive** in the web UI and click **Authenticate** to complete device-flow login.
4. Set the OneDrive folder path (default `/Pictures/PiFrame`) and sync interval.

Photos are downloaded to the local `photo_dir`. The service re-scans the folder every 5 minutes; a manual rescan can be triggered from the Dashboard.

---

## Schedule

Enable in **Settings → Schedule**. The display turns on at `on_time` and off at `off_time`. Overnight schedules (e.g. on at 20:00, off at 08:00) are supported.

`off_action`:
- `blank` — fills the screen black (service keeps running)
- `off` — sends an HDMI power-off signal via `vcgencmd display_power 0` (Pi only)

---

## Keyboard shortcuts (on the Pi)

| Shortcut | Action |
|----------|--------|
| `Ctrl + W` | Toggle fullscreen / windowed |
| `Ctrl + D` | Minimise to taskbar |
| `Esc` | Quit PiFrame |

---

## File structure

```
PiFrame/
├── run.py                  # Entry point
├── config.yaml             # Main configuration
├── secrets.yaml            # Credentials (gitignored)
├── setup.sh                # One-shot setup script
├── requirements.txt        # Python dependencies
├── photos/                 # Default media folder (gitignored)
├── .thumbcache/            # Generated thumbnails (gitignored)
├── .piframe_state.json     # Resume state (gitignored)
├── service/
│   └── piframe.service     # systemd unit template
└── piframe/
    ├── config.py           # Config load/save with secrets split
    ├── state.py            # Thread-safe shared state + persistence
    ├── slideshow.py        # Main loop: photo + video scheduling
    ├── display/
    │   ├── hdmi.py         # pygame display driver + mpv video player
    │   └── eink.py         # Inky Impression driver
    ├── overlay/
    │   ├── _base.py        # Font registry, text rendering helpers
    │   ├── engine.py       # Composite all overlays onto a frame
    │   ├── clock.py        # Clock / date overlay
    │   ├── weather.py      # OpenWeatherMap overlay
    │   └── photo_info.py   # EXIF date + filename overlay
    ├── sync/
    │   └── onedrive.py     # MSAL device-flow + background sync
    └── web/
        ├── app.py          # Flask routes + settings parser
        └── templates/      # Jinja2 templates (base, index, library, settings, …)
```

---

## Troubleshooting

**Display is blank / pygame can't find a screen**

PiFrame needs a running desktop session. Enable auto-login to desktop with `sudo raspi-config` (Boot Options → Desktop Autologin) or re-run `setup.sh`. The service reads the Wayland/X11 socket automatically when launched over SSH.

**Videos don't play**

Check that `mpv` is installed (`mpv --version`). On Wayland, ensure the session is running before the service starts. Check logs with `journalctl -u piframe -f`.

**Video thumbnails show 404**

`ffmpeg` is required for video thumbnails. Install with `sudo apt install ffmpeg`.

**Restart / Reboot buttons don't work**

The web UI uses `sudo systemctl` to restart the service or reboot. Re-run `setup.sh` and answer Yes when asked about sudoers, or add the rules manually:

```bash
SYSTEMCTL=$(which systemctl)
echo "$USER ALL=(ALL) NOPASSWD: $SYSTEMCTL restart piframe" | sudo tee /etc/sudoers.d/piframe
echo "$USER ALL=(ALL) NOPASSWD: $SYSTEMCTL reboot"          | sudo tee -a /etc/sudoers.d/piframe
sudo chmod 0440 /etc/sudoers.d/piframe
```

**Weather overlay shows nothing**

Verify the API key in `secrets.yaml` (`overlays.weather.api_key`) and that the location string is valid (city name or `lat,lon`). The overlay fetches in the background — allow up to `update_interval` seconds on first start.

**Settings changes don't take effect without restarting**

Most settings apply to the next photo shown. Overlay appearance updates on the next photo transition. Display resolution and web port changes require a service restart.

**Thumbnail cache is stale**

Delete `.thumbcache/` and reload the Library page to regenerate all thumbnails.

---

## Development

```bash
source venv/bin/activate
python run.py          # runs with display (needs a screen)
```

The Flask web UI runs on a daemon thread; the slideshow runs on the main thread (required by pygame). Environment variables `DISPLAY` or `WAYLAND_DISPLAY` are auto-detected if not set.

Python 3.11+ is required (uses `str | None` union syntax).

---

## License

GPL v3 — see [LICENSE](LICENSE).
