"""soomfon_bridge.py - local WebSocket bridge for browsers that can't use
WebHID (Safari, and any Linux browser without udev permission for the raw
HID device). Keeps soomfon.py's StreamController open and relays input
events / display commands over ws://localhost:8765 as JSON.

Requires: pip install hidapi pillow websockets
Run:      python3 soomfon_bridge.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time

import websockets

from soomfon import Event, StreamController

PORT = 8765

clients: set = set()
loop: asyncio.AbstractEventLoop | None = None


def event_to_dict(ev: Event) -> dict:
    return {
        "type": "input",
        "kind": ev.kind,
        "index": ev.index,
        "pressed": ev.pressed,
        "delta": ev.delta,
        "code": ev.code,
    }


async def broadcast(message: dict) -> None:
    if not clients:
        return
    text = json.dumps(message)
    await asyncio.gather(*(c.send(text) for c in clients), return_exceptions=True)


def reader_thread(dev: StreamController) -> None:
    """Relay input events forever. HID reads can intermittently fail (e.g. a
    transient USB hiccup or a competing handle); log and keep going instead
    of letting one error silently kill event relay for the rest of the
    process."""
    while True:
        try:
            for ev in dev.events():
                if loop is not None:
                    asyncio.run_coroutine_threadsafe(broadcast(event_to_dict(ev)), loop)
            return  # events() only stops when dev.close() was called deliberately
        except OSError as exc:
            print(f"reader thread: {exc} - retrying in 2s")
            time.sleep(2)


def handle_command(dev: StreamController, msg: dict) -> None:
    action = msg.get("action")
    if action == "setKeyImage":
        image = base64.b64decode(msg["imageData"])
        dev.set_key_image(msg["key"], image, flush=msg.get("flush", True))
    elif action == "setKeyText":
        dev.set_key_text(
            msg["key"], msg["text"],
            fg=msg.get("fg", "white"), bg=msg.get("bg", "black"),
            font_size=msg.get("fontSize", 18), flush=msg.get("flush", True),
        )
    elif action == "setBrightness":
        dev.set_brightness(msg["percent"])
    elif action == "clearKey":
        dev.clear_key(msg["key"])
    elif action == "clearAll":
        dev.clear_all()
    elif action == "flush":
        dev.flush()
    else:
        raise ValueError(f"unknown action {action!r}")


async def handler(websocket, dev: StreamController) -> None:
    clients.add(websocket)
    print(f"client connected ({len(clients)} total)")
    try:
        async for raw in websocket:
            msg = json.loads(raw)
            if msg.get("type") != "cmd":
                continue
            try:
                handle_command(dev, msg)
            except Exception as exc:
                await websocket.send(json.dumps({"type": "error", "message": str(exc)}))
    finally:
        clients.discard(websocket)
        print(f"client disconnected ({len(clients)} total)")


async def main() -> None:
    global loop
    loop = asyncio.get_running_loop()

    print("Devices:", [(f"{d['vendor_id']:04x}:{d['product_id']:04x}",
                        d.get("product_string")) for d in StreamController.find()])
    dev = StreamController().open()
    threading.Thread(target=reader_thread, args=(dev,), daemon=True).start()

    async def _handler(ws):
        await handler(ws, dev)

    async with websockets.serve(_handler, "localhost", PORT):
        print(f"Soomfon bridge listening on ws://localhost:{PORT}")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
