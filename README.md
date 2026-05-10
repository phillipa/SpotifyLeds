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

## File layout

| File | Purpose |
| --- | --- |
| [spotify_led_http.py](spotify_led_http.py) | Entry point. Audio capture loop, settings store, HTTP wiring. |
| [led_effects.py](led_effects.py) | Palettes, gradient builder, four effect classes, WLED UDP packet builder. |
| [web_ui.py](web_ui.py) | `http.server`-based JSON API. State management is injected via callables. |
| [index.html](index.html) | Mobile-first control panel (vanilla JS, no build step). |
| [TestingScripts/](TestingScripts/) | Standalone helpers: audio device enumeration, a sACN/DMX smoke test, and an earlier prototype. |

## Web UI

- `GET /` — control panel (served from [index.html](index.html))
- `GET /state` — current settings as JSON, plus enum metadata (palette/mode/boundary lists)
- `POST /state` — JSON patch of any subset of settings; unknown keys and out-of-range values are dropped
- `POST /randomize` — re-rolls mode, color mode, palette, and color

The audio loop and HTTP handler share `settings` under a lock; structural changes (`mode`, `color_mode`, `agents_count`) rebuild the effect, while tunables update live without resetting effect state.

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

### Palettes

All palettes are defined in [led_effects.py](led_effects.py:9-32) as ordered RGB stops; `palette_gradient` linearly interpolates them across the strip.

| Name | Vibe | Stops (hex) |
| --- | --- | --- |
| `rainbow` | Full-spectrum rainbow, loops back to red | `#FF0000` `#FFFF00` `#00FF00` `#00FFFF` `#0000FF` `#FF00FF` `#FF0000` |
| `fire` | Black → red → orange → yellow → white | `#000000` `#800000` `#FF0000` `#FF8000` `#FFFF00` `#FFFFFF` |
| `ocean` | Deep navy through cyan to pale aqua | `#000020` `#004080` `#0080FF` `#80FFFF` |
| `sunset` | Dusky violet, hot pink, orange, gold | `#140028` `#FF0080` `#FF8000` `#FFDC50` |
| `forest` | Dark green through bright leaf-green | `#001000` `#005010` `#20A020` `#B4DC50` |
| `purples` | Dark plum to lavender pink | `#140028` `#5000A0` `#B450FF` `#FFC8FF` |
| `purplesgreens` | Moody, low-brightness purple/green alternation | `#280028` `#001000` `#140014` `#002000` |
| `lava` | Black → dark red → molten orange-red | `#000000` `#3C0000` `#C81E00` `#FF6400` `#FFC83C` `#FF3200` |
| `embers` | Glowing coals; low overall brightness | `#000000` `#280000` `#A01400` `#FF5014` `#5A0A00` |
| `arctic` | Navy → icy blue → white | `#081020` `#2864B4` `#8CC8FF` `#F0FFFF` `#B4DCF0` |
| `neon` | Hot pink, cyan, lime, magenta — all max-saturation | `#FF00C8` `#00FFF0` `#C8FF00` `#FF3CC8` |
| `synthwave` | Retro purple/magenta/cyan | `#14003C` `#FF00B4` `#5000C8` `#00DCFF` `#3C0078` |
| `cyberpunk` | Mostly dark with green accents and bright pops | `#000000` `#002800` `#00781E` `#28DC3C` `#A0FFB4` `#003C0A` |
| `autumn` | Browns, burnt orange, gold | `#1E0800` `#B43200` `#DC6E00` `#F0B41E` `#6E320A` |
| `tropical` | Teal, mint, gold, coral, magenta | `#006464` `#28DCC8` `#FFC850` `#FF6450` `#C83296` |
| `mint` | Dark teal through mint to near-white | `#001E1E` `#28B48C` `#A0F0C8` `#F0FFF0` `#3CC8B4` |
| `candy` | Bright pink, teal, gold, purple | `#FF3CA0` `#28C8B4` `#FFB428` `#A03CF0` `#FF64C8` |
| `berry` | Deep aubergine through hot pink and magenta | `#140014` `#780042` `#DC0064` `#FF50A0` `#8C0050` |
| `citrus` | Yellow, orange, lime — all bright | `#FFF03C` `#FFA000` `#B4DC00` `#FFC828` |
