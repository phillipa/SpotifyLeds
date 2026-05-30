"""Shared LED-effect infrastructure: palettes, base class, wire-format helpers.

Each effect produces a list of (r, g, b) tuples of length num_leds. Byte
ordering for the strip is applied later at render time, not here.
"""

import random

PALETTES = {
    "rainbow": [
        (255, 0, 0), (255, 255, 0), (0, 255, 0),
        (0, 255, 255), (0, 0, 255), (255, 0, 255), (255, 0, 0),
    ],
    "fire":    [(0, 0, 0), (128, 0, 0), (255, 0, 0), (255, 128, 0), (255, 255, 0), (255, 255, 255)],
    "ocean":   [(0, 0, 32), (0, 64, 128), (0, 128, 255), (128, 255, 255)],
    "sunset":  [(20, 0, 40), (255, 0, 128), (255, 128, 0), (255, 220, 80)],
    "forest":  [(0, 16, 0), (0, 80, 16), (32, 160, 32), (180, 220, 80)],
    "purples": [(20, 0, 40), (80, 0, 160), (180, 80, 255), (255, 200, 255)],
    "purplesgreens": [(40, 0, 40), (0, 16, 0), (20, 0, 20), (0, 32, 0)],
    "lava":      [(0, 0, 0), (60, 0, 0), (200, 30, 0), (255, 100, 0), (255, 200, 60), (255, 50, 0)],
    "embers":    [(0, 0, 0), (40, 0, 0), (160, 20, 0), (255, 80, 20), (90, 10, 0)],
    "arctic":    [(8, 16, 32), (40, 100, 180), (140, 200, 255), (240, 255, 255), (180, 220, 240)],
    "neon":      [(255, 0, 200), (0, 255, 240), (200, 255, 0), (255, 60, 200)],
    "synthwave": [(20, 0, 60), (255, 0, 180), (80, 0, 200), (0, 220, 255), (60, 0, 120)],
    "cyberpunk": [(0, 0, 0), (0, 40, 0), (0, 120, 30), (40, 220, 60), (160, 255, 180), (0, 60, 10)],
    "autumn":    [(30, 8, 0), (180, 50, 0), (220, 110, 0), (240, 180, 30), (110, 50, 10)],
    "tropical":  [(0, 100, 100), (40, 220, 200), (255, 200, 80), (255, 100, 80), (200, 50, 150)],
    "mint":      [(0, 30, 30), (40, 180, 140), (160, 240, 200), (240, 255, 240), (60, 200, 180)],
    "candy":     [(255, 60, 160), (40, 200, 180), (255, 180, 40), (160, 60, 240), (255, 100, 200)],
    "berry":     [(20, 0, 20), (120, 0, 60), (220, 0, 100), (255, 80, 160), (140, 0, 80)],
    "citrus":    [(255, 240, 60), (255, 160, 0), (180, 220, 0), (255, 200, 40)],
}


def solid(color, num_leds):
    """All LEDs the same color."""
    return [tuple(color)] * num_leds


def palette_gradient(stops, num_leds, loop=False):
    """Linearly interpolate a list of (r, g, b) stops across num_leds.

    `stops` may be a palette name from PALETTES or a list of (r, g, b) tuples.
    When `loop=True`, the gradient ends back at the starting color so the
    palette tiles seamlessly when scrolled.
    """
    if isinstance(stops, str):
        stops = PALETTES[stops]
    if num_leds <= 0:
        return []
    if num_leds == 1 or len(stops) == 1:
        return [tuple(stops[0])] * num_leds
    if loop:
        # Append a wrap-around stop and divide by num_leds (not num_leds - 1) so
        # the last LED lands just before the start color instead of on it —
        # otherwise tiling would show the start color twice in a row.
        stops = list(stops) + [tuple(stops[0])]
        denom = num_leds
    else:
        denom = num_leds - 1

    n_segments = len(stops) - 1
    out = []
    for i in range(num_leds):
        pos = i * n_segments / denom
        idx = int(pos)
        if idx >= n_segments:
            out.append(tuple(stops[-1]))
            continue
        frac = pos - idx
        a, b = stops[idx], stops[idx + 1]
        out.append((
            int(a[0] + (b[0] - a[0]) * frac),
            int(a[1] + (b[1] - a[1]) * frac),
            int(a[2] + (b[2] - a[2]) * frac),
        ))
    return out


class _ColoredEffect:
    """Base for effects that produce one stable color per LED each frame.

    color_mode:
      - "solid":          every LED uses `color`
      - "palette_linear": LED i uses pixels[i] (rotates with the palette)
      - "palette_random": LED i uses a random palette color, snapshotted on
                          first call so the assignment stays stable across frames
                          (otherwise it would flicker every frame).
    """
    def __init__(self, num_leds, color_mode="palette_linear", color=(255, 255, 255)):
        self.num_leds = num_leds
        self.color_mode = color_mode
        self.color = tuple(color)
        self._random_colors = None

    def _resolve_colors(self, pixels):
        if self.color_mode == "solid":
            return [self.color] * self.num_leds
        if self.color_mode == "palette_linear":
            return list(pixels)
        if self._random_colors is None:
            self._random_colors = [random.choice(pixels) for _ in range(self.num_leds)]
        return self._random_colors


_COLOR_ORDERS = {"RGB": (0, 1, 2), "GRB": (1, 0, 2), "BRG": (2, 0, 1),
                 "BGR": (2, 1, 0), "GBR": (1, 2, 0), "RBG": (0, 2, 1)}


def dnrgb_packets(pixels, color_order="RGB", timeout_secs=2, leds_per_chunk=480):
    """Yield DNRGB-framed UDP packets covering the full strip.

    DNRGB (protocol 4) is WLED's realtime UDP format for long strips:

        byte 0:    4                  (protocol = DNRGB)
        byte 1:    timeout_secs       (WLED reverts when no packets arrive for this long)
        byte 2-3:  start LED index, big-endian uint16
        byte 4+:   RGB triples

    Splitting at 480 LEDs/chunk keeps each packet's payload under the safe
    UDP-over-Ethernet MTU (~1472 bytes) so nothing relies on IP fragmentation.
    """
    order = _COLOR_ORDERS[color_order]
    n = len(pixels)
    for start in range(0, n, leds_per_chunk):
        chunk = pixels[start:start + leds_per_chunk]
        header = bytes([4, timeout_secs, (start >> 8) & 0xFF, start & 0xFF])
        body = bytearray(len(chunk) * 3)
        for i, px in enumerate(chunk):
            body[i*3 + 0] = px[order[0]]
            body[i*3 + 1] = px[order[1]]
            body[i*3 + 2] = px[order[2]]
        yield header + bytes(body)
