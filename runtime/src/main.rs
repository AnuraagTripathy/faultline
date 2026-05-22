use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::Serialize;

/// One committed checkpoint entry in metadata.json.
#[derive(Serialize)]
struct CheckpointEntry {
    step: u32,
    path: String,
    status: String,
}

/// Tracks the latest step and all committed checkpoints.
#[derive(Serialize)]
struct Metadata {
    latest_step: u32,
    checkpoints: Vec<CheckpointEntry>,
}

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("runtime crate should live inside the repo")
        .to_path_buf()
}

fn checkpoints_dir() -> PathBuf {
    repo_root().join("checkpoints")
}

fn checkpoint_path(step: u32) -> PathBuf {
    checkpoints_dir().join(format!("step_{step:04}.ckpt"))
}

fn temp_checkpoint_path(step: u32) -> PathBuf {
    checkpoints_dir().join(format!("step_{step:04}.ckpt.tmp"))
}

fn write_checkpoint(step: u32, data: &str) -> std::io::Result<()> {
    let temp_path = temp_checkpoint_path(step);
    let final_path = checkpoint_path(step);

    println!("Writing temporary checkpoint");

    let mut file = File::create(&temp_path)?;
    file.write_all(data.as_bytes())?;
    file.flush()?;
    file.sync_all()?;

    fs::rename(&temp_path, &final_path)?;

    Ok(())
}

fn write_metadata(step: u32) -> std::io::Result<()> {
    let metadata = Metadata {
        latest_step: step,
        checkpoints: vec![CheckpointEntry {
            step,
            path: format!("checkpoints/step_{step:04}.ckpt"),
            status: "committed".to_string(),
        }],
    };

    let json = serde_json::to_string_pretty(&metadata)?;
    fs::write(checkpoints_dir().join("metadata.json"), json)?;
    Ok(())
}

fn main() {
    println!("Faultline runtime started");

    let dir = checkpoints_dir();
    if !dir.exists() {
        fs::create_dir_all(&dir).expect("failed to create checkpoints directory");
        println!("Created checkpoints directory");
    }

    let step = 1;
    let data = "fake checkpoint data for step 1";

    write_checkpoint(step, data).expect("failed to write checkpoint");
    println!("Committed checkpoint step {step}");

    write_metadata(step).expect("failed to write metadata");
    println!("Wrote metadata.json");
}
