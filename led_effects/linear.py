"""Effects for a generic linear LED strip — geometry-agnostic.

These work on any single contiguous strip regardless of physical layout.
"""

import random

from led_effects.common import _ColoredEffect


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
