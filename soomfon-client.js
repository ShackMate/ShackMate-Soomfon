/**
 * soomfon-client.js - unified Soomfon controller for the browser.
 *
 * Talks directly to the device over WebHID when the browser supports it
 * (Chrome/Edge, any OS). Falls back to the local soomfon_bridge.py
 * WebSocket relay otherwise - this is the only path that works in Safari,
 * which has no WebHID support at all, and is also a safety net for Linux
 * browsers that haven't been granted udev permission for the raw device.
 *
 * Both backends expose the same interface:
 *   open(), close(), setBrightness(), clearKey(), clearAll(), flush(),
 *   setKeyImage(key, image, opts), setKeyText(key, text, opts),
 *   addEventListener("input", (e) => ... e.detail = {kind,index,pressed,delta,code})
 *
 * Usage:
 *   import { connectSoomfon } from "./soomfon-client.js";
 *   const dev = await connectSoomfon();   // call from a click handler
 */

import { SoomfonController } from "./soomfon-webhid.js";

export const DEFAULT_BRIDGE_URL = "ws://localhost:8765";

function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

async function toRawBytes(imageSource) {
  if (imageSource instanceof Uint8Array) return imageSource;
  if (imageSource instanceof ArrayBuffer) return new Uint8Array(imageSource);
  if (imageSource instanceof Blob) return new Uint8Array(await imageSource.arrayBuffer());
  throw new Error("setKeyImage: expected a Blob/File or raw bytes for the bridge backend");
}

/** WebSocket-backed controller, talking to soomfon_bridge.py. The Python
 * side does all image resize/rotate/encode work, same as the native demo -
 * no image processing happens in this backend. */
class SoomfonBridgeController extends EventTarget {
  constructor(url = DEFAULT_BRIDGE_URL) {
    super();
    this.url = url;
    this.ws = null;
  }

  static get supported() {
    return "WebSocket" in window;
  }

  async open() {
    await new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url);
      const onError = () =>
        reject(new Error(`Could not reach Soomfon bridge at ${this.url} - is soomfon_bridge.py running?`));
      ws.addEventListener("open", () => {
        ws.removeEventListener("error", onError);
        resolve();
      }, { once: true });
      ws.addEventListener("error", onError, { once: true });
      this.ws = ws;
    });

    this.ws.addEventListener("message", (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      if (msg.type === "input") {
        const { kind, index, pressed, delta, code } = msg;
        this.dispatchEvent(new CustomEvent("input", { detail: { kind, index, pressed, delta, code } }));
      } else if (msg.type === "error") {
        console.error("Soomfon bridge error:", msg.message);
      }
    });

    return this;
  }

  close() {
    this.ws?.close();
    this.ws = null;
  }

  _send(action, extra = {}) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error("bridge not connected");
    }
    this.ws.send(JSON.stringify({ type: "cmd", action, ...extra }));
  }

  async setBrightness(percent) {
    this._send("setBrightness", { percent });
  }

  async clearKey(key) {
    this._send("clearKey", { key });
  }

  async clearAll() {
    this._send("clearAll");
  }

  async flush() {
    this._send("flush");
  }

  async setKeyImage(key, image, { flush = true } = {}) {
    const bytes = await toRawBytes(image);
    this._send("setKeyImage", { key, imageData: bytesToBase64(bytes), flush });
  }

  async setKeyText(key, text, { fg = "white", bg = "black", fontSize = 18, flush = true } = {}) {
    this._send("setKeyText", { key, text, fg, bg, fontSize, flush });
  }
}

/**
 * Open a Soomfon controller, preferring WebHID and falling back to the
 * local WebSocket bridge. Must be called from inside a user gesture
 * (e.g. a click handler) so the WebHID permission prompt is allowed.
 */
export async function connectSoomfon({ bridgeUrl = DEFAULT_BRIDGE_URL, preferBridge = false } = {}) {
  if (!preferBridge && SoomfonController.supported) {
    try {
      const dev = new SoomfonController();
      await dev.open();
      dev.backend = "webhid";
      return dev;
    } catch (err) {
      console.warn("WebHID unavailable, falling back to bridge:", err.message);
    }
  }
  const dev = new SoomfonBridgeController(bridgeUrl);
  await dev.open();
  dev.backend = "bridge";
  return dev;
}

/**
 * Try to connect without any user gesture: reopens a WebHID device the page
 * was already granted permission for in a past session (no picker prompt),
 * then falls back to the WebSocket bridge (which never needs a gesture).
 * Returns null - never throws - if neither is available, so the caller can
 * show a message and fall back to a manual "Connect" button.
 */
export async function autoConnect({ bridgeUrl = DEFAULT_BRIDGE_URL } = {}) {
  if (SoomfonController.supported) {
    try {
      const authorized = await SoomfonController.getAuthorizedDevices();
      if (authorized.length) {
        const dev = new SoomfonController();
        await dev.open(authorized[0]);
        dev.backend = "webhid";
        return dev;
      }
    } catch (err) {
      console.warn("Auto WebHID connect failed:", err.message);
    }
  }
  try {
    const dev = new SoomfonBridgeController(bridgeUrl);
    await dev.open();
    dev.backend = "bridge";
    return dev;
  } catch (err) {
    console.warn("Auto bridge connect failed:", err.message);
    return null;
  }
}

export { SoomfonBridgeController };
