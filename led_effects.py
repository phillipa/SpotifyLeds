"""LED effect library.

Each effect returns a list of (r, g, b) tuples of length num_leds.
Byte ordering for the strip is applied later at render time, not here.
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


class Pulse(_ColoredEffect):
    """Every LED at its assigned color, scaled by an envelope of the audio.

    The envelope snaps up on rises and decays slowly on dips, so each beat is a
    visible flash that holds and fades. A gamma curve gives perceptual contrast
    so quiet sections actually look quiet.

    attack  — fraction of (peak - current) to adopt this frame on rises (0..1).
              1.0 = snap to the new peak instantly.
    release — per-frame multiplier when audio dips below current level (0..1).
              Closer to 1 = slower fall.
    gamma   — perceptual curve; >1 darkens midtones so peaks dominate.
    """
    def __init__(self, num_leds, color_mode="palette_linear", color=(255, 255, 255),
                 attack=1.0, release=0.92, gamma=2.2):
        super().__init__(num_leds, color_mode, color)
        self.attack = attack
        self.release = release
        self.gamma = gamma
        self.level = 0.0

    def __call__(self, pixels, brightness):
        if brightness > self.level:
            self.level += (brightness - self.level) * self.attack
        else:
            self.level *= self.release

        scale = (self.level / 255.0) ** self.gamma
        return [
            (int(r * scale), int(g * scale), int(b * scale))
            for r, g, b in self._resolve_colors(pixels)
        ]


class Progressive(_ColoredEffect):
    """Light LEDs left-to-right; the lit count scales with the audio level."""
    def __call__(self, pixels, brightness):
        colors = self._resolve_colors(pixels)
        lit = int(round((brightness / 255.0) * self.num_leds))
        return list(colors[:lit]) + [(0, 0, 0)] * (self.num_leds - lit)


class Twinkle:
    """Random LEDs sparkle on and fade out over subsequent frames.

    color_mode:
      - "solid":          every twinkle uses `color`
      - "palette_linear": twinkle at LED i uses pixels[i] (positionally themed)
      - "palette_random": twinkle picks a random color from pixels

    fade        — per-frame brightness multiplier in [0, 1]; lower = shorter trails.
    fade_jitter — when > 0, each new twinkle picks its own fade rate uniformly
                  from [fade - fade_jitter, fade + fade_jitter] (clamped to [0, 1]),
                  so sparkles decay at slightly varied speeds.
    density     — target fraction of LEDs lit at peak audio (brightness=255).
                  Each frame, dark positions are spawned into until the count of
                  lit LEDs matches density * (brightness / 255) * num_leds.
    """
    def __init__(self, num_leds, color_mode="palette_random",
                 color=(255, 255, 255), fade=0.9, fade_jitter=0.0, density=0.3):
        self.num_leds = num_leds
        self.color_mode = color_mode
        self.color = tuple(color)
        self.fade = fade
        self.fade_jitter = fade_jitter
        self.density = density
        self.state = [(0, 0, 0)] * num_leds
        self.fades = [fade] * num_leds

    def __call__(self, pixels, brightness):
        self.state = [
            (int(r * f), int(g * f), int(b * f))
            for (r, g, b), f in zip(self.state, self.fades)
        ]

        target = int(round(self.density * (brightness / 255.0) * self.num_leds))
        dark = [i for i, (r, g, b) in enumerate(self.state) if not (r or g or b)]
        n_new = min(target - (self.num_leds - len(dark)), len(dark))

        if n_new > 0:
            for i in random.sample(dark, n_new):
                if self.color_mode == "solid":
                    c = self.color
                elif self.color_mode == "palette_linear":
                    c = pixels[i]
                else:  # palette_random
                    c = pixels[random.randrange(len(pixels))]
                self.state[i] = c
                if self.fade_jitter:
                    jitter = random.uniform(-self.fade_jitter, self.fade_jitter)
                    self.fades[i] = max(0.0, min(1.0, self.fade + jitter))

        return list(self.state)

class Agents:
    """Moving pixels that leave a fading tail behind them.

    Each agent walks the strip with a fixed direction and color. The trail
    emerges naturally from fading the framebuffer each frame and redrawing
    each agent on top.

    color_mode:
      - "solid":  every agent uses `color`
      - anything else: each agent picks a random palette color on its first frame
        (palette_linear has no meaning for a moving agent, so it's treated the
        same as palette_random here).

    count        — number of agents on the strip (each picks a random direction).
    fade         — multiplier per LED of distance from the agent (in [0, 1]).
                   Lower = shorter tails. The per-frame fade is fade ** speed,
                   so the visible tail length stays constant when speed changes.
    base_speed   — LEDs per frame at silence (0 = stationary in quiet sections).
    audio_speed  — extra LEDs per frame at peak audio (brightness=255).
    boundary     — "wrap" (agent reappears at the opposite end) or "bounce"
                   (agent reverses direction at each end). With long tails,
                   "bounce" avoids the detached-ghost artifact wrap-around can
                   produce.
    flip_threshold — brightness fraction in [0, 1] that arms a flip event on its
                   rising edge. Hysteresis: brightness must drop back below the
                   threshold before another event can fire. 0 disables.
    flip_probability — on each flip event, each agent independently reverses
                   direction with this probability (0..1). 1.0 = always flip,
                   0.5 = roughly half the agents flip per peak, etc.
    """
    def __init__(self, num_leds, color_mode="palette_linear", color=(255, 255, 255),
                 count=5, fade=0.85, base_speed=0.2, audio_speed=2.0,
                 boundary="wrap", flip_threshold=0.0, flip_probability=1.0):
        self.num_leds = num_leds
        self.color_mode = color_mode
        self.color = tuple(color)
        self.count = count
        self.fade = fade
        self.base_speed = base_speed
        self.audio_speed = audio_speed
        self.boundary = boundary
        self.flip_threshold = flip_threshold
        self.flip_probability = flip_probability
        self._was_above = False
        self.state = [(0, 0, 0)] * num_leds
        # Each agent: [position (float), direction (-1 or +1), color (None until first frame)]
        self.agents = [
            [random.uniform(0, num_leds), random.choice([-1, 1]), None]
            for _ in range(count)
        ]

    def __call__(self, pixels, brightness):
        speed = self.base_speed + self.audio_speed * (brightness / 255.0)
        max_pos = self.num_leds - 1

        # fade is interpreted per-LED-of-distance, so per-frame fade = fade ** speed.
        # That keeps the visible tail length constant regardless of speed.
        fade_amount = self.fade ** speed if speed > 0 else 1.0
        self.state = [
            (int(r * fade_amount), int(g * fade_amount), int(b * fade_amount))
            for r, g, b in self.state
        ]

        # Rising-edge flip when audio peaks; each agent flips independently.
        above = self.flip_threshold > 0 and brightness >= self.flip_threshold * 255
        if above and not self._was_above:
            for agent in self.agents:
                if random.random() < self.flip_probability:
                    agent[1] = -agent[1]
        self._was_above = above

        for agent in self.agents:
            if agent[2] is None:
                if self.color_mode == "solid":
                    agent[2] = self.color
                else:
                    agent[2] = random.choice(pixels)

            old_pos = agent[0]
            raw_new = old_pos + agent[1] * speed

            # Paint every LED the agent crossed this frame so the trail has no
            # gaps when speed > 1. Use the agent's direction so we walk from
            # old → new in path order (modulo handles wrap-around indexing).
            start_int = int(old_pos)
            end_int = int(raw_new)
            step_dir = 1 if agent[1] > 0 else -1
            i = start_int
            while True:
                self.state[i % self.num_leds] = agent[2]
                if i == end_int:
                    break
                i += step_dir

            if self.boundary == "bounce":
                if raw_new < 0:
                    new_pos = -raw_new
                    agent[1] = -agent[1]
                elif raw_new > max_pos:
                    new_pos = 2 * max_pos - raw_new
                    agent[1] = -agent[1]
                else:
                    new_pos = raw_new
                new_pos = max(0.0, min(max_pos, new_pos))
            else:  # wrap
                new_pos = raw_new % self.num_leds

            agent[0] = new_pos

        return list(self.state)


def to_packet(pixels, color_order="RGB"):
    """Flatten a list of (r, g, b) tuples into a bytes packet for WLED UDP."""
    order = {"RGB": (0, 1, 2), "GRB": (1, 0, 2), "BRG": (2, 0, 1),
             "BGR": (2, 1, 0), "GBR": (1, 2, 0), "RBG": (0, 2, 1)}[color_order]
    out = bytearray(len(pixels) * 3)
    for i, px in enumerate(pixels):
        out[i*3 + 0] = px[order[0]]
        out[i*3 + 1] = px[order[1]]
        out[i*3 + 2] = px[order[2]]
    return bytes(out)
