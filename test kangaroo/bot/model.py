"""
Shared policy network + save/load helpers, used by both behavior cloning
(train_bc.py) and reinforcement learning (train_reinforce.py) so the "learn
from you" and "grow on its own" stages speak the same model.
"""
import os
import torch
import torch.nn as nn

from kangaroo_env import OBS_DIM, N_ACTIONS


class Policy(nn.Module):
    """Maps an 8-dim observation to logits over the 6 actions."""

    def __init__(self, obs_dim=OBS_DIM, n_actions=N_ACTIONS, hidden=64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, n_actions),
        )

    def forward(self, x):
        return self.net(x)


def save(policy, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    torch.save(policy.state_dict(), path)
    print(f"saved policy -> {path}")


def load(path, **kw):
    policy = Policy(**kw)
    policy.load_state_dict(torch.load(path, map_location="cpu"))
    policy.eval()
    print(f"loaded policy <- {path}")
    return policy
