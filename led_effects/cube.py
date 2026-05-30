"""Effects for the 4-line cube layout.

Each line is physically routed bottom edge -> vertical edge -> top edge.
The four lines are parallel, so per-line offsets within the flat strip are:

    [0, bottom_leds)                              bottom face
    [bottom_leds, bottom_leds + vertical_leds)    vertical column
    [bottom_leds + vertical_leds, leds_per_line)  top face
"""

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

    def __call__(self, pixels, brightness):
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


class Radiate(_ColoredEffect):
    """Light radiates from each line's vertical-to-top bend.

    From the top corner — the bend where vertical meets top — light fills two
    directions in sync with the audio level:

      * down the vertical column, starting from the topmost LED
      * outward along the top face, starting at the corner

    Both segments fill to the same fraction of their length. The far end of
    each top strip stays dark until peak audio, so the top fills fractionally
    rather than all at once. The bottom face is never lit.
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

    def __call__(self, pixels, brightness):
        colors = self._resolve_colors(pixels)
        frac = brightness / 255.0
        v_lit = int(round(frac * self.vertical_leds))
        t_lit = int(round(frac * self.top_leds))
        out = [(0, 0, 0)] * self.num_leds
        for line in range(self.lines):
            base = line * self.leds_per_line
            v_start = base + self.bottom_leds
            corner = v_start + self.vertical_leds  # first index of top strip
            # Vertical column: light v_lit LEDs working DOWN from the top corner.
            for j in range(v_lit):
                idx = corner - 1 - j
                out[idx] = colors[idx]
            # Top strip: light t_lit LEDs working OUTWARD from the top corner.
            for j in range(t_lit):
                idx = corner + j
                out[idx] = colors[idx]
            # Bottom face stays dark.
        return out
