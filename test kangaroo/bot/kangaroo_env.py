"""
Kangaroo practice environment (headless, no display needed).

A tiny Gym-style world: a cursor you control and a bouncing "kangaroo" target
you try to click. This is the SAFE learning target for the whole project — it
runs entirely on your machine, has no server and no other players, so training
an AI to play it is completely fine.

Observation (float32, length 8), all roughly in [-1, 1]:
    0 cursor_x / W        1 cursor_y / H
    2 target_x / W        3 target_y / H
    4 target_vx / MAXV    5 target_vy / MAXV
    6 (target_x-cursor_x)/W   7 (target_y-cursor_y)/H

Actions (Discrete 6):
    0 = noop   1 = up   2 = down   3 = left   4 = right   5 = click
"""
import numpy as np

W, H = 640, 360
TARGET_R = 18
CURSOR_STEP = 14
MAX_SPEED = 4.0
MAX_STEPS = 400
N_ACTIONS = 6
OBS_DIM = 8


class KangarooEnv:
    def __init__(self, seed=None, shaping=True):
        self.rng = np.random.default_rng(seed)
        self.shaping = shaping   # reward help that speeds up early learning
        self.reset()

    # ---- lifecycle ----
    def reset(self):
        self.cursor = np.array([W / 2, H / 2], dtype=np.float32)
        self._spawn_target()
        self.steps = 0
        self.hits = 0
        self._prev_dist = self._dist()
        return self._obs()

    def step(self, action):
        reward = -0.01  # small time cost so it doesn't dawdle

        if action == 1:
            self.cursor[1] -= CURSOR_STEP
        elif action == 2:
            self.cursor[1] += CURSOR_STEP
        elif action == 3:
            self.cursor[0] -= CURSOR_STEP
        elif action == 4:
            self.cursor[0] += CURSOR_STEP
        self.cursor[0] = float(np.clip(self.cursor[0], 0, W))
        self.cursor[1] = float(np.clip(self.cursor[1], 0, H))

        if action == 5:  # click
            if self._dist() <= TARGET_R:
                reward += 1.0
                self.hits += 1
                self._spawn_target()
            else:
                reward -= 0.05  # wasted click is discouraged

        self._move_target()

        d = self._dist()
        if self.shaping:
            # reward getting closer, penalize drifting away
            reward += 0.02 * (self._prev_dist - d) / CURSOR_STEP
        self._prev_dist = d

        self.steps += 1
        done = self.steps >= MAX_STEPS
        return self._obs(), reward, done, {"hits": self.hits}

    # ---- helpers ----
    def _spawn_target(self):
        self.target = np.array(
            [self.rng.uniform(40, W - 40), self.rng.uniform(40, H - 40)],
            dtype=np.float32,
        )
        ang = self.rng.uniform(0, 2 * np.pi)
        spd = self.rng.uniform(2.0, MAX_SPEED)
        self.tvel = np.array([np.cos(ang) * spd, np.sin(ang) * spd], dtype=np.float32)

    def _move_target(self):
        self.target += self.tvel
        for i, (lo, hi) in enumerate([(20, W - 20), (20, H - 20)]):
            if self.target[i] < lo or self.target[i] > hi:
                self.tvel[i] *= -1
                self.target[i] = float(np.clip(self.target[i], lo, hi))

    def _dist(self):
        return float(np.linalg.norm(self.cursor - self.target))

    def _obs(self):
        d = self.target - self.cursor
        return np.array(
            [
                self.cursor[0] / W, self.cursor[1] / H,
                self.target[0] / W, self.target[1] / H,
                self.tvel[0] / MAX_SPEED, self.tvel[1] / MAX_SPEED,
                d[0] / W, d[1] / H,
            ],
            dtype=np.float32,
        )
