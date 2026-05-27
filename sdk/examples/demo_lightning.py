#!/usr/bin/env python3
"""
PyTorch Lightning + Faultline demo (requires lightning or pytorch-lightning).
"""

from __future__ import annotations

print(
    """
import lightning as pl
from faultline.integrations import FaultlineLightningCallback

callback = FaultlineLightningCallback(
    project="protein-model",
    run_name="exp-7",
    api_key="fl_...",
    base_url="http://127.0.0.1:8080",
    upload_checkpoints=True,
    auto_resume=True,
)

trainer = pl.Trainer(callbacks=[callback])
trainer.fit(model, datamodule)
"""
)
