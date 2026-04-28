#!/usr/bin/env python3
"""PiFrame entry point."""
import os
import sys
import threading
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('piframe')

# ── Resolve project root so relative paths in config work ─────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

from piframe.config import Config
from piframe.state import State
from piframe.display import create_display
from piframe.overlay import OverlayEngine
from piframe.slideshow import Slideshow


def main():
    config = Config('config.yaml')
    state = State()
    state.load('.piframe_state.json')

    # ── OneDrive sync ──────────────────────────────────────────────────────────
    sync = None
    if config.onedrive.get('enabled') and config.onedrive.get('client_id'):
        try:
            from piframe.sync import OneDriveSync
            sync = OneDriveSync(config, state)
            sync.start_background()
            log.info('OneDrive sync started (interval %ds)',
                     config.onedrive['sync_interval'])
        except Exception as exc:
            log.warning('OneDrive sync disabled: %s', exc)

    # ── Web UI ─────────────────────────────────────────────────────────────────
    if config.web.get('enabled', True):
        try:
            from piframe.web import create_app
            app = create_app(config, state, sync)
            host = config.web.get('host', '0.0.0.0')
            port = config.web.get('port', 8080)

            web_thread = threading.Thread(
                target=lambda: app.run(host=host, port=port,
                                       use_reloader=False, debug=False),
                daemon=True,
                name='web-ui',
            )
            web_thread.start()
            log.info('Web UI available at http://<pi-ip>:%d', port)
        except Exception as exc:
            log.warning('Web UI disabled: %s', exc)

    # ── Display + slideshow (main thread) ──────────────────────────────────────
    display = create_display(config)
    overlay = OverlayEngine(config, state)
    slideshow = Slideshow(config, state, display, overlay)

    log.info('Starting PiFrame in %s mode', config.display['mode'])
    try:
        slideshow.run()
    except KeyboardInterrupt:
        log.info('Shutting down.')
    finally:
        if sync:
            sync.stop_background()


if __name__ == '__main__':
    main()
