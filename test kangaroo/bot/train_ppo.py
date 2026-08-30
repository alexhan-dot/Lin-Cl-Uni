"""
PPO via stable-baselines3 — a much stronger, steadier learner than our
hand-written REINFORCE. Same practice game, industrial-grade algorithm.

Run:    python train_ppo.py                       (default 150k steps)
        python train_ppo.py --steps 400000
Out:    data/policy_ppo.zip
Eval:   python train_ppo.py --eval data/policy_ppo.zip
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from gym_wrapper import KangarooGymEnv

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "policy_ppo")


def evaluate(model, episodes=20, seed=123):
    env = KangarooGymEnv(shaping=False)
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
    ap.add_argument("--steps", type=int, default=150_000)
    ap.add_argument("--eval", default=None, help="evaluate a saved model instead of training")
    args = ap.parse_args()

    from stable_baselines3 import PPO

    if args.eval:
        model = PPO.load(args.eval)
        evaluate(model)
        return

    env = KangarooGymEnv()
    model = PPO("MlpPolicy", env, verbose=1, n_steps=1024, batch_size=256,
                gae_lambda=0.95, gamma=0.99, ent_coef=0.01)
    model.learn(total_timesteps=args.steps)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    model.save(OUT)
    print(f"saved -> {OUT}.zip")
    evaluate(model)


if __name__ == "__main__":
    main()
