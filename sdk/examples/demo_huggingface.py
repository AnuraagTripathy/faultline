#!/usr/bin/env python3
"""
Hugging Face Trainer + Faultline demo (requires transformers).

This script documents the integration pattern; run a real Trainer job by wiring
FaultlineTrainerCallback into your training script.
"""

from __future__ import annotations

print(
    """
from faultline.integrations import FaultlineTrainerCallback
from transformers import Trainer

callback = FaultlineTrainerCallback(
    project="llama-finetune",
    run_name="alpaca-run",
    api_key="fl_...",
    base_url="http://127.0.0.1:8080",
    upload_checkpoints=True,
    auto_resume=True,
)

trainer = Trainer(..., callbacks=[callback])
trainer.train()
"""
)
