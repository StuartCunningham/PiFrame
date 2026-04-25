"""Flask web UI for PiFrame — settings, controls, OneDrive auth."""
import os
import threading
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, redirect, url_for, request,
                   jsonify, session, flash)


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
            if request.form.get('password') == config.web.get('password', ''):
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
        action = request.json.get('action')
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

    @app.route('/api/sync', methods=['POST'])
    @login_required
    def api_sync():
        if sync and not state.syncing:
            threading.Thread(target=sync.sync, daemon=True).start()
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
        return render_template('settings.html', config=config)

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
        'display': {
            'mode': form.get('display_mode', 'hdmi'),
            'hdmi': {
                'width': _int(form, 'hdmi_width', 1920),
                'height': _int(form, 'hdmi_height', 1080),
                'fullscreen': _bool(form, 'hdmi_fullscreen'),
                'rotation': _int(form, 'hdmi_rotation', 0),
                'background_color': _color(form, 'hdmi_bg_color', [0, 0, 0]),
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
            },
            'photo_info': {
                'enabled': _bool(form, 'info_enabled'),
                'show_filename': _bool(form, 'info_show_filename'),
                'show_date_taken': _bool(form, 'info_show_date'),
                'position': form.get('info_position', 'bottom-center'),
                'font_size': _int(form, 'info_font_size', 30),
                'color': _color(form, 'info_color', [220, 220, 220]),
                'shadow': _bool(form, 'info_shadow'),
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
            'password': form.get('web_password', ''),
        },
    }
    config.update(update)
