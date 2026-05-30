"""LED effect package.

Public surface:
    PALETTES, palette_gradient, solid     -- palette utilities
    dnrgb_packets                         -- WLED realtime packet builder

Effect classes live in shape-specific submodules:
    led_effects.linear   -- generic strip effects (Pulse, Twinkle, Agents)
    led_effects.cube     -- 4-line cube effects (Cube)
    led_effects.column   -- column-arrangement effects (none yet)
"""

from led_effects.common import (
    PALETTES,
    solid,
    palette_gradient,
    dnrgb_packets,
)

__all__ = ["PALETTES", "solid", "palette_gradient", "dnrgb_packets"]
