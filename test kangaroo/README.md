# test kangaroo 🦘

A **learning project** for the three skills you wanted to practice:

1. **Screen recognition + auto-click** — capture a region, find something in it, move the mouse and click.
2. **Business/workflow automation (RPA)** — the same loop, applied to repetitive desktop tasks.
3. **Game AI / open-source game bot** — a state machine that "plays" a target on its own.

## Ground rule (why this is safe)

The bot here plays a **practice mini-game that you run yourself** — a window with a
moving "kangaroo" target you click. There is **no third-party server, no other
players, and no Terms of Service to break**. That is the whole point: you get to
learn the real techniques (computer vision, input automation, state machines)
against a target where automating is completely fine.

> Do **not** point this at an online game you don't own the rules to. Automating
> a live MMO (Lineage, etc.) violates its operating policy and gets accounts
> permanently banned. Keep the capture region on *your* practice window.

## What's here

| File | What it is |
|------|-----------|
| `kangaroo-console.html` | The UX/UI design — an interactive mockup of the bot's control panel (open in a browser). |
| `docs/ARCHITECTURE.md` | How a vision bot is built: the 4-part pipeline + the state machine. |

## The design, in one screen

The console mockup (`kangaroo-console.html`) shows the standard layout used by
modern automation dashboards (patterned after the BOT-MMORPG-AI launcher and the
LearnCodeByGaming OpenCV series):

- **Detection viewport** — the captured region with the reticle, bounding box, and
  live match-confidence readout.
- **Loop pipeline** — the five stages (Capture → Detect → Decide → Act → Wait) lighting
  up as the state machine advances.
- **KPI tiles** — uptime, actions/min, hit rate, average confidence, with sparklines.
- **Config** — match threshold, click delay, humanize jitter, corner fail-safe.
- **Event log** — timestamped feed of what the bot decided and did.

Open it, press **Start**, and watch the whole loop run against the simulated feed.

## Suggested build order (next steps)

1. Build the practice mini-game window (`pygame` moving target).
2. Capture the region (`mss`) and show it (`opencv`).
3. Find the target (`cv2.matchTemplate`) and draw the box.
4. Click it (`pyautogui`) with a small humanized delay + `pyautogui.FAILSAFE = True`.
5. Wrap it in the state machine from `docs/ARCHITECTURE.md`.

See `docs/ARCHITECTURE.md` for the details of each step.
