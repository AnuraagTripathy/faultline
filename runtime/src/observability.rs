use std::collections::HashSet;

use crate::dataset_registry::{DatasetRegistry, ShardMetadata, ShardStatus};
use crate::metadata::CheckpointEntry;
use crate::runtime_metrics::RuntimeMetrics;

/// Aggregated runtime snapshot for observability APIs (read-only).
#[derive(Debug, Clone, PartialEq)]
pub struct RuntimeOverview {
    pub total_datasets: u64,
    pub total_shards: u64,
    pub pending_shards: u64,
    pub claimed_shards: u64,
    pub completed_shards: u64,
    pub failed_shards: u64,
    pub total_checkpoints: u64,
    pub workers_seen: u64,
    pub async_metrics: RuntimeMetrics,
}

/// Per-worker progress derived from checkpoints and shard registry.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerSummary {
    pub worker_id: u64,
    pub latest_checkpoint_step: Option<u64>,
    pub latest_local_step: Option<u64>,
    pub committed_checkpoints: u64,
    pub claimed_shards: u64,
    pub completed_shards: u64,
}

pub fn build_runtime_overview(
    registry: &DatasetRegistry,
    checkpoints: &[CheckpointEntry],
    metrics: RuntimeMetrics,
) -> RuntimeOverview {
    let shard_counts = registry.aggregate_shard_counts();
    let workers_seen = collect_worker_ids(registry, checkpoints).len() as u64;

    RuntimeOverview {
        total_datasets: shard_counts.total_datasets,
        total_shards: shard_counts.total_shards,
        pending_shards: shard_counts.pending_shards,
        claimed_shards: shard_counts.claimed_shards,
        completed_shards: shard_counts.completed_shards,
        failed_shards: shard_counts.failed_shards,
        total_checkpoints: checkpoints.len() as u64,
        workers_seen,
        async_metrics: metrics,
    }
}

pub fn build_worker_summaries(
    registry: &DatasetRegistry,
    checkpoints: &[CheckpointEntry],
) -> Vec<WorkerSummary> {
    let mut worker_ids = collect_worker_ids(registry, checkpoints);
    let shard_counts = registry.worker_shard_counts();

    for worker_id in shard_counts.keys() {
        worker_ids.insert(*worker_id);
    }

    let mut summaries: Vec<WorkerSummary> = worker_ids
        .into_iter()
        .map(|worker_id| {
            let committed_checkpoints = checkpoints
                .iter()
                .filter(|entry| entry.worker_id == Some(worker_id))
                .count() as u64;

            let latest = checkpoints
                .iter()
                .filter(|entry| entry.worker_id == Some(worker_id))
                .max_by_key(|entry| entry.local_step.unwrap_or(0));

            let (claimed_shards, completed_shards) = shard_counts
                .get(&worker_id)
                .copied()
                .unwrap_or((0, 0));

            WorkerSummary {
                worker_id,
                latest_checkpoint_step: latest.map(|entry| entry.step),
                latest_local_step: latest.and_then(|entry| entry.local_step),
                committed_checkpoints,
                claimed_shards,
                completed_shards,
            }
        })
        .collect();

    summaries.sort_by_key(|summary| summary.worker_id);
    summaries
}

pub fn shard_worker_id(shard: &ShardMetadata) -> Option<u64> {
    match shard.status {
        ShardStatus::Claimed | ShardStatus::Completed => shard.claimed_by,
        _ => None,
    }
}

fn collect_worker_ids(
    registry: &DatasetRegistry,
    checkpoints: &[CheckpointEntry],
) -> HashSet<u64> {
    let mut ids = HashSet::new();
    for entry in checkpoints {
        if let Some(worker_id) = entry.worker_id {
            ids.insert(worker_id);
        }
    }
    for worker_id in registry.worker_shard_counts().keys() {
        ids.insert(*worker_id);
    }
    ids
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dataset_registry::DatasetRegistry;
    use tempfile::tempdir;

    fn sample_checkpoint(worker_id: u64, local_step: u64, step: u64) -> CheckpointEntry {
        CheckpointEntry {
            step,
            path: format!("checkpoints/step_{step:04}.ckpt"),
            status: "committed".to_string(),
            worker_id: Some(worker_id),
            local_step: Some(local_step),
        }
    }

    #[test]
    fn overview_reflects_registered_shard_counts() -> anyhow::Result<()> {
        let dir = tempdir()?;
        let registry = DatasetRegistry::new(dir.path())?;
        registry.register_dataset("train", 100, 10)?;

        let overview = build_runtime_overview(&registry, &[], RuntimeMetrics::default());
        assert_eq!(overview.total_datasets, 1);
        assert_eq!(overview.total_shards, 10);
        assert_eq!(overview.pending_shards, 10);
        assert_eq!(overview.claimed_shards, 0);
        assert_eq!(overview.completed_shards, 0);
        Ok(())
    }

    #[test]
    fn list_workers_from_checkpoints_and_shard_claims() -> anyhow::Result<()> {
        let dir = tempdir()?;
        let registry = DatasetRegistry::new(dir.path())?;
        registry.register_dataset("train", 30, 10)?;

        let shard = registry.claim_next_shard(2, "train")?.expect("shard");
        registry.complete_shard(2, "train", shard.shard_id)?;

        let claimed = registry.claim_next_shard(1, "train")?.expect("claimed");

        let checkpoints = vec![
            sample_checkpoint(2, 1, 2_000_001),
            sample_checkpoint(2, 2, 2_000_002),
        ];
        let workers = build_worker_summaries(&registry, &checkpoints);

        assert_eq!(workers.len(), 2);
        let worker2 = workers.iter().find(|w| w.worker_id == 2).expect("worker 2");
        assert_eq!(worker2.committed_checkpoints, 2);
        assert_eq!(worker2.completed_shards, 1);
        assert_eq!(worker2.latest_local_step, Some(2));

        let worker1 = workers.iter().find(|w| w.worker_id == 1).expect("worker 1");
        assert_eq!(worker1.claimed_shards, 1);
        assert_eq!(worker1.completed_shards, 0);
        assert!(worker1.latest_checkpoint_step.is_none());

        let _ = claimed;
        Ok(())
    }

    #[test]
    fn list_shards_filters_by_status() -> anyhow::Result<()> {
        let dir = tempdir()?;
        let registry = DatasetRegistry::new(dir.path())?;
        registry.register_dataset("train", 30, 10)?;

        registry.claim_next_shard(0, "train")?;
        let shard_one = registry.claim_next_shard(1, "train")?.expect("shard 1");
        registry.complete_shard(1, "train", shard_one.shard_id)?;

        let pending = registry.list_shards("train", Some("pending"))?;
        assert_eq!(pending.len(), 1);
        assert!(pending.iter().all(|s| s.status == ShardStatus::Pending));

        let claimed = registry.list_shards("train", Some("claimed"))?;
        assert_eq!(claimed.len(), 1);

        let completed = registry.list_shards("train", Some("completed"))?;
        assert_eq!(completed.len(), 1);

        Ok(())
    }
}
