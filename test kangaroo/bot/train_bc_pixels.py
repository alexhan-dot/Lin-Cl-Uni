"""
Behavior cloning FROM PIXELS: the CNN learns to act from the rendered image
alone — it never sees the target coordinates, only the picture, exactly like a
human watching the screen.

For a clean demo this generates expert demonstrations with the scripted policy
(which peeks at coordinates) and trains the CNN to reproduce those actions from
pixels. Swap in your own recorded pixel demos later.

Run:    python train_bc_pixels.py
Out:    data/policy_cnn.pt
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import torch
import torch.nn as nn

from kangaroo_env import N_ACTIONS
from pixel_env import PixelKangaroo
from model_cnn import CNNPolicy, save
from synth_demos import scripted_action

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "policy_cnn.pt")
EPISODES = 30
EPOCHS = 30
BATCH = 128
LR = 1e-3


def collect(episodes, seed=0):
    env = PixelKangaroo(seed=seed, shaping=False)
    obs_buf, act_buf = [], []
    for _ in range(episodes):
        obs = env.reset()
        done = False
        while not done:
            a = scripted_action(env.base)   # expert peeks at coords
            obs_buf.append(obs)             # ...but the CNN only sees pixels
            act_buf.append(a)
            obs, _, done, _ = env.step(a)
    X = torch.tensor(np.asarray(obs_buf, dtype=np.uint8))  # (N,2,64,64)
    y = torch.tensor(np.asarray(act_buf, dtype=np.int64))
    return X, y


def evaluate(policy, episodes=10, seed=999):
    env = PixelKangaroo(seed=seed, shaping=False)
    hits = []
    for _ in range(episodes):
        obs = env.reset()
        done = False
        while not done:
            with torch.no_grad():
                a = int(policy(torch.tensor(obs)[None]).argmax(1).item())
            obs, _, done, info = env.step(a)
        hits.append(info["hits"])
    return float(np.mean(hits))


def main():
    print(f"collecting {EPISODES} expert episodes as pixels...")
    X, y = collect(EPISODES)
    n = len(X)
    print(f"{n} pixel samples, shape {tuple(X.shape[1:])}")

    # the "click" action is rare in expert play -> weight classes inversely to
    # their frequency so the CNN actually learns to click, not just to move.
    counts = torch.bincount(y, minlength=N_ACTIONS).float()
    weights = (counts.sum() / (counts.clamp(min=1) * N_ACTIONS))
    print("action counts:", counts.tolist())

    policy = CNNPolicy()
    opt = torch.optim.Adam(policy.parameters(), lr=LR)
    loss_fn = nn.CrossEntropyLoss(weight=weights)

    for epoch in range(EPOCHS):
        perm = torch.randperm(n)
        total = 0.0
        for i in range(0, n, BATCH):
            idx = perm[i:i + BATCH]
            loss = loss_fn(policy(X[idx]), y[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item() * len(idx)
        with torch.no_grad():
            accs = []
            for i in range(0, n, 1024):
                accs.append((policy(X[i:i + 1024]).argmax(1) == y[i:i + 1024]).float().sum().item())
            acc = sum(accs) / n
        print(f"epoch {epoch+1:2d}  loss {total/n:.4f}  train-acc {acc:.3f}")

    save(policy, OUT)
    print(f"eval (hits/episode, from pixels only): {evaluate(policy):.1f}")


if __name__ == "__main__":
    main()
