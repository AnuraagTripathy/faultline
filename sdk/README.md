# Faultline Python SDK (temporary)

This is a minimal subprocess-based SDK. It calls the Rust `runtime` crate CLI via:

```text
cargo run -- <command>
```

Later versions will replace this with a gRPC service to the Rust runtime.

## Requirements

- Python 3.10+
- Rust toolchain (`cargo`)
- The `runtime/` crate in this repo

## Run the example

From the repo root:

```bash
python sdk/examples/basic_usage.py
```

The example resolves `runtime/` from the repo layout (`faultline/runtime`), so it works from any working directory.

## Quick usage

```python
from faultline import Runtime

runtime = Runtime(runtime_dir="runtime")  # path to the Rust crate

# Save real UTF-8 payload through the CLI (--data)
runtime.save_checkpoint(1, data="checkpoint payload from Python step 1")
runtime.save_checkpoint(2, data="checkpoint payload from Python step 2")

# Omit data to use Rust's fake placeholder string
runtime.save_checkpoint(3)

print(runtime.list_checkpoints())
print(runtime.latest_checkpoint())
print(runtime.load_latest())  # e.g. step 2 payload if that is latest
print(runtime.prune(keep_last=1))
```

`save_checkpoint` accepts `str`, `bytes` (UTF-8 only for now), or `None`.

Add the `sdk` directory to `PYTHONPATH` or run from a layout where `faultline` is importable (e.g. `PYTHONPATH=sdk`).
