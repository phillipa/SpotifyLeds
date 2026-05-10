import pyaudio
import numpy as np
import time
import socket
import random
import colorsys
import threading
import os

from led_effects import palette_gradient, to_packet, Pulse, Progressive, Twinkle, Agents, PALETTES
from web_ui import serve

# Hardware / runtime constants — not editable from the UI
WLED_IP = "192.168.1.124"
WLED_PORT = 19446
HTTP_PORT = 8080
NUM_LEDS = 90
COLOR_ORDER = "RGB"

PALETTE_SHIFT = 0.5     # LEDs to scroll the palette per frame
PALETTE_LOOP = True     # blend the last LED back to the first so scrolling is seamless
PEAK_DECAY = 0.999      # auto-gain decay rate

INDEX_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
VALID_MODES = ["pulse", "progressive", "twinkle", "agents"]
VALID_COLOR_MODES = ["solid", "palette_linear", "palette_random"]
VALID_BOUNDARIES = ["wrap", "bounce"]

# All UI-editable settings live here. Audio loop reads, HTTP handler writes.
settings = {
    "mode": "twinkle",
    "color_mode": "palette_random",
    "palette": "purplesgreens",
    "color": [255, 255, 255],
    "randomize_interval": 0.0,  # 0 = no auto-rotation; UI can re-enable

    "pulse_attack": 1.0,
    "pulse_release": 0.92,
    "pulse_gamma": 2.2,

    "twinkle_fade": 0.9,
    "twinkle_fade_jitter": 0.05,
    "twinkle_density": 0.99,

    "agents_count": 16,
    "agents_fade": 0.5,
    "agents_base_speed": 0.2,
    "agents_audio_speed": 2.0,
    "agents_boundary": "bounce",
    "agents_flip_threshold": 0.9,
    "agents_flip_probability": 0.5,
}

settings_lock = threading.Lock()
effect_fn = None
base_pixels = None
last_switch = 0.0


def build_effect():
    """Construct a fresh effect instance from the current settings."""
    s = settings
    color = tuple(s["color"])
    cm = s["color_mode"]
    mode = s["mode"]
    if mode == "pulse":
        return Pulse(NUM_LEDS, color_mode=cm, color=color,
                     attack=s["pulse_attack"], release=s["pulse_release"],
                     gamma=s["pulse_gamma"])
    if mode == "progressive":
        return Progressive(NUM_LEDS, color_mode=cm, color=color)
    if mode == "twinkle":
        return Twinkle(NUM_LEDS, color_mode=cm, color=color,
                       fade=s["twinkle_fade"],
                       fade_jitter=s["twinkle_fade_jitter"],
                       density=s["twinkle_density"])
    if mode == "agents":
        return Agents(NUM_LEDS, color_mode=cm, color=color,
                      count=int(s["agents_count"]), fade=s["agents_fade"],
                      base_speed=s["agents_base_speed"],
                      audio_speed=s["agents_audio_speed"],
                      boundary=s["agents_boundary"],
                      flip_threshold=s["agents_flip_threshold"],
                      flip_probability=s["agents_flip_probability"])
    raise ValueError(f"Unknown mode: {mode}")


# Settings whose change requires rebuilding the effect (different class or
# different agent population). Other tunables can be mutated live without
# losing accumulated state (twinkle sparkles, agent positions, etc.).
STRUCTURAL_KEYS = {"mode", "color_mode", "agents_count"}


def apply_settings(changed_keys):
    """Propagate settings changes to the running effect. Caller must hold settings_lock."""
    global effect_fn, base_pixels

    if STRUCTURAL_KEYS & changed_keys:
        effect_fn = build_effect()
        base_pixels = palette_gradient(settings["palette"], NUM_LEDS, loop=PALETTE_LOOP)
        return

    if "palette" in changed_keys:
        base_pixels = palette_gradient(settings["palette"], NUM_LEDS, loop=PALETTE_LOOP)

    if "color" in changed_keys:
        effect_fn.color = tuple(settings["color"])

    s = settings
    m = s["mode"]
    if m == "pulse":
        if "pulse_attack" in changed_keys:  effect_fn.attack = s["pulse_attack"]
        if "pulse_release" in changed_keys: effect_fn.release = s["pulse_release"]
        if "pulse_gamma" in changed_keys:   effect_fn.gamma = s["pulse_gamma"]
    elif m == "twinkle":
        if "twinkle_fade" in changed_keys:        effect_fn.fade = s["twinkle_fade"]
        if "twinkle_fade_jitter" in changed_keys: effect_fn.fade_jitter = s["twinkle_fade_jitter"]
        if "twinkle_density" in changed_keys:     effect_fn.density = s["twinkle_density"]
    elif m == "agents":
        if "agents_fade" in changed_keys:             effect_fn.fade = s["agents_fade"]
        if "agents_base_speed" in changed_keys:      effect_fn.base_speed = s["agents_base_speed"]
        if "agents_audio_speed" in changed_keys:     effect_fn.audio_speed = s["agents_audio_speed"]
        if "agents_boundary" in changed_keys:         effect_fn.boundary = s["agents_boundary"]
        if "agents_flip_threshold" in changed_keys:  effect_fn.flip_threshold = s["agents_flip_threshold"]
        if "agents_flip_probability" in changed_keys: effect_fn.flip_probability = s["agents_flip_probability"]


def random_pick():
    r, g, b = colorsys.hsv_to_rgb(random.random(), 1.0, 1.0)
    return {
        "mode": random.choice(VALID_MODES),
        "color_mode": random.choice(VALID_COLOR_MODES),
        "palette": random.choice(list(PALETTES.keys())),
        "color": [int(r * 255), int(g * 255), int(b * 255)],
    }


def validate_patch(patch):
    """Sanity-check incoming UI changes. Drop unknown keys and clamp values.
    Returns the cleaned dict (only valid changes).
    """
    cleaned = {}
    for key, val in patch.items():
        if key not in settings:
            continue
        if key == "mode" and val not in VALID_MODES:
            continue
        if key == "color_mode" and val not in VALID_COLOR_MODES:
            continue
        if key == "agents_boundary" and val not in VALID_BOUNDARIES:
            continue
        if key == "palette" and val not in PALETTES:
            continue
        if key == "color":
            try:
                val = [max(0, min(255, int(c))) for c in val[:3]]
                if len(val) != 3:
                    continue
            except (TypeError, ValueError):
                continue
        if isinstance(settings[key], (int, float)) and key not in ("color",):
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
        cleaned[key] = val
    return cleaned


# ------------------------------------------------------------------- audio

def find_blackhole():
    p = pyaudio.PyAudio()
    for i in range(p.get_device_count()):
        if "BlackHole" in p.get_device_info_by_index(i)["name"]:
            return p, i
    p.terminate()
    return None, -1


def audio_loop():
    global last_switch

    p, idx = find_blackhole()
    if idx == -1:
        print("Error: BlackHole audio device not found.")
        os._exit(1)
    print(f"Using audio device index {idx}: BlackHole")

    stream = p.open(format=pyaudio.paFloat32, channels=2, rate=44100, input=True,
                    input_device_index=idx, frames_per_buffer=1024)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    shift_offset = 0.0
    peak_rms = 1e-6
    last_switch = time.time()

    try:
        while True:
            data = np.frombuffer(stream.read(1024, exception_on_overflow=False), dtype=np.float32)

            if len(data) == 0:
                brightness = 0
            else:
                rms = float(np.sqrt(np.mean(data**2)))
                peak_rms = max(rms, peak_rms * PEAK_DECAY)
                brightness = int(np.clip(rms / peak_rms * 255, 0, 255))

            with settings_lock:
                interval = settings["randomize_interval"]
                if interval > 0 and time.time() - last_switch >= interval:
                    settings.update(random_pick())
                    apply_settings({"mode", "color_mode", "palette", "color"})
                    last_switch = time.time()
                    print(f"Auto-switched: mode={settings['mode']} "
                          f"color_mode={settings['color_mode']} "
                          f"palette={settings['palette']} color={settings['color']}")

                shift = int(shift_offset) % NUM_LEDS
                rotated = base_pixels[shift:] + base_pixels[:shift]
                pixels = effect_fn(rotated, brightness)

            sock.sendto(to_packet(pixels, COLOR_ORDER), (WLED_IP, WLED_PORT))
            shift_offset += PALETTE_SHIFT
            time.sleep(0.01)
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


# --------------------------------------------------------------------- web

def state_payload():
    return {
        **settings,
        "palettes": list(PALETTES.keys()),
        "modes": VALID_MODES,
        "color_modes": VALID_COLOR_MODES,
        "boundaries": VALID_BOUNDARIES,
    }


# Thin wrappers exposed to the web layer. Each handles locking internally so
# web_ui doesn't need to know about settings_lock.

def get_state():
    with settings_lock:
        return state_payload()


def apply_patch(patch):
    cleaned = validate_patch(patch)
    with settings_lock:
        changed = set()
        for k, v in cleaned.items():
            if settings[k] != v:
                settings[k] = v
                changed.add(k)
        if changed:
            apply_settings(changed)
        return state_payload()


def randomize_now():
    with settings_lock:
        settings.update(random_pick())
        apply_settings({"mode", "color_mode", "palette", "color"})
        return state_payload()


# -------------------------------------------------------------------- main

def main():
    global effect_fn, base_pixels
    effect_fn = build_effect()
    base_pixels = palette_gradient(settings["palette"], NUM_LEDS, loop=PALETTE_LOOP)

    threading.Thread(target=audio_loop, daemon=True).start()

    server = serve("0.0.0.0", HTTP_PORT,
                   get_state=get_state,
                   apply_patch=apply_patch,
                   randomize=randomize_now,
                   index_html_path=INDEX_HTML_PATH)
    hostname = socket.gethostname()
    print(f"Web UI: http://{hostname}.local:{HTTP_PORT}/")
    print(f"Initial: mode={settings['mode']} color_mode={settings['color_mode']} "
          f"palette={settings['palette']} color={settings['color']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
        server.shutdown()


if __name__ == "__main__":
    main()
