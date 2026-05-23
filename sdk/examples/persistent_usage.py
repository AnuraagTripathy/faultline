import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import PersistentRuntime

runtime_dir = Path(__file__).resolve().parents[2] / "runtime"

with PersistentRuntime(runtime_dir=str(runtime_dir)) as runtime:
    runtime.save_pickle_checkpoint(1, {"step": 1, "loss": 0.9})
    runtime.save_pickle_checkpoint(2, {"step": 2, "loss": 0.7})
    print(runtime.load_latest_pickle())
