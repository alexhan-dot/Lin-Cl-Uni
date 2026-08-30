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

## Where to go next (all on the practice game)

- **Better observations:** feed raw pixels + a small CNN instead of hand-made
  features — this is where "screen recognition" rejoins the AI (the bot *sees*
  the game like you do). Start with `mss` capture of the practice window.
- **Stronger RL:** swap REINFORCE for PPO (e.g. `stable-baselines3`) for faster,
  steadier learning.
- **Harder game:** add obstacles, multiple targets, a score for accuracy — the
  richer the environment, the more interesting the learned behavior.
- **Gymnasium wrapper:** wrap `KangarooEnv` in the `gymnasium.Env` API so you can
  plug in any standard RL library.

## Install

```
pip install -r bot/requirements.txt
```

`numpy` (env), `torch` (learning), `pygame` (play + render). Training with
REINFORCE runs headless and needs no display; only `play_and_record.py` and
`evaluate.py --render` open a window.
