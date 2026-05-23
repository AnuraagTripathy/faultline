use serde::{Deserialize, Serialize};

/// One committed checkpoint recorded in metadata.json.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CheckpointEntry {
    pub step: u64,
    pub path: String,
    pub status: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub worker_id: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub local_step: Option<u64>,
}

/// Top-level metadata file written after each successful commit.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CheckpointMetadata {
    pub latest_step: u64,
    pub checkpoints: Vec<CheckpointEntry>,
}

impl CheckpointMetadata {
    /// Empty metadata used before the first checkpoint is saved.
    pub fn empty() -> Self {
        Self {
            latest_step: 0,
            checkpoints: Vec::new(),
        }
    }

    /// Add or update one committed checkpoint and set it as latest.
    ///
    /// If this step was saved before, the old entry is replaced instead of duplicated.
    pub fn record_commit(&mut self, step: u64, relative_path: String) {
        self.record_commit_inner(step, relative_path, None, None);
    }

    /// Record a worker-aware committed checkpoint and set it as latest.
    pub fn record_worker_commit(
        &mut self,
        step: u64,
        relative_path: String,
        worker_id: u64,
        local_step: u64,
    ) {
        self.record_commit_inner(step, relative_path, Some(worker_id), Some(local_step));
    }

    fn record_commit_inner(
        &mut self,
        step: u64,
        relative_path: String,
        worker_id: Option<u64>,
        local_step: Option<u64>,
    ) {
        let entry = CheckpointEntry {
            step,
            path: relative_path,
            status: "committed".to_string(),
            worker_id,
            local_step,
        };

        if let Some(existing) = self.checkpoints.iter_mut().find(|e| e.step == step) {
            *existing = entry;
        } else {
            self.checkpoints.push(entry);
        }

        self.checkpoints.sort_by_key(|entry| entry.step);
        self.latest_step = step;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deserialize_legacy_entry_without_worker_fields() {
        let json = r#"{"step":1,"path":"checkpoints/step_0001.ckpt","status":"committed"}"#;
        let entry: CheckpointEntry = serde_json::from_str(json).unwrap();
        assert_eq!(entry.step, 1);
        assert_eq!(entry.worker_id, None);
        assert_eq!(entry.local_step, None);
    }
}
