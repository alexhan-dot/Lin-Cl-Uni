# Architecture — how a vision bot works

Every screen-recognition bot, whether it clicks a game target or automates a
tedious desktop task, is the same **four parts in a loop**. Learn these once and
you can build any of them.

```
        ┌──────────────────────────── loop ────────────────────────────┐
        │                                                               │
   ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌───────┐     ┌──────┐
   │ CAPTURE │ ──▶ │ DETECT  │ ──▶ │ DECIDE  │ ──▶ │  ACT  │ ──▶ │ WAIT │
   │ pixels  │     │ opencv  │     │  FSM    │     │ mouse │     │ sleep│
   └─────────┘     └─────────┘     └─────────┘     └───────┘     └──────┘
    perception      perception       decision        action        loop
```

## 1. Perception — Capture

Grab the pixels of a screen region.

- **`mss`** is the fast, cross-platform grabber. `sct.grab({top, left, width, height})`
  returns a raw frame in ~1–5 ms.
- Convert to a NumPy array so OpenCV can read it: `np.array(frame)` then
  `cv2.cvtColor(..., cv2.COLOR_BGRA2BGR)`.

Keep the region **small and fixed** — you only need the part of the screen where
the target can appear. Smaller region = faster loop.

## 2. Perception — Detect

Find *where* the thing is in the frame.

- **Template matching** — the beginner-friendly method. You save a small picture of
  the target (`kangaroo_32.png`) and slide it over the frame:
  ```python
  res = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
  _, confidence, _, top_left = cv2.minMaxLoc(res)
  if confidence >= THRESHOLD:      # e.g. 0.80
      cx = top_left[0] + tw // 2
      cy = top_left[1] + th // 2   # centre of the match
  ```
- `confidence` is 0–1. The **match threshold** (a config slider in the console)
  decides how sure you must be before you act. Too low = false clicks; too high =
  misses.
- Later upgrades: multi-scale matching, colour masks (HSV), or a small trained
  detector — but template matching teaches the idea cleanly.

## 3. Decision — the State Machine (FSM)

Don't scatter `if` statements everywhere. Model the bot as a handful of **states**
with clear transitions. This is what the console's "Loop Pipeline" visualizes:

```
        target found ≥ threshold          click sent
  SCAN ───────────────────────▶ LOCK ───────────────▶ CLICK
   ▲                             │                       │
   │ lost / low confidence       │ confidence drops      │ done
   └─────────────────────────────┘                       ▼
                        COOLDOWN ◀───────────────────────┘
                           │  timer elapsed
                           └────────────▶ SCAN
```

| State | Doing | Leaves when |
|-------|-------|-------------|
| `SCAN` | capture + detect, no target yet | confidence ≥ threshold |
| `LOCK` | target held, aim the cursor | cursor on target → `CLICK`; lost → `SCAN` |
| `CLICK`| send the click | click issued → `COOLDOWN` |
| `COOLDOWN` | wait out the action delay | timer done → `SCAN` |

A state machine keeps behaviour predictable and easy to debug — you always know
*why* the bot is doing what it's doing.

## 4. Action — Act

Move and click.

- **`pyautogui`**: `pyautogui.moveTo(x, y, duration=…)`, `pyautogui.click()`.
- **Humanize** so motion isn't a robotic teleport: add a few pixels of random
  **jitter** to the target point, and a small random **delay** before the click
  (both are config sliders in the console).
- **Safety:** keep `pyautogui.FAILSAFE = True`. Slamming the mouse into a screen
  corner then aborts the program — your emergency stop. The console mirrors this as
  the "Corner fail-safe" toggle.

## 5. Loop — Wait

Sleep a short, slightly randomized interval and repeat. A fixed loop rate
(e.g. ~30 Hz) is plenty; you don't need to burn a full CPU core.

```python
while running:
    frame = capture()
    target, confidence = detect(frame, template)
    state = fsm.step(target, confidence)   # SCAN / LOCK / CLICK / COOLDOWN
    if state == "CLICK":
        act(target, jitter=JITTER, delay=DELAY)
    time.sleep(1/30 + random.uniform(0, 0.01))
```

## Where each skill shows up

| Your goal | Same pieces, different target |
|-----------|-------------------------------|
| **Screen recognition + auto-click** | Capture + Detect + Act, on the practice window. |
| **Business automation (RPA)** | Same loop, but "target" = a button/field in an app; "act" = fill + submit. Detection is often simpler (fixed positions or text). |
| **Game AI / bot** | Add a richer FSM (or a learned policy) in the Decide step; everything else is identical. |

## Libraries to install

```
pip install mss opencv-python numpy pyautogui pygame
```

- `mss` — screen capture
- `opencv-python` + `numpy` — detection
- `pyautogui` — mouse/keyboard output (+ fail-safe)
- `pygame` — for building the practice target window
