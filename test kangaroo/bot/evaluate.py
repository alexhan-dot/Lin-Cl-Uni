"""
Measure a trained policy — and optionally watch it play.

Run (headless score over many episodes):
    python evaluate.py --policy data/policy_bc.pt
    python evaluate.py --policy data/policy_rl.pt --episodes 50

Watch it play (needs a display):
    python evaluate.py --policy data/policy_rl.pt --render
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import torch

from kangaroo_env import KangarooEnv, W, H, TARGET_R
from model import load


def act(policy, obs, greedy=True):
    with torch.no_grad():
        logits = policy(torch.tensor(obs))
    if greedy:
        return int(logits.argmax().item())
    dist = torch.distributions.Categorical(logits=logits)
    return int(dist.sample().item())


def evaluate(policy, episodes, seed):
    env = KangarooEnv(seed=seed, shaping=False)
    scores = []
    for _ in range(episodes):
        obs = env.reset()
        done = False
        while not done:
            obs, _, done, info = env.step(act(policy, obs))
        scores.append(info["hits"])
    print(f"episodes {episodes}   hits: mean {np.mean(scores):.1f}  "
          f"min {min(scores)}  max {max(scores)}")


def render(policy, seed):
    import pygame
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Kangaroo — trained policy playing")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("monospace", 16)
    env = KangarooEnv(seed=seed, shaping=False)
    obs = env.reset()
    running = True
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (
                e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                running = False
        obs, _, done, info = env.step(act(policy, obs))
        if done:
            obs = env.reset()
        screen.fill((12, 20, 23))
        pygame.draw.circle(screen, (51, 226, 196),
                           (int(env.target[0]), int(env.target[1])), TARGET_R)
        cx, cy = int(env.cursor[0]), int(env.cursor[1])
        pygame.draw.line(screen, (52, 211, 139), (cx - 12, cy), (cx + 12, cy), 2)
        pygame.draw.line(screen, (52, 211, 139), (cx, cy - 12), (cx, cy + 12), 2)
        screen.blit(font.render(f"hits: {env.hits}", True, (207, 233, 227)), (10, 10))
        pygame.display.flip()
        clock.tick(30)
    pygame.quit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True)
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--seed", type=int, default=123)
    args = ap.parse_args()

    policy = load(args.policy)
    if args.render:
        render(policy, args.seed)
    else:
        evaluate(policy, args.episodes, args.seed)


if __name__ == "__main__":
    main()
