import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import Runtime

runtime_dir = Path(__file__).resolve().parents[2] / "runtime"
runtime = Runtime(runtime_dir=str(runtime_dir))

payload = {
    "step": 5,
    "loss": 0.42,
    "weights": [1.0, 2.0, 3.0],
    "optimizer": {
        "lr": 0.001,
        "momentum": 0.9,
    },
}

runtime.save_pickle_checkpoint(5, payload)
latest = runtime.load_latest_pickle()

assert latest["step"] == 5
assert latest["optimizer"]["lr"] == 0.001

print(latest)
