"""E-ink display driver for Pimoroni Inky Impression."""
import logging
import os
from PIL import Image

_log = logging.getLogger(__name__)


def _check_spi():
    """Log an error if SPI doesn't appear to be enabled."""
    spi_devs = [e for e in os.listdir('/dev') if e.startswith('spidev')]
    if not spi_devs:
        _log.error(
            "No /dev/spidev* devices found — SPI is probably not enabled. "
            "Run: sudo raspi-config → Interface Options → SPI → Enable, then reboot."
        )
        return False
    _log.info("SPI devices present: %s", ', '.join(sorted(spi_devs)))
    return True


# Resolution map for supported Inky Impression models
_MODEL_SIZES = {
    '7.3': (800, 480),
    '5.7': (600, 448),
}


def _manual_init(model: str):
    """Manually initialise an Inky Impression when EEPROM auto-detection fails."""
    if model == '5.7':
        from inky.inky_uc8159 import Inky as InkyUC8159
        return InkyUC8159(resolution=(600, 448))
    # Default: 7.3" Impression (AC073TC1A chip)
    from inky.inky_ac073tc1a import Inky as InkyAC073TC1A
    return InkyAC073TC1A(resolution=(800, 480))


class EinkDisplay:
    def __init__(self, config):
        self._cfg = config.display['eink']
        self._model = str(self._cfg.get('model', '7.3'))
        self._width, self._height = _MODEL_SIZES.get(self._model, (800, 480))
        self._rotation = self._cfg.get('rotation', 0)
        self._saturation = float(self._cfg.get('saturation', 0.5))
        self._display = None

    def start(self):
        _check_spi()
        _log.info("Initialising e-ink display (model %s\")", self._model)
        try:
            from inky.auto import auto
            self._display = auto(ask_user=False, verbose=False)
            _log.info("Inky auto-detected OK")
        except RuntimeError:
            _log.warning("Inky EEPROM not detected; manually initialising %s\" model", self._model)
            try:
                self._display = _manual_init(self._model)
                _log.info("Inky manual init OK (%s\")", self._model)
            except Exception as exc:
                raise RuntimeError(
                    f"Could not initialise Inky display: {exc}\n"
                    "Make sure inky[rpi,fonts] is installed and SPI is enabled."
                ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Could not initialise Inky display: {exc}\n"
                "Make sure inky[rpi,fonts] is installed and SPI is enabled."
            ) from exc

    def stop(self):
        pass  # Nothing to tear down

    @property
    def size(self):
        return (self._width, self._height)

    def show(self, pil_image: Image.Image, transition: str = 'cut'):
        """Push a PIL image to the e-ink panel. transition is ignored (always cut)."""
        import time
        import warnings
        if self._rotation:
            pil_image = pil_image.rotate(-self._rotation, expand=True)

        img = pil_image.resize((self._width, self._height), Image.LANCZOS).convert('RGB')
        _log.info("Sending image to e-ink panel (%dx%d, saturation=%.2f) — this takes ~30-45s",
                  self._width, self._height, self._saturation)
        self._display.set_image(img, saturation=self._saturation)
        t0 = time.monotonic()
        timed_out = []
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            self._display.show()
        for w in caught:
            msg = str(w.message)
            if 'Timed out' in msg or 'Busy Wait' in msg:
                timed_out.append(msg)
            _log.warning("inky: %s", msg)
        elapsed = time.monotonic() - t0
        if timed_out:
            _log.error(
                "E-ink refresh timed out after %.1fs — display likely not responding. "
                "Check SPI is enabled and display is seated correctly.", elapsed
            )
        else:
            _log.info("E-ink refresh complete in %.1fs", elapsed)

    def blank(self):
        blank = Image.new('RGB', (self._width, self._height), (255, 255, 255))
        self._display.set_image(blank)
        self._display.show()

    def pump_events(self):
        return True  # No event loop needed for e-ink
