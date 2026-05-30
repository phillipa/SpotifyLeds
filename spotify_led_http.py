import pyaudio
import numpy as np
import time
import socket
import random
import colorsys
import threading
import os

from led_effects import palette_gradient, dnrgb_packets, PALETTES
from led_effects.linear import Pulse, Twinkle, Agents
from led_effects.cube import Cube, RisingEmbers, Spectrum
from web_ui import serve

# Hardware / runtime constants — not editable from the UI
WLED_IP = "192.168.0.194"   # mDNS: wled-0bec08.local
WLED_PORT = 21324           # WLED realtime UDP (DNRGB)
HTTP_PORT = 8080

# Reference LED count: the cube is 4 lines x 273 = 1092. Cube is locked to the
# cube geometry below; linear effects (pulse/twinkle/agents) size themselves to
# the editable "linear_leds" setting so the strip length can be set to match
# whatever hardware is attached.
DEFAULT_LINEAR_LEDS = 1092
MAX_LINEAR_LEDS = 10000

# Cube geometry: each line is routed bottom -> vertical -> top.
# Defaults assume equal thirds (273 / 3 = 91); adjust if the physical split differs.
CUBE_LINES = 4
CUBE_LINE_LEDS = 273
CUBE_BOTTOM_LEDS = 91
CUBE_VERTICAL_LEDS = 91
CUBE_TOP_LEDS = 91

COLOR_ORDER = "RGB"

PALETTE_SHIFT = 0.5     # LEDs to scroll the palette per frame
PALETTE_LOOP = True     # blend the last LED back to the first so scrolling is seamless
PEAK_DECAY = 0.999      # auto-gain decay rate

# Audio capture / FFT. The realtime spectrum (for the Spectrum effect) is
# computed once per frame and handed to the effect as per-band energies.
SAMPLE_RATE = 44100
FRAMES_PER_BUFFER = 1024
AUDIO_BANDS = 32        # frequency bands mapped onto the cube's height axis
BAND_FMIN = 40          # Hz, lowest band edge
BAND_FMAX = 16000       # Hz, highest band edge
BAND_DECAY = 0.999      # spectrum auto-gain decay rate

# Cube-geometry effects size themselves to the physical cube, not linear_leds.
CUBE_MODES = ("cube", "embers", "spectrum")

INDEX_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

# Available effects, listed flat in the UI. Cube/embers/spectrum are designed
# for the cube geometry, the rest for a generic linear strip, but all are
# selectable.
MODES = ["pulse", "twinkle", "agents", "cube", "embers", "spectrum"]
VALID_COLOR_MODES = ["solid", "palette_linear", "palette_random"]
VALID_BOUNDARIES = ["wrap", "bounce"]


# All UI-editable settings live here. Audio loop reads, HTTP handler writes.
settings = {
    "mode": MODES[0],
    "linear_leds": DEFAULT_LINEAR_LEDS,  # strip length for linear modes (editable)
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

    "embers_fade": 0.85,
    "embers_spawn": 0.6,
    "embers_base_speed": 0.5,
    "embers_audio_speed": 3.0,

    "spectrum_gamma": 1.5,
}

settings_lock = threading.Lock()
effect_fn = None
base_pixels = None
last_switch = 0.0


def active_num_leds():
    """Framebuffer length for the currently selected mode.

    Cube-geometry effects are fixed to the physical cube; every other (linear)
    mode uses the user-editable linear_leds so the strip length can match the
    attached hardware.
    """
    if settings["mode"] in CUBE_MODES:
        return CUBE_LINES * CUBE_LINE_LEDS
    return int(settings["linear_leds"])


def build_effect():
    """Construct a fresh effect instance from the current settings.

    Returns None when no mode is selected — the audio loop renders an
    all-dark frame in that case.
    """
    s = settings
    color = tuple(s["color"])
    cm = s["color_mode"]
    mode = s["mode"]
    n = active_num_leds()
    if not mode:
        return None
    if mode == "pulse":
        return Pulse(n, color_mode=cm, color=color,
                     attack=s["pulse_attack"], release=s["pulse_release"],
                     gamma=s["pulse_gamma"])
    if mode == "twinkle":
        return Twinkle(n, color_mode=cm, color=color,
                       fade=s["twinkle_fade"],
                       fade_jitter=s["twinkle_fade_jitter"],
                       density=s["twinkle_density"])
    if mode == "agents":
        return Agents(n, color_mode=cm, color=color,
                      count=int(s["agents_count"]), fade=s["agents_fade"],
                      base_speed=s["agents_base_speed"],
                      audio_speed=s["agents_audio_speed"],
                      boundary=s["agents_boundary"],
                      flip_threshold=s["agents_flip_threshold"],
                      flip_probability=s["agents_flip_probability"])
    if mode == "cube":
        return Cube(n, color_mode=cm, color=color,
                    lines=CUBE_LINES, leds_per_line=CUBE_LINE_LEDS,
                    bottom_leds=CUBE_BOTTOM_LEDS,
                    vertical_leds=CUBE_VERTICAL_LEDS,
                    top_leds=CUBE_TOP_LEDS)
    if mode == "embers":
        return RisingEmbers(n, color_mode=cm, color=color,
                            lines=CUBE_LINES, leds_per_line=CUBE_LINE_LEDS,
                            bottom_leds=CUBE_BOTTOM_LEDS,
                            vertical_leds=CUBE_VERTICAL_LEDS,
                            top_leds=CUBE_TOP_LEDS,
                            fade=s["embers_fade"], spawn_rate=s["embers_spawn"],
                            base_speed=s["embers_base_speed"],
                            audio_speed=s["embers_audio_speed"])
    if mode == "spectrum":
        return Spectrum(n, color_mode=cm, color=color,
                        lines=CUBE_LINES, leds_per_line=CUBE_LINE_LEDS,
                        bottom_leds=CUBE_BOTTOM_LEDS,
                        vertical_leds=CUBE_VERTICAL_LEDS,
                        top_leds=CUBE_TOP_LEDS, gamma=s["spectrum_gamma"])
    raise ValueError(f"Unknown mode: {mode}")


# Settings whose change requires rebuilding the effect (different class,
# different agent population, or a different LED count). Other tunables can be
# mutated live without losing accumulated state (twinkle sparkles, agent
# positions, etc.). linear_leds is structural because it resizes the
# framebuffer.
STRUCTURAL_KEYS = {"mode", "color_mode", "agents_count", "linear_leds"}


def apply_settings(changed_keys):
    """Propagate settings changes to the running effect. Caller must hold settings_lock."""
    global effect_fn, base_pixels

    n = active_num_leds()
    if STRUCTURAL_KEYS & changed_keys:
        effect_fn = build_effect()
        base_pixels = palette_gradient(settings["palette"], n, loop=PALETTE_LOOP)
        return

    if "palette" in changed_keys:
        base_pixels = palette_gradient(settings["palette"], n, loop=PALETTE_LOOP)

    if effect_fn is None:
        return  # no live effect to tune

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
    elif m == "embers":
        if "embers_fade" in changed_keys:        effect_fn.fade = s["embers_fade"]
        if "embers_spawn" in changed_keys:       effect_fn.spawn_rate = s["embers_spawn"]
        if "embers_base_speed" in changed_keys:  effect_fn.base_speed = s["embers_base_speed"]
        if "embers_audio_speed" in changed_keys: effect_fn.audio_speed = s["embers_audio_speed"]
    elif m == "spectrum":
        if "spectrum_gamma" in changed_keys: effect_fn.gamma = s["spectrum_gamma"]


def random_pick():
    r, g, b = colorsys.hsv_to_rgb(random.random(), 1.0, 1.0)
    return {
        "mode": random.choice(MODES),
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
        if key == "mode" and val not in MODES:
            continue
        if key == "color_mode" and val not in VALID_COLOR_MODES:
            continue
        if key == "agents_boundary" and val not in VALID_BOUNDARIES:
            continue
        if key == "palette" and val not in PALETTES:
            continue
        if key == "linear_leds":
            try:
                val = max(1, min(MAX_LINEAR_LEDS, int(float(val))))
            except (TypeError, ValueError):
                continue
            cleaned[key] = val
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


def band_bin_edges():
    """rfft bin-index edges for AUDIO_BANDS log-spaced bands (length BANDS+1)."""
    edges = np.logspace(np.log10(BAND_FMIN), np.log10(BAND_FMAX), AUDIO_BANDS + 1)
    bins = (edges * FRAMES_PER_BUFFER / SAMPLE_RATE).astype(int)
    return np.clip(bins, 1, FRAMES_PER_BUFFER // 2)


def audio_loop():
    global last_switch

    p, idx = find_blackhole()
    if idx == -1:
        print("Error: BlackHole audio device not found.")
        os._exit(1)
    print(f"Using audio device index {idx}: BlackHole")

    stream = p.open(format=pyaudio.paFloat32, channels=2, rate=SAMPLE_RATE, input=True,
                    input_device_index=idx, frames_per_buffer=FRAMES_PER_BUFFER)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    window = np.hanning(FRAMES_PER_BUFFER)
    band_edges = band_bin_edges()

    shift_offset = 0.0
    peak_rms = 1e-6
    peak_spec = 1e-6
    last_switch = time.time()

    try:
        while True:
            data = np.frombuffer(stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False), dtype=np.float32)

            if len(data) == 0:
                brightness = 0
                bands = [0.0] * AUDIO_BANDS
            else:
                rms = float(np.sqrt(np.mean(data**2)))
                peak_rms = max(rms, peak_rms * PEAK_DECAY)
                brightness = int(np.clip(rms / peak_rms * 255, 0, 255))

                # Per-band spectrum (mono mix) for the Spectrum effect, auto-gained
                # against a decaying peak so it stays responsive across volumes.
                mono = data.reshape(-1, 2).mean(axis=1)[:FRAMES_PER_BUFFER]
                if mono.size == FRAMES_PER_BUFFER:
                    mag = np.abs(np.fft.rfft(mono * window))
                    energy = np.array([
                        mag[band_edges[b]:max(band_edges[b] + 1, band_edges[b + 1])].mean()
                        for b in range(AUDIO_BANDS)
                    ])
                    peak_spec = max(float(energy.max()), peak_spec * BAND_DECAY)
                    bands = np.clip(energy / peak_spec, 0.0, 1.0).tolist()
                else:
                    bands = [0.0] * AUDIO_BANDS

            with settings_lock:
                interval = settings["randomize_interval"]
                if interval > 0 and time.time() - last_switch >= interval:
                    settings.update(random_pick())
                    apply_settings({"mode", "color_mode", "palette", "color"})
                    last_switch = time.time()
                    print(f"Auto-switched: mode={settings['mode']} "
                          f"color_mode={settings['color_mode']} "
                          f"palette={settings['palette']} color={settings['color']}")

                n = len(base_pixels)
                shift = int(shift_offset) % n
                rotated = base_pixels[shift:] + base_pixels[:shift]
                if effect_fn is None:
                    pixels = [(0, 0, 0)] * n
                else:
                    pixels = effect_fn(rotated, brightness, bands)

            for packet in dnrgb_packets(pixels, COLOR_ORDER):
                sock.sendto(packet, (WLED_IP, WLED_PORT))
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
        "modes": MODES,
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
    base_pixels = palette_gradient(settings["palette"], active_num_leds(), loop=PALETTE_LOOP)

    threading.Thread(target=audio_loop, daemon=True).start()

    server = serve("0.0.0.0", HTTP_PORT,
                   get_state=get_state,
                   apply_patch=apply_patch,
                   randomize=randomize_now,
                   index_html_path=INDEX_HTML_PATH)
    hostname = socket.gethostname().removesuffix(".local")
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
