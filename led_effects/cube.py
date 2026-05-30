"""Effects for the 4-line cube layout.

Each line is physically routed bottom edge -> vertical edge -> top edge.
The four lines are parallel, so per-line offsets within the flat strip are:

    [0, bottom_leds)                              bottom face
    [bottom_leds, bottom_leds + vertical_leds)    vertical column
    [bottom_leds + vertical_leds, leds_per_line)  top face

So within one line the LED index also tracks two physical coordinates for
free, without needing to know how the four lines join at the pillars:

    role   — floor (bottom), wall (vertical), or ceiling (top)
    height — 0 on the floor, ramps 0->1 up the wall, 1 on the ceiling
"""

import random

from led_effects.common import _ColoredEffect


class Cube(_ColoredEffect):
    """Bottom face always lit; four vertical columns rise together with audio.

    All four vertical columns reach the same height each frame, scaled by the
    audio level. The top face stays dark. Lit LEDs take their color from the
    same palette/color resolution as the other effects.
    """
    def __init__(self, num_leds, color_mode="palette_linear", color=(255, 255, 255),
                 lines=4, leds_per_line=273,
                 bottom_leds=91, vertical_leds=91, top_leds=91):
        super().__init__(num_leds, color_mode, color)
        self.lines = lines
        self.leds_per_line = leds_per_line
        self.bottom_leds = bottom_leds
        self.vertical_leds = vertical_leds
        self.top_leds = top_leds

    def __call__(self, pixels, brightness, bands=None):
        colors = self._resolve_colors(pixels)
        v_lit = int(round((brightness / 255.0) * self.vertical_leds))
        out = [(0, 0, 0)] * self.num_leds
        for line in range(self.lines):
            base = line * self.leds_per_line
            v_start = base + self.bottom_leds
            # Bottom face: always lit.
            for j in range(self.bottom_leds):
                out[base + j] = colors[base + j]
            # Vertical column: lit from the bottom up to v_lit.
            for j in range(v_lit):
                out[v_start + j] = colors[v_start + j]
            # Top face: stays dark.
        return out


class RisingEmbers(_ColoredEffect):
    """Sparks born on the floor that drift upward, leaving fading trails.

    Each ember is spawned somewhere on a line's floor segment and then walks
    forward along that line's path (floor -> up the wall -> across the ceiling)
    a little each frame. The framebuffer is faded every frame, so a moving
    ember smears into a rising streak. Louder audio spawns more embers and
    pushes them faster, so beats throw up bursts of sparks.

    fade        — per-frame brightness multiplier in [0, 1]; lower = shorter trails.
    base_speed  — LEDs per frame an ember rises at silence.
    audio_speed — extra LEDs per frame at peak audio (brightness = 255).
    spawn_rate  — embers spawned per line per frame at peak audio.
    """
    MAX_EMBERS = 600

    def __init__(self, num_leds, color_mode="palette_random", color=(255, 255, 255),
                 lines=4, leds_per_line=273,
                 bottom_leds=91, vertical_leds=91, top_leds=91,
                 fade=0.85, base_speed=0.5, audio_speed=3.0, spawn_rate=0.6):
        super().__init__(num_leds, color_mode, color)
        self.lines = lines
        self.leds_per_line = leds_per_line
        self.bottom_leds = bottom_leds
        self.vertical_leds = vertical_leds
        self.top_leds = top_leds
        self.fade = fade
        self.base_speed = base_speed
        self.audio_speed = audio_speed
        self.spawn_rate = spawn_rate
        self.state = [(0, 0, 0)] * num_leds
        self.embers = []  # each: [line, pos (float along the line's path), color]

    def _spawn_color(self, pixels):
        if self.color_mode == "solid":
            return self.color
        return random.choice(pixels)

    def __call__(self, pixels, brightness, bands=None):
        # Fade the framebuffer so moving embers leave trails.
        self.state = [
            (int(r * self.fade), int(g * self.fade), int(b * self.fade))
            for r, g, b in self.state
        ]

        # Spawn new embers on the floor, more when the audio is loud.
        level = brightness / 255.0
        expected = self.spawn_rate * level * self.lines
        n_new = int(expected) + (1 if random.random() < (expected % 1.0) else 0)
        for _ in range(min(n_new, self.MAX_EMBERS - len(self.embers))):
            line = random.randrange(self.lines)
            pos = random.uniform(0, self.bottom_leds)
            self.embers.append([line, pos, self._spawn_color(pixels)])

        # Move each ember up its line's path; drop it once it runs off the top.
        speed = self.base_speed + self.audio_speed * level
        alive = []
        for line, pos, col in self.embers:
            pos += speed
            if pos >= self.leds_per_line:
                continue
            self.state[line * self.leds_per_line + int(pos)] = col
            alive.append([line, pos, col])
        self.embers = alive

        return list(self.state)


class Spectrum(_ColoredEffect):
    """A frequency spectrum wrapped onto the cube's height axis.

    Bass lights the floor, mids climb the walls, and treble lights the ceiling:
    each LED's height picks a frequency band, and that band's energy sets the
    LED's brightness. `bands` is a list of per-band energies in [0, 1] (low to
    high frequency) supplied by the audio loop; with no bands the cube is dark.

    gamma — perceptual curve; >1 darkens quiet bands so peaks stand out.
    """
    def __init__(self, num_leds, color_mode="palette_linear", color=(255, 255, 255),
                 lines=4, leds_per_line=273,
                 bottom_leds=91, vertical_leds=91, top_leds=91, gamma=1.5):
        super().__init__(num_leds, color_mode, color)
        self.lines = lines
        self.leds_per_line = leds_per_line
        self.bottom_leds = bottom_leds
        self.vertical_leds = vertical_leds
        self.top_leds = top_leds
        self.gamma = gamma
        self._height = self._compute_heights()

    def _compute_heights(self):
        """Per-LED height in [0, 1]: 0 on the floor, ramping up the wall, 1 on top."""
        h = [0.0] * self.num_leds
        for line in range(self.lines):
            base = line * self.leds_per_line
            v_start = base + self.bottom_leds
            t_start = v_start + self.vertical_leds
            for j in range(self.vertical_leds):
                h[v_start + j] = (j + 0.5) / self.vertical_leds
            for j in range(self.top_leds):
                h[t_start + j] = 1.0
        return h

    def __call__(self, pixels, brightness, bands=None):
        out = [(0, 0, 0)] * self.num_leds
        if not bands:
            return out
        colors = self._resolve_colors(pixels)
        last = len(bands) - 1
        for i in range(self.num_leds):
            energy = bands[int(self._height[i] * last)]
            if energy <= 0:
                continue
            scale = energy ** self.gamma
            r, g, b = colors[i]
            out[i] = (int(r * scale), int(g * scale), int(b * scale))
        return out
