# AI roadmap — an agent that learns a game and grows

Goal: an AI that **watches how a player plays, imitates it, then improves on its
own.** We build this on the **practice game** (`bot/kangaroo_env.py`) — a target
you run yourself. That's the safe place to learn these techniques for real.

> Not on a live online game. Capturing a real game's screen to train an
> auto-player and loop it violates its operating policy and gets accounts banned.
> Everything below is designed so you never need to.

## The three stages

```
   YOU play          AI imitates you        AI improves itself
  ┌─────────┐        ┌─────────────┐        ┌──────────────────┐
  │ record  │  ───▶  │  behavior   │  ───▶  │  reinforcement   │  ───▶  evaluate
  │ demos   │        │  cloning    │        │  learning        │
  └─────────┘        └─────────────┘        └──────────────────┘
 play_and_record.py    train_bc.py           train_reinforce.py       evaluate.py
```

### Stage 1 — Record demonstrations  (`play_and_record.py`)
You play the game with the arrow keys + space. Every frame we log the
`(observation, action)` pair. This is the dataset of "the real player's
patterns" — captured safely, from a game you own.

```
cd "test kangaroo/bot"
python play_and_record.py        # play a few minutes, then close  -> data/demos.npz
```

### Stage 2 — Behavior Cloning  (`train_bc.py`)
Supervised learning: train a small network to predict *your* action from the
observation. The AI now imitates you. Its skill ceiling ≈ your skill.

```
python train_bc.py               # -> data/policy_bc.pt
python evaluate.py --policy data/policy_bc.pt
```

**Why start here?** Imitation gives the agent a huge head start — it doesn't
have to discover "move toward the target, then click" from random flailing.

### Stage 3 — Reinforcement Learning  (`train_reinforce.py`)
Now the agent plays alone and learns from **reward** (+1 per hit). Using the
REINFORCE policy-gradient rule, it strengthens actions that led to more reward.
Warm-start from your BC policy so it begins at human level and climbs past it —
this is the "grows on its own" part.

```
python train_reinforce.py --init data/policy_bc.pt   # -> data/policy_rl.pt
python evaluate.py --policy data/policy_rl.pt --render
```

## How each piece maps to the concepts

| Concept | Where it lives | What it teaches |
|---|---|---|
| Environment / observation / action | `kangaroo_env.py` | how to frame a task for an agent (the MDP) |
| Imitation learning (behavior cloning) | `train_bc.py` | learning a policy from human demonstrations |
| Policy network | `model.py` | the shared brain: observation → action |
| Policy-gradient RL (REINFORCE) | `train_reinforce.py` | learning from reward, improving beyond the demos |
| Evaluation | `evaluate.py` | measuring a policy honestly, watching it play |

## Verified results (all measured on this machine)

| Method | Script | Hits/episode |
|---|---|---|
| Random policy | — | 0.2 |
| Pixel BC (CNN sees the screen) | `train_bc_pixels.py` | 1.9 |
| Feature BC (imitate the player) | `train_bc.py` | ~18 |
| REINFORCE, from scratch | `train_reinforce.py` | ~0.1 |
| REINFORCE, warm-started from BC | `train_reinforce.py --init …` | ~18 |
| **PPO (stable-baselines3)** | `train_ppo.py` | **18.2** |

## Extra track A — the AI sees pixels (real screen recognition)

Instead of hand-made features, the agent gets the **rendered image** and a CNN
learns to see and act. This is where screen recognition and decision-making fuse
into one network.

```
python train_bc_pixels.py                 # CNN learns from pixels -> data/policy_cnn.pt
```

**Lesson from the numbers:** pixel BC reaches ~1.9 hits (10× random — it clearly
learned to *see*), but far below feature BC's ~18. That gap is **distribution
shift**: behavior cloning only ever sees expert states, so once the agent drifts
into a state the expert never visited, small errors compound. The fixes are
**RL directly from pixels** (reward corrects the drift) or **DAgger** (relabel
the states the agent actually visits). Files: `pixel_env.py`, `model_cnn.py`.

## Extra track B — PPO (stronger, steadier RL)

REINFORCE is simple but noisy and weak from scratch. **PPO** from
`stable-baselines3` learns far better. Our `gym_wrapper.py` exposes the practice
game through the standard `gymnasium.Env` API, so any RL library plugs in.

```
python train_ppo.py --steps 150000        # -> data/policy_ppo.zip
python train_ppo.py --eval data/policy_ppo.zip
```

PPO reached **18.2 hits from scratch, reward only** (no demonstrations) — and was
still improving. This is the clean answer to "AI learns the game and grows".

## Extra track C — your own desktop (RPA)

The same pipeline, pointed at your real work instead of a game, lives in
`../rpa/`: `record_session.py` captures your screen + real mouse/keys,
`replay_session.py` automates them back, and `build_dataset.py` turns a recording
into a (screen → click) training set — the desktop twin of `train_bc_pixels.py`.
See `../rpa/README.md`.

## Where to go further

- **RL from pixels:** run PPO with SB3's `CnnPolicy` on a pixel `gymnasium`
  wrapper of `PixelKangaroo` — fixes the BC distribution-shift plateau above.
- **Harder game:** obstacles, multiple targets, an accuracy score — richer
  environment, richer learned behavior.
- **DAgger:** iteratively relabel the agent's own trajectories with the expert to
  beat plain behavior cloning.

## Install

```
pip install -r bot/requirements.txt
```

`numpy` (env), `torch` (learning), `pygame` (play + render). Training with
REINFORCE runs headless and needs no display; only `play_and_record.py` and
`evaluate.py --render` open a window.
