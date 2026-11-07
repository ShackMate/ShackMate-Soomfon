/**
 * soomfon-webhid.js - browser driver for the SOOMFON Stream Controller SE,
 * ported from soomfon.py. Uses the WebHID API (Chrome/Edge only, HTTPS or
 * localhost). No backend process required - the page talks to the device
 * directly.
 *
 * Protocol: Mirabox "CRT" HID protocol, v3 (1024-byte packets, no report ID).
 *
 * Usage:
 *   import { SoomfonController, KEY_COUNT } from "./soomfon-webhid.js";
 *   const dev = new SoomfonController();
 *   await dev.open();                       // prompts the WebHID device picker
 *   dev.addEventListener("input", (e) => console.log(e.detail));
 *   await dev.setKeyText(1, "HELLO");
 */

export const DEVICE_FILTERS = [
  { vendorId: 0x1500, productId: 0x3001 }, // Soomfon Stream Controller SE
  { vendorId: 0x6603, productId: 0x1003 }, // Mirabox N3 rev.2
  { vendorId: 0x0300, productId: 0x3002 }, // Ajazz AKP03E
];

const PACKET_SIZE = 1024;
const PREFIX = strToBytes("CRT\x00\x00");
export const KEY_COUNT = 6;
export const KEY_SIZE = 64;
const KEEPALIVE_MS = 15000;

// input codes (byte 9 of an "ACK" input report)
const BUTTON_CODES = { 0x25: 0, 0x30: 1, 0x31: 2 };
const KNOB_TURN = {
  0x90: [0, -1], 0x91: [0, 1],
  0x50: [1, -1], 0x51: [1, 1],
  0x60: [2, -1], 0x61: [2, 1],
};
const KNOB_PRESS = { 0x33: 0, 0x35: 1, 0x34: 2 };

function strToBytes(s) {
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}

function concatBytes(...parts) {
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

/** Draw any image source onto a 64x64 canvas, rotated to match the key
 * screen's physical orientation, and return JPEG bytes. */
async function toKeyJpegBytes(imageSource) {
  let bitmap;
  if (imageSource instanceof ImageBitmap) {
    bitmap = imageSource;
  } else {
    bitmap = await createImageBitmap(imageSource);
  }
  const canvas = document.createElement("canvas");
  canvas.width = KEY_SIZE;
  canvas.height = KEY_SIZE;
  const ctx = canvas.getContext("2d");
  ctx.translate(KEY_SIZE / 2, KEY_SIZE / 2);
  // Canvas rotate() is clockwise-positive (y-axis points down), opposite of
  // PIL's rotate() which is CCW-positive - so +90 here equals soomfon.py's
  // KEY_ROTATION = -90 (clockwise 90).
  ctx.rotate(Math.PI / 2);
  ctx.drawImage(bitmap, -KEY_SIZE / 2, -KEY_SIZE / 2, KEY_SIZE, KEY_SIZE);
  ctx.resetTransform();

  const blob = await new Promise((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", 0.9)
  );
  return new Uint8Array(await blob.arrayBuffer());
}

export class SoomfonController extends EventTarget {
  constructor() {
    super();
    /** @type {HIDDevice|null} */
    this.device = null;
    this._keepaliveTimer = null;
    this._onInputReport = this._onInputReport.bind(this);
  }

  /** Browsers that support WebHID at all. Doesn't guarantee this device works. */
  static get supported() {
    return "hid" in navigator;
  }

  /** List devices the page already has permission for (granted in a past session). */
  static async getAuthorizedDevices() {
    if (!SoomfonController.supported) return [];
    const devices = await navigator.hid.getDevices();
    return devices.filter((d) =>
      DEVICE_FILTERS.some((f) => f.vendorId === d.vendorId && f.productId === d.productId)
    );
  }

  /**
   * Open the controller. If `device` isn't given, prompts the WebHID picker.
   * NOTE: this device exposes multiple USB HID interfaces - if nothing
   * responds after opening, call close() and reopen, picking a different
   * entry in the browser's device chooser.
   */
  async open(device) {
    if (!SoomfonController.supported) {
      throw new Error("WebHID is not available in this browser (use Chrome/Edge over HTTPS or localhost)");
    }
    if (!device) {
      const picked = await navigator.hid.requestDevice({ filters: DEVICE_FILTERS });
      if (!picked.length) throw new Error("No device selected");
      device = picked[0];
    }
    if (!device.opened) await device.open();
    this.device = device;
    this.device.addEventListener("inputreport", this._onInputReport);

    await this._send(strToBytes("DIS")); // wake / init
    await this.setBrightness(80);

    this._keepaliveTimer = setInterval(() => {
      this._send(strToBytes("CONNECT")).catch(() => this.close());
    }, KEEPALIVE_MS);

    return this;
  }

  async close(sleep = false) {
    if (this._keepaliveTimer) {
      clearInterval(this._keepaliveTimer);
      this._keepaliveTimer = null;
    }
    if (!this.device) return;
    try {
      if (sleep) {
        await this._send(concatBytes(strToBytes("CLE\x00\x00"), Uint8Array.of(0xdc)));
        await this._send(strToBytes("HAN"));
      }
    } finally {
      this.device.removeEventListener("inputreport", this._onInputReport);
      await this.device.close();
      this.device = null;
    }
  }

  // ---- low level ----------------------------------------------------------
  async _write(payload) {
    const buf = new Uint8Array(PACKET_SIZE);
    buf.set(payload.subarray(0, PACKET_SIZE));
    await this.device.sendReport(0x00, buf);
  }

  async _send(cmd) {
    await this._write(concatBytes(PREFIX, cmd));
  }

  // ---- display --------------------------------------------------------------
  async setBrightness(percent) {
    const p = Math.max(0, Math.min(100, Math.round(percent)));
    await this._send(concatBytes(strToBytes("LIG\x00\x00"), Uint8Array.of(p)));
  }

  async clearKey(key) {
    this._checkKey(key);
    await this._send(concatBytes(strToBytes("CLE\x00\x00\x00"), Uint8Array.of(key)));
    await this.flush();
  }

  async clearAll() {
    await this._send(concatBytes(strToBytes("CLE\x00\x00\x00"), Uint8Array.of(0xff)));
    await this.flush();
  }

  async flush() {
    await this._send(strToBytes("STP"));
  }

  /** Show an image on LCD key 1-6. `image` is anything createImageBitmap()
   * accepts: Blob, File, ImageBitmap, HTMLImageElement, OffscreenCanvas... */
  async setKeyImage(key, image, { flush = true } = {}) {
    this._checkKey(key);
    const jpeg = await toKeyJpegBytes(image);
    if (jpeg.length > 0xffff) throw new Error("encoded image too large");

    const lenBytes = Uint8Array.of((jpeg.length >> 8) & 0xff, jpeg.length & 0xff);
    await this._send(concatBytes(strToBytes("BAT\x00\x00"), lenBytes, Uint8Array.of(key)));
    for (let i = 0; i < jpeg.length; i += PACKET_SIZE) {
      await this._write(jpeg.subarray(i, i + PACKET_SIZE));
    }
    if (flush) await this.flush();
  }

  /** Render text onto a key via an offscreen canvas, then push it as an image. */
  async setKeyText(key, text, { fg = "white", bg = "black", fontSize = 18, flush = true } = {}) {
    const canvas = document.createElement("canvas");
    canvas.width = KEY_SIZE;
    canvas.height = KEY_SIZE;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, KEY_SIZE, KEY_SIZE);
    ctx.fillStyle = fg;
    ctx.font = `${fontSize}px sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const lines = String(text).split("\n");
    const lineHeight = fontSize * 1.2;
    const startY = KEY_SIZE / 2 - ((lines.length - 1) * lineHeight) / 2;
    lines.forEach((line, i) => ctx.fillText(line, KEY_SIZE / 2, startY + i * lineHeight));

    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    await this.setKeyImage(key, blob, { flush });
  }

  _checkKey(key) {
    if (!(key >= 1 && key <= KEY_COUNT)) {
      throw new RangeError(`key must be 1..${KEY_COUNT}`);
    }
  }

  // ---- input ----------------------------------------------------------------
  _onInputReport(event) {
    const { data } = event; // DataView, report ID already stripped by WebHID
    if (data.byteLength < 11) return;
    const ack = String.fromCharCode(data.getUint8(0), data.getUint8(1), data.getUint8(2));
    if (ack !== "ACK") return;

    const code = data.getUint8(9);
    const state = data.getUint8(10);
    const pressed = state !== 0;

    let detail;
    if (code >= 1 && code <= KEY_COUNT) {
      detail = { kind: "key", index: code, pressed, delta: 0, code };
    } else if (code in BUTTON_CODES) {
      detail = { kind: "button", index: BUTTON_CODES[code], pressed, delta: 0, code };
    } else if (code in KNOB_TURN) {
      const [knob, delta] = KNOB_TURN[code];
      detail = { kind: "knob_turn", index: knob, pressed: false, delta, code };
    } else if (code in KNOB_PRESS) {
      detail = { kind: "knob_press", index: KNOB_PRESS[code], pressed, delta: 0, code };
    } else {
      detail = { kind: "raw", index: -1, pressed, delta: 0, code };
    }
    this.dispatchEvent(new CustomEvent("input", { detail }));
  }
}
