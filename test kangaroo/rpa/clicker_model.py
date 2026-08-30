"""
Shared model for the desktop clicker: given a screen frame, predict WHERE to
click (x, y in 0..1 of the captured region). A small CNN regressor — the desktop
twin of the game's pixel policy, output 2 coordinates instead of 6 action logits.
"""
import os

import torch
import torch.nn as nn

IMG = 64


class ClickerCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 16, 3, stride=2, padding=1), nn.ReLU(),   # 64->32
            nn.Conv2d(16, 32, 3, stride=2, padding=1), nn.ReLU(),  # 32->16
            nn.Conv2d(32, 32, 3, stride=2, padding=1), nn.ReLU(),  # 16->8
        )
        self.head = nn.Sequential(
            nn.Flatten(), nn.Linear(32 * 8 * 8, 128), nn.ReLU(),
            nn.Linear(128, 2), nn.Sigmoid(),   # -> (x, y) in [0,1]
        )

    def forward(self, x):
        if x.dtype != torch.float32:
            x = x.float()
        return self.head(self.conv(x / 255.0))


def save(model, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    torch.save(model.state_dict(), path)
    print(f"saved clicker -> {path}")


def load(path):
    m = ClickerCNN()
    m.load_state_dict(torch.load(path, map_location="cpu"))
    m.eval()
    print(f"loaded clicker <- {path}")
    return m
