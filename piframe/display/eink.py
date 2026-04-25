"""E-ink display driver for Pimoroni Inky Impression."""
from PIL import Image


# Resolution map for supported Inky Impression models
_MODEL_SIZES = {
    '7.3': (800, 480),
    '5.7': (600, 448),
}


class EinkDisplay:
    def __init__(self, config):
        self._cfg = config.display['eink']
        model = str(self._cfg.get('model', '7.3'))
        self._width, self._height = _MODEL_SIZES.get(model, (800, 480))
        self._rotation = self._cfg.get('rotation', 0)
        self._saturation = float(self._cfg.get('saturation', 0.5))
        self._display = None

    def start(self):
        try:
            from inky.auto import auto
            self._display = auto(ask_user=False, verbose=False)
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
        if self._rotation:
            pil_image = pil_image.rotate(-self._rotation, expand=True)

        img = pil_image.resize((self._width, self._height), Image.LANCZOS).convert('RGB')
        self._display.set_image(img, saturation=self._saturation)
        self._display.show()

    def blank(self):
        blank = Image.new('RGB', (self._width, self._height), (255, 255, 255))
        self._display.set_image(blank)
        self._display.show()

    def pump_events(self):
        return True  # No event loop needed for e-ink
