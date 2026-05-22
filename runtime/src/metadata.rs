use serde::{Deserialize, Serialize};

/// One committed checkpoint recorded in metadata.json.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CheckpointEntry {
    pub step: u64,
    pub path: String,
    pub status: String,
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
        let entry = CheckpointEntry {
            step,
            path: relative_path,
            status: "committed".to_string(),
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
