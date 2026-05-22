use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};

use crate::metadata::{CheckpointEntry, CheckpointMetadata};

/// Manages safe checkpoint writes and metadata updates for one directory.
pub struct CheckpointManager {
    checkpoint_dir: PathBuf,
    /// Prefix used in metadata.json path fields (e.g. "checkpoints").
    path_prefix: String,
}

impl CheckpointManager {
    pub fn new(checkpoint_dir: PathBuf, path_prefix: impl Into<String>) -> Self {
        Self {
            checkpoint_dir,
            path_prefix: path_prefix.into(),
        }
    }

    /// Write a checkpoint atomically and update metadata.json.
    pub fn save_checkpoint(&self, step: u64, data: &[u8]) -> Result<()> {
        self.ensure_checkpoint_dir()?;

        let temp_path = self.temp_checkpoint_path(step);
        let final_path = self.checkpoint_path(step);

        println!("Writing temporary checkpoint");

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

        println!("Committed checkpoint step {step}");

        self.write_metadata(step)?;
        println!("Wrote metadata.json");

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
        println!("Created checkpoints directory");
        Ok(())
    }

    fn write_metadata(&self, step: u64) -> Result<()> {
        let relative_path = format!(
            "{}/step_{step:04}.ckpt",
            self.path_prefix.trim_end_matches('/')
        );

        let mut metadata = self
            .read_metadata()?
            .unwrap_or_else(CheckpointMetadata::empty);
        metadata.record_commit(step, relative_path);
        self.persist_metadata(&metadata)?;

        Ok(())
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
}
