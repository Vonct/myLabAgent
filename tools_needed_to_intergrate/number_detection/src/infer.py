import argparse
import json
import os
from pathlib import Path
from typing import Dict

import torch
from PIL import Image
from torchvision import transforms

from model import build_model


def read_cfg(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_device(device_cfg: str) -> torch.device:
    if device_cfg == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(device_cfg)


def build_transform(normalize: bool):
    steps = [transforms.Grayscale(num_output_channels=1), transforms.Resize((28, 28)), transforms.ToTensor()]
    if normalize:
        steps.append(transforms.Normalize((0.1307,), (0.3081,)))
    return transforms.Compose(steps)


def load_image_tensor(image_path: str, normalize: bool, invert: bool) -> torch.Tensor:
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    image = Image.open(image_path).convert("L")
    if invert:
        image = Image.eval(image, lambda x: 255 - x)

    transform = build_transform(normalize=normalize)
    tensor = transform(image).unsqueeze(0)
    return tensor


def infer(cfg: Dict) -> Dict:
    model_path = cfg.get("model_path")
    image_path = cfg.get("image_path")
    output_json = cfg.get("output_json", "./outputs/infer_result.json")

    if not model_path:
        raise ValueError("cfg field `model_path` is required")
    if not image_path:
        raise ValueError("cfg field `image_path` is required")
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model not found: {model_path}")

    device = resolve_device(cfg.get("device", "auto"))
    normalize = bool(cfg.get("normalize", True))
    invert = bool(cfg.get("invert", False))

    model = build_model().to(device)
    state_dict = torch.load(model_path, map_location=device)
    model.load_state_dict(state_dict)
    model.eval()

    image_tensor = load_image_tensor(image_path=image_path, normalize=normalize, invert=invert).to(device)

    with torch.no_grad():
        logits = model(image_tensor)
        probs = torch.softmax(logits, dim=1).squeeze(0)
        confidence, digit = torch.max(probs, dim=0)

    result = {
        "digit": int(digit.item()),
        "confidence": float(confidence.item()),
        "probs": [float(x) for x in probs.cpu().tolist()],
        "image_path": image_path,
        "model_path": model_path,
    }

    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Predicted digit: {result['digit']}")
    print(f"Confidence: {result['confidence']:.6f}")
    print(f"Saved inference JSON to: {output_path.resolve()}")

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Infer handwritten digit from image")
    parser.add_argument("--cfg", type=str, required=True, help="Path to inference config JSON")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if not os.path.exists(args.cfg):
        raise FileNotFoundError(f"Config file not found: {args.cfg}")

    cfg = read_cfg(args.cfg)
    infer(cfg)
