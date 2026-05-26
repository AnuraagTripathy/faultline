use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use tokio::sync::{mpsc, oneshot, Mutex};
use tokio::task::JoinHandle;

use crate::checkpoint_manager::CheckpointManager;
use crate::event_log::{record_event, EventLevel, EventLog, RuntimeEventInput};
use crate::metadata::CheckpointEntry;
use crate::runtime_metrics::RuntimeMetrics;

/// One checkpoint write request sent through the async queue.
pub struct CheckpointJob {
    pub step: u64,
    pub data: Vec<u8>,
    pub worker_id: Option<u64>,
    pub local_step: Option<u64>,
}

/// Runtime-only status for a checkpoint job, keyed by training step.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CheckpointJobStatus {
    Queued,
    Writing,
    Retrying(u32),
    Committed,
    Failed(String),
    FailedPermanent(String),
    Dropped,
}

/// Retry policy for transient checkpoint write failures in the async writer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RetryConfig {
    pub max_retries: u32,
    pub retry_backoff_ms: u64,
    pub exponential_backoff: bool,
}

impl Default for RetryConfig {
    fn default() -> Self {
        Self {
            max_retries: 0,
            retry_backoff_ms: 100,
            exponential_backoff: false,
        }
    }
}

impl RetryConfig {
    pub fn backoff_ms(&self, retry_index: u32) -> u64 {
        if self.exponential_backoff {
            self.retry_backoff_ms.saturating_mul(1u64 << retry_index.min(31))
        } else {
            self.retry_backoff_ms
        }
    }
}

type StatusMap = Arc<Mutex<HashMap<u64, CheckpointJobStatus>>>;
type MetricsMap = Arc<Mutex<RuntimeMetrics>>;

/// Queues checkpoint jobs and writes them on a background Tokio task.
pub struct AsyncCheckpointRuntime {
    sender: mpsc::Sender<CheckpointJob>,
    writer_handle: JoinHandle<()>,
    statuses: StatusMap,
    metrics: MetricsMap,
    manager: Arc<CheckpointManager>,
    event_log: Option<Arc<EventLog>>,
}

impl AsyncCheckpointRuntime {
    /// Start the background writer with a bounded queue (no retries by default).
    pub async fn start(manager: CheckpointManager, queue_capacity: usize) -> Self {
        Self::start_with_retry_config(manager, queue_capacity, RetryConfig::default()).await
    }

    /// Start the background writer with an explicit retry policy.
    pub async fn start_with_retry_config(
        manager: CheckpointManager,
        queue_capacity: usize,
        retry_config: RetryConfig,
    ) -> Self {
        Self::spawn(manager, queue_capacity, retry_config, None).await
    }

    /// Try to queue a checkpoint without waiting. Returns `Ok(false)` when the queue is full.
    pub async fn try_enqueue_checkpoint(&self, step: u64, data: Vec<u8>) -> Result<bool> {
        self.try_enqueue_job(CheckpointJob {
            step,
            data,
            worker_id: None,
            local_step: None,
        })
        .await
    }

    pub async fn try_enqueue_worker_checkpoint(
        &self,
        worker_id: u64,
        local_step: u64,
        global_step: u64,
        data: Vec<u8>,
    ) -> Result<bool> {
        self.try_enqueue_job(CheckpointJob {
            step: global_step,
            data,
            worker_id: Some(worker_id),
            local_step: Some(local_step),
        })
        .await
    }

    async fn try_enqueue_job(&self, job: CheckpointJob) -> Result<bool> {
        let step = job.step;
        let worker_id = job.worker_id;
        let local_step = job.local_step;
        match self.sender.try_send(job) {
            Ok(()) => {
                record_enqueued(&self.metrics).await;
                set_status(&self.statuses, step, CheckpointJobStatus::Queued).await;
                record_event(
                    &self.event_log,
                    checkpoint_queued_event(step, worker_id, local_step),
                );
                Ok(true)
            }
            Err(mpsc::error::TrySendError::Full(_)) => {
                record_dropped(&self.metrics).await;
                set_status(&self.statuses, step, CheckpointJobStatus::Dropped).await;
                Ok(false)
            }
            Err(mpsc::error::TrySendError::Closed(_)) => {
                anyhow::bail!("checkpoint writer is shut down")
            }
        }
    }

    /// Queue a checkpoint write. Waits for queue space when the queue is full.
    pub async fn enqueue_checkpoint(&self, step: u64, data: Vec<u8>) -> Result<()> {
        self.enqueue_job(CheckpointJob {
            step,
            data,
            worker_id: None,
            local_step: None,
        })
        .await
    }

    pub async fn enqueue_worker_checkpoint(
        &self,
        worker_id: u64,
        local_step: u64,
        global_step: u64,
        data: Vec<u8>,
    ) -> Result<()> {
        self.enqueue_job(CheckpointJob {
            step: global_step,
            data,
            worker_id: Some(worker_id),
            local_step: Some(local_step),
        })
        .await
    }

    async fn enqueue_job(&self, job: CheckpointJob) -> Result<()> {
        let step = job.step;
        let worker_id = job.worker_id;
        let local_step = job.local_step;
        self.sender
            .send(job)
            .await
            .context("checkpoint writer is shut down")?;
        record_enqueued(&self.metrics).await;
        set_status(&self.statuses, step, CheckpointJobStatus::Queued).await;
        record_event(
            &self.event_log,
            checkpoint_queued_event(step, worker_id, local_step),
        );
        Ok(())
    }

    pub fn latest_checkpoint_for_worker(
        &self,
        worker_id: u64,
    ) -> Result<Option<CheckpointEntry>> {
        self.manager.latest_checkpoint_for_worker(worker_id)
    }

    /// Prune worker-aware checkpoints. Prefer calling after the queue has drained;
    /// concurrent writes may race with metadata updates.
    pub fn prune_checkpoints_per_worker(&self, keep_last_per_worker: usize) -> Result<usize> {
        self.manager
            .prune_checkpoints_per_worker(keep_last_per_worker)
    }

    /// Return the latest known status for one training step.
    pub async fn checkpoint_status(&self, step: u64) -> Option<CheckpointJobStatus> {
        self.statuses.lock().await.get(&step).cloned()
    }

    /// Return a copy of all tracked checkpoint job statuses.
    pub async fn all_statuses(&self) -> HashMap<u64, CheckpointJobStatus> {
        self.statuses.lock().await.clone()
    }

    /// Return a copy of current runtime metrics.
    pub async fn metrics(&self) -> RuntimeMetrics {
        self.metrics.lock().await.clone()
    }

    /// Clone the shared status map (still readable after `shutdown` if you keep this handle).
    pub fn status_map(&self) -> StatusMap {
        Arc::clone(&self.statuses)
    }

    /// Clone the shared metrics map (still readable after `shutdown` if you keep this handle).
    pub fn metrics_map(&self) -> MetricsMap {
        Arc::clone(&self.metrics)
    }

    /// Shared checkpoint manager used by the background writer (and gRPC sync saves).
    pub fn shared_manager(&self) -> Arc<CheckpointManager> {
        Arc::clone(&self.manager)
    }

    /// Close the queue and wait until all pending jobs finish.
    pub async fn shutdown(self) -> Result<()> {
        drop(self.sender);

        self.writer_handle
            .await
            .context("background writer task panicked")?;

        Ok(())
    }

    async fn spawn(
        manager: CheckpointManager,
        queue_capacity: usize,
        retry_config: RetryConfig,
        writer_gate: Option<oneshot::Receiver<()>>,
    ) -> Self {
        let (sender, mut receiver) = mpsc::channel::<CheckpointJob>(queue_capacity);
        let event_log = manager.event_log();
        let manager = Arc::new(manager);
        let reader_manager = Arc::clone(&manager);
        let statuses: StatusMap = Arc::new(Mutex::new(HashMap::new()));
        let metrics: MetricsMap = Arc::new(Mutex::new(RuntimeMetrics::default()));
        let writer_statuses = Arc::clone(&statuses);
        let writer_metrics = Arc::clone(&metrics);
        let writer_event_log = event_log.clone();

        let writer_handle = tokio::spawn(async move {
            if let Some(gate) = writer_gate {
                let _ = gate.await;
            }

            while let Some(job) = receiver.recv().await {
                let step = job.step;
                let worker_id = job.worker_id;
                let local_step = job.local_step;
                set_status(&writer_statuses, step, CheckpointJobStatus::Writing).await;

                eprintln!("Queued checkpoint step {step}");
                eprintln!("Writing checkpoint step {step}");

                let mut failures_so_far = 0u32;
                loop {
                    let manager = Arc::clone(&manager);
                    let data = job.data.clone();
                    let byte_len = data.len() as u64;
                    let save_result = tokio::task::spawn_blocking(move || {
                        let started = Instant::now();
                        let result = match (worker_id, local_step) {
                            (Some(worker_id), Some(local_step)) => manager
                                .save_worker_checkpoint(worker_id, local_step, step, &data),
                            _ => manager.save_checkpoint(step, &data),
                        };
                        (result, started.elapsed(), byte_len)
                    })
                    .await;

                    let status = match save_result {
                        Ok((Ok(()), elapsed, bytes)) => {
                            record_committed(&writer_metrics, bytes, elapsed.as_millis()).await;
                            eprintln!("Committed checkpoint step {step}");
                            record_event(
                                &writer_event_log,
                                checkpoint_committed_event(step, worker_id, local_step),
                            );
                            CheckpointJobStatus::Committed
                        }
                        Ok((Err(error), _, _)) => {
                            record_failed(&writer_metrics).await;
                            let message = error.to_string();
                            record_event(
                                &writer_event_log,
                                checkpoint_failed_event(step, worker_id, &message),
                            );
                            if failures_so_far < retry_config.max_retries {
                                failures_so_far += 1;
                                record_retry(&writer_metrics).await;
                                record_event(
                                    &writer_event_log,
                                    checkpoint_retrying_event(
                                        step,
                                        worker_id,
                                        failures_so_far,
                                        retry_config.max_retries,
                                    ),
                                );
                                set_status(
                                    &writer_statuses,
                                    step,
                                    CheckpointJobStatus::Retrying(failures_so_far),
                                )
                                .await;
                                let delay = retry_config.backoff_ms(failures_so_far - 1);
                                tokio::time::sleep(Duration::from_millis(delay)).await;
                                set_status(
                                    &writer_statuses,
                                    step,
                                    CheckpointJobStatus::Writing,
                                )
                                .await;
                                eprintln!(
                                    "Retrying checkpoint step {step} (attempt {failures_so_far})"
                                );
                                continue;
                            }
                            record_permanent_failure(&writer_metrics).await;
                            record_event(
                                &writer_event_log,
                                checkpoint_failed_permanent_event(step, worker_id, &message),
                            );
                            CheckpointJobStatus::FailedPermanent(message)
                        }
                        Err(join_error) => {
                            record_failed(&writer_metrics).await;
                            let message = join_error.to_string();
                            record_event(
                                &writer_event_log,
                                checkpoint_failed_event(step, worker_id, &message),
                            );
                            CheckpointJobStatus::Failed(message)
                        }
                    };

                    set_status(&writer_statuses, step, status).await;
                    break;
                }
            }
        });

        Self {
            sender,
            writer_handle,
            statuses,
            metrics,
            manager: reader_manager,
            event_log,
        }
    }

    /// Test helper: start runtime but keep the writer paused until the gate is opened.
    #[cfg(test)]
    async fn start_with_writer_gate(
        manager: CheckpointManager,
        queue_capacity: usize,
        writer_gate: oneshot::Receiver<()>,
    ) -> Self {
        Self::spawn(manager, queue_capacity, RetryConfig::default(), Some(writer_gate)).await
    }
}

async fn set_status(
    statuses: &StatusMap,
    step: u64,
    status: CheckpointJobStatus,
) {
    statuses.lock().await.insert(step, status);
}

async fn record_enqueued(metrics: &MetricsMap) {
    metrics.lock().await.total_enqueued += 1;
}

async fn record_dropped(metrics: &MetricsMap) {
    metrics.lock().await.total_dropped += 1;
}

async fn record_committed(metrics: &MetricsMap, bytes: u64, elapsed_ms: u128) {
    let mut metrics = metrics.lock().await;
    metrics.total_committed += 1;
    metrics.total_bytes_written += bytes;
    metrics.total_write_time_ms += elapsed_ms;
}

async fn record_failed(metrics: &MetricsMap) {
    metrics.lock().await.total_failed += 1;
}

async fn record_retry(metrics: &MetricsMap) {
    metrics.lock().await.total_retries += 1;
}

async fn record_permanent_failure(metrics: &MetricsMap) {
    metrics.lock().await.total_permanent_failures += 1;
}

fn checkpoint_queued_event(
    step: u64,
    worker_id: Option<u64>,
    local_step: Option<u64>,
) -> RuntimeEventInput {
    let message = match (worker_id, local_step) {
        (Some(worker_id), Some(local_step)) => {
            format!(
                "worker {worker_id} checkpoint local_step {local_step} (step {step}) queued"
            )
        }
        _ => format!("checkpoint step {step} queued"),
    };
    let mut input = RuntimeEventInput::new(EventLevel::Info, "checkpoint_queued", message).step(step);
    if let Some(worker_id) = worker_id {
        input = input.worker_id(worker_id);
    }
    input
}

fn checkpoint_committed_event(
    step: u64,
    worker_id: Option<u64>,
    local_step: Option<u64>,
) -> RuntimeEventInput {
    let message = match (worker_id, local_step) {
        (Some(worker_id), Some(local_step)) => format!(
            "worker {worker_id} checkpoint local_step {local_step} (step {step}) committed"
        ),
        _ => format!("checkpoint step {step} committed"),
    };
    let mut input =
        RuntimeEventInput::new(EventLevel::Info, "checkpoint_committed", message).step(step);
    if let Some(worker_id) = worker_id {
        input = input.worker_id(worker_id);
    }
    input
}

fn checkpoint_retrying_event(
    step: u64,
    worker_id: Option<u64>,
    attempt: u32,
    max_retries: u32,
) -> RuntimeEventInput {
    let message = match worker_id {
        Some(worker_id) => format!(
            "worker {worker_id} checkpoint step {step} retrying (attempt {attempt}/{max_retries})"
        ),
        None => format!("checkpoint step {step} retrying (attempt {attempt}/{max_retries})"),
    };
    let mut input =
        RuntimeEventInput::new(EventLevel::Warn, "checkpoint_retrying", message).step(step);
    if let Some(worker_id) = worker_id {
        input = input.worker_id(worker_id);
    }
    input
}

fn checkpoint_failed_permanent_event(
    step: u64,
    worker_id: Option<u64>,
    error: &str,
) -> RuntimeEventInput {
    let message = match worker_id {
        Some(worker_id) => format!(
            "worker {worker_id} checkpoint step {step} permanently failed: {error}"
        ),
        None => format!("checkpoint step {step} permanently failed: {error}"),
    };
    let mut input = RuntimeEventInput::new(EventLevel::Error, "checkpoint_failed_permanent", message)
        .step(step);
    if let Some(worker_id) = worker_id {
        input = input.worker_id(worker_id);
    }
    input
}

fn checkpoint_failed_event(
    step: u64,
    worker_id: Option<u64>,
    error: &str,
) -> RuntimeEventInput {
    let message = match worker_id {
        Some(worker_id) => {
            format!("worker {worker_id} checkpoint step {step} failed: {error}")
        }
        None => format!("checkpoint step {step} failed: {error}"),
    };
    let mut input = RuntimeEventInput::new(EventLevel::Error, "checkpoint_failed", message).step(step);
    if let Some(worker_id) = worker_id {
        input = input.worker_id(worker_id);
    }
    input
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::{Path, PathBuf};

    fn manager_in_temp_dir(dir: &Path) -> CheckpointManager {
        CheckpointManager::new(dir.to_path_buf(), "checkpoints")
    }

    fn checkpoint_file(dir: &Path, step: u64) -> PathBuf {
        dir.join(format!("step_{step:04}.ckpt"))
    }

    #[tokio::test]
    async fn metrics_track_enqueued_and_committed_checkpoints() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        let data_one = b"step one".to_vec();
        let data_two = b"step two bytes".to_vec();
        let expected_bytes = data_one.len() as u64 + data_two.len() as u64;

        let runtime = AsyncCheckpointRuntime::start(manager, 4).await;
        let metrics = runtime.metrics_map();
        runtime.enqueue_checkpoint(1, data_one).await?;
        runtime.enqueue_checkpoint(2, data_two).await?;
        runtime.shutdown().await?;

        let metrics = metrics.lock().await;
        assert_eq!(metrics.total_enqueued, 2);
        assert_eq!(metrics.total_committed, 2);
        assert_eq!(metrics.total_failed, 0);
        assert_eq!(metrics.total_dropped, 0);
        assert_eq!(metrics.total_bytes_written, expected_bytes);

        Ok(())
    }

    #[tokio::test]
    async fn metrics_track_dropped_try_enqueue() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());
        let (gate_tx, gate_rx) = oneshot::channel();

        let runtime = AsyncCheckpointRuntime::start_with_writer_gate(manager, 1, gate_rx).await;
        let metrics = runtime.metrics_map();

        assert!(runtime.try_enqueue_checkpoint(1, b"step one".to_vec()).await?);
        assert!(!runtime.try_enqueue_checkpoint(2, b"step two".to_vec()).await?);

        assert_eq!(metrics.lock().await.total_dropped, 1);

        let _ = gate_tx.send(());
        runtime.shutdown().await?;

        Ok(())
    }

    #[tokio::test]
    async fn average_write_time_available_after_commit() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        let runtime = AsyncCheckpointRuntime::start(manager, 2).await;
        let metrics = runtime.metrics_map();
        runtime.enqueue_checkpoint(1, b"step one".to_vec()).await?;
        runtime.shutdown().await?;

        let metrics = metrics.lock().await;
        assert_eq!(metrics.total_committed, 1);
        assert!(metrics.average_write_time_ms().is_some());

        Ok(())
    }

    #[tokio::test]
    async fn status_is_committed_after_enqueue_and_shutdown() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        let runtime = AsyncCheckpointRuntime::start(manager, 2).await;
        let statuses = runtime.status_map();
        runtime.enqueue_checkpoint(1, b"step one".to_vec()).await?;
        runtime.shutdown().await?;

        assert_eq!(
            statuses.lock().await.get(&1),
            Some(&CheckpointJobStatus::Committed)
        );

        Ok(())
    }

    #[tokio::test]
    async fn try_enqueue_full_sets_dropped_status() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());
        let (gate_tx, gate_rx) = oneshot::channel();

        let runtime = AsyncCheckpointRuntime::start_with_writer_gate(manager, 1, gate_rx).await;

        assert!(runtime.try_enqueue_checkpoint(1, b"step one".to_vec()).await?);
        assert!(!runtime.try_enqueue_checkpoint(2, b"step two".to_vec()).await?);

        assert_eq!(
            runtime.checkpoint_status(2).await,
            Some(CheckpointJobStatus::Dropped)
        );

        let _ = gate_tx.send(());
        runtime.shutdown().await?;

        Ok(())
    }

    #[tokio::test]
    async fn all_statuses_committed_after_multiple_enqueues() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        let runtime = AsyncCheckpointRuntime::start(manager, 4).await;
        runtime.enqueue_checkpoint(1, b"step one".to_vec()).await?;
        runtime.enqueue_checkpoint(2, b"step two".to_vec()).await?;
        runtime.enqueue_checkpoint(3, b"step three".to_vec()).await?;
        let statuses = runtime.status_map();
        runtime.shutdown().await?;

        let statuses = statuses.lock().await;
        assert_eq!(statuses.len(), 3);
        assert_eq!(statuses.get(&1), Some(&CheckpointJobStatus::Committed));
        assert_eq!(statuses.get(&2), Some(&CheckpointJobStatus::Committed));
        assert_eq!(statuses.get(&3), Some(&CheckpointJobStatus::Committed));

        Ok(())
    }

    #[tokio::test]
    async fn try_enqueue_succeeds_when_queue_has_room() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        let runtime = AsyncCheckpointRuntime::start(manager, 1).await;
        assert!(runtime.try_enqueue_checkpoint(1, b"step one".to_vec()).await?);

        runtime.shutdown().await?;
        assert!(checkpoint_file(temp.path(), 1).is_file());

        Ok(())
    }

    #[tokio::test]
    async fn try_enqueue_returns_false_when_queue_is_full() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());
        let (gate_tx, gate_rx) = oneshot::channel();

        let runtime = AsyncCheckpointRuntime::start_with_writer_gate(manager, 1, gate_rx).await;

        assert!(runtime.try_enqueue_checkpoint(1, b"step one".to_vec()).await?);
        assert!(!runtime.try_enqueue_checkpoint(2, b"step two".to_vec()).await?);

        let _ = gate_tx.send(());
        runtime.shutdown().await?;

        Ok(())
    }

    #[tokio::test]
    async fn blocking_enqueue_writes_all_jobs_after_shutdown() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        let runtime = AsyncCheckpointRuntime::start(manager, 1).await;
        runtime.enqueue_checkpoint(1, b"step one".to_vec()).await?;
        runtime.enqueue_checkpoint(2, b"step two".to_vec()).await?;
        runtime.shutdown().await?;

        assert!(checkpoint_file(temp.path(), 1).is_file());
        assert!(checkpoint_file(temp.path(), 2).is_file());

        Ok(())
    }

    #[tokio::test]
    async fn enqueue_one_checkpoint_then_shutdown_writes_file() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        let runtime = AsyncCheckpointRuntime::start(manager, 4).await;
        runtime
            .enqueue_checkpoint(1, b"async step one".to_vec())
            .await?;
        runtime.shutdown().await?;

        assert!(checkpoint_file(temp.path(), 1).is_file());

        Ok(())
    }

    #[tokio::test]
    async fn enqueue_two_checkpoints_latest_is_step_two() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        let runtime = AsyncCheckpointRuntime::start(manager, 4).await;
        runtime.enqueue_checkpoint(1, b"step one".to_vec()).await?;
        runtime.enqueue_checkpoint(2, b"step two".to_vec()).await?;
        runtime.shutdown().await?;

        let manager = manager_in_temp_dir(temp.path());
        let latest = manager
            .latest_checkpoint()?
            .expect("expected latest checkpoint");
        assert_eq!(latest.step, 2);

        let data = manager.load_latest()?.expect("expected checkpoint bytes");
        assert_eq!(data, b"step two");

        Ok(())
    }

    #[tokio::test]
    async fn shutdown_waits_for_queued_jobs_to_finish() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let manager = manager_in_temp_dir(temp.path());

        let runtime = AsyncCheckpointRuntime::start(manager, 4).await;
        runtime.enqueue_checkpoint(1, b"step one".to_vec()).await?;
        runtime.enqueue_checkpoint(2, b"step two".to_vec()).await?;
        runtime.enqueue_checkpoint(3, b"step three".to_vec()).await?;
        runtime.shutdown().await?;

        assert!(checkpoint_file(temp.path(), 1).is_file());
        assert!(checkpoint_file(temp.path(), 2).is_file());
        assert!(checkpoint_file(temp.path(), 3).is_file());

        Ok(())
    }

    fn manager_with_failing_storage(failures: u32) -> CheckpointManager {
        use std::sync::Arc;

        use crate::storage::{FailureInjectingStorageBackend, InMemoryStorageBackend};

        let inner = Arc::new(InMemoryStorageBackend::new("checkpoints"));
        let failing = FailureInjectingStorageBackend::new(Arc::clone(&inner));
        failing.set_write_atomic_failures(failures);
        CheckpointManager::with_storage(Arc::new(failing), 0)
    }

    #[tokio::test]
    async fn transient_write_failure_retries_then_commits() -> Result<()> {
        let manager = manager_with_failing_storage(1);
        let retry = RetryConfig {
            max_retries: 2,
            retry_backoff_ms: 1,
            exponential_backoff: false,
        };
        let runtime =
            AsyncCheckpointRuntime::start_with_retry_config(manager, 2, retry).await;
        let metrics = runtime.metrics_map();
        let statuses = runtime.status_map();
        runtime.enqueue_checkpoint(1, b"recovered".to_vec()).await?;
        runtime.shutdown().await?;

        assert_eq!(
            statuses.lock().await.get(&1),
            Some(&CheckpointJobStatus::Committed)
        );
        let metrics = metrics.lock().await;
        assert_eq!(metrics.total_retries, 1);
        assert_eq!(metrics.total_permanent_failures, 0);
        assert_eq!(metrics.total_committed, 1);
        assert_eq!(metrics.total_failed, 1);

        Ok(())
    }

    #[tokio::test]
    async fn exhausted_retries_mark_failed_permanent() -> Result<()> {
        let manager = manager_with_failing_storage(3);
        let retry = RetryConfig {
            max_retries: 1,
            retry_backoff_ms: 1,
            exponential_backoff: false,
        };
        let runtime =
            AsyncCheckpointRuntime::start_with_retry_config(manager, 2, retry).await;
        let metrics = runtime.metrics_map();
        let statuses = runtime.status_map();
        runtime.enqueue_checkpoint(2, b"never".to_vec()).await?;
        runtime.shutdown().await?;

        let status = statuses.lock().await.get(&2).cloned();
        assert!(
            matches!(status, Some(CheckpointJobStatus::FailedPermanent(_))),
            "expected permanent failure, got {status:?}"
        );
        let metrics = metrics.lock().await;
        assert_eq!(metrics.total_retries, 1);
        assert_eq!(metrics.total_permanent_failures, 1);
        assert_eq!(metrics.total_committed, 0);
        assert!(metrics.total_failed >= 2);

        Ok(())
    }
}
