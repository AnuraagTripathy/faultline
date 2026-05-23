import sys
from pathlib import Path

# Allow `from faultline import Runtime` when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import Runtime

runtime_dir = Path(__file__).resolve().parents[2] / "runtime"
runtime = Runtime(runtime_dir=str(runtime_dir))

print(
    runtime.save_json_checkpoint(
        1,
        {
            "step": 1,
            "loss": 0.95,
            "model": "toy-model",
            "weights": [0.1, 0.2, 0.3],
        },
    )
)
print(
    runtime.save_json_checkpoint(
        2,
        {
            "step": 2,
            "loss": 0.72,
            "model": "toy-model",
            "weights": [0.15, 0.25, 0.35],
        },
    )
)
print(runtime.list_checkpoints())
print(runtime.latest_checkpoint())

latest = runtime.load_latest_json()
print(latest)
assert latest["step"] == 2
assert latest["loss"] == 0.72

print(runtime.prune(keep_last=1))
print(runtime.list_checkpoints())
