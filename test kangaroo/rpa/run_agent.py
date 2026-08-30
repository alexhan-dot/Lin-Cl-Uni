"""
Run the trained clicker live: capture the region, predict where to click, and
(optionally) click there — the "실행" step. Start with --dry-run to CHECK the
automation safely: it only draws/prints where it WOULD click, no real clicks.

    python run_agent.py --model sessions/<ts>/clicker.pt --region 0,0,1280,720 --dry-run
    python run_agent.py --model sessions/<ts>/clicker.pt --region 0,0,1280,720 --interval 1.0

SAFETY: pyautogui fail-safe is ON (mouse to a screen corner aborts). Press Esc
to stop. Only run on your own machine and workflows.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image

from clicker_model import load, IMG


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--region", required=True, help="left,top,width,height")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--max-actions", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true", help="predict only, no clicks")
    ap.add_argument("--countdown", type=int, default=4)
    args = ap.parse_args()

    import mss
    import torch

    left, top, w, h = (int(v) for v in args.region.split(","))
    region = {"left": left, "top": top, "width": w, "height": h}
    model = load(args.model)

    stop = {"v": False}
    if not args.dry_run:
        import pyautogui
        pyautogui.FAILSAFE = True
        try:
            from pynput import keyboard

            def on_press(k):
                if k == keyboard.Key.esc:
                    stop["v"] = True
                    return False
            keyboard.Listener(on_press=on_press).start()
        except Exception:
            print("(pynput unavailable — use Ctrl-C or the corner fail-safe to stop)")

    mode = "DRY RUN (no clicks)" if args.dry_run else "LIVE (will click)"
    print(f"{mode}  region={region}  every {args.interval}s")
    for i in range(args.countdown, 0, -1):
        print(f"  starting in {i}...")
        time.sleep(1)

    with mss.mss() as sct:
        for step in range(args.max_actions):
            if stop["v"]:
                print("stopped (Esc)")
                break
            shot = sct.grab(region)
            img = Image.frombytes("RGB", shot.size, shot.rgb).convert("L").resize((IMG, IMG))
            x = torch.tensor(np.asarray(img, dtype=np.uint8))[None, None]
            with torch.no_grad():
                nx, ny = model(x)[0].tolist()
            sx, sy = int(left + nx * w), int(top + ny * h)
            print(f"  [{step+1}/{args.max_actions}] predict click @ ({sx},{sy})  "
                  f"= region ({nx:.2f},{ny:.2f})")
            if not args.dry_run:
                import pyautogui
                pyautogui.click(sx, sy)
            time.sleep(args.interval)
    print("done")


if __name__ == "__main__":
    main()
