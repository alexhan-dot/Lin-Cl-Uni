# RPA — learn your own desktop workflows

Capture how **you** use the computer (screen + mouse + keyboard), then replay or
learn it. This is the legitimate real-world payoff of the practice game: same
four-part pipeline (capture → detect → decide → act), pointed at **your own
machine and your own tasks**.

> This is your computer and your workflows — automating them is fine. Two limits:
> keep secrets (passwords, card numbers) out of recordings — hit **F9** to pause,
> or use `--no-keys`; and don't point replay at a system whose own rules forbid
> automation.

## Install

```
pip install -r requirements.txt
```

`mss` (screen capture), `pynput` (record real mouse/keys), `pyautogui` (replay),
`pillow`+`numpy` (dataset).

## 1. Record a session

```
python record_session.py                    # full primary screen
python record_session.py --region 0,0,1280,720
python record_session.py --no-keys          # skip keystroke logging
```

- **Esc** stops · **F9** pauses/resumes (use it before typing anything private).
- Saves to `sessions/<timestamp>/`: periodic screenshots (`frames/`), an event
  log (`events.jsonl`), and `meta.json`.

## 2a. Replay it (deterministic automation)

Play the exact events back, honoring timing. This is the no-learning baseline —
already useful for repetitive tasks.

```
python replay_session.py sessions/<timestamp>
python replay_session.py sessions/<timestamp> --loops 3 --speed 1.5
```

Fail-safe is on: **slam the mouse into a screen corner to abort.** You get a few
seconds after launch to focus the target window.

## 2b. Learn it (imitation from your screen)

Turn the session into a training set — for each click, the screen frame paired
with where you clicked:

```
python build_dataset.py sessions/<timestamp>   # -> dataset.npz  (X frames, y click-xy)
```

Then train a small CNN to predict the click location from the screen — the exact
same technique as the game's `bot/train_bc_pixels.py`, just regressing a 2-D
coordinate instead of choosing among 6 actions. A learned policy generalizes to
screens it hasn't seen; pure replay does not.

## How this maps to the game project

| Game (`bot/`) | RPA (here) |
|---|---|
| `KangarooEnv` observation | your screen (`mss` capture) |
| arrow/space actions | your real mouse + keys (`pynput`) |
| `play_and_record.py` | `record_session.py` |
| `train_bc_pixels.py` (frame → action) | `build_dataset.py` + a CNN (frame → click) |
| `evaluate.py --render` | `replay_session.py` |

Learn the technique safely on the game, then bring it to your real work.
