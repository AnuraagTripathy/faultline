"""
Illustrative Slurm + Faultline recovery workflow (not executed in CI).

On an HPC cluster:

1. Training script uses faultline.start(), run.log(), run.save().
2. Register the Slurm script once per run:

    run.register_slurm_script("train.slurm")

3. If the job dies, open the Faultline dashboard → Recovery → Resume Run.
   The API runs: sbatch train.slurm

4. Your script should restore on startup:

    start_step = run.restore_latest(model=model, optimizer=optimizer)
    for step in range(start_step, max_steps):
        ...

Example train.slurm (adjust for your site):

    #!/bin/bash
    #SBATCH --job-name=llama-train
    #SBATCH --time=24:00:00
    #SBATCH --gres=gpu:1

    module load python/3.11
    export FAULTLINE_API_KEY="your-key"
    export FAULTLINE_BASE_URL="https://faultline.example.com"

    python train.py --resume
"""

from __future__ import annotations

# This file is documentation-first; import faultline in your real train.py.


def example_registration() -> None:
    import faultline

    run = faultline.start(
        "slurm-exp-1",
        project="protein-model",
        api_key="fl_dev_local",
        base_url="http://127.0.0.1:8080",
    )
    run.register_slurm_script(
        "train.slurm",
        working_dir="/home/user/experiments/run1",
    )
    print("When the job fails, POST /v1/runs/{id}/resume or click Resume in the dashboard.")


if __name__ == "__main__":
    print(__doc__)
