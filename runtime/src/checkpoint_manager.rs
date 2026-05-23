use std::collections::HashMap;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use anyhow::{Context, Result};

use crate::metadata::{CheckpointEntry, CheckpointMetadata};

/// Manages safe checkpoint writes and metadata updates for one directory.
pub struct CheckpointManager {
    checkpoint_dir: PathBuf,
    /// Prefix used in metadata.json path fields (e.g. "checkpoints").
    path_prefix: String,
    /// Artificial delay before each save, for simulating slow storage in benchmarks.
    write_delay_ms: u64,
}

impl CheckpointManager {
    pub fn new(checkpoint_dir: PathBuf, path_prefix: impl Into<String>) -> Self {
        Self::new_with_delay(checkpoint_dir, path_prefix, 0)
    }

    pub fn new_with_delay(
        checkpoint_dir: PathBuf,
        path_prefix: impl Into<String>,
        write_delay_ms: u64,
    ) -> Self {
        Self {
            checkpoint_dir,
            path_prefix: path_prefix.into(),
            write_delay_ms,
        }
    }

    pub fn write_delay_ms(&self) -> u64 {
        self.write_delay_ms
    }

    /// Write a checkpoint atomically and update metadata.json.
    pub fn save_checkpoint(&self, step: u64, data: &[u8]) -> Result<()> {
        self.persist_checkpoint_bytes(step, data)?;
        self.write_metadata(step)?;
        eprintln!("Wrote metadata.json");
        Ok(())
    }

    /// Write a worker-aware checkpoint using `global_step` for the on-disk filename.
    pub fn save_worker_checkpoint(
        &self,
        worker_id: u64,
        local_step: u64,
        global_step: u64,
        data: &[u8],
    ) -> Result<()> {
        self.persist_checkpoint_bytes(global_step, data)?;
        self.write_worker_metadata(global_step, worker_id, local_step)?;
        eprintln!("Wrote metadata.json");
        Ok(())
    }

    /// Return the committed checkpoint with the highest `local_step` for one worker.
    pub fn latest_checkpoint_for_worker(
        &self,
        worker_id: u64,
    ) -> Result<Option<CheckpointEntry>> {
        let Some(metadata) = self.read_metadata()? else {
            return Ok(None);
        };

        let latest = metadata
            .checkpoints
            .iter()
            .filter(|entry| entry.worker_id == Some(worker_id))
            .max_by_key(|entry| entry.local_step.unwrap_or(0));

        Ok(latest.cloned())
    }

    /// Load bytes for the latest committed checkpoint belonging to one worker.
    pub fn load_latest_for_worker(&self, worker_id: u64) -> Result<Option<Vec<u8>>> {
        let Some(entry) = self.latest_checkpoint_for_worker(worker_id)? else {
            return Ok(None);
        };

        let path = self.resolve_checkpoint_path(&entry.path);
        let bytes = fs::read(&path).with_context(|| {
            format!("failed to read checkpoint file {}", path.display())
        })?;

        Ok(Some(bytes))
    }

    fn persist_checkpoint_bytes(&self, step: u64, data: &[u8]) -> Result<()> {
        if self.write_delay_ms > 0 {
            thread::sleep(Duration::from_millis(self.write_delay_ms));
        }

        self.ensure_checkpoint_dir()?;

        let temp_path = self.temp_checkpoint_path(step);
        let final_path = self.checkpoint_path(step);

        eprintln!("Writing temporary checkpoint");

        let mut file = File::create(&temp_path)
            .with_context(|| format!("failed to create {}", temp_path.display()))?;
        file.write_all(data)
            .with_context(|| format!("failed to write {}", temp_path.display()))?;
        file.flush()
            .with_context(|| format!("failed to flush {}", temp_path.display()))?;
        file.sync_all()
            .with_context(|| format!("failed to sync {}", temp_path.display()))?;

        fs::rename(&temp_path, &final_path).with_context(|| {
            format!(
                "failed to rename {} to {}",
                temp_path.display(),
                final_path.display()
            )
        })?;

        eprintln!("Committed checkpoint step {step}");
        Ok(())
    }

    /// Return all committed checkpoints from metadata.json.
    pub fn list_checkpoints(&self) -> Result<Vec<CheckpointEntry>> {
        Ok(self
            .read_metadata()?
            .map(|metadata| metadata.checkpoints)
            .unwrap_or_default())
    }

    /// Return the checkpoint entry for the latest training step.
    pub fn latest_checkpoint(&self) -> Result<Option<CheckpointEntry>> {
        let Some(metadata) = self.read_metadata()? else {
            return Ok(None);
        };

        let latest = metadata
            .checkpoints
            .into_iter()
            .find(|entry| entry.step == metadata.latest_step);

        Ok(latest)
    }

    /// Read the bytes of the latest committed checkpoint, if one exists.
    pub fn load_latest(&self) -> Result<Option<Vec<u8>>> {
        let Some(entry) = self.latest_checkpoint()? else {
            return Ok(None);
        };

        let path = self.resolve_checkpoint_path(&entry.path);
        let bytes = fs::read(&path).with_context(|| {
            format!("failed to read checkpoint file {}", path.display())
        })?;

        Ok(Some(bytes))
    }

    /// Keep only the latest `keep_last` checkpoints by step and delete older files.
    ///
    /// Returns how many checkpoint files were removed from disk.
    pub fn prune_checkpoints(&self, keep_last: usize) -> Result<usize> {
        let Some(metadata) = self.read_metadata()? else {
            return Ok(0);
        };

        let mut deleted = 0;
        let retained = Self::select_retained_checkpoints(&metadata.checkpoints, keep_last);
        let retained_steps: std::collections::HashSet<u64> =
            retained.iter().map(|entry| entry.step).collect();

        for entry in &metadata.checkpoints {
            if retained_steps.contains(&entry.step) {
                continue;
            }

            let path = self.resolve_checkpoint_path(&entry.path);
            if !path.exists() {
                continue;
            }

            if fs::remove_file(&path).is_ok() {
                deleted += 1;
            }
        }

        let pruned = CheckpointMetadata {
            latest_step: retained.last().map(|entry| entry.step).unwrap_or(0),
            checkpoints: retained,
        };
        self.persist_metadata(&pruned)?;

        Ok(deleted)
    }

    /// Keep the latest `keep_last_per_worker` checkpoints for each worker (by `local_step`).
    ///
    /// Legacy entries without `worker_id` are left unchanged. Returns the number of
    /// checkpoint files removed from disk.
    pub fn prune_checkpoints_per_worker(&self, keep_last_per_worker: usize) -> Result<usize> {
        let Some(metadata) = self.read_metadata()? else {
            return Ok(0);
        };

        let mut legacy = Vec::new();
        let mut by_worker: HashMap<u64, Vec<CheckpointEntry>> = HashMap::new();

        for entry in &metadata.checkpoints {
            match entry.worker_id {
                Some(worker_id) => {
                    by_worker.entry(worker_id).or_default().push(entry.clone());
                }
                None => legacy.push(entry.clone()),
            }
        }

        let mut retained = legacy;
        for mut entries in by_worker.into_values() {
            entries.sort_by_key(|entry| entry.local_step.unwrap_or(0));
            let retain_from = entries.len().saturating_sub(keep_last_per_worker);
            retained.extend(entries.split_off(retain_from));
        }

        retained.sort_by_key(|entry| entry.step);
        let retained_steps: std::collections::HashSet<u64> =
            retained.iter().map(|entry| entry.step).collect();

        let mut deleted = 0;
        for entry in &metadata.checkpoints {
            if retained_steps.contains(&entry.step) {
                continue;
            }

            let path = self.resolve_checkpoint_path(&entry.path);
            if !path.exists() {
                continue;
            }

            if fs::remove_file(&path).is_ok() {
                deleted += 1;
            }
        }

        let latest_step = retained.iter().map(|entry| entry.step).max().unwrap_or(0);
        let pruned = CheckpointMetadata {
            latest_step,
            checkpoints: retained,
        };
        self.persist_metadata(&pruned)?;

        Ok(deleted)
    }

    fn read_metadata(&self) -> Result<Option<CheckpointMetadata>> {
        let metadata_path = self.checkpoint_dir.join("metadata.json");
        if !metadata_path.exists() {
            return Ok(None);
        }

        let json = fs::read_to_string(&metadata_path).with_context(|| {
            format!(
                "failed to read metadata file {}",
                metadata_path.display()
            )
        })?;
        let metadata = serde_json::from_str(&json).with_context(|| {
            format!(
                "failed to parse metadata file {}",
                metadata_path.display()
            )
        })?;

        Ok(Some(metadata))
    }

    /// Map a metadata path like `checkpoints/step_0001.ckpt` to a real file
    /// inside `checkpoint_dir`. Tests use temp dirs, so we only need the file name.
    fn resolve_checkpoint_path(&self, metadata_path: &str) -> PathBuf {
        let file_name = Path::new(metadata_path)
            .file_name()
            .expect("checkpoint path in metadata should include a file name");
        self.checkpoint_dir.join(file_name)
    }

    fn ensure_checkpoint_dir(&self) -> Result<()> {
        if self.checkpoint_dir.exists() {
            return Ok(());
        }

        fs::create_dir_all(&self.checkpoint_dir).with_context(|| {
            format!(
                "failed to create checkpoint directory {}",
                self.checkpoint_dir.display()
            )
        })?;
        eprintln!("Created checkpoints directory");
        Ok(())
    }

    fn write_metadata(&self, step: u64) -> Result<()> {
        let relative_path = self.relative_checkpoint_path(step);
        let mut metadata = self
            .read_metadata()?
            .unwrap_or_else(CheckpointMetadata::empty);
        metadata.record_commit(step, relative_path);
        self.persist_metadata(&metadata)?;
        Ok(())
    }

    fn write_worker_metadata(
        &self,
        global_step: u64,
        worker_id: u64,
        local_step: u64,
    ) -> Result<()> {
        let relative_path = self.relative_checkpoint_path(global_step);
        let mut metadata = self
            .read_metadata()?
            .unwrap_or_else(CheckpointMetadata::empty);
        metadata.record_worker_commit(global_step, relative_path, worker_id, local_step);
        self.persist_metadata(&metadata)?;
        Ok(())
    }

    fn relative_checkpoint_path(&self, step: u64) -> String {
        format!(
            "{}/step_{step:04}.ckpt",
            self.path_prefix.trim_end_matches('/')
        )
    }

    fn persist_metadata(&self, metadata: &CheckpointMetadata) -> Result<()> {
        let json = serde_json::to_string_pretty(metadata)
            .context("failed to serialize metadata.json")?;
        let metadata_path = self.checkpoint_dir.join("metadata.json");
        fs::write(&metadata_path, json).with_context(|| {
            format!(
                "failed to write metadata file {}",
                metadata_path.display()
            )
        })?;

        Ok(())
    }

    fn select_retained_checkpoints(
        checkpoints: &[CheckpointEntry],
        keep_last: usize,
    ) -> Vec<CheckpointEntry> {
        if keep_last == 0 {
            return Vec::new();
        }

        let mut sorted = checkpoints.to_vec();
        sorted.sort_by_key(|entry| entry.step);

        let retain_from = sorted.len().saturating_sub(keep_last);
        sorted.split_off(retain_from)
    }

    fn checkpoint_path(&self, step: u64) -> PathBuf {
        self.checkpoint_dir
            .join(format!("step_{step:04}.ckpt"))
    }

    fn temp_checkpoint_path(&self, step: u64) -> PathBuf {
        self.checkpoint_dir
            .join(format!("step_{step:04}.ckpt.tmp"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    fn manager_in_temp_dir(dir: &Path) -> CheckpointManager {
        CheckpointManager::new(dir.to_path_buf(), "checkpoints")
    }

    #[test]
    fn new_defaults_delay_to_zero() {
        let temp = tempfile::tempdir().unwrap();
        let manager = manager_in_temp_dir(temp.path());
        assert_eq!(manager.write_delay_ms(), 0);
    }

    #[test]
    fn new_with_delay_stores_delay() {
        let temp = tempfile::tempdir().unwrap();
        let manager =
            CheckpointManager::new_with_delay(temp.path().to_path_buf(), "checkpoints", 500);
        assert_eq!(manager.write_delay_ms(), 500);
    }

    #[test]
    fn save_with_delay_takes_at_least_delay_duration() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let delay_ms = 100;
        let manager =
            CheckpointManager::new_with_delay(temp.path().to_path_buf(), "checkpoints", delay_ms);

        let started = std::time::Instant::now();
        manager.save_checkpoint(1, b"delayed")?;
        let elapsed = started.elapsed();

        assert!(
            elapsed >= Duration::from_millis(delay_ms),
            "expected at least {delay_ms} ms, got {} ms",
            elapsed.as_millis()
        );

        Ok(())
    }

    #[test]
    fn save_worker_checkpoint_writes_worker_metadata() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        manager.save_worker_checkpoint(1, 10, 1_000_010, b"worker one")?;

        let metadata = manager
            .read_metadata()?
            .expect("expected metadata after worker save");
        let entry = metadata
            .checkpoints
            .iter()
            .find(|e| e.step == 1_000_010)
            .expect("expected worker checkpoint entry");

        assert_eq!(entry.worker_id, Some(1));
        assert_eq!(entry.local_step, Some(10));
        assert_eq!(entry.path, "checkpoints/step_1000010.ckpt");

        Ok(())
    }

    #[test]
    fn latest_checkpoint_for_worker_returns_highest_local_step() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        manager.save_worker_checkpoint(2, 5, 2_000_005, b"step five")?;
        manager.save_worker_checkpoint(2, 10, 2_000_010, b"step ten")?;
        manager.save_worker_checkpoint(1, 99, 1_000_099, b"other worker")?;

        let latest = manager
            .latest_checkpoint_for_worker(2)?
            .expect("expected worker 2 checkpoint");

        assert_eq!(latest.local_step, Some(10));
        assert_eq!(latest.step, 2_000_010);

        Ok(())
    }

    #[test]
    fn load_latest_for_worker_returns_correct_bytes() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        manager.save_worker_checkpoint(3, 7, 3_000_007, b"worker three")?;

        let bytes = manager
            .load_latest_for_worker(3)?
            .expect("expected checkpoint bytes");

        assert_eq!(bytes, b"worker three");

        Ok(())
    }

    #[test]
    fn save_checkpoint_creates_ckpt_and_metadata() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        manager.save_checkpoint(1, b"test data")?;

        assert!(manager.checkpoint_path(1).is_file());
        assert!(temp.path().join("metadata.json").is_file());

        Ok(())
    }

    #[test]
    fn save_checkpoint_leaves_no_tmp_file() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        manager.save_checkpoint(1, b"test data")?;

        let tmp_path = manager.temp_checkpoint_path(1);
        assert!(
            !tmp_path.exists(),
            "temporary file should be removed after commit: {}",
            tmp_path.display()
        );

        Ok(())
    }

    #[test]
    fn list_checkpoints_empty_before_save() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        let checkpoints = manager.list_checkpoints()?;
        assert!(checkpoints.is_empty());

        Ok(())
    }

    #[test]
    fn latest_checkpoint_after_save() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        manager.save_checkpoint(1, b"hello")?;

        let latest = manager
            .latest_checkpoint()?
            .expect("expected a latest checkpoint");
        assert_eq!(latest.step, 1);
        assert_eq!(latest.status, "committed");

        Ok(())
    }

    #[test]
    fn load_latest_returns_saved_bytes() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        manager.save_checkpoint(1, b"hello")?;

        let data = manager.load_latest()?.expect("expected checkpoint bytes");
        assert_eq!(data, b"hello");

        Ok(())
    }

    #[test]
    fn load_latest_returns_newest_checkpoint() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        manager.save_checkpoint(1, b"step one")?;
        manager.save_checkpoint(2, b"step two")?;

        let latest = manager
            .latest_checkpoint()?
            .expect("expected a latest checkpoint");
        assert_eq!(latest.step, 2);

        let data = manager.load_latest()?.expect("expected checkpoint bytes");
        assert_eq!(data, b"step two");

        Ok(())
    }

    #[test]
    fn list_checkpoints_keeps_all_saved_steps() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        manager.save_checkpoint(1, b"step one")?;
        manager.save_checkpoint(2, b"step two")?;

        let checkpoints = manager.list_checkpoints()?;
        assert_eq!(checkpoints.len(), 2);
        assert_eq!(checkpoints[0].step, 1);
        assert_eq!(checkpoints[1].step, 2);

        Ok(())
    }

    #[test]
    fn saving_same_step_replaces_entry() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        manager.save_checkpoint(1, b"first version")?;
        manager.save_checkpoint(1, b"second version")?;

        let checkpoints = manager.list_checkpoints()?;
        assert_eq!(checkpoints.len(), 1);
        assert_eq!(checkpoints[0].step, 1);

        let data = manager.load_latest()?.expect("expected checkpoint bytes");
        assert_eq!(data, b"second version");

        Ok(())
    }

    #[test]
    fn prune_checkpoints_keeps_latest_n() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        manager.save_checkpoint(1, b"step one")?;
        manager.save_checkpoint(2, b"step two")?;
        manager.save_checkpoint(3, b"step three")?;

        let deleted = manager.prune_checkpoints(2)?;
        assert_eq!(deleted, 1);

        assert!(!manager.checkpoint_path(1).exists());
        assert!(manager.checkpoint_path(2).is_file());
        assert!(manager.checkpoint_path(3).is_file());

        let checkpoints = manager.list_checkpoints()?;
        assert_eq!(checkpoints.len(), 2);
        assert_eq!(checkpoints[0].step, 2);
        assert_eq!(checkpoints[1].step, 3);

        let metadata = manager.read_metadata()?.expect("metadata should exist");
        assert_eq!(metadata.latest_step, 3);

        Ok(())
    }

    #[test]
    fn prune_checkpoints_zero_deletes_all() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        manager.save_checkpoint(1, b"step one")?;
        manager.save_checkpoint(2, b"step two")?;

        let deleted = manager.prune_checkpoints(0)?;
        assert_eq!(deleted, 2);

        assert!(!manager.checkpoint_path(1).exists());
        assert!(!manager.checkpoint_path(2).exists());

        let metadata = manager.read_metadata()?.expect("metadata should exist");
        assert_eq!(metadata.latest_step, 0);
        assert!(metadata.checkpoints.is_empty());

        Ok(())
    }

    #[test]
    fn prune_checkpoints_before_any_save_returns_zero() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        let deleted = manager.prune_checkpoints(2)?;
        assert_eq!(deleted, 0);
        assert!(!temp.path().join("metadata.json").exists());

        Ok(())
    }

    #[test]
    fn prune_checkpoints_per_worker_keeps_one_per_worker() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        for local_step in [5, 10, 15] {
            manager.save_worker_checkpoint(0, local_step, local_step, b"worker zero")?;
            manager.save_worker_checkpoint(
                1,
                local_step,
                1_000_000 + local_step,
                b"worker one",
            )?;
        }

        let deleted = manager.prune_checkpoints_per_worker(1)?;
        assert_eq!(deleted, 4);

        assert!(!manager.checkpoint_path(5).exists());
        assert!(!manager.checkpoint_path(10).exists());
        assert!(manager.checkpoint_path(15).is_file());
        assert!(!manager.checkpoint_path(1_000_005).exists());
        assert!(!manager.checkpoint_path(1_000_010).exists());
        assert!(manager.checkpoint_path(1_000_015).is_file());

        let checkpoints = manager.list_checkpoints()?;
        assert_eq!(checkpoints.len(), 2);
        assert_eq!(
            checkpoints
                .iter()
                .map(|entry| entry.local_step)
                .collect::<Vec<_>>(),
            vec![Some(15), Some(15)]
        );

        Ok(())
    }

    #[test]
    fn prune_checkpoints_per_worker_keeps_two_per_worker() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        for local_step in [5, 10, 15] {
            manager.save_worker_checkpoint(0, local_step, local_step, b"worker zero")?;
            manager.save_worker_checkpoint(
                1,
                local_step,
                1_000_000 + local_step,
                b"worker one",
            )?;
        }

        let deleted = manager.prune_checkpoints_per_worker(2)?;
        assert_eq!(deleted, 2);

        assert!(!manager.checkpoint_path(5).exists());
        assert!(manager.checkpoint_path(10).is_file());
        assert!(manager.checkpoint_path(15).is_file());
        assert!(!manager.checkpoint_path(1_000_005).exists());
        assert!(manager.checkpoint_path(1_000_010).is_file());
        assert!(manager.checkpoint_path(1_000_015).is_file());

        let checkpoints = manager.list_checkpoints()?;
        assert_eq!(checkpoints.len(), 4);

        Ok(())
    }

    #[test]
    fn prune_checkpoints_per_worker_preserves_legacy_entries() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        manager.save_checkpoint(99, b"legacy global")?;
        for local_step in [5, 10, 15] {
            manager.save_worker_checkpoint(0, local_step, local_step, b"worker zero")?;
        }

        let deleted = manager.prune_checkpoints_per_worker(1)?;
        assert_eq!(deleted, 2);

        assert!(manager.checkpoint_path(99).exists());
        assert!(!manager.checkpoint_path(5).exists());
        assert!(!manager.checkpoint_path(10).exists());
        assert!(manager.checkpoint_path(15).is_file());

        let checkpoints = manager.list_checkpoints()?;
        assert_eq!(checkpoints.len(), 2);
        assert!(checkpoints.iter().any(|entry| entry.step == 99 && entry.worker_id.is_none()));

        Ok(())
    }
}
