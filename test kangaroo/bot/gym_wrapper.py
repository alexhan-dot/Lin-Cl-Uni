"""
Gymnasium adapter so any standard RL library (stable-baselines3, etc.) can train
on the practice game. Wraps KangarooEnv in the gymnasium.Env API.

Feature observations (the 8-vector). For a pixel-based PPO, wrap PixelKangaroo
the same way with a Box(0,255, (2,64,64), uint8) space and use SB3's CnnPolicy.
"""
import gymnasium as gym
import numpy as np
from gymnasium import spaces

from kangaroo_env import KangarooEnv, OBS_DIM, N_ACTIONS


class KangarooGymEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, shaping=True):
        super().__init__()
        self.env = KangarooEnv(shaping=shaping)
        self.observation_space = spaces.Box(-2.0, 2.0, (OBS_DIM,), dtype=np.float32)
        self.action_space = spaces.Discrete(N_ACTIONS)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self.env = KangarooEnv(seed=seed, shaping=self.env.shaping)
        obs = self.env.reset()
        return obs, {}

    def step(self, action):
        obs, reward, done, info = self.env.step(int(action))
        # continuing task cut off at MAX_STEPS -> "truncated", not "terminated"
        return obs, float(reward), False, done, info
