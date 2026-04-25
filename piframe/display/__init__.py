from .hdmi import HDMIDisplay
from .eink import EinkDisplay


def create_display(config):
    mode = config.display.get('mode', 'hdmi')
    if mode == 'eink':
        return EinkDisplay(config)
    return HDMIDisplay(config)
