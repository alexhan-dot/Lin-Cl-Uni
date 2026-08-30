"""
Fabricate a fake recorded session so the RPA learning chain can be tested
WITHOUT a display or real recording. Each 'frame' shows a bright target at a
random spot and the matching 'click' event lands on it — so a model trained on
it should learn to click the target.

    python synth_session.py
    python build_dataset.py sessions/synth
    python train_clicker.py sessions/synth
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SESS = os.path.join(HERE, "sessions", "synth")
SZ = 256
N = 400


def main(seed=0):
    rng = np.random.default_rng(seed)
    frames = os.path.join(SESS, "frames")
    os.makedirs(frames, exist_ok=True)

    with open(os.path.join(SESS, "meta.json"), "w") as f:
        json.dump({"region": {"left": 0, "top": 0, "width": SZ, "height": SZ},
                   "fps": 4, "log_keys": False, "started": "synthetic"}, f, indent=2)

    with open(os.path.join(SESS, "events.jsonl"), "w") as ev:
        for i in range(N):
            tx, ty = int(rng.uniform(30, SZ - 30)), int(rng.uniform(30, SZ - 30))
            img = Image.new("RGB", (SZ, SZ), (14, 20, 24))
            d = ImageDraw.Draw(img)
            d.ellipse([tx - 12, ty - 12, tx + 12, ty + 12], fill=(60, 210, 190))
            name = f"{i:06d}.png"
            img.save(os.path.join(frames, name))
            ev.write(json.dumps({"t": i * 0.25, "kind": "frame", "file": name}) + "\n")
            ev.write(json.dumps({"t": i * 0.25 + 0.05, "kind": "click",
                                 "x": tx, "y": ty, "button": "Button.left",
                                 "pressed": True}) + "\n")
    print(f"wrote synthetic session ({N} frames+clicks) -> {SESS}")


if __name__ == "__main__":
    main()
