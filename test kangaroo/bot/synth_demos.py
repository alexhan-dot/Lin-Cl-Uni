"""
Optional: generate synthetic demonstrations from a simple scripted "expert"
(move toward the target, click when on it). Handy for testing the training
pipeline WITHOUT a display before you record your own play with
play_and_record.py.

Run:    python synth_demos.py           -> data/demos.npz
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from kangaroo_env import KangarooEnv, TARGET_R

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "demos.npz")


def scripted_action(env):
    dx = env.target[0] - env.cursor[0]
    dy = env.target[1] - env.cursor[1]
    if abs(dx) < TARGET_R and abs(dy) < TARGET_R:
        return 5  # click
    if abs(dx) > abs(dy):
        return 4 if dx > 0 else 3
    return 2 if dy > 0 else 1


def main(episodes=40, seed=0):
    env = KangarooEnv(seed=seed, shaping=False)
    obs_log, act_log = [], []
    for _ in range(episodes):
        obs = env.reset()
        done = False
        while not done:
            a = scripted_action(env)
            obs_log.append(obs.copy())
            act_log.append(a)
            obs, _, done, _ = env.step(a)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    np.savez_compressed(OUT,
                        obs=np.array(obs_log, dtype=np.float32),
                        act=np.array(act_log, dtype=np.int64))
    print(f"wrote {len(obs_log)} synthetic steps from {episodes} episodes -> {OUT}")


if __name__ == "__main__":
    main()
