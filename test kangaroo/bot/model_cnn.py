"""
Convolutional policy — the "eyes" of the agent. Takes the stacked pixel frames
from pixel_env.py and outputs action logits. This is where screen recognition
and decision-making fuse into one learned network, instead of hand-made features.
"""
import os

import torch
import torch.nn as nn

from kangaroo_env import N_ACTIONS
from pixel_env import IMG


class CNNPolicy(nn.Module):
    def __init__(self, in_frames=2, n_actions=N_ACTIONS):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_frames, 16, 3, stride=2, padding=1), nn.ReLU(),  # 64->32
            nn.Conv2d(16, 32, 3, stride=2, padding=1), nn.ReLU(),         # 32->16
            nn.Conv2d(32, 32, 3, stride=2, padding=1), nn.ReLU(),         # 16->8
        )
        feat = 32 * (IMG // 8) * (IMG // 8)
        self.head = nn.Sequential(
            nn.Flatten(), nn.Linear(feat, 128), nn.ReLU(), nn.Linear(128, n_actions)
        )

    def forward(self, x):
        # x: (N, 2, 64, 64) — uint8 or float; normalize to [0,1]
        if x.dtype != torch.float32:
            x = x.float()
        return self.head(self.conv(x / 255.0))


def save(policy, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    torch.save(policy.state_dict(), path)
    print(f"saved CNN policy -> {path}")


def load(path):
    p = CNNPolicy()
    p.load_state_dict(torch.load(path, map_location="cpu"))
    p.eval()
    print(f"loaded CNN policy <- {path}")
    return p
