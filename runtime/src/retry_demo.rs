//! Async checkpoint retry demonstration (in-memory storage + failure injection).

use std::sync::Arc;

use anyhow::{Context, Result};

use crate::async_runtime::{AsyncCheckpointRuntime, RetryConfig};
use crate::checkpoint_manager::CheckpointManager;
use crate::event_log::EventLog;
use crate::storage::{
    FailureInjectingStorageBackend, InMemoryStorageBackend, StorageBackend,
};

/// Run the Version 13.1 retry demo: one injected write failure, then success after retry.
pub fn run_retry_demo() -> Result<()> {
    let event_log = Arc::new(EventLog::new(100));
    let inner = Arc::new(InMemoryStorageBackend::new("checkpoints"));
    let failing = FailureInjectingStorageBackend::new(Arc::clone(&inner));
    failing.set_write_atomic_failures(1);

    let storage: Arc<dyn StorageBackend> = Arc::new(failing);
    let manager = CheckpointManager::with_storage_and_event_log(storage, 0, Some(Arc::clone(&event_log)));

    let retry_config = RetryConfig {
        max_retries: 3,
        retry_backoff_ms: 25,
        exponential_backoff: false,
    };

    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("failed to start tokio for retry demo")?;

    runtime.block_on(async {
        let async_runtime =
            AsyncCheckpointRuntime::start_with_retry_config(manager, 4, retry_config).await;
        let metrics_map = async_runtime.metrics_map();
        async_runtime
            .enqueue_checkpoint(1, b"retry-demo-payload".to_vec())
            .await?;
        async_runtime.shutdown().await?;
        let metrics = metrics_map.lock().await.clone();

        println!("Retry demo metrics:");
        println!("  total_enqueued: {}", metrics.total_enqueued);
        println!("  total_committed: {}", metrics.total_committed);
        println!("  total_failed: {}", metrics.total_failed);
        println!("  total_retries: {}", metrics.total_retries);
        println!(
            "  total_permanent_failures: {}",
            metrics.total_permanent_failures
        );

        println!("\nEvent timeline (oldest first):");
        let mut events: Vec<_> = event_log.list_events(50);
        events.reverse();
        for event in events {
            println!(
                "  [{}] {} type={} step={:?} {}",
                event.timestamp_ms,
                event.level.as_str(),
                event.event_type,
                event.step,
                event.message
            );
        }

        Ok(())
    })
}
