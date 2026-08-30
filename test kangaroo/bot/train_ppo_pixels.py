"""
PPO from PIXELS with a CNN policy — the agent sees the screen and learns to play
from reward alone. Slower than feature-based PPO (a conv net on CPU), but this is
the real thing: perception + control learned end to end.

Run:    python train_ppo_pixels.py --steps 200000      (CPU: allow time)
Out:    data/policy_ppo_pixels.zip
Eval:   python train_ppo_pixels.py --eval data/policy_ppo_pixels.zip
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from pixel_gym import PixelKangarooGym

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "policy_ppo_pixels")


def evaluate(model, episodes=15, seed=321):
    env = PixelKangarooGym(shaping=False)
    hits = []
    for i in range(episodes):
        obs, _ = env.reset(seed=seed + i)
        done = trunc = False
        while not (done or trunc):
            action, _ = model.predict(obs, deterministic=True)
            obs, _, done, trunc, info = env.step(action)
        hits.append(info["hits"])
    print(f"episodes {episodes}  hits: mean {np.mean(hits):.1f}  "
          f"min {min(hits)}  max {max(hits)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=200_000)
    ap.add_argument("--eval", default=None)
    args = ap.parse_args()

    from stable_baselines3 import PPO

    if args.eval:
        evaluate(PPO.load(args.eval))
        return

    env = PixelKangarooGym()
    model = PPO("CnnPolicy", env, verbose=1, n_steps=1024, batch_size=256,
                gamma=0.99, ent_coef=0.01)
    model.learn(total_timesteps=args.steps)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    model.save(OUT)
    print(f"saved -> {OUT}.zip")
    evaluate(model)


if __name__ == "__main__":
    main()
