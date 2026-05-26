use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use std::sync::Arc;

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};

use crate::event_log::{record_event, EventLevel, EventLog, RuntimeEventInput};

/// Dataset-level metadata (name, sizing, shard count).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DatasetMetadata {
    pub name: String,
    pub total_samples: u64,
    pub shard_size: u64,
    pub total_shards: u64,
}

/// Lifecycle state for one shard of a dataset.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ShardStatus {
    Pending,
    Claimed,
    Completed,
    Failed,
}

impl ShardStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Claimed => "claimed",
            Self::Completed => "completed",
            Self::Failed => "failed",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "pending" => Some(Self::Pending),
            "claimed" => Some(Self::Claimed),
            "completed" => Some(Self::Completed),
            "failed" => Some(Self::Failed),
            _ => None,
        }
    }
}

/// One shard assignment unit within a dataset.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ShardMetadata {
    pub shard_id: u64,
    pub dataset_name: String,
    pub start_sample: u64,
    pub end_sample: u64,
    pub status: ShardStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub claimed_by: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub claimed_at_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub updated_at_ms: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
struct DatasetRecord {
    metadata: DatasetMetadata,
    shards: Vec<ShardMetadata>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq, Eq)]
struct RegistryState {
    datasets: Vec<DatasetRecord>,
}

/// In-process dataset/shard coordinator with JSON persistence.
pub struct DatasetRegistry {
    registry_path: PathBuf,
    state: Mutex<RegistryState>,
    event_log: Option<Arc<EventLog>>,
}

impl DatasetRegistry {
    pub fn new(registry_dir: impl AsRef<Path>) -> Result<Self> {
        Self::new_with_event_log(registry_dir, None)
    }

    pub fn new_with_event_log(
        registry_dir: impl AsRef<Path>,
        event_log: Option<Arc<EventLog>>,
    ) -> Result<Self> {
        let registry_dir = registry_dir.as_ref().to_path_buf();
        fs::create_dir_all(&registry_dir)
            .with_context(|| format!("create dataset registry dir {}", registry_dir.display()))?;
        let registry_path = registry_dir.join("registry.json");
        let state = if registry_path.is_file() {
            let bytes = fs::read(&registry_path)
                .with_context(|| format!("read {}", registry_path.display()))?;
            serde_json::from_slice(&bytes).context("parse dataset registry.json")?
        } else {
            RegistryState::default()
        };

        Ok(Self {
            registry_path,
            state: Mutex::new(state),
            event_log,
        })
    }

    pub fn event_log(&self) -> Option<Arc<EventLog>> {
        self.event_log.clone()
    }

    pub fn register_dataset(
        &self,
        name: &str,
        total_samples: u64,
        shard_size: u64,
    ) -> Result<DatasetMetadata> {
        if name.trim().is_empty() {
            return Err(anyhow!("dataset name must not be empty"));
        }
        if total_samples == 0 {
            return Err(anyhow!("total_samples must be > 0"));
        }
        if shard_size == 0 {
            return Err(anyhow!("shard_size must be > 0"));
        }

        let total_shards = shard_count(total_samples, shard_size);
        let metadata = DatasetMetadata {
            name: name.to_string(),
            total_samples,
            shard_size,
            total_shards,
        };

        let mut shards = Vec::with_capacity(total_shards as usize);
        for shard_id in 0..total_shards {
            let start_sample = shard_id * shard_size;
            let end_sample = (start_sample + shard_size).min(total_samples);
            let now_ms = current_time_ms();
            shards.push(ShardMetadata {
                shard_id,
                dataset_name: name.to_string(),
                start_sample,
                end_sample,
                status: ShardStatus::Pending,
                claimed_by: None,
                claimed_at_ms: None,
                updated_at_ms: Some(now_ms),
            });
        }

        let mut guard = self.state.lock().expect("dataset registry lock poisoned");
        if guard.datasets.iter().any(|record| record.metadata.name == name) {
            return Err(anyhow!("dataset already registered: {name}"));
        }
        guard.datasets.push(DatasetRecord { metadata: metadata.clone(), shards });
        self.persist(&guard)?;
        record_event(
            &self.event_log,
            RuntimeEventInput::new(
                EventLevel::Info,
                "dataset_registered",
                format!(
                    "registered dataset {name} ({total_samples} samples, shard_size={shard_size}, {total_shards} shards)",
                    name = metadata.name,
                    total_samples = metadata.total_samples,
                    shard_size = metadata.shard_size,
                    total_shards = metadata.total_shards,
                ),
            )
            .dataset_name(&metadata.name),
        );
        Ok(metadata)
    }

    pub fn list_datasets(&self) -> Result<Vec<DatasetMetadata>> {
        let guard = self.state.lock().expect("dataset registry lock poisoned");
        Ok(guard
            .datasets
            .iter()
            .map(|record| record.metadata.clone())
            .collect())
    }

    pub fn claim_next_shard(
        &self,
        worker_id: u64,
        dataset_name: &str,
    ) -> Result<Option<ShardMetadata>> {
        let mut guard = self.state.lock().expect("dataset registry lock poisoned");
        let record = guard
            .datasets
            .iter_mut()
            .find(|record| record.metadata.name == dataset_name)
            .ok_or_else(|| anyhow!("unknown dataset: {dataset_name}"))?;

        let now_ms = current_time_ms();
        let shard = record
            .shards
            .iter_mut()
            .filter(|shard| shard.status == ShardStatus::Pending)
            .min_by_key(|shard| shard.shard_id);

        let Some(shard) = shard else {
            return Ok(None);
        };

        shard.status = ShardStatus::Claimed;
        shard.claimed_by = Some(worker_id);
        shard.claimed_at_ms = Some(now_ms);
        shard.updated_at_ms = Some(now_ms);
        let claimed = shard.clone();
        self.persist(&guard)?;
        record_event(
            &self.event_log,
            RuntimeEventInput::new(
                EventLevel::Info,
                "shard_claimed",
                format!(
                    "worker {worker_id} claimed shard {shard_id} on {dataset_name}",
                    shard_id = claimed.shard_id,
                    dataset_name = claimed.dataset_name,
                ),
            )
            .worker_id(worker_id)
            .dataset_name(&claimed.dataset_name)
            .shard_id(claimed.shard_id),
        );
        Ok(Some(claimed))
    }

    pub fn complete_shard(
        &self,
        worker_id: u64,
        dataset_name: &str,
        shard_id: u64,
    ) -> Result<ShardMetadata> {
        let mut guard = self.state.lock().expect("dataset registry lock poisoned");
        let record = guard
            .datasets
            .iter_mut()
            .find(|record| record.metadata.name == dataset_name)
            .ok_or_else(|| anyhow!("unknown dataset: {dataset_name}"))?;

        let shard = record
            .shards
            .iter_mut()
            .find(|shard| shard.shard_id == shard_id)
            .ok_or_else(|| anyhow!("unknown shard_id {shard_id} for dataset {dataset_name}"))?;

        if shard.status != ShardStatus::Claimed {
            return Err(anyhow!(
                "shard {shard_id} is {:?}, expected claimed",
                shard.status
            ));
        }
        if shard.claimed_by != Some(worker_id) {
            return Err(anyhow!(
                "shard {shard_id} claimed by {:?}, not worker {worker_id}",
                shard.claimed_by
            ));
        }

        shard.status = ShardStatus::Completed;
        shard.claimed_at_ms = None;
        shard.updated_at_ms = Some(current_time_ms());
        let completed = shard.clone();
        self.persist(&guard)?;
        record_event(
            &self.event_log,
            RuntimeEventInput::new(
                EventLevel::Info,
                "shard_completed",
                format!(
                    "worker {worker_id} completed shard {shard_id} on {dataset_name}",
                    shard_id = completed.shard_id,
                    dataset_name = completed.dataset_name,
                ),
            )
            .worker_id(worker_id)
            .dataset_name(&completed.dataset_name)
            .shard_id(completed.shard_id),
        );
        Ok(completed)
    }

    pub fn release_stale_shards(&self, timeout_ms: u64) -> Result<u64> {
        let mut guard = self.state.lock().expect("dataset registry lock poisoned");
        let now_ms = current_time_ms();
        let mut released = 0_u64;

        for record in guard.datasets.iter_mut() {
            for shard in record.shards.iter_mut() {
                if shard.status != ShardStatus::Claimed {
                    continue;
                }
                let Some(claimed_at_ms) = shard.claimed_at_ms else {
                    continue;
                };
                if now_ms.saturating_sub(claimed_at_ms) < timeout_ms {
                    continue;
                }
                shard.status = ShardStatus::Pending;
                shard.claimed_by = None;
                shard.claimed_at_ms = None;
                shard.updated_at_ms = Some(now_ms);
                released += 1;
            }
        }

        if released > 0 {
            self.persist(&guard)?;
            record_event(
                &self.event_log,
                RuntimeEventInput::new(
                    EventLevel::Warn,
                    "stale_shard_released",
                    format!("released {released} stale shard claim(s) (timeout_ms={timeout_ms})"),
                ),
            );
        }
        Ok(released)
    }

    /// Aggregate shard counts across all registered datasets.
    pub fn aggregate_shard_counts(&self) -> ShardAggregateCounts {
        let guard = self.state.lock().expect("dataset registry lock poisoned");
        let mut counts = ShardAggregateCounts::default();
        counts.total_datasets = guard.datasets.len() as u64;

        for record in &guard.datasets {
            counts.total_shards += record.metadata.total_shards;
            for shard in &record.shards {
                match shard.status {
                    ShardStatus::Pending => counts.pending_shards += 1,
                    ShardStatus::Claimed => counts.claimed_shards += 1,
                    ShardStatus::Completed => counts.completed_shards += 1,
                    ShardStatus::Failed => counts.failed_shards += 1,
                }
            }
        }
        counts
    }

    /// List shards for one dataset, optionally filtered by status string (`pending`, etc.).
    pub fn list_shards(
        &self,
        dataset_name: &str,
        status_filter: Option<&str>,
    ) -> Result<Vec<ShardMetadata>> {
        let filter = match status_filter {
            None => None,
            Some(value) => Some(
                ShardStatus::parse(value)
                    .ok_or_else(|| anyhow!("invalid status filter: {value}"))?,
            ),
        };

        let guard = self.state.lock().expect("dataset registry lock poisoned");
        let record = guard
            .datasets
            .iter()
            .find(|record| record.metadata.name == dataset_name)
            .ok_or_else(|| anyhow!("unknown dataset: {dataset_name}"))?;

        let shards = record
            .shards
            .iter()
            .filter(|shard| filter.is_none_or(|expected| shard.status == expected))
            .cloned()
            .collect();
        Ok(shards)
    }

    /// Per-worker claimed/completed shard counts from the registry.
    pub fn worker_shard_counts(&self) -> std::collections::HashMap<u64, (u64, u64)> {
        let guard = self.state.lock().expect("dataset registry lock poisoned");
        let mut counts: std::collections::HashMap<u64, (u64, u64)> = std::collections::HashMap::new();

        for record in &guard.datasets {
            for shard in &record.shards {
                let worker_id = match shard.status {
                    ShardStatus::Claimed | ShardStatus::Completed => shard.claimed_by,
                    _ => None,
                };
                let Some(worker_id) = worker_id else {
                    continue;
                };
                let entry = counts.entry(worker_id).or_insert((0, 0));
                match shard.status {
                    ShardStatus::Claimed => entry.0 += 1,
                    ShardStatus::Completed => entry.1 += 1,
                    _ => {}
                }
            }
        }
        counts
    }

    pub fn shard_status_counts(&self, dataset_name: &str) -> Result<(u64, u64, u64)> {
        let guard = self.state.lock().expect("dataset registry lock poisoned");
        let record = guard
            .datasets
            .iter()
            .find(|record| record.metadata.name == dataset_name)
            .ok_or_else(|| anyhow!("unknown dataset: {dataset_name}"))?;

        let mut pending = 0_u64;
        let mut claimed = 0_u64;
        let mut completed = 0_u64;
        for shard in &record.shards {
            match shard.status {
                ShardStatus::Pending => pending += 1,
                ShardStatus::Claimed => claimed += 1,
                ShardStatus::Completed => completed += 1,
                ShardStatus::Failed => {}
            }
        }
        Ok((pending, claimed, completed))
    }

    fn persist(&self, state: &RegistryState) -> Result<()> {
        let bytes = serde_json::to_vec_pretty(state).context("serialize dataset registry")?;
        fs::write(&self.registry_path, bytes)
            .with_context(|| format!("write {}", self.registry_path.display()))
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ShardAggregateCounts {
    pub total_datasets: u64,
    pub total_shards: u64,
    pub pending_shards: u64,
    pub claimed_shards: u64,
    pub completed_shards: u64,
    pub failed_shards: u64,
}

fn shard_count(total_samples: u64, shard_size: u64) -> u64 {
    total_samples.div_ceil(shard_size)
}

pub fn current_time_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn register_dataset_creates_shards() -> Result<()> {
        let dir = tempdir()?;
        let registry = DatasetRegistry::new(dir.path())?;
        let metadata = registry.register_dataset("train", 100, 10)?;
        assert_eq!(metadata.total_shards, 10);
        assert_eq!(metadata.total_samples, 100);

        let (pending, claimed, completed) = registry.shard_status_counts("train")?;
        assert_eq!((pending, claimed, completed), (10, 0, 0));
        Ok(())
    }

    #[test]
    fn claim_complete_and_release_stale() -> Result<()> {
        let dir = tempdir()?;
        let registry = DatasetRegistry::new(dir.path())?;
        registry.register_dataset("train", 30, 10)?;

        let shard = registry
            .claim_next_shard(1, "train")?
            .expect("expected shard");
        assert_eq!(shard.shard_id, 0);
        assert_eq!(shard.start_sample, 0);
        assert_eq!(shard.end_sample, 10);

        registry.complete_shard(1, "train", shard.shard_id)?;

        let stale = registry
            .claim_next_shard(2, "train")?
            .expect("expected second shard");
        assert_eq!(stale.shard_id, 1);

        std::thread::sleep(std::time::Duration::from_millis(5));
        let released = registry.release_stale_shards(1)?;
        assert_eq!(released, 1);

        let reclaimed = registry
            .claim_next_shard(3, "train")?
            .expect("reclaimed stale shard");
        assert_eq!(reclaimed.shard_id, stale.shard_id);
        registry.complete_shard(3, "train", reclaimed.shard_id)?;
        Ok(())
    }

    #[test]
    fn duplicate_register_fails() -> Result<()> {
        let dir = tempdir()?;
        let registry = DatasetRegistry::new(dir.path())?;
        registry.register_dataset("train", 10, 5)?;
        let error = registry
            .register_dataset("train", 10, 5)
            .expect_err("duplicate should fail");
        assert!(error.to_string().contains("already registered"));
        Ok(())
    }
}
