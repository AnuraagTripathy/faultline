use std::path::{Path, PathBuf};

use anyhow::Result;
use clap::{Parser, Subcommand};
use runtime::checkpoint_manager::CheckpointManager;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("runtime crate should live inside the repo")
        .to_path_buf()
}

fn checkpoint_manager() -> CheckpointManager {
    CheckpointManager::new(repo_root().join("checkpoints"), "checkpoints")
}

#[derive(Parser)]
#[command(name = "faultline", about = "Faultline checkpoint CLI")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Save a checkpoint for a training step.
    Save {
        step: u64,
        /// Checkpoint payload. If omitted, saves fake placeholder data.
        #[arg(long)]
        data: Option<String>,
    },
    /// List all committed checkpoints from metadata.json.
    List,
    /// Show the latest committed checkpoint.
    Latest,
    /// Load and print the latest checkpoint bytes.
    #[command(name = "load-latest")]
    LoadLatest,
    /// Keep only the latest N checkpoints and delete older files.
    Prune {
        keep_last: usize,
    },
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let manager = checkpoint_manager();

    match cli.command {
        Command::Save { step, data } => {
            let bytes = match data {
                Some(payload) => payload.into_bytes(),
                None => format!("fake checkpoint data for step {step}").into_bytes(),
            };
            manager.save_checkpoint(step, &bytes)?;
        }
        Command::List => {
            let checkpoints = manager.list_checkpoints()?;
            if checkpoints.is_empty() {
                println!("No checkpoints found.");
            } else {
                for entry in checkpoints {
                    println!(
                        "step {} | path {} | status {}",
                        entry.step, entry.path, entry.status
                    );
                }
            }
        }
        Command::Latest => {
            match manager.latest_checkpoint()? {
                Some(entry) => {
                    println!("latest step: {}", entry.step);
                    println!("path: {}", entry.path);
                }
                None => println!("No latest checkpoint found."),
            }
        }
        Command::LoadLatest => match manager.load_latest()? {
            Some(bytes) => println!("{}", String::from_utf8_lossy(&bytes)),
            None => println!("No latest checkpoint found."),
        },
        Command::Prune { keep_last } => {
            let deleted = manager.prune_checkpoints(keep_last)?;
            println!("Deleted {deleted} checkpoint file(s).");
        }
    }

    Ok(())
}
