# soomfon — agent progress notes

Universal context file for any AI coding agent working in this repo (Claude Code, Cursor, Codex, etc). Keep this updated as work progresses instead of relying on chat history.

## What this project is

Driver stack for the **SOOMFON Stream Controller SE** (a Mirabox N3 / Ajazz AKP03 clone: 6 LCD keys, 3 buttons, 3 knobs), branded "ShackMate Soomfon" — built for ham-radio shack control (keys map to RIG / ANTENNA / TUNER / ROTATOR / SATELLITES / SCANNER). Protocol is Mirabox's "CRT" HID protocol v3 (1024-byte packets).

Three ways to drive the device, same protocol, different transport:

| File | Role |
|---|---|
| `soomfon.py` | Core Python driver. `StreamController` class: open/close, set key images/text, brightness, read input events (keys/buttons/knobs). Has a `__main__` demo that paints icons on all 6 keys and prints input events until Ctrl-C. |
| `soomfon_bridge.py` | Local WebSocket bridge (`ws://localhost:8765`) that keeps a `StreamController` open and relays events/commands as JSON — for browsers without WebHID (Safari, or Linux without udev perms). Run with `python3 soomfon_bridge.py`. |
| `soomfon-webhid.js` | Browser-native driver via the WebHID API (Chrome/Edge only, HTTPS or localhost). No backend needed. |
| `soomfon-client.js` | Unified JS wrapper — picks WebHID if available, else falls back to `soomfon_bridge.py` over WebSocket. Same interface either way. |
| `demo.html` | Browser demo UI exercising `soomfon-client.js`, mirrors the physical device layout. |
| `generate_icons.py` | Generates `icons/1.png` .. `icons/6.png` from reference art in `assets/` (recolored/cropped to white glyphs on colored backgrounds). Re-run after changing `assets/*_ref.*`. |

Device IDs (same for all three COMPATIBLE_IDS lists — keep in sync if adding a new clone):
- `0x1500:0x3001` — Soomfon Stream Controller SE
- `0x6603:0x1003` — Mirabox N3 rev.2
- `0x0300:0x3002` — Ajazz AKP03E

## Environment

- Python **3.14.7**, venv at `.venv/` (`pip install hidapi pillow`; bridge also needs `websockets`).
- `.vscode/settings.json` pins the interpreter to `.venv/bin/python`.
- `.vscode/launch.json` has one debug config, **"Python: soomfon.py"**, hardcoded to run `soomfon.py` regardless of which file is focused in the editor (avoid `${file}` here — if `launch.json` itself is the active tab, VS Code will try to run the JSON as Python).

## Known issues

- **debugpy vs Python 3.14**: debugpy 2025.10.0 (current VS Code Python ext bundle) intermittently throws `AttributeError: '_MainThread' object has no attribute '_handle'` during F5 debugging — a sys.monitoring thread-tracing incompatibility with 3.14's threading internals (3.14 is very new; debugpy hasn't fully caught up). It did NOT reproduce after pinning the interpreter explicitly in `launch.json`, but if it recurs, use **"Run Without Debugging"** (`Fn+Ctrl+F5`) instead of `F5` — bypasses debugpy entirely, no functional loss for this script.
- No physical device has been available during recent sessions, so `StreamController.find()` returns `[]` and `open()` raises `OSError: No device 1500:3001 found`. This is expected without hardware attached — not a code bug. Plug in the controller via USB before expecting `soomfon.py` to run past that point.

## Packaging

Full project zip (code + `.venv` + `assets` + `icons` + `.vscode`, excluding `.DS_Store`/`__pycache__`) lives at `/Users/rts/Development/soomfon.zip`. Rebuild with:

```bash
cd /Users/rts/Development
rm -f soomfon.zip
zip -rq soomfon.zip soomfon -x "*.DS_Store" -x "*/__pycache__/*"
```

Note: bundling `.venv` makes the zip non-portable to other machines (absolute paths baked in) — fine for local backup, not for sharing/deploying. For that, ship `requirements.txt` instead and let the recipient create their own venv.

## Open items / next steps

- Verify `soomfon.py` end-to-end against physical hardware (icons on keys, button/knob input, brightness via knob 0).
- `soomfon_bridge.py` and the WebHID/bridge fallback path in `soomfon-client.js` haven't been exercised in recent sessions — worth a manual pass once hardware is available.
- No `requirements.txt` exists yet; dependencies are only documented in file docstrings (`hidapi`, `pillow`, `websockets` for the bridge).
