"""
Pixel view of the practice game — the AI "sees" the screen instead of being
handed tidy coordinates.

PixelKangaroo wraps KangarooEnv and returns a small rendered image (drawn with
numpy, no display needed). Two frames are stacked so motion — the target's
velocity — is visible in the pixels, the same trick classic Atari agents use.

Observation: uint8 array, shape (2, 64, 64)   # 2 stacked grayscale frames
Actions: unchanged (Discrete 6)
"""
from collections import deque

import numpy as np

from kangaroo_env import KangarooEnv, W, H, TARGET_R

IMG = 64
SX, SY = IMG / W, IMG / H


def _disk(img, cx, cy, r, val):
    x0, x1 = max(0, cx - r), min(IMG, cx + r + 1)
    y0, y1 = max(0, cy - r), min(IMG, cy + r + 1)
    for y in range(y0, y1):
        for x in range(x0, x1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                img[y, x] = val


class PixelKangaroo:
    def __init__(self, seed=None, shaping=True):
        self.base = KangarooEnv(seed=seed, shaping=shaping)
        self.frames = deque(maxlen=2)

    def _frame(self):
        img = np.zeros((IMG, IMG), dtype=np.uint8)
        _disk(img, int(self.base.target[0] * SX), int(self.base.target[1] * SY), 3, 255)
        _disk(img, int(self.base.cursor[0] * SX), int(self.base.cursor[1] * SY), 2, 130)
        return img

    def _obs(self):
        return np.stack(self.frames, axis=0)  # (2, 64, 64) uint8

    def reset(self):
        self.base.reset()
        f = self._frame()
        self.frames.clear()
        self.frames.append(f)
        self.frames.append(f)
        return self._obs()

    def step(self, action):
        _, reward, done, info = self.base.step(action)
        self.frames.append(self._frame())
        return self._obs(), reward, done, info
