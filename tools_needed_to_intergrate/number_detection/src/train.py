import argparse
import json
import os
import random
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from model import build_model


def read_cfg(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def resolve_device(device_cfg: str) -> torch.device:
    if device_cfg == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(device_cfg)


def build_dataloaders(cfg: Dict) -> Tuple[DataLoader, DataLoader]:
    transform = transforms.Compose(
        [
            transforms.ToTensor(),
            transforms.Normalize((0.1307,), (0.3081,)),
        ]
    )

    root = cfg.get("data_root", "./data")
    train_set = datasets.MNIST(root=root, train=True, transform=transform, download=True)
    test_set = datasets.MNIST(root=root, train=False, transform=transform, download=True)

    train_loader = DataLoader(
        train_set,
        batch_size=int(cfg.get("batch_size", 128)),
        shuffle=True,
        num_workers=int(cfg.get("num_workers", 0)),
    )
    test_loader = DataLoader(
        test_set,
        batch_size=int(cfg.get("batch_size", 128)),
        shuffle=False,
        num_workers=int(cfg.get("num_workers", 0)),
    )
    return train_loader, test_loader


def evaluate(model: nn.Module, data_loader: DataLoader, device: torch.device) -> float:
    model.eval()
    correct = 0
    total = 0

    with torch.no_grad():
        for images, labels in data_loader:
            images = images.to(device)
            labels = labels.to(device)

            logits = model(images)
            preds = torch.argmax(logits, dim=1)

            correct += (preds == labels).sum().item()
            total += labels.size(0)

    return correct / max(total, 1)


def train(cfg: Dict) -> None:
    set_seed(int(cfg.get("seed", 42)))
    device = resolve_device(cfg.get("device", "auto"))

    train_loader, test_loader = build_dataloaders(cfg)

    model = build_model().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=float(cfg.get("learning_rate", 1e-3)))

    checkpoint_dir = Path(cfg.get("checkpoint_dir", "./checkpoints"))
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    best_acc = 0.0
    num_epochs = int(cfg.get("num_epochs", 5))

    print(f"Training on device: {device}")
    for epoch in range(1, num_epochs + 1):
        model.train()
        running_loss = 0.0

        for images, labels in train_loader:
            images = images.to(device)
            labels = labels.to(device)

            optimizer.zero_grad()
            logits = model(images)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item()

        avg_loss = running_loss / max(len(train_loader), 1)
        acc = evaluate(model, test_loader, device)
        print(f"Epoch [{epoch}/{num_epochs}] loss={avg_loss:.4f} test_acc={acc:.4f}")

        if acc > best_acc:
            best_acc = acc
            torch.save(model.state_dict(), checkpoint_dir / "best_model.pth")

    torch.save(model.state_dict(), checkpoint_dir / "last_model.pth")
    print(f"Best test accuracy: {best_acc:.4f}")
    print(f"Saved checkpoints at: {checkpoint_dir.resolve()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train MNIST digit classifier")
    parser.add_argument("--cfg", type=str, required=True, help="Path to training config JSON")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    cfg_path = args.cfg
    if not os.path.exists(cfg_path):
        raise FileNotFoundError(f"Config file not found: {cfg_path}")

    config = read_cfg(cfg_path)
    train(config)
