# Handwritten Digit Recognition (PyTorch)

Train a CNN on MNIST and run config-driven inference on a single image.

## Structure

- `src/model.py`: CNN model
- `src/train.py`: training entry
- `src/infer.py`: inference entry
- `configs/train_config.json`: training config
- `configs/infer_config.json`: inference config
- `checkpoints/`: saved model weights
- `outputs/`: inference output JSON

## Run

1. Train

```powershell
python src/train.py --cfg configs/train_config.json
```

2. Infer

```powershell
python src/infer.py --cfg configs/infer_config.json
```

Inference prints predicted `digit` and `confidence`, and writes a JSON file.
