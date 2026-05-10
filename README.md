# SpotifyLeds

Audio-reactive LED controller. Captures system audio (e.g. Spotify) on macOS via [BlackHole](https://github.com/ExistentialAudio/BlackHole), runs it through one of four effects, and streams pixels over UDP to a [WLED](https://kno.wled.ge/)-flashed strip. A mobile-friendly web UI lets you change mode, palette, and per-effect parameters in real time.

```
Spotify ──▶ BlackHole ──▶ PyAudio ──▶ effect ──▶ UDP ──▶ WLED strip
                                         ▲
                                  HTTP control panel
                                  (phone or browser)
```

## Prerequisites

- Python 3.9+
- [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole) installed and set up as a Multi-Output Device alongside your speakers, so audio plays *and* gets captured
- A WLED-flashed ESP32/ESP8266 LED controller reachable on your LAN, with **UDP Realtime** enabled (DRGB/WARLS on port 19446 by default)
- Python deps: `pyaudio`, `numpy`

```bash
pip install pyaudio numpy
```

## Configuration

Hardware constants live at the top of [spotify_led_http.py](spotify_led_http.py:14-19). Edit these to match your setup:

```python
WLED_IP = "192.168.1.124"   # your WLED controller's IP
WLED_PORT = 19446           # WLED UDP realtime port
HTTP_PORT = 8080            # web UI port
NUM_LEDS = 90
COLOR_ORDER = "RGB"         # try "GRB" if colors look swapped
```

Audio device selection is automatic — the script searches for any input device with `BlackHole` in its name. Use [TestingScripts/list_audio_devices.py](TestingScripts/list_audio_devices.py) to see what's available if it can't find one.

## Running

```bash
python3 spotify_led_http.py
```

It prints the web UI URL on startup, e.g. `http://yourmac.local:8080/`. Open it on your phone to control the strip live.

## Effects

| Mode | Behavior |
| --- | --- |
| `pulse` | Every LED flashes at its assigned color, scaled by an audio envelope with attack/release/gamma. |
| `progressive` | LEDs light left-to-right; the lit count tracks the audio level. |
| `twinkle` | Random LEDs sparkle on and fade out. Density scales with audio. |
| `agents` | Moving pixels with fading tails; speed reacts to audio, optional rising-edge direction flips on peaks. |

Color modes apply to all effects:

- `solid` — every LED uses one chosen color
- `palette_linear` — LED *i* uses the *i*-th color of the palette (rotates over time)
- `palette_random` — each LED picks a random palette color, fixed across frames

19 named palettes are defined in [led_effects.py](led_effects.py:9-32) (`rainbow`, `fire`, `ocean`, `sunset`, `synthwave`, `lava`, etc.).

## Web UI

- `GET /` — control panel (served from [index.html](index.html))
- `GET /state` — current settings as JSON, plus enum metadata (palette/mode/boundary lists)
- `POST /state` — JSON patch of any subset of settings; unknown keys and out-of-range values are dropped
- `POST /randomize` — re-rolls mode, color mode, palette, and color

The audio loop and HTTP handler share `settings` under a lock; structural changes (`mode`, `color_mode`, `agents_count`) rebuild the effect, while tunables update live without resetting effect state.

## File layout

| File | Purpose |
| --- | --- |
| [spotify_led_http.py](spotify_led_http.py) | Entry point. Audio capture loop, settings store, HTTP wiring. |
| [led_effects.py](led_effects.py) | Palettes, gradient builder, four effect classes, WLED UDP packet builder. |
| [web_ui.py](web_ui.py) | `http.server`-based JSON API. State management is injected via callables. |
| [index.html](index.html) | Mobile-first control panel (vanilla JS, no build step). |
| [TestingScripts/](TestingScripts/) | Standalone helpers: audio device enumeration, a sACN/DMX smoke test, and an earlier prototype. |
