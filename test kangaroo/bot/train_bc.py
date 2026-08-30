"""
Stage 2 — Behavior Cloning: the AI learns to imitate YOU.

Supervised learning on the (observation -> action) pairs you recorded. The
policy network learns "in this situation, the player pressed this key". This is
imitation learning: the ceiling is roughly your own skill.

Run:    python train_bc.py
In:     data/demos.npz         (from play_and_record.py)
Out:    data/policy_bc.pt
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import torch
import torch.nn as nn

from model import Policy, save

HERE = os.path.dirname(os.path.abspath(__file__))
DEMOS = os.path.join(HERE, "data", "demos.npz")
OUT = os.path.join(HERE, "data", "policy_bc.pt")
EPOCHS = 40
BATCH = 128
LR = 1e-3


def main():
    if not os.path.exists(DEMOS):
        sys.exit(f"no demos at {DEMOS} — run play_and_record.py first")

    d = np.load(DEMOS)
    obs = torch.tensor(d["obs"], dtype=torch.float32)
    act = torch.tensor(d["act"], dtype=torch.long)
    n = len(obs)
    print(f"loaded {n} demonstration steps")

    policy = Policy()
    opt = torch.optim.Adam(policy.parameters(), lr=LR)
    loss_fn = nn.CrossEntropyLoss()

    for epoch in range(EPOCHS):
        perm = torch.randperm(n)
        total = 0.0
        for i in range(0, n, BATCH):
            idx = perm[i:i + BATCH]
            logits = policy(obs[idx])
            loss = loss_fn(logits, act[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item() * len(idx)
        if (epoch + 1) % 5 == 0 or epoch == 0:
            with torch.no_grad():
                acc = (policy(obs).argmax(1) == act).float().mean().item()
            print(f"epoch {epoch+1:2d}  loss {total/n:.4f}  train-acc {acc:.3f}")

    save(policy, OUT)
    print("done — now: python evaluate.py --policy data/policy_bc.pt "
          "(or keep training with train_reinforce.py)")


if __name__ == "__main__":
    main()
