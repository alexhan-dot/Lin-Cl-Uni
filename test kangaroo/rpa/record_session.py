"""
RPA recorder — capture how YOU use the computer: screen frames + mouse + keys.

This is the data-collection front-end for own-desktop automation. It is the same
idea as the game's play_and_record.py, but the "screen" is your real desktop and
the "actions" are your real mouse and keyboard. Everything is saved locally.

    python record_session.py                      # record full primary screen
    python record_session.py --region 0,0,1280,720
    python record_session.py --no-keys            # don't log keystrokes (privacy)

Stop:  press  Esc.     Pause/resume:  press  F9  (use it before typing secrets).

Output (sessions/<timestamp>/):
    frames/000123.jpg   periodic screenshots
    events.jsonl        one JSON event per line (mouse move/click/scroll, key, frame)
    meta.json           region, fps, start time

────────────────────────  READ THIS  ────────────────────────
• This records your screen AND your keystrokes. Do NOT record while entering
  passwords, card numbers, or private messages — hit F9 to pause first, or use
  --no-keys. Review a session before you ever feed it to a model.
• Only automate your own machine and workflows. Don't point replay at a system
  whose rules forbid automation.
──────────────────────────────────────────────────────────────
"""
import argparse
import json
import os
import threading
import time
from datetime import datetime

import mss
import mss.tools

try:
    from pynput import mouse, keyboard
except Exception as e:  # pragma: no cover
    raise SystemExit("pynput is required: pip install -r requirements.txt") from e

FRAME_FPS = 4          # screenshots per second
MOVE_MIN_MS = 50       # throttle mouse-move logging


class Recorder:
    def __init__(self, region, log_keys):
        self.region = region                       # dict for mss or None (full)
        self.log_keys = log_keys
        self.paused = False
        self.stop = threading.Event()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions", stamp)
        os.makedirs(os.path.join(self.dir, "frames"), exist_ok=True)
        self.events = open(os.path.join(self.dir, "events.jsonl"), "w")
        self.t0 = time.time()
        self.frame_i = 0
        self._last_move = 0.0
        self._lock = threading.Lock()

    def emit(self, kind, **data):
        if self.paused and kind != "control":
            return
        rec = {"t": round(time.time() - self.t0, 4), "kind": kind, **data}
        with self._lock:
            self.events.write(json.dumps(rec) + "\n")

    # ---- input callbacks ----
    def on_move(self, x, y):
        now = time.time()
        if (now - self._last_move) * 1000 >= MOVE_MIN_MS:
            self._last_move = now
            self.emit("move", x=x, y=y)

    def on_click(self, x, y, button, pressed):
        self.emit("click", x=x, y=y, button=str(button), pressed=pressed)

    def on_scroll(self, x, y, dx, dy):
        self.emit("scroll", x=x, y=y, dx=dx, dy=dy)

    def on_press(self, key):
        if key == keyboard.Key.esc:
            self.stop.set()
            return False
        if key == keyboard.Key.f9:
            self.paused = not self.paused
            self.emit("control", paused=self.paused)
            print("  [paused]" if self.paused else "  [recording]")
            return
        if self.log_keys:
            self.emit("key", key=getattr(key, "char", None) or str(key), pressed=True)

    # ---- screen capture loop ----
    def capture_loop(self):
        with mss.mss() as sct:
            region = self.region or sct.monitors[1]
            self.save_meta(region)
            interval = 1.0 / FRAME_FPS
            while not self.stop.is_set():
                start = time.time()
                if not self.paused:
                    shot = sct.grab(region)
                    path = os.path.join(self.dir, "frames", f"{self.frame_i:06d}.jpg")
                    # mss gives BGRA; store as PNG (lossless) — rename to .png
                    png = path[:-4] + ".png"
                    mss.tools.to_png(shot.rgb, shot.size, output=png)
                    self.emit("frame", file=os.path.basename(png))
                    self.frame_i += 1
                time.sleep(max(0, interval - (time.time() - start)))

    def save_meta(self, region):
        with open(os.path.join(self.dir, "meta.json"), "w") as f:
            json.dump({"region": region, "fps": FRAME_FPS,
                       "log_keys": self.log_keys,
                       "started": datetime.now().isoformat()}, f, indent=2)

    def run(self):
        print(f"recording -> {self.dir}\n  Esc = stop   F9 = pause/resume")
        ml = mouse.Listener(on_move=self.on_move, on_click=self.on_click,
                            on_scroll=self.on_scroll)
        kl = keyboard.Listener(on_press=self.on_press)
        ml.start()
        kl.start()
        try:
            self.capture_loop()
        finally:
            self.stop.set()
            ml.stop()
            kl.stop()
            self.events.close()
            print(f"done — {self.frame_i} frames saved to {self.dir}")


def parse_region(s):
    if not s:
        return None
    left, top, w, h = (int(v) for v in s.split(","))
    return {"left": left, "top": top, "width": w, "height": h}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default=None, help="left,top,width,height (default: full primary screen)")
    ap.add_argument("--no-keys", action="store_true", help="do not log keystrokes")
    args = ap.parse_args()
    Recorder(parse_region(args.region), log_keys=not args.no_keys).run()


if __name__ == "__main__":
    main()
