"""
DAgger (Dataset Aggregation) from pixels — beats plain behavior cloning.

Plain BC only ever sees the expert's states, so when the agent drifts it's lost
(the distribution-shift plateau, ~1.9 hits). DAgger fixes this: let the AGENT
drive, but ask the EXPERT what it would have done in every state the agent
actually visits, add those labels to the dataset, and retrain. The agent learns
to recover from its own mistakes.

Loop:
    iter 0: expert drives -> collect (pixels, expert_action)   [= BC data]
    iter k: agent drives  -> collect (pixels, expert_action)   [recovery data]
            retrain on ALL data, measure hits

Run:    python dagger_pixels.py
Out:    data/policy_cnn_dagger.pt
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
OUT = os.path.join(HERE, "data", "policy_cnn_dagger.pt")

ITERS = 5
EPISODES_PER_ITER = 8
EPOCHS = 8
BATCH = 128
EPSILON = 0.1   # exploration while the agent drives


def agent_action(policy, obs):
    with torch.no_grad():
        return int(policy(torch.tensor(obs)[None]).argmax(1).item())


def collect(policy, episodes, use_agent, seed):
    env = PixelKangaroo(seed=seed, shaping=False)
    X, y = [], []
    for _ in range(episodes):
        obs = env.reset()
        done = False
        while not done:
            expert = scripted_action(env.base)   # label = what expert would do
            X.append(obs)
            y.append(expert)
            if use_agent:                        # but the AGENT drives
                a = expert if np.random.rand() < EPSILON else agent_action(policy, obs)
            else:
                a = expert
            obs, _, done, _ = env.step(a)
    return X, y


def evaluate(policy, episodes=10, seed=999):
    env = PixelKangaroo(seed=seed, shaping=False)
    hits = []
    for _ in range(episodes):
        obs = env.reset()
        done = False
        while not done:
            obs, _, done, info = env.step(agent_action(policy, obs))
        hits.append(info["hits"])
    return float(np.mean(hits))


def train(policy, X, y):
    Xt = torch.tensor(np.asarray(X, dtype=np.uint8))
    yt = torch.tensor(np.asarray(y, dtype=np.int64))
    counts = torch.bincount(yt, minlength=N_ACTIONS).float()
    w = counts.sum() / (counts.clamp(min=1) * N_ACTIONS)
    opt = torch.optim.Adam(policy.parameters(), lr=1e-3)
    loss_fn = nn.CrossEntropyLoss(weight=w)
    n = len(Xt)
    for _ in range(EPOCHS):
        perm = torch.randperm(n)
        for i in range(0, n, BATCH):
            idx = perm[i:i + BATCH]
            loss = loss_fn(policy(Xt[idx]), yt[idx])
            opt.zero_grad(); loss.backward(); opt.step()


def main():
    policy = CNNPolicy()
    dataX, dataY = [], []
    for it in range(ITERS):
        Xn, yn = collect(policy, EPISODES_PER_ITER, use_agent=(it > 0), seed=it)
        dataX += Xn
        dataY += yn
        train(policy, dataX, dataY)
        print(f"iter {it}: dataset={len(dataX):5d}  hits/episode={evaluate(policy):.1f}"
              f"   ({'expert-driven' if it == 0 else 'agent-driven'})")
    save(policy, OUT)


if __name__ == "__main__":
    main()
