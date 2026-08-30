"""
Replay a recorded session — the simplest form of automation: play the exact
mouse/keyboard events back, honoring the original timing. This is the
deterministic baseline (no learning yet); the learned version trains a model on
frames -> next action (see build_dataset.py and the game's train_bc_pixels.py).

    python replay_session.py sessions/<timestamp>            # replay once
    python replay_session.py sessions/<timestamp> --loops 3 --speed 1.5

SAFETY: pyautogui fail-safe is ON — slam the mouse into a screen corner to abort.
Only replay on your own machine. Give yourself a few seconds after launching to
switch to the target window.
"""
import argparse
import json
import os
import time

import pyautogui

pyautogui.FAILSAFE = True   # mouse to a corner = emergency stop
pyautogui.PAUSE = 0.0

BUTTON = {"Button.left": "left", "Button.right": "right", "Button.middle": "middle"}


def load_events(session_dir):
    path = os.path.join(session_dir, "events.jsonl")
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def replay(session_dir, speed, countdown):
    events = [e for e in load_events(session_dir) if e["kind"] in
              ("move", "click", "scroll", "key")]
    if not events:
        print("no replayable events")
        return
    print(f"replaying {len(events)} events in {countdown}s "
          f"(move mouse to a corner to abort)...")
    for i in range(countdown, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    prev_t = events[0]["t"]
    for e in events:
        dt = (e["t"] - prev_t) / speed
        if dt > 0:
            time.sleep(min(dt, 5.0))   # cap long idle gaps
        prev_t = e["t"]
        k = e["kind"]
        if k == "move":
            pyautogui.moveTo(e["x"], e["y"])
        elif k == "click":
            btn = BUTTON.get(e["button"], "left")
            if e["pressed"]:
                pyautogui.mouseDown(e["x"], e["y"], button=btn)
            else:
                pyautogui.mouseUp(e["x"], e["y"], button=btn)
        elif k == "scroll":
            pyautogui.scroll(int(e["dy"]), x=e["x"], y=e["y"])
        elif k == "key":
            key = e["key"]
            if key and len(key) == 1:
                pyautogui.press(key)
            # named keys (e.g. "Key.enter") -> strip prefix if pyautogui knows it
            elif key and key.startswith("Key."):
                name = key[4:]
                if name in pyautogui.KEYBOARD_KEYS:
                    pyautogui.press(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dir")
    ap.add_argument("--loops", type=int, default=1)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--countdown", type=int, default=4)
    args = ap.parse_args()
    for n in range(args.loops):
        print(f"--- loop {n+1}/{args.loops} ---")
        replay(args.session_dir, args.speed, args.countdown if n == 0 else 1)
    print("done")


if __name__ == "__main__":
    main()
