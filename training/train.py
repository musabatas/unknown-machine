"""LoRA fine-tune of a small instruct model on the reference's decisions, with mlx-lm.

    poetry run python -m training.train

Reads the chat files `training.make_dataset` wrote and saves the adapter under
`training/artifacts/adapter/`. Apple Silicon only (MLX).
"""

import types

from mlx_lm import lora

from training.make_dataset import ARTIFACTS, DATA

# The 1.5B model of the same family takes four times as long per decision on an M4 Pro,
# which does not fit a run of training and scoring that is meant to stay under an hour.
MODEL = "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
ADAPTER = ARTIFACTS / "adapter"

# Everything that differs from mlx-lm's defaults (`lora.CONFIG_DEFAULTS`).
HYPERPARAMETERS = {
    "model": MODEL,
    "train": True,
    "data": str(DATA),
    "adapter_path": str(ADAPTER),
    "fine_tune_type": "lora",
    "lora_parameters": {"rank": 16, "dropout": 0.0, "scale": 20.0},
    "num_layers": 16,  # the last 16 of the model's 24 blocks
    "mask_prompt": True,  # the loss counts the action line only, not the observation
    "batch_size": 8,
    "iters": 600,  # 4800 of the 19397 pairs: what fits in about a quarter of an hour here
    "learning_rate": 1e-4,
    "max_seq_length": 512,  # the longest turn is under 300 tokens
    "steps_per_report": 50,
    "steps_per_eval": 200,
    "val_batches": 10,
    "save_every": 200,
    "seed": 0,
}


def main() -> None:
    lora.run(types.SimpleNamespace(**{**lora.CONFIG_DEFAULTS, **HYPERPARAMETERS}))


if __name__ == "__main__":
    main()
