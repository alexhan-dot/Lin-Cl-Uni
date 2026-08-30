"""
Gymnasium wrapper around PixelKangaroo so stable-baselines3's CnnPolicy can
learn to play from the raw image — reinforcement learning directly from pixels.
This is the fix for the behavior-cloning-from-pixels plateau: reward corrects the
drift that pure imitation can't.
"""
import gymnasium as gym
import numpy as np
from gymnasium import spaces

from kangaroo_env import N_ACTIONS
from pixel_env import PixelKangaroo, IMG


class PixelKangarooGym(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, shaping=True):
        super().__init__()
        self.env = PixelKangaroo(shaping=shaping)
        self.observation_space = spaces.Box(0, 255, (2, IMG, IMG), dtype=np.uint8)
        self.action_space = spaces.Discrete(N_ACTIONS)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self.env = PixelKangaroo(seed=seed, shaping=self.env.base.shaping)
        return self.env.reset(), {}

    def step(self, action):
        obs, reward, done, info = self.env.step(int(action))
        return obs, float(reward), False, done, info
