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
    """Light radiates from each top corner out along all three incident edges.

    Every top corner is the bend where one line's vertical column meets its top
    edge. Three edges meet there, and all three fill in sync with the audio:

      * that line's vertical column      — fills downward from the corner
      * that line's own top edge         — fills outward from the corner
      * the neighbouring line's top edge — meets this corner at its far end,
                                           so it fills inward from that far end

    Each line runs in one direction (base, then up, then along the top, never
    doubling back), so the four top edges form a ring in line order: line i's
    top edge runs from corner i to corner i-1. Corner i is therefore shared by
    line i's top edge (near end) and line i+1's top edge (far end) — e.g.
    corner 1 is fed by line 2's top edge. Because each top edge is lit from
    both of its corners, the two fronts overlap in the middle at high audio —
    that overlap is intentional.

    `corners` is a per-line list of booleans; a corner radiates only when its
    entry is True, so the active corners can be chosen at runtime. The bottom
    face is never lit.
    """
    def __init__(self, num_leds, color_mode="palette_linear", color=(255, 255, 255),
                 lines=4, leds_per_line=273,
                 bottom_leds=91, vertical_leds=91, top_leds=91, corners=None):
        super().__init__(num_leds, color_mode, color)
        self.lines = lines
        self.leds_per_line = leds_per_line
        self.bottom_leds = bottom_leds
        self.vertical_leds = vertical_leds
        self.top_leds = top_leds
        self.corners = list(corners) if corners is not None else [True] * lines

    def _corner_active(self, i):
        return i < len(self.corners) and bool(self.corners[i])

    def _top_corner_index(self, line):
        """Flat index of `line`'s top corner — the first LED of its top strip."""
        return line * self.leds_per_line + self.bottom_leds + self.vertical_leds

    def __call__(self, pixels, brightness):
        colors = self._resolve_colors(pixels)
        frac = brightness / 255.0
        v_lit = int(round(frac * self.vertical_leds))
        t_lit = int(round(frac * self.top_leds))
        out = [(0, 0, 0)] * self.num_leds
        for line in range(self.lines):
            if not self._corner_active(line):
                continue
            corner = self._top_corner_index(line)
            # Vertical column: light v_lit LEDs working DOWN from the corner.
            for j in range(v_lit):
                idx = corner - 1 - j
                out[idx] = colors[idx]
            # This line's own top edge: light OUTWARD from the corner.
            for j in range(t_lit):
                idx = corner + j
                out[idx] = colors[idx]
            # Neighbouring line's top edge ends at this corner: light INWARD
            # from its far end (line i+1's top edge runs corner i+1 -> corner i).
            nbr_corner = self._top_corner_index((line + 1) % self.lines)
            far_end = nbr_corner + self.top_leds - 1
            for j in range(t_lit):
                idx = far_end - j
                out[idx] = colors[idx]
            # Bottom face stays dark.
        return out
