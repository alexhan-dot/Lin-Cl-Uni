"""
Train the screen -> click model on a recorded session's dataset, and save a
visual review so you can CHECK what it learned before running it.

    python build_dataset.py sessions/<ts>      # first, make dataset.npz
    python train_clicker.py sessions/<ts>       # -> sessions/<ts>/clicker.pt + review/

Review images (sessions/<ts>/review/*.png) show green = where you clicked,
red = where the model would click. Close markers = it learned your target.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import torch
import torch.nn as nn
from PIL import Image

from clicker_model import ClickerCNN, IMG, save


def train(session_dir, epochs=60, batch=64, lr=1e-3):
    data = np.load(os.path.join(session_dir, "dataset.npz"))
    X = torch.tensor(data["X"])          # (N,1,64,64) uint8
    y = torch.tensor(data["y"])          # (N,2) float32 in [0,1]
    n = len(X)
    print(f"{n} (frame, click) pairs")

    model = ClickerCNN()
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()
    for epoch in range(epochs):
        perm = torch.randperm(n)
        total = 0.0
        for i in range(0, n, batch):
            idx = perm[i:i + batch]
            loss = loss_fn(model(X[idx]), y[idx])
            opt.zero_grad(); loss.backward(); opt.step()
            total += loss.item() * len(idx)
        if (epoch + 1) % 10 == 0 or epoch == 0:
            with torch.no_grad():
                pred = model(X)
                px_err = (torch.sqrt(((pred - y) ** 2).sum(1)) * IMG).mean().item()
            print(f"epoch {epoch+1:3d}  mse {total/n:.5f}  "
                  f"mean click error {px_err:.1f}px (of {IMG})")

    save(model, os.path.join(session_dir, "clicker.pt"))
    write_review(session_dir, model, X, y)
    return model


def write_review(session_dir, model, X, y, k=8):
    out = os.path.join(session_dir, "review")
    os.makedirs(out, exist_ok=True)
    idxs = np.linspace(0, len(X) - 1, min(k, len(X))).astype(int)
    with torch.no_grad():
        pred = model(X[idxs]).numpy()
    for j, i in enumerate(idxs):
        big = Image.fromarray(X[i, 0].numpy()).convert("RGB").resize((256, 256),
                                                                     Image.NEAREST)
        px = big.load()

        def mark(nx, ny, color):
            cx, cy = int(nx * 256), int(ny * 256)
            for dx in range(-4, 5):
                for dy in range(-4, 5):
                    if 0 <= cx + dx < 256 and 0 <= cy + dy < 256:
                        px[cx + dx, cy + dy] = color
        mark(float(y[i, 0]), float(y[i, 1]), (60, 220, 130))   # green = you
        mark(float(pred[j, 0]), float(pred[j, 1]), (240, 90, 100))  # red = model
        big.save(os.path.join(out, f"review_{j:02d}.png"))
    print(f"wrote {len(idxs)} review images -> {out}  (green=you, red=model)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dir")
    ap.add_argument("--epochs", type=int, default=60)
    args = ap.parse_args()
    train(args.session_dir, epochs=args.epochs)


if __name__ == "__main__":
    main()
