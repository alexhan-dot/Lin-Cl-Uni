"""
Bridge RPA capture -> the learning pipeline.

Turns a recorded session into an imitation-learning dataset: for every mouse
click, pair the screen frame shown at that moment with WHERE you clicked
(normalized 0..1). A CNN trained on this answers "given this screen, where does
the user click?" — the desktop version of the game's train_bc_pixels.py.

    python build_dataset.py sessions/<timestamp>
    -> sessions/<timestamp>/dataset.npz   (X: [N,1,64,64] uint8, y: [N,2] float32)
"""
import argparse
import json
import os

import numpy as np
from PIL import Image

IMG = 64


def build(session_dir):
    with open(os.path.join(session_dir, "meta.json")) as f:
        meta = json.load(f)
    reg = meta["region"]
    fw, fh = reg["width"], reg["height"]
    left, top = reg.get("left", 0), reg.get("top", 0)

    frames_dir = os.path.join(session_dir, "frames")
    events = []
    with open(os.path.join(session_dir, "events.jsonl")) as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))

    X, y = [], []
    last_frame = None
    cache = {}
    for e in events:
        if e["kind"] == "frame":
            last_frame = e["file"]
        elif e["kind"] == "click" and e["pressed"] and last_frame:
            # normalized click position within the captured region
            nx = (e["x"] - left) / fw
            ny = (e["y"] - top) / fh
            if not (0 <= nx <= 1 and 0 <= ny <= 1):
                continue  # click landed outside the recorded region
            if last_frame not in cache:
                img = Image.open(os.path.join(frames_dir, last_frame)).convert("L")
                cache[last_frame] = np.asarray(img.resize((IMG, IMG)), dtype=np.uint8)
            X.append(cache[last_frame][None])          # (1,64,64)
            y.append([nx, ny])

    if not X:
        print("no (frame, click) pairs found — did the session capture clicks?")
        return
    X = np.asarray(X, dtype=np.uint8)
    y = np.asarray(y, dtype=np.float32)
    out = os.path.join(session_dir, "dataset.npz")
    np.savez_compressed(out, X=X, y=y)
    print(f"wrote {len(X)} (frame, click-xy) pairs -> {out}")
    print("next: train a small CNN to regress y from X — same shape as the game's "
          "pixel policy, output 2 coords instead of 6 action logits.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dir")
    build(ap.parse_args().session_dir)


if __name__ == "__main__":
    main()
