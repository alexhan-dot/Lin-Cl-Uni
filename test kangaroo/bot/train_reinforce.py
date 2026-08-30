"""
Stage 3 — Reinforcement Learning (REINFORCE): the AI grows beyond you.

No demonstrations here. The agent plays on its own, gets rewards (+1 per hit),
and nudges its policy toward actions that led to more reward. Over many
episodes it improves — this is the "AI learns the game and gets better" part.

Optionally warm-start from your behavior-cloned policy so it starts at roughly
human level and climbs from there.

Run:    python train_reinforce.py                    (from scratch)
        python train_reinforce.py --init data/policy_bc.pt   (start from your BC policy)
Out:    data/policy_rl.pt
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import torch

from kangaroo_env import KangarooEnv
from model import Policy, save, load

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "policy_rl.pt")
GAMMA = 0.99


def run_episode(env, policy):
    obs = env.reset()
    log_probs, rewards = [], []
    done = False
    while not done:
        logits = policy(torch.tensor(obs))
        dist = torch.distributions.Categorical(logits=logits)
        action = dist.sample()
        obs, reward, done, info = env.step(int(action.item()))
        log_probs.append(dist.log_prob(action))
        rewards.append(reward)
    return log_probs, rewards, info["hits"]


def returns_to_go(rewards):
    out, running = [], 0.0
    for r in reversed(rewards):
        running = r + GAMMA * running
        out.append(running)
    out.reverse()
    t = torch.tensor(out, dtype=torch.float32)
    return (t - t.mean()) / (t.std() + 1e-8)   # normalize -> stable gradients


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=1500)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--init", default=None, help="warm-start from a BC policy .pt")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    env = KangarooEnv(seed=args.seed)
    policy = load(args.init) if args.init else Policy()
    opt = torch.optim.Adam(policy.parameters(), lr=args.lr)

    recent = []
    for ep in range(args.episodes):
        log_probs, rewards, hits = run_episode(env, policy)
        R = returns_to_go(rewards)
        loss = -(torch.stack(log_probs) * R).sum()
        opt.zero_grad()
        loss.backward()
        opt.step()

        recent.append(hits)
        if len(recent) > 50:
            recent.pop(0)
        if (ep + 1) % 50 == 0:
            print(f"episode {ep+1:4d}   hits(last50 avg) {np.mean(recent):5.1f}")

    save(policy, OUT)
    print("done — compare: python evaluate.py --policy data/policy_rl.pt")


if __name__ == "__main__":
    main()
