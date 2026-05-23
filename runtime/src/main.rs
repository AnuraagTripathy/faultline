use std::net::SocketAddr;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
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

fn checkpoint_manager_with_delay(write_delay_ms: u64) -> CheckpointManager {
    CheckpointManager::new_with_delay(
        repo_root().join("checkpoints"),
        "checkpoints",
        write_delay_ms,
    )
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
    /// Save a checkpoint from a file on disk.
    #[command(name = "save-from-file")]
    SaveFromFile {
        step: u64,
        path: PathBuf,
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
    /// Run a long-lived JSON line checkpoint service on stdin/stdout.
    Serve {
        /// Artificial per-save delay in milliseconds (simulates slow storage).
        #[arg(long, default_value_t = 0)]
        write_delay_ms: u64,
    },
    /// Run a long-lived async JSON line service with a bounded checkpoint queue.
    #[command(name = "serve-async")]
    ServeAsync {
        /// Maximum number of checkpoint jobs waiting in the queue.
        #[arg(long, default_value_t = runtime::async_service::default_queue_capacity())]
        queue_capacity: usize,
        /// Artificial per-save delay in milliseconds (simulates slow storage).
        #[arg(long, default_value_t = 0)]
        write_delay_ms: u64,
    },
    /// Run a gRPC checkpoint service (optional transport alongside JSON stdin/stdout).
    #[command(name = "serve-grpc")]
    ServeGrpc {
        /// Socket address to bind (for example 127.0.0.1:50051).
        #[arg(long, default_value = "127.0.0.1:50051")]
        addr: String,
        #[arg(long, default_value_t = runtime::grpc_service::default_queue_capacity())]
        queue_capacity: usize,
        #[arg(long, default_value_t = 0)]
        write_delay_ms: u64,
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
        Command::SaveFromFile { step, path } => {
            let path = path.to_string_lossy().to_string();
            let bytes = runtime::service::read_checkpoint_file(&path)
                .map_err(|error| anyhow::anyhow!(error))?;
            manager.save_checkpoint(step, &bytes)?;
            println!("saved checkpoint step {step} from file");
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
        Command::Serve { write_delay_ms } => {
            let manager = checkpoint_manager_with_delay(write_delay_ms);
            runtime::service::run_service(manager)?;
        }
        Command::ServeAsync {
            queue_capacity,
            write_delay_ms,
        } => {
            let manager = checkpoint_manager_with_delay(write_delay_ms);
            runtime::async_service::run_async_service(manager, queue_capacity)?;
        }
        Command::ServeGrpc {
            addr,
            queue_capacity,
            write_delay_ms,
        } => {
            let addr: SocketAddr = addr
                .parse()
                .with_context(|| format!("invalid --addr value: {addr}"))?;
            let rt = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()
                .context("failed to start tokio runtime for gRPC")?;
            rt.block_on(runtime::grpc_service::run_grpc_server(
                addr,
                repo_root().join("checkpoints"),
                queue_capacity,
                write_delay_ms,
            ))?;
        }
    }

    Ok(())
}
