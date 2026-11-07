"""
soomfon.py - minimal Python driver for the SOOMFON Stream Controller SE
(a Mirabox N3 / Ajazz AKP03 clone: 6 LCD keys, 3 buttons, 3 knobs).

Protocol: Mirabox "CRT" HID protocol, version 3 (1024-byte packets + report ID).
Reference: the mirajazz Rust crate and the opendeck-akp03 plugin.

Requires:  pip install hidapi pillow
"""

from __future__ import annotations

import io
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterator, Optional, Union

import hid
from PIL import Image

VENDOR_ID = 0x1500
PRODUCT_ID = 0x3001

# Other devices that speak the same v3 protocol (VID, PID).
COMPATIBLE_IDS = [
    (0x1500, 0x3001),  # Soomfon Stream Controller SE
    (0x6603, 0x1003),  # Mirabox N3 rev.2
    (0x0300, 0x3002),  # Ajazz AKP03E
]

PACKET_SIZE = 1024
REPORT_SIZE = PACKET_SIZE + 1      # leading 0x00 report ID
READ_SIZE = 512
PREFIX = b"CRT\x00\x00"

KEY_COUNT = 6                      # LCD keys
KEY_SIZE = (64, 64)
KEY_ROTATION = -90                 # PIL rotate() is CCW; -90 == clockwise 90
KEEPALIVE_SECONDS = 15

# ---- input codes (data[9]) -------------------------------------------------
# LCD keys: codes 1..6 -> key 1..6
BUTTON_CODES = {0x25: 0, 0x30: 1, 0x31: 2}          # round buttons, left->right
KNOB_TURN = {                                         # code -> (knob, direction)
    0x90: (0, -1), 0x91: (0, +1),
    0x50: (1, -1), 0x51: (1, +1),
    0x60: (2, -1), 0x61: (2, +1),
}
KNOB_PRESS = {0x33: 0, 0x35: 1, 0x34: 2}


@dataclass
class Event:
    kind: str           # "key", "button", "knob_turn", "knob_press", "raw"
    index: int          # which key / button / knob
    pressed: bool = False
    delta: int = 0      # knob turn: -1 left, +1 right
    code: int = 0       # raw input code, handy for remapping

    def __str__(self) -> str:
        if self.kind == "knob_turn":
            return f"knob {self.index} {'right' if self.delta > 0 else 'left'}"
        if self.kind == "raw":
            return f"unknown code 0x{self.code:02x} state={int(self.pressed)}"
        return f"{self.kind} {self.index} {'down' if self.pressed else 'up'}"


ImageLike = Union[Image.Image, str, bytes, tuple]


class StreamController:
    """Open with `with StreamController() as dev:` or call open()/close()."""

    def __init__(self, vid: int = VENDOR_ID, pid: int = PRODUCT_ID,
                 path: Optional[bytes] = None, keepalive: bool = True):
        self.vid, self.pid, self.path = vid, pid, path
        self._keepalive = keepalive
        self._dev: Optional[hid.device] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ka_thread: Optional[threading.Thread] = None

    # ---- discovery ---------------------------------------------------------
    @staticmethod
    def find() -> list[dict]:
        """Return hidapi info dicts for every compatible device attached."""
        found = []
        for vid, pid in COMPATIBLE_IDS:
            found.extend(hid.enumerate(vid, pid))
        return found

    # ---- lifecycle ---------------------------------------------------------
    def open(self) -> "StreamController":
        dev = hid.device()
        if self.path is None:
            infos = hid.enumerate(self.vid, self.pid)
            if not infos:
                raise IOError(f"No device {self.vid:04x}:{self.pid:04x} found")
            # Prefer the vendor-defined interface if there are several.
            infos.sort(key=lambda i: i.get("usage_page", 0) < 0xFF00)
            self.path = infos[0]["path"]
        dev.open_path(self.path)
        self._dev = dev
        self._send(b"DIS")                 # wake / init
        self.set_brightness(80)
        if self._keepalive:
            self._ka_thread = threading.Thread(target=self._keepalive_loop, daemon=True)
            self._ka_thread.start()
        return self

    def close(self, sleep: bool = False) -> None:
        self._stop.set()
        if self._dev is None:
            return
        try:
            if sleep:
                self._send(b"CLE\x00\x00DC")
                self._send(b"HAN")
        finally:
            self._dev.close()
            self._dev = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # ---- low level ---------------------------------------------------------
    def _write(self, payload: bytes) -> None:
        buf = b"\x00" + payload
        buf = buf + b"\x00" * (REPORT_SIZE - len(buf))
        with self._lock:
            if self._dev is None:
                raise IOError("device not open")
            if self._dev.write(buf) < 0:
                raise IOError("HID write failed")

    def _send(self, cmd: bytes) -> None:
        self._write(PREFIX + cmd)

    def _keepalive_loop(self) -> None:
        while not self._stop.wait(KEEPALIVE_SECONDS):
            try:
                self._send(b"CONNECT")
            except IOError:
                return

    # ---- display -----------------------------------------------------------
    def set_brightness(self, percent: int) -> None:
        self._send(b"LIG\x00\x00" + bytes([max(0, min(100, percent))]))

    def clear_key(self, key: int) -> None:
        self._check_key(key)
        self._send(b"CLE\x00\x00\x00" + bytes([key]))
        self.flush()

    def clear_all(self) -> None:
        self._send(b"CLE\x00\x00\x00\xff")
        self.flush()

    def flush(self) -> None:
        """Commit pending image/clear operations to the screens."""
        self._send(b"STP")

    def set_key_image(self, key: int, image: ImageLike, flush: bool = True) -> None:
        """Show an image on LCD key 1-6.

        `image` may be a PIL Image, a file path, raw bytes of an image file,
        or an (r, g, b) tuple for a solid colour.
        """
        self._check_key(key)
        jpeg = self._to_jpeg(image)
        if len(jpeg) > 0xFFFF:
            raise ValueError("encoded image too large")
        self._send(b"BAT\x00\x00" + len(jpeg).to_bytes(2, "big") + bytes([key]))
        for i in range(0, len(jpeg), PACKET_SIZE):
            self._write(jpeg[i:i + PACKET_SIZE])
        if flush:
            self.flush()

    def set_key_text(self, key: int, text: str, fg="white", bg="black",
                     font_size: int = 18, flush: bool = True) -> None:
        from PIL import ImageDraw, ImageFont
        img = Image.new("RGB", KEY_SIZE, bg)
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default(size=font_size)
        except TypeError:                       # Pillow < 10.1
            font = ImageFont.load_default()
        draw.multiline_text((KEY_SIZE[0] / 2, KEY_SIZE[1] / 2), text, fill=fg,
                            font=font, anchor="mm", align="center")
        self.set_key_image(key, img, flush=flush)

    @staticmethod
    def _to_jpeg(image: ImageLike) -> runbytes:
        if isinstance(image, tuple):
            img = Image.new("RGB", KEY_SIZE, image)
        elif isinstance(image, (bytes, bytearray)):
            img = Image.open(io.BytesIO(image))
        elif isinstance(image, str):
            img = Image.open(image)
        else:
            img = image
        img = img.convert("RGB").resize(KEY_SIZE, Image.LANCZOS)
        img = img.rotate(KEY_ROTATION, expand=True)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=90)
        return out.getvalue()

    @staticmethod
    def _check_key(key: int) -> None:
        if not 1 <= key <= KEY_COUNT:
            raise ValueError(f"key must be 1..{KEY_COUNT}")

    # ---- input -------------------------------------------------------------
    def read_event(self, timeout_ms: int = 100) -> Optional[Event]:
        """Return the next Event, or None on timeout."""
        with self._lock:
            data = self._dev.read(READ_SIZE, timeout_ms)
        if not data or bytes(data[:3]) != b"ACK":
            return None
        code, state = data[9], data[10]
        pressed = state != 0
        if 1 <= code <= KEY_COUNT:
            return Event("key", code, pressed, code=code)
        if code in BUTTON_CODES:
            return Event("button", BUTTON_CODES[code], pressed, code=code)
        if code in KNOB_TURN:
            knob, delta = KNOB_TURN[code]
            return Event("knob_turn", knob, delta=delta, code=code)
        if code in KNOB_PRESS:
            return Event("knob_press", KNOB_PRESS[code], pressed, code=code)
        return Event("raw", -1, pressed, code=code)

    def events(self) -> Iterator[Event]:
        """Blocking generator of input events."""
        while not self._stop.is_set():
            ev = self.read_event()
            if ev:
                yield ev

    def run(self, callback: Callable[[Event], None]) -> None:
        """Call `callback(event)` for every input until Ctrl-C."""
        try:
            for ev in self.events():
                callback(ev)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    # Quick demo: show an icon (or coloured text) on each key, then print every input.
    import colorsys
    import os

    ICON_DIR = "icons"   # see generate_icons.py

    print("Devices:", [(f"{d['vendor_id']:04x}:{d['product_id']:04x}",
                        d.get("product_string")) for d in StreamController.find()])
    with StreamController() as dev:
        dev.clear_all()
        colours = {}
        for k in range(1, KEY_COUNT + 1):
            r, g, b = colorsys.hsv_to_rgb((k - 1) / KEY_COUNT, 0.8, 0.6)
            colours[k] = (int(r * 255), int(g * 255), int(b * 255))
            icon_path = os.path.join(ICON_DIR, f"{k}.png")
            if os.path.isfile(icon_path):
                dev.set_key_image(k, icon_path, flush=False)
            else:
                dev.set_key_text(k, f"KEY\n{k}", bg=colours[k], flush=False)
        dev.flush()
        print("Press keys / turn knobs (Ctrl-C to quit)...")
        level = 80

        def on_event(ev: Event):
            global level
            print(ev)
            if ev.kind == "key" and ev.pressed:
                dev.set_key_text(ev.index, "HIT!", bg="red")
            elif ev.kind == "key":
                icon_path = os.path.join(ICON_DIR, f"{ev.index}.png")
                if os.path.isfile(icon_path):
                    dev.set_key_image(ev.index, icon_path)
                else:
                    dev.set_key_text(ev.index, f"KEY\n{ev.index}", bg=colours[ev.index])
            elif ev.kind == "knob_turn" and ev.index == 0:
                level = max(0, min(100, level + 5 * ev.delta))
                dev.set_brightness(level)

        dev.run(on_event)
