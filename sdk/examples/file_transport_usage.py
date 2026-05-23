import pickle
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import PersistentRuntime

runtime_dir = Path(__file__).resolve().parents[2] / "runtime"

# Larger than CLI-safe JSON/base64 transport limits.
large_payload = {
    "step": 1,
    "loss": 0.42,
    "model_state": {f"tensor_{index}": torch.randn(128, 128) for index in range(16)},
    "optimizer_state": {"lr": 0.001, "momentum": 0.9},
}

encoded_len = len(pickle.dumps(large_payload))
print(f"Pickled payload size: {encoded_len} bytes")

with PersistentRuntime(runtime_dir=str(runtime_dir)) as runtime:
    message = runtime.save_pickle_checkpoint_via_file(1, large_payload)
    print(message)

    loaded = runtime.load_latest_pickle()
    assert loaded["step"] == 1
    assert len(loaded["model_state"]) == 16
    print("Loaded checkpoint matches saved payload shape.")
