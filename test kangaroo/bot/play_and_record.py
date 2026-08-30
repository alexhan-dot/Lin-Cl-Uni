"""
Stage 1 data: YOU play the practice game, we record (observation, action) pairs.

This is the "learn the real player's patterns" step — but on the practice game,
which is the safe target. Your demonstrations become the training set for
behavior cloning (train_bc.py).

Controls:  arrow keys = move cursor   space = click   Esc / close = quit & save
Run:       python play_and_record.py            (needs a display)
Output:    data/demos.npz   (arrays: obs [N,8], act [N])
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pygame

from kangaroo_env import KangarooEnv, W, H, TARGET_R

FPS = 30
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "demos.npz")


def current_action(keys, clicked):
    if clicked:
        return 5
    if keys[pygame.K_UP]:
        return 1
    if keys[pygame.K_DOWN]:
        return 2
    if keys[pygame.K_LEFT]:
        return 3
    if keys[pygame.K_RIGHT]:
        return 4
    return 0


def main():
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Kangaroo — record demonstrations (space = click)")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("monospace", 16)

    env = KangarooEnv(shaping=False)   # raw play, no reward help while recording
    obs = env.reset()
    obs_log, act_log = [], []
    running = True

    while running:
        clicked = False
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                running = False
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                clicked = True

        keys = pygame.key.get_pressed()
        action = current_action(keys, clicked)

        obs_log.append(obs.copy())
        act_log.append(action)
        obs, _, done, info = env.step(action)
        if done:
            obs = env.reset()

        # render
        screen.fill((12, 20, 23))
        tx, ty = int(env.target[0]), int(env.target[1])
        pygame.draw.circle(screen, (51, 226, 196), (tx, ty), TARGET_R)
        cx, cy = int(env.cursor[0]), int(env.cursor[1])
        pygame.draw.line(screen, (242, 178, 74), (cx - 12, cy), (cx + 12, cy), 2)
        pygame.draw.line(screen, (242, 178, 74), (cx, cy - 12), (cx, cy + 12), 2)
        screen.blit(font.render(f"hits: {env.hits}   samples: {len(obs_log)}",
                                True, (207, 233, 227)), (10, 10))
        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()

    if obs_log:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        np.savez_compressed(OUT,
                            obs=np.array(obs_log, dtype=np.float32),
                            act=np.array(act_log, dtype=np.int64))
        print(f"saved {len(obs_log)} demonstration steps -> {OUT}")
    else:
        print("no samples recorded")


if __name__ == "__main__":
    main()
