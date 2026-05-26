use std::net::SocketAddr;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use runtime::checkpoint_manager::CheckpointManager;
use runtime::s3_storage::S3StorageConfig;
use runtime::storage::build_grpc_storage_backend;

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
    /// Demonstrate async checkpoint retries after injected write failures.
    #[command(name = "retry-demo")]
    RetryDemo,
    /// Demonstrate failure injection and recovery (in-memory; not production).
    #[command(name = "failure-demo")]
    FailureDemo {
        /// Write a summary file in addition to stdout.
        #[arg(long)]
        summary: Option<PathBuf>,
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
        /// Checkpoint storage backend: local filesystem or S3-compatible object store.
        #[arg(long, default_value = "local")]
        storage: String,
        /// S3 API endpoint (MinIO default: http://127.0.0.1:9000).
        #[arg(long, default_value = "http://127.0.0.1:9000")]
        s3_endpoint_url: String,
        #[arg(long, default_value = "faultline")]
        s3_bucket: String,
        #[arg(long, default_value = "minioadmin")]
        s3_access_key: String,
        #[arg(long, default_value = "minioadmin")]
        s3_secret_key: String,
        #[arg(long, default_value = "us-east-1")]
        s3_region: String,
        /// Key prefix inside the bucket (for example `faultline` → `faultline/checkpoints/...`).
        #[arg(long, default_value = "faultline")]
        s3_prefix: String,
    },
}

fn default_failure_demo_summary_path() -> PathBuf {
    repo_root()
        .join("benchmarks")
        .join("output")
        .join("failure_demo_summary.txt")
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    match cli.command {
        Command::RetryDemo => {
            runtime::retry_demo::run_retry_demo()?;
        }
        Command::FailureDemo { summary } => {
            let summary_path = summary.or_else(|| Some(default_failure_demo_summary_path()));
            runtime::failure_demo::run_failure_demo_and_report(summary_path)?;
        }
        Command::Save { step, data } => {
            let manager = checkpoint_manager();
            let bytes = match data {
                Some(payload) => payload.into_bytes(),
                None => format!("fake checkpoint data for step {step}").into_bytes(),
            };
            manager.save_checkpoint(step, &bytes)?;
        }
        Command::SaveFromFile { step, path } => {
            let manager = checkpoint_manager();
            let path = path.to_string_lossy().to_string();
            let bytes = runtime::service::read_checkpoint_file(&path)
                .map_err(|error| anyhow::anyhow!(error))?;
            manager.save_checkpoint(step, &bytes)?;
            println!("saved checkpoint step {step} from file");
        }
        Command::List => {
            let manager = checkpoint_manager();
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
            let manager = checkpoint_manager();
            match manager.latest_checkpoint()? {
                Some(entry) => {
                    println!("latest step: {}", entry.step);
                    println!("path: {}", entry.path);
                }
                None => println!("No latest checkpoint found."),
            }
        }
        Command::LoadLatest => {
            let manager = checkpoint_manager();
            match manager.load_latest()? {
                Some(bytes) => println!("{}", String::from_utf8_lossy(&bytes)),
                None => println!("No latest checkpoint found."),
            }
        }
        Command::Prune { keep_last } => {
            let manager = checkpoint_manager();
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
            storage,
            s3_endpoint_url,
            s3_bucket,
            s3_access_key,
            s3_secret_key,
            s3_region,
            s3_prefix,
        } => {
            let addr: SocketAddr = addr
                .parse()
                .with_context(|| format!("invalid --addr value: {addr}"))?;
            if storage == "s3" {
                eprintln!(
                    "Faultline gRPC using S3 storage endpoint={s3_endpoint_url} bucket={s3_bucket} prefix={s3_prefix}"
                );
            }
            let s3_config = if storage == "s3" {
                Some(S3StorageConfig {
                    endpoint_url: s3_endpoint_url,
                    bucket: s3_bucket,
                    access_key: s3_access_key,
                    secret_key: s3_secret_key,
                    region: s3_region,
                    prefix: s3_prefix,
                })
            } else {
                None
            };
            let checkpoint_storage = build_grpc_storage_backend(
                &storage,
                repo_root().join("checkpoints"),
                s3_config,
            )?;
            let rt = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()
                .context("failed to start tokio runtime for gRPC")?;
            rt.block_on(runtime::grpc_service::run_grpc_server(
                addr,
                checkpoint_storage,
                repo_root().join("datasets"),
                repo_root().join("runs"),
                queue_capacity,
                write_delay_ms,
            ))?;
        }
    }

    Ok(())
}
