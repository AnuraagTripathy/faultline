use std::io::{self, BufRead, BufReader, Write};

use serde::Serialize;

use crate::async_runtime::{AsyncCheckpointRuntime, CheckpointJobStatus};
use crate::checkpoint_manager::CheckpointManager;
use crate::metadata::CheckpointEntry;
use crate::runtime_metrics::RuntimeMetrics;
use crate::service::read_checkpoint_file;

const DEFAULT_QUEUE_CAPACITY: usize = 8;

/// Incoming newline-delimited JSON command for the async service.
#[derive(Debug, serde::Deserialize, PartialEq, Eq)]
#[serde(tag = "cmd", rename_all = "snake_case")]
pub enum AsyncServiceCommand {
    #[serde(rename = "enqueue_from_file")]
    EnqueueFromFile { step: u64, path: String },
    #[serde(rename = "try_enqueue_from_file")]
    TryEnqueueFromFile { step: u64, path: String },
    #[serde(rename = "enqueue_worker_from_file")]
    EnqueueWorkerFromFile {
        worker_id: u64,
        local_step: u64,
        step: u64,
        path: String,
    },
    #[serde(rename = "latest_for_worker")]
    LatestForWorker { worker_id: u64 },
    #[serde(rename = "status")]
    Status { step: u64 },
    #[serde(rename = "metrics")]
    Metrics,
    #[serde(rename = "prune_per_worker")]
    PrunePerWorker { keep_last_per_worker: usize },
    #[serde(rename = "shutdown")]
    Shutdown,
}

/// JSON response written to stdout (one line per command).
#[derive(Debug, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub struct AsyncServiceResponse {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub queued: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metrics: Option<MetricsResponse>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub checkpoint: Option<Option<CheckpointEntry>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Option<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub deleted: Option<usize>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub struct MetricsResponse {
    pub total_enqueued: u64,
    pub total_committed: u64,
    pub total_failed: u64,
    pub total_dropped: u64,
    pub total_bytes_written: u64,
    pub total_write_time_ms: u128,
    pub average_write_time_ms: Option<f64>,
}

impl AsyncServiceResponse {
    pub fn error(message: impl Into<String>) -> Self {
        Self {
            ok: false,
            message: None,
            error: Some(message.into()),
            status: None,
            queued: None,
            metrics: None,
            checkpoint: None,
            data: None,
            deleted: None,
        }
    }

    pub fn pruned(deleted: usize) -> Self {
        Self {
            ok: true,
            message: None,
            error: None,
            status: None,
            queued: None,
            metrics: None,
            checkpoint: None,
            data: None,
            deleted: Some(deleted),
        }
    }

    pub fn queued(step: u64) -> Self {
        Self {
            ok: true,
            message: Some(format!("queued checkpoint step {step}")),
            error: None,
            status: None,
            queued: None,
            metrics: None,
            checkpoint: None,
            data: None,
            deleted: None,
        }
    }

    pub fn queued_worker(worker_id: u64, local_step: u64, step: u64) -> Self {
        Self {
            ok: true,
            message: Some(format!(
                "queued worker {worker_id} checkpoint local_step {local_step} (step {step})"
            )),
            error: None,
            status: None,
            queued: None,
            metrics: None,
            checkpoint: None,
            data: None,
            deleted: None,
        }
    }

    pub fn try_queued(queued: bool) -> Self {
        Self {
            ok: true,
            message: None,
            error: None,
            status: None,
            queued: Some(queued),
            metrics: None,
            checkpoint: None,
            data: None,
            deleted: None,
        }
    }

    pub fn latest(checkpoint: Option<CheckpointEntry>) -> Self {
        Self {
            ok: true,
            message: None,
            error: None,
            status: None,
            queued: None,
            metrics: None,
            checkpoint: Some(checkpoint),
            data: None,
            deleted: None,
        }
    }

    pub fn status(status: impl Into<String>) -> Self {
        Self {
            ok: true,
            message: None,
            error: None,
            status: Some(status.into()),
            queued: None,
            metrics: None,
            checkpoint: None,
            data: None,
            deleted: None,
        }
    }

    pub fn metrics(metrics: RuntimeMetrics) -> Self {
        Self {
            ok: true,
            message: None,
            error: None,
            status: None,
            queued: None,
            metrics: Some(MetricsResponse::from(metrics)),
            checkpoint: None,
            data: None,
            deleted: None,
        }
    }

    pub fn shutting_down() -> Self {
        Self {
            ok: true,
            message: Some("shutting down".to_string()),
            error: None,
            status: None,
            queued: None,
            metrics: None,
            checkpoint: None,
            data: None,
            deleted: None,
        }
    }
}

impl From<RuntimeMetrics> for MetricsResponse {
    fn from(metrics: RuntimeMetrics) -> Self {
        Self {
            total_enqueued: metrics.total_enqueued,
            total_committed: metrics.total_committed,
            total_failed: metrics.total_failed,
            total_dropped: metrics.total_dropped,
            total_bytes_written: metrics.total_bytes_written,
            total_write_time_ms: metrics.total_write_time_ms,
            average_write_time_ms: metrics.average_write_time_ms(),
        }
    }
}

pub fn format_job_status(status: CheckpointJobStatus) -> String {
    match status {
        CheckpointJobStatus::Queued => "Queued".to_string(),
        CheckpointJobStatus::Writing => "Writing".to_string(),
        CheckpointJobStatus::Committed => "Committed".to_string(),
        CheckpointJobStatus::Dropped => "Dropped".to_string(),
        CheckpointJobStatus::Failed(message) => format!("Failed({message})"),
    }
}

/// Handle one parsed async command. Returns (response, should_shutdown).
pub async fn handle_async_command(
    runtime: &AsyncCheckpointRuntime,
    command: AsyncServiceCommand,
) -> (AsyncServiceResponse, bool) {
    match command {
        AsyncServiceCommand::EnqueueFromFile { step, path } => {
            match read_checkpoint_file(&path) {
                Ok(bytes) => match runtime.enqueue_checkpoint(step, bytes).await {
                    Ok(()) => (AsyncServiceResponse::queued(step), false),
                    Err(error) => (AsyncServiceResponse::error(error.to_string()), false),
                },
                Err(error) => (AsyncServiceResponse::error(error), false),
            }
        }
        AsyncServiceCommand::TryEnqueueFromFile { step, path } => {
            match read_checkpoint_file(&path) {
                Ok(bytes) => match runtime.try_enqueue_checkpoint(step, bytes).await {
                    Ok(queued) => (AsyncServiceResponse::try_queued(queued), false),
                    Err(error) => (AsyncServiceResponse::error(error.to_string()), false),
                },
                Err(error) => (AsyncServiceResponse::error(error), false),
            }
        }
        AsyncServiceCommand::EnqueueWorkerFromFile {
            worker_id,
            local_step,
            step,
            path,
        } => match read_checkpoint_file(&path) {
            Ok(bytes) => {
                match runtime
                    .enqueue_worker_checkpoint(worker_id, local_step, step, bytes)
                    .await
                {
                    Ok(()) => (AsyncServiceResponse::queued_worker(worker_id, local_step, step), false),
                    Err(error) => (AsyncServiceResponse::error(error.to_string()), false),
                }
            }
            Err(error) => (AsyncServiceResponse::error(error), false),
        },
        AsyncServiceCommand::LatestForWorker { worker_id } => {
            match runtime.latest_checkpoint_for_worker(worker_id) {
                Ok(checkpoint) => (AsyncServiceResponse::latest(checkpoint), false),
                Err(error) => (AsyncServiceResponse::error(error.to_string()), false),
            }
        }
        AsyncServiceCommand::Status { step } => {
            match runtime.checkpoint_status(step).await {
                Some(status) => (
                    AsyncServiceResponse::status(format_job_status(status)),
                    false,
                ),
                None => (
                    AsyncServiceResponse::error(format!("no status for step {step}")),
                    false,
                ),
            }
        }
        AsyncServiceCommand::Metrics => {
            let metrics = runtime.metrics().await;
            (AsyncServiceResponse::metrics(metrics), false)
        }
        AsyncServiceCommand::PrunePerWorker {
            keep_last_per_worker,
        } => match runtime.prune_checkpoints_per_worker(keep_last_per_worker) {
            Ok(deleted) => (AsyncServiceResponse::pruned(deleted), false),
            Err(error) => (AsyncServiceResponse::error(error.to_string()), false),
        },
        AsyncServiceCommand::Shutdown => (AsyncServiceResponse::shutting_down(), true),
    }
}

pub async fn handle_async_line(
    runtime: &AsyncCheckpointRuntime,
    line: &str,
) -> (AsyncServiceResponse, bool) {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return (AsyncServiceResponse::error("empty command line"), false);
    }

    match serde_json::from_str::<AsyncServiceCommand>(trimmed) {
        Ok(command) => handle_async_command(runtime, command).await,
        Err(error) => {
            let message = if is_unknown_command_error(&error) {
                "unknown command".to_string()
            } else {
                format!("invalid JSON: {error}")
            };
            (AsyncServiceResponse::error(message), false)
        }
    }
}

fn is_unknown_command_error(error: &serde_json::Error) -> bool {
    error.is_data() && error.to_string().contains("unknown variant")
}

pub fn write_async_response(
    writer: &mut impl Write,
    response: &AsyncServiceResponse,
) -> io::Result<()> {
    let json = serde_json::to_string(response).map_err(io::Error::other)?;
    writeln!(writer, "{json}")?;
    writer.flush()?;
    Ok(())
}

/// Run the long-lived async JSON line service on stdin/stdout.
pub fn run_async_service(
    manager: CheckpointManager,
    queue_capacity: usize,
) -> io::Result<()> {
    let tokio_runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .worker_threads(2)
        .build()
        .map_err(io::Error::other)?;

    let mut async_runtime = Some(tokio_runtime.block_on(AsyncCheckpointRuntime::start(
        manager,
        queue_capacity,
    )));

    let stdin = io::stdin();
    let mut stdout = io::stdout();
    let reader = BufReader::new(stdin.lock());

    for line in reader.lines() {
        let line = match line {
            Ok(line) => line,
            Err(error) => {
                eprintln!("failed to read stdin: {error}");
                break;
            }
        };

        let runtime_ref = async_runtime
            .as_ref()
            .expect("async runtime should be running");
        let (response, shutdown) = tokio_runtime.block_on(handle_async_line(runtime_ref, &line));
        write_async_response(&mut stdout, &response)?;

        if shutdown {
            if let Some(runtime) = async_runtime.take() {
                tokio_runtime
                    .block_on(runtime.shutdown())
                    .map_err(io::Error::other)?;
            }
            break;
        }
    }

    Ok(())
}

pub fn default_queue_capacity() -> usize {
    DEFAULT_QUEUE_CAPACITY
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    fn manager_in_temp_dir(dir: &Path) -> CheckpointManager {
        CheckpointManager::new(dir.to_path_buf(), "checkpoints")
    }

    fn block_on<F: std::future::Future>(future: F) -> F::Output {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
            .block_on(future)
    }

    #[test]
    fn enqueue_worker_from_file_queues_worker_checkpoint() {
        let temp = tempfile::tempdir().unwrap();
        let manager = manager_in_temp_dir(temp.path());
        let payload_file = temp.path().join("worker_payload.bin");
        std::fs::write(&payload_file, b"worker async").unwrap();

        block_on(async {
            let runtime = AsyncCheckpointRuntime::start(manager, 4).await;
            let path_json = serde_json::to_string(&payload_file.to_string_lossy()).unwrap();
            let line = format!(
                r#"{{"cmd":"enqueue_worker_from_file","worker_id":2,"local_step":7,"step":2000007,"path":{path_json}}}"#
            );
            let (response, _) = handle_async_line(&runtime, &line).await;
            assert!(response.ok);
            runtime.shutdown().await.unwrap();
        });

        let manager = manager_in_temp_dir(temp.path());
        let entry = manager
            .latest_checkpoint_for_worker(2)
            .expect("lookup failed")
            .expect("expected worker checkpoint");
        assert_eq!(entry.worker_id, Some(2));
        assert_eq!(entry.local_step, Some(7));
    }

    #[test]
    fn enqueue_from_file_queues_checkpoint() {
        let temp = tempfile::tempdir().unwrap();
        let manager = manager_in_temp_dir(temp.path());
        let payload_file = temp.path().join("payload.bin");
        std::fs::write(&payload_file, b"async payload").unwrap();

        block_on(async {
            let runtime = AsyncCheckpointRuntime::start(manager, 4).await;
            let path_json = serde_json::to_string(&payload_file.to_string_lossy()).unwrap();
            let line = format!(r#"{{"cmd":"enqueue_from_file","step":2,"path":{path_json}}}"#);

            let (response, shutdown) = handle_async_line(&runtime, &line).await;
            assert!(!shutdown);
            assert!(response.ok);
            assert_eq!(
                response.message.as_deref(),
                Some("queued checkpoint step 2")
            );

            runtime.shutdown().await.unwrap();
        });
    }

    #[test]
    fn try_enqueue_from_file_reports_queue_full() {
        let temp = tempfile::tempdir().unwrap();
        let manager = manager_in_temp_dir(temp.path());

        block_on(async {
            let runtime = AsyncCheckpointRuntime::start(manager, 1).await;
            let path = temp.path().join("one.bin");
            std::fs::write(&path, b"one").unwrap();
            let path_json = serde_json::to_string(&path.to_string_lossy()).unwrap();

            let first = format!(r#"{{"cmd":"try_enqueue_from_file","step":1,"path":{path_json}}}"#);
            let (response, _) = handle_async_line(&runtime, &first).await;
            assert_eq!(response.queued, Some(true));

            let second =
                format!(r#"{{"cmd":"try_enqueue_from_file","step":2,"path":{path_json}}}"#);
            let (response, _) = handle_async_line(&runtime, &second).await;
            assert_eq!(response.queued, Some(false));

            runtime.shutdown().await.unwrap();
        });
    }

    #[test]
    fn status_and_metrics_after_commit() {
        let temp = tempfile::tempdir().unwrap();
        let manager = manager_in_temp_dir(temp.path());
        let payload_file = temp.path().join("payload.bin");
        std::fs::write(&payload_file, b"metrics test").unwrap();

        block_on(async {
            let runtime = AsyncCheckpointRuntime::start(manager, 4).await;
            let statuses = runtime.status_map();
            let metrics_map = runtime.metrics_map();
            let path_json = serde_json::to_string(&payload_file.to_string_lossy()).unwrap();
            let enqueue =
                format!(r#"{{"cmd":"enqueue_from_file","step":5,"path":{path_json}}}"#);
            handle_async_line(&runtime, &enqueue).await;

            runtime.shutdown().await.unwrap();

            let status = statuses.lock().await.get(&5).cloned();
            assert_eq!(status, Some(CheckpointJobStatus::Committed));

            let metrics = metrics_map.lock().await.clone();
            assert_eq!(metrics.total_committed, 1);
            assert_eq!(metrics.total_enqueued, 1);
        });
    }

    #[test]
    fn format_job_status_variants() {
        assert_eq!(format_job_status(CheckpointJobStatus::Queued), "Queued");
        assert_eq!(
            format_job_status(CheckpointJobStatus::Failed("disk".to_string())),
            "Failed(disk)"
        );
    }
}
