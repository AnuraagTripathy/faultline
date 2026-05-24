//! Failure-injection demo harness (in-memory storage; not used in production).

use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{Context, Result};

use crate::checkpoint_manager::CheckpointManager;
use crate::storage::{
    FailureInjectingStorageBackend, InMemoryStorageBackend, StorageBackend,
};

/// Outcome of the failure-injection walkthrough.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FailureDemoResult {
    pub latest_step: u64,
    pub latest_data: Vec<u8>,
    pub step2_blob_present: bool,
    pub step2_in_metadata: bool,
    pub step3_blob_present: bool,
    pub step3_in_metadata: bool,
}

fn checkpoint_path(step: u64) -> String {
    format!("checkpoints/step_{step:04}.ckpt")
}

fn step_in_metadata(manager: &CheckpointManager, step: u64) -> Result<bool> {
    Ok(manager
        .list_checkpoints()?
        .iter()
        .any(|entry| entry.step == step))
}

/// Run the Version 9.4 failure-injection demonstration.
pub fn run_failure_demo() -> Result<FailureDemoResult> {
    let inner = Arc::new(InMemoryStorageBackend::new("checkpoints"));

    // Step 1: successful save
    {
        let storage: Arc<dyn StorageBackend> = Arc::new(FailureInjectingStorageBackend::new(
            Arc::clone(&inner),
        ));
        let manager = CheckpointManager::with_storage(storage, 0);
        manager.save_checkpoint(1, b"step-1-bytes")?;
    }

    // Step 2: injected metadata failure
    {
        let failing = FailureInjectingStorageBackend::new(Arc::clone(&inner));
        failing.fail_next_write_metadata();
        let manager = CheckpointManager::with_storage(Arc::new(failing), 0);
        if manager.save_checkpoint(2, b"step-2-bytes").is_ok() {
            anyhow::bail!("expected step 2 save to fail after metadata injection");
        }
    }

    let step2_blob_present = inner.exists(&checkpoint_path(2));
    let storage: Arc<dyn StorageBackend> = Arc::new(FailureInjectingStorageBackend::new(Arc::clone(
        &inner,
    )));
    let probe = CheckpointManager::with_storage(storage, 0);
    let step2_in_metadata = step_in_metadata(&probe, 2)?;

    // Step 3: injected blob write failure
    {
        let failing = FailureInjectingStorageBackend::new(Arc::clone(&inner));
        failing.fail_next_write_atomic();
        let manager = CheckpointManager::with_storage(Arc::new(failing), 0);
        if manager.save_checkpoint(3, b"step-3-bytes").is_ok() {
            anyhow::bail!("expected step 3 save to fail after write_atomic injection");
        }
    }

    let step3_blob_present = inner.exists(&checkpoint_path(3));
    let storage: Arc<dyn StorageBackend> = Arc::new(FailureInjectingStorageBackend::new(Arc::clone(
        &inner,
    )));
    let probe = CheckpointManager::with_storage(storage, 0);
    let step3_in_metadata = step_in_metadata(&probe, 3)?;

    // Step 4: recovery save
    {
        let storage: Arc<dyn StorageBackend> = Arc::new(FailureInjectingStorageBackend::new(
            Arc::clone(&inner),
        ));
        let manager = CheckpointManager::with_storage(storage, 0);
        manager.save_checkpoint(4, b"step-4-bytes")?;
        let latest = manager.latest_checkpoint()?.expect("latest after step 4");
        let data = manager.load_latest()?.expect("latest bytes");
        return Ok(FailureDemoResult {
            latest_step: latest.step,
            latest_data: data,
            step2_blob_present,
            step2_in_metadata,
            step3_blob_present,
            step3_in_metadata,
        });
    }
}

fn format_demo_output(result: &FailureDemoResult) -> Vec<String> {
    vec![
        "Faultline failure injection demo".to_string(),
        String::new(),
        "Step 1 saved successfully.".to_string(),
        String::new(),
        "Injected metadata failure.".to_string(),
        "Step 2 not committed (metadata is source of truth).".to_string(),
        format!(
            "  step 2 blob present in storage: {}",
            result.step2_blob_present
        ),
        format!("  step 2 listed in metadata: {}", result.step2_in_metadata),
        String::new(),
        "Injected blob write failure.".to_string(),
        "Step 3 not committed.".to_string(),
        format!(
            "  step 3 blob present in storage: {}",
            result.step3_blob_present
        ),
        format!("  step 3 listed in metadata: {}", result.step3_in_metadata),
        String::new(),
        format!(
            "Recovery latest checkpoint: step {} ({})",
            result.latest_step,
            String::from_utf8_lossy(&result.latest_data)
        ),
        String::new(),
        "Takeaway: failed writes do not advance latest; retry can succeed later.".to_string(),
    ]
}

/// Run the demo, print to stdout, and optionally write a summary file.
pub fn run_failure_demo_and_report(summary_path: Option<PathBuf>) -> Result<FailureDemoResult> {
    let result = run_failure_demo()?;

    for line in format_demo_output(&result) {
        println!("{line}");
    }

    if let Some(path) = summary_path {
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent).with_context(|| {
                    format!("failed to create directory {}", parent.display())
                })?;
            }
        }
        let body = format_demo_output(&result).join("\n");
        std::fs::write(&path, body).with_context(|| format!("failed to write {}", path.display()))?;
        println!();
        println!("Wrote summary to {}", path.display());
    }

    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn failure_demo_core_logic_returns_step_four_latest() -> Result<()> {
        let result = run_failure_demo()?;

        assert_eq!(result.latest_step, 4);
        assert_eq!(result.latest_data, b"step-4-bytes");
        assert!(result.step2_blob_present);
        assert!(!result.step2_in_metadata);
        assert!(!result.step3_blob_present);
        assert!(!result.step3_in_metadata);

        Ok(())
    }
}
