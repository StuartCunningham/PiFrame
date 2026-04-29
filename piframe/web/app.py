"""Flask web UI for PiFrame — settings, controls, OneDrive auth."""
import hashlib
import io
import json
import os
import platform
import shutil
import socket
import subprocess
import threading
from datetime import datetime
from functools import wraps
from pathlib import Path

# ── Thumbnail cache ───────────────────────────────────────────────────────────
_THUMB_CACHE = Path('.thumbcache')
_THUMB_SIZE  = (400, 300)   # max thumbnail dimensions

def _make_thumbnail(p: Path) -> bytes | None:
    """Generate a JPEG thumbnail for any supported file. Returns bytes or None."""
    from piframe.slideshow import VIDEO_EXT
    if p.suffix.lower() in VIDEO_EXT:
        try:
            r = subprocess.run(
                ['ffmpeg', '-ss', '0', '-i', str(p),
                 '-frames:v', '1', '-vf', f'scale={_THUMB_SIZE[0]}:-1',
                 '-f', 'image2', '-vcodec', 'mjpeg', '-'],
                capture_output=True, timeout=15,
            )
            return r.stdout if r.returncode == 0 and r.stdout else None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
    else:
        try:
            buf = io.BytesIO()
            img = Image.open(str(p)).convert('RGB')
            img = ImageOps.exif_transpose(img)
            img.thumbnail(_THUMB_SIZE)
            img.save(buf, 'JPEG', quality=78)
            return buf.getvalue()
        except Exception:
            return None

def _get_thumbnail(p: Path) -> bytes | None:
    """Return cached thumbnail bytes, generating and saving to disk if needed."""
    try:
        key = hashlib.md5(f"{p}:{p.stat().st_mtime_ns}".encode()).hexdigest()
    except OSError:
        return None
    cache_file = _THUMB_CACHE / (key + '.jpg')
    if cache_file.exists():
        return cache_file.read_bytes()
    data = _make_thumbnail(p)
    if data:
        try:
            _THUMB_CACHE.mkdir(exist_ok=True)
            cache_file.write_bytes(data)
        except OSError:
            pass
    return data

from flask import (Flask, render_template, redirect, url_for, request,
                   jsonify, session, flash, send_file, abort)
from PIL import Image, ImageOps
from werkzeug.security import check_password_hash, generate_password_hash


def _is_hash(s: str) -> bool:
    return s.startswith(('pbkdf2:', 'scrypt:'))


def create_app(config, state, sync=None):
    app = Flask(__name__, template_folder='templates')
    app.secret_key = config.web.get('secret_key', 'piframe-secret')

    # ── Auth middleware ───────────────────────────────────────────────────────

    def login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            password = config.web.get('password', '')
            if password and not session.get('authenticated'):
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            stored = config.web.get('password', '')
            entered = request.form.get('password', '')
            ok = (check_password_hash(stored, entered)
                  if _is_hash(stored) else entered == stored)
            if ok:
                session['authenticated'] = True
                return redirect(url_for('index'))
            flash('Incorrect password.')
        return render_template('login.html')

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    # ── Dashboard ─────────────────────────────────────────────────────────────

    @app.route('/')
    @login_required
    def index():
        return render_template('index.html', config=config, state=state)

    # ── REST controls (called by dashboard JS) ────────────────────────────────

    @app.route('/api/status')
    @login_required
    def api_status():
        current = state.current_photo
        last_sync = state.last_sync
        return jsonify({
            'paused': state.paused,
            'current_photo': os.path.basename(current) if current else '',
            'photo_index': state.photo_index + 1,
            'total_photos': state.total_photos,
            'sync_status': state.sync_status,
            'syncing': state.syncing,
            'last_sync': last_sync.strftime('%d %b %Y %H:%M') if last_sync else 'Never',
            'onedrive_enabled': config.onedrive['enabled'],
            'onedrive_authenticated': state.onedrive_authenticated,
        })

    @app.route('/api/control', methods=['POST'])
    @login_required
    def api_control():
        action = (request.get_json(silent=True) or {}).get('action')
        if action == 'next':
            state.send_command('next')
        elif action == 'prev':
            state.send_command('prev')
        elif action == 'pause':
            state.paused = True
        elif action == 'play':
            state.paused = False
        elif action == 'toggle':
            state.paused = not state.paused
        elif action == 'reload':
            state.send_command('reload')
        return jsonify({'ok': True})

    @app.route('/api/sysinfo')
    @login_required
    def api_sysinfo():
        hostname = socket.gethostname()
        try:
            addrs = socket.getaddrinfo(hostname, None)
            ip = next(
                (a[4][0] for a in addrs
                 if not a[4][0].startswith('127.') and a[4][0] != '::1'),
                'unknown',
            )
        except Exception:
            ip = 'unknown'
        disk = shutil.disk_usage('/')
        return jsonify({
            'hostname': hostname,
            'ip': ip,
            'python': platform.python_version(),
            'disk_used_gb': round(disk.used / 1e9, 1),
            'disk_free_gb': round(disk.free / 1e9, 1),
            'disk_total_gb': round(disk.total / 1e9, 1),
        })

    @app.route('/api/volume', methods=['POST'])
    @login_required
    def api_volume():
        volume = max(0, min(100, int((request.get_json(silent=True) or {}).get('volume', 50))))
        config.update({'slideshow': {'video': {'volume': volume}}})
        return jsonify({'ok': True})

    @app.route('/api/brightness', methods=['POST'])
    @login_required
    def api_brightness():
        brightness = max(0.1, min(1.0, float((request.get_json(silent=True) or {}).get('brightness', 1.0))))
        config.update({'display': {'hdmi': {'brightness': brightness}}})
        from piframe.display.hdmi import _xrandr_brightness
        _xrandr_brightness(brightness)
        return jsonify({'ok': True})

    @app.route('/api/browse')
    @login_required
    def api_browse():
        req = request.args.get('path', str(Path.home()))
        p = Path(req).resolve()
        allowed = [Path.home(), Path('/media'), Path('/mnt'), Path('/home')]
        if not any(str(p).startswith(str(r)) for r in allowed):
            p = Path.home()
        try:
            dirs = sorted(d.name for d in p.iterdir() if d.is_dir() and not d.name.startswith('.'))
        except PermissionError:
            dirs = []
        parent = str(p.parent) if p.parent != p else None
        return jsonify({'path': str(p), 'parent': parent, 'dirs': dirs})

    @app.route('/api/photo/current')
    @login_required
    def api_photo_current():
        path = state.current_photo
        if not path or not os.path.exists(path):
            abort(404)
        data = _get_thumbnail(Path(path))
        if not data:
            abort(404)
        return send_file(io.BytesIO(data), mimetype='image/jpeg')

    @app.route('/api/photo/meta')
    @login_required
    def api_photo_meta_get():
        path = state.current_photo
        if not path:
            return jsonify({'path': None, 'meta': {}})
        meta_file = Path(path).parent / (Path(path).stem + '.json')
        meta = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
            except Exception:
                pass
        return jsonify({'path': os.path.basename(path), 'meta': meta})

    @app.route('/api/photo/meta', methods=['POST'])
    @login_required
    def api_photo_meta_post():
        path = state.current_photo
        if not path:
            return jsonify({'ok': False, 'error': 'No current photo'})
        data = request.get_json(silent=True) or {}
        raw = data.get('meta', {})
        _allowed = {'fit_mode', 'caption', 'caption_position', 'caption_font_size',
                    'skip', 'duration', 'custom_scale', 'custom_pan_x', 'custom_pan_y'}
        meta = {}
        for k, v in raw.items():
            if k not in _allowed:
                continue
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            meta[k] = v
        meta_file = Path(path).parent / (Path(path).stem + '.json')
        if meta:
            meta_file.write_text(json.dumps(meta, indent=2))
        elif meta_file.exists():
            meta_file.unlink()
        return jsonify({'ok': True})

    @app.route('/api/system/restart', methods=['POST'])
    @login_required
    def api_system_restart():
        def _do():
            import time; time.sleep(0.5)
            subprocess.run(['sudo', '/usr/bin/systemctl', 'restart', 'piframe'])
        threading.Thread(target=_do, daemon=True).start()
        return jsonify({'ok': True})

    @app.route('/api/system/reboot', methods=['POST'])
    @login_required
    def api_system_reboot():
        def _do():
            import time; time.sleep(0.5)
            subprocess.run(['sudo', '/usr/bin/systemctl', 'reboot'])
        threading.Thread(target=_do, daemon=True).start()
        return jsonify({'ok': True})

    @app.route('/api/system/update', methods=['POST'])
    @login_required
    def api_system_update():
        root = Path(__file__).resolve().parent.parent.parent
        if not (root / '.git').exists():
            return jsonify({'ok': False, 'error': 'Not a git repository'}), 400
        try:
            result = subprocess.run(
                ['git', 'pull'],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=60,
            )
            return jsonify({
                'ok': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'changed': 'Already up to date' not in result.stdout,
            })
        except subprocess.TimeoutExpired:
            return jsonify({'ok': False, 'error': 'git pull timed out'}), 504
        except FileNotFoundError:
            return jsonify({'ok': False, 'error': 'git not found on this system'}), 500

    @app.route('/api/fonts')
    @login_required
    def api_fonts():
        from piframe.overlay._base import available_fonts
        return jsonify({'fonts': [{'key': k, 'name': n} for k, n in available_fonts()]})

    @app.route('/api/logs')
    @login_required
    def api_logs():
        from piframe.logbuffer import get_buffer
        since = int(request.args.get('since', 0))
        buf = get_buffer()
        return jsonify({'entries': buf.since(since), 'seq': buf.latest_seq()})

    @app.route('/api/sync', methods=['POST'])
    @login_required
    def api_sync():
        if sync and not state.syncing:
            threading.Thread(target=sync.sync, daemon=True).start()
        return jsonify({'ok': True})

    # ── Library ───────────────────────────────────────────────────────────────

    @app.route('/library')
    @login_required
    def library():
        return render_template('library.html', config=config, state=state)

    @app.route('/api/library')
    @login_required
    def api_library():
        from piframe.slideshow import VIDEO_EXT
        cfg = config.slideshow
        photo_dir = Path(cfg['photo_dir']).resolve()
        img_exts = {f'.{e.lower()}' for e in cfg.get('supported_formats', [])}
        video_exts = {f'.{e.lower()}' for e in cfg.get('video', {}).get('formats', [])}
        all_exts = img_exts | video_exts

        if not photo_dir.exists():
            return jsonify({'files': []})

        pattern = '**/*' if cfg.get('recursive', True) else '*'
        files = []
        for p in sorted(photo_dir.glob(pattern)):
            if p.is_file() and p.suffix.lower() in all_exts:
                is_video = p.suffix.lower() in video_exts
                files.append({
                    'path': str(p),
                    'name': p.name,
                    'rel': str(p.relative_to(photo_dir)),
                    'type': 'video' if is_video else 'photo',
                    'is_current': str(p) == state.current_photo,
                })
        return jsonify({'files': files})

    @app.route('/api/library/thumb')
    @login_required
    def api_library_thumb():
        from piframe.slideshow import VIDEO_EXT
        path_str = request.args.get('path', '')
        p = Path(path_str).resolve()
        photo_dir = Path(config.slideshow['photo_dir']).resolve()
        try:
            p.relative_to(photo_dir)
        except ValueError:
            abort(403)
        if not p.exists():
            abort(404)

        data = _get_thumbnail(p)
        if not data:
            abort(404)
        return send_file(io.BytesIO(data), mimetype='image/jpeg')

    @app.route('/api/media/info')
    @login_required
    def api_media_info():
        from piframe.slideshow import VIDEO_EXT
        path_str = request.args.get('path', '')
        p = Path(path_str).resolve()
        photo_dir = Path(config.slideshow['photo_dir']).resolve()
        try:
            p.relative_to(photo_dir)
        except ValueError:
            abort(403)
        if not p.exists():
            abort(404)

        is_video = p.suffix.lower() in VIDEO_EXT
        info = {'name': p.name, 'size': p.stat().st_size,
                'type': 'video' if is_video else 'photo', 'path': str(p)}

        if is_video:
            try:
                result = subprocess.run(
                    ['ffprobe', '-v', 'quiet', '-print_format', 'json',
                     '-show_streams', '-show_format', str(p)],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    for stream in data.get('streams', []):
                        if stream.get('codec_type') == 'video':
                            info['width'] = stream.get('width')
                            info['height'] = stream.get('height')
                            break
                    dur = float(data.get('format', {}).get('duration', 0) or 0)
                    info['duration'] = dur
                    info['duration_str'] = f"{int(dur // 60)}:{int(dur % 60):02d}"
            except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
                pass
        else:
            try:
                with Image.open(str(p)) as img:
                    info['width'], info['height'] = img.size
            except Exception:
                pass

        return jsonify(info)

    @app.route('/api/media/meta')
    @login_required
    def api_media_meta_get():
        path_str = request.args.get('path', '')
        p = Path(path_str).resolve()
        photo_dir = Path(config.slideshow['photo_dir']).resolve()
        try:
            p.relative_to(photo_dir)
        except ValueError:
            abort(403)
        meta_file = p.parent / (p.stem + '.json')
        meta = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
            except Exception:
                pass
        return jsonify({'path': str(p), 'meta': meta})

    @app.route('/api/media/meta', methods=['POST'])
    @login_required
    def api_media_meta_post():
        data = request.get_json(silent=True) or {}
        path_str = data.get('path', '')
        p = Path(path_str).resolve()
        photo_dir = Path(config.slideshow['photo_dir']).resolve()
        try:
            p.relative_to(photo_dir)
        except ValueError:
            return jsonify({'ok': False, 'error': 'Access denied'}), 403
        if not p.exists():
            return jsonify({'ok': False, 'error': 'File not found'}), 404

        _allowed = {
            'fit_mode', 'caption', 'caption_position', 'caption_font_size',
            'skip', 'duration', 'custom_scale', 'custom_pan_x', 'custom_pan_y',
            'video_fit', 'video_pan_x', 'video_pan_y', 'video_zoom', 'volume',
        }
        meta = {}
        for k, v in (data.get('meta') or {}).items():
            if k not in _allowed or v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            meta[k] = v

        meta_file = p.parent / (p.stem + '.json')
        if meta:
            meta_file.write_text(json.dumps(meta, indent=2))
        elif meta_file.exists():
            meta_file.unlink()
        return jsonify({'ok': True})

    # ── Settings ──────────────────────────────────────────────────────────────

    @app.route('/settings', methods=['GET', 'POST'])
    @login_required
    def settings():
        if request.method == 'POST':
            _apply_settings(request.form, config)
            state.send_command('reload')
            flash('Settings saved.')
            return redirect(url_for('settings'))
        from piframe.overlay._base import available_fonts
        return render_template('settings.html', config=config, fonts=available_fonts())

    # ── OneDrive ──────────────────────────────────────────────────────────────

    @app.route('/onedrive')
    @login_required
    def onedrive():
        return render_template('onedrive.html', config=config, state=state)

    @app.route('/onedrive/start-auth', methods=['POST'])
    @login_required
    def onedrive_start_auth():
        if not sync:
            flash('OneDrive is not configured.')
            return redirect(url_for('onedrive'))
        try:
            flow = sync.start_device_flow()
            return render_template('onedrive_auth.html',
                                   user_code=flow['user_code'],
                                   verification_uri=flow['verification_uri'],
                                   message=flow.get('message', ''))
        except Exception as exc:
            flash(f'Error: {exc}')
            return redirect(url_for('onedrive'))

    @app.route('/onedrive/poll-auth', methods=['POST'])
    @login_required
    def onedrive_poll_auth():
        if not sync:
            return jsonify({'ok': False, 'error': 'Not configured'})
        ok = sync.poll_device_flow()
        return jsonify({'ok': ok})

    @app.route('/onedrive/revoke', methods=['POST'])
    @login_required
    def onedrive_revoke():
        if sync:
            sync.revoke()
        flash('Signed out of OneDrive.')
        return redirect(url_for('onedrive'))

    @app.route('/onedrive/sync-now', methods=['POST'])
    @login_required
    def onedrive_sync_now():
        if sync and not state.syncing:
            threading.Thread(target=sync.sync, daemon=True).start()
        flash('Sync started.')
        return redirect(url_for('onedrive'))

    return app


# ── Settings form parser ───────────────────────────────────────────────────────

def _hash_password(new_pw: str, config) -> str:
    """Hash new_pw if provided; keep existing stored value if blank."""
    if not new_pw:
        return config.web.get('password', '')
    if _is_hash(new_pw):
        return new_pw
    return generate_password_hash(new_pw)


def _bool(form, key):
    return key in form and form[key] in ('on', '1', 'true', 'yes')


def _int(form, key, default=0):
    try:
        return int(form.get(key, default))
    except (ValueError, TypeError):
        return default


def _color(form, key, default):
    raw = form.get(key, '').strip()
    if raw.startswith('#') and len(raw) == 7:
        r = int(raw[1:3], 16)
        g = int(raw[3:5], 16)
        b = int(raw[5:7], 16)
        return [r, g, b]
    return default


def _apply_settings(form, config):
    update = {
        'fonts': {
            'global': form.get('fonts_global', 'dejavu-bold'),
        },
        'display': {
            'mode': form.get('display_mode', 'hdmi'),
            'hdmi': {
                'width': _int(form, 'hdmi_width', 1920),
                'height': _int(form, 'hdmi_height', 1080),
                'fullscreen': _bool(form, 'hdmi_fullscreen'),
                'rotation': _int(form, 'hdmi_rotation', 0),
                'background_color': _color(form, 'hdmi_bg_color', [0, 0, 0]),
                'brightness': round(float(form.get('hdmi_brightness', 1.0)), 2),
            },
            'eink': {
                'model': form.get('eink_model', '7.3'),
                'rotation': _int(form, 'eink_rotation', 0),
                'saturation': round(float(form.get('eink_saturation', 0.5)), 2),
            },
        },
        'slideshow': {
            'photo_dir': form.get('photo_dir', 'photos'),
            'interval': _int(form, 'interval', 60),
            'shuffle': _bool(form, 'shuffle'),
            'transition': form.get('transition', 'cut'),
            'fit_mode': form.get('fit_mode', 'fill'),
            'recursive': _bool(form, 'recursive'),
            'video': {
                'enabled': _bool(form, 'video_enabled'),
                'volume': _int(form, 'video_volume', 50),
            },
        },
        'onedrive': {
            'enabled': _bool(form, 'onedrive_enabled'),
            'client_id': form.get('onedrive_client_id', ''),
            'folder_path': form.get('onedrive_folder', '/Pictures/PiFrame'),
            'sync_subfolders': _bool(form, 'onedrive_sync_subfolders'),
            'sync_interval': _int(form, 'onedrive_sync_interval', 3600),
            'delete_local_removed': _bool(form, 'onedrive_delete_removed'),
        },
        'overlays': {
            'clock': {
                'enabled': _bool(form, 'clock_enabled'),
                'position': form.get('clock_position', 'bottom-right'),
                'time_format': form.get('clock_time_format', '%-H:%M'),
                'show_date': _bool(form, 'clock_show_date'),
                'date_format': form.get('clock_date_format', '%A, %-d %B'),
                'font_size': _int(form, 'clock_font_size', 52),
                'color': _color(form, 'clock_color', [255, 255, 255]),
                'shadow': _bool(form, 'clock_shadow'),
                'background': _bool(form, 'clock_background'),
                'background_opacity': _int(form, 'clock_bg_opacity', 120),
                'font': form.get('clock_font', ''),
            },
            'weather': {
                'enabled': _bool(form, 'weather_enabled'),
                'api_key': form.get('weather_api_key', ''),
                'location': form.get('weather_location', ''),
                'units': form.get('weather_units', 'metric'),
                'position': form.get('weather_position', 'bottom-left'),
                'show_icon': _bool(form, 'weather_show_icon'),
                'font_size': _int(form, 'weather_font_size', 40),
                'color': _color(form, 'weather_color', [255, 255, 255]),
                'shadow': _bool(form, 'weather_shadow'),
                'background': _bool(form, 'weather_background'),
                'background_opacity': _int(form, 'weather_bg_opacity', 120),
                'update_interval': _int(form, 'weather_update_interval', 1800),
                'font': form.get('weather_font', ''),
            },
            'photo_info': {
                'enabled': _bool(form, 'info_enabled'),
                'show_filename': _bool(form, 'info_show_filename'),
                'show_date_taken': _bool(form, 'info_show_date'),
                'position': form.get('info_position', 'bottom-center'),
                'font_size': _int(form, 'info_font_size', 30),
                'color': _color(form, 'info_color', [220, 220, 220]),
                'shadow': _bool(form, 'info_shadow'),
                'font': form.get('info_font', ''),
            },
        },
        'schedule': {
            'enabled': _bool(form, 'schedule_enabled'),
            'on_time': form.get('schedule_on', '07:00'),
            'off_time': form.get('schedule_off', '22:00'),
            'off_action': form.get('schedule_off_action', 'blank'),
        },
        'web': {
            'port': _int(form, 'web_port', 8080),
            'password': _hash_password(form.get('web_password', ''), config),
            'secret_key': form.get('web_secret_key') or config.web.get('secret_key', ''),
        },
    }
    config.update(update)
