from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_DEPENDENCY_ERROR = (
    "手写字识别推理依赖缺失，请先安装 torch torchvision pillow。"
)

try:
    import torch
    from PIL import Image, ImageOps
    from torch import nn
    from torchvision import transforms
except Exception as exc:
    torch = None
    Image = None
    ImageOps = None
    nn = None
    transforms = None
    _IMPORT_EXCEPTION = exc
else:
    _IMPORT_EXCEPTION = None

_BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = _BASE_DIR / "tools_needed_to_intergrate" / "number_detection" / "checkpoints" / "best_model.pth"
_MODEL_CACHE: Dict[Tuple[str, str], Any] = {}


def _build_model():
    class DigitCNN(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(1, 32, kernel_size=3, padding=1),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(kernel_size=2),
                nn.Conv2d(32, 64, kernel_size=3, padding=1),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(kernel_size=2),
            )
            self.classifier = nn.Sequential(
                nn.Flatten(),
                nn.Linear(64 * 7 * 7, 128),
                nn.ReLU(inplace=True),
                nn.Dropout(0.2),
                nn.Linear(128, 10),
            )

        def forward(self, x):
            x = self.features(x)
            x = self.classifier(x)
            return x

    return DigitCNN()


def _ensure_dependencies() -> None:
    if _IMPORT_EXCEPTION is not None:
        raise RuntimeError(f"{_DEPENDENCY_ERROR} (Original error: {_IMPORT_EXCEPTION})") from _IMPORT_EXCEPTION


def _resolve_path(path_value: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = (_BASE_DIR / path).resolve()
    return path


def _resolve_device(device_cfg: str):
    if device_cfg == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(device_cfg)


def _build_transform(normalize: bool):
    steps = [
        transforms.Grayscale(num_output_channels=1),
        transforms.Resize((28, 28)),
        transforms.ToTensor(),
    ]
    if normalize:
        steps.append(transforms.Normalize((0.1307,), (0.3081,)))
    return transforms.Compose(steps)


def _load_model(model_path: Path, device_name: str):
    cache_key = (str(model_path), device_name)
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]
    resolved_device = _resolve_device(device_name)
    model = _build_model().to(resolved_device)
    state_dict = torch.load(str(model_path), map_location=resolved_device)
    model.load_state_dict(state_dict)
    model.eval()
    _MODEL_CACHE[cache_key] = model
    return model


def recognize_handwritten_digit(
    image_path: str,
    invert: bool = False,
    normalize: bool = True,
    device: str = "auto",
    model_path: Optional[str] = None,
) -> Dict[str, Any]:
    _ensure_dependencies()
    if not image_path:
        raise ValueError("参数 image_path 不能为空。")

    resolved_image_path = _resolve_path(image_path)
    if not resolved_image_path.exists():
        raise FileNotFoundError(f"图片不存在: {resolved_image_path}")

    resolved_model_path = _resolve_path(model_path) if model_path else DEFAULT_MODEL_PATH
    if not resolved_model_path.exists():
        raise FileNotFoundError(f"模型文件不存在: {resolved_model_path}")

    image = Image.open(str(resolved_image_path)).convert("L")
    if invert:
        image = ImageOps.invert(image)
    image_tensor = _build_transform(normalize=normalize)(image).unsqueeze(0).to(_resolve_device(device))
    model = _load_model(resolved_model_path, device_name=device)

    with torch.no_grad():
        logits = model(image_tensor)
        probs = torch.softmax(logits, dim=1).squeeze(0)
        confidence, digit = torch.max(probs, dim=0)

    return {
        "digit": int(digit.item()),
        "confidence": float(confidence.item()),
        "probs": [float(x) for x in probs.cpu().tolist()],
        "image_path": str(resolved_image_path),
        "model_path": str(resolved_model_path),
    }


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Handwritten Digit Recognition Service")
    parser.add_argument("image_path", help="Path to the image file")
    parser.add_argument("--invert", action="store_true", help="Invert image colors")
    parser.add_argument("--no-normalize", dest="normalize", action="store_false", help="Disable normalization")
    parser.add_argument("--device", default="auto", help="Device to use (cpu, cuda, auto)")
    parser.add_argument("--model-path", default=None, help="Path to custom model checkpoint")
    
    args = parser.parse_args()

    try:
        # Check if torch is available before proceeding
        _ensure_dependencies()
        
        result = recognize_handwritten_digit(
            image_path=args.image_path,
            invert=args.invert,
            normalize=args.normalize,
            device=args.device,
            model_path=args.model_path
        )
        print(json.dumps(result))
    except Exception as e:
        # Print error as JSON to be parsed by the caller
        print(json.dumps({"error": str(e), "type": type(e).__name__}))
        sys.exit(1)
