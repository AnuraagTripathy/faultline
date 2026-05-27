# Failure Testing (v22.0)

Faultline includes realistic failure simulations to validate crash-to-resume behavior and dashboard
signals.

## Scenarios

From `sdk/examples/failure_scenarios/`:

1. `spot_gpu_interruption.py` - simulated spot eviction
2. `slurm_preemption.py` - simulated Slurm preemption and delayed resume
3. `corrupted_checkpoint.py` - simulated checkpoint corruption + failed restore
4. `network_disconnect.py` - interrupted checkpoint upload + stale run signal
5. `process_kill_resume.py` - SIGKILL-style process death + resume flow

Run with CLI:

```bash
python -m faultline.cli demo crash --scenario process_kill_resume
```

## Expected outcomes

- Dashboard timelines show failure and recovery events
- Recovery panel shows resume readiness for recoverable runs
- Recovery statistics update (avg lost steps, successful resumes)
- Public demo workspace remains explorable without signup

## Guarantees

- Checkpoint metadata and run state are persisted in Postgres
- Checkpoint blobs are persisted in object storage
- Resume guidance is computed from latest known run/checkpoint state

## Known limitations

- Simulations are synthetic and not tied to cloud-provider control planes
- Corruption detection is event-driven unless checksum verification task runs
- Open-source stack has no built-in multi-region HA/SLA
