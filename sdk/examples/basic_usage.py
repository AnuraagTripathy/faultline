import sys
from pathlib import Path

# Allow `from faultline import Runtime` when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import Runtime

runtime_dir = Path(__file__).resolve().parents[2] / "runtime"
runtime = Runtime(runtime_dir=str(runtime_dir))

print(runtime.save_checkpoint(1, data="checkpoint payload from Python step 1"))
print(runtime.save_checkpoint(2, data="checkpoint payload from Python step 2"))
print(runtime.list_checkpoints())
print(runtime.latest_checkpoint())
print(runtime.load_latest())
print(runtime.prune(keep_last=1))
print(runtime.list_checkpoints())
