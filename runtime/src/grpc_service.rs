use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{Context, Result};
use tokio::sync::Mutex;
use tonic::{transport::Server, Request, Response, Status};

use crate::async_runtime::AsyncCheckpointRuntime;
use crate::async_service::format_job_status;
use crate::checkpoint_manager::CheckpointManager;
use crate::metadata::CheckpointEntry as RustCheckpointEntry;
use crate::service::read_checkpoint_file;

pub mod proto {
    tonic::include_proto!("faultline");
}

use proto::faultline_service_server::{FaultlineService, FaultlineServiceServer};
use proto::{
    CheckpointEntry, EnqueueWorkerFromFileRequest, GenericResponse, LatestForWorkerRequest,
    LatestForWorkerResponse, MetricsRequest, MetricsResponse, SaveFromFileRequest, ShutdownRequest,
    StatusRequest, StatusResponse,
};

const DEFAULT_QUEUE_CAPACITY: usize = 8;

/// gRPC front-end sharing one async runtime and its checkpoint manager.
pub struct FaultlineGrpc {
    runtime: Arc<Mutex<Option<AsyncCheckpointRuntime>>>,
    server_shutdown: Mutex<Option<tokio::sync::oneshot::Sender<()>>>,
}

impl FaultlineGrpc {
    pub async fn new(
        manager: CheckpointManager,
        queue_capacity: usize,
        server_shutdown: tokio::sync::oneshot::Sender<()>,
    ) -> Result<Self> {
        let runtime = AsyncCheckpointRuntime::start(manager, queue_capacity).await;
        Ok(Self {
            runtime: Arc::new(Mutex::new(Some(runtime))),
            server_shutdown: Mutex::new(Some(server_shutdown)),
        })
    }

    async fn runtime_ref(&self) -> tokio::sync::MutexGuard<'_, Option<AsyncCheckpointRuntime>> {
        self.runtime.lock().await
    }

    fn require_runtime<'a>(
        guard: &'a tokio::sync::MutexGuard<'_, Option<AsyncCheckpointRuntime>>,
    ) -> Result<&'a AsyncCheckpointRuntime, Status> {
        guard
            .as_ref()
            .ok_or_else(|| Status::failed_precondition("gRPC service is shut down"))
    }
}

#[tonic::async_trait]
impl FaultlineService for FaultlineGrpc {
    async fn save_from_file(
        &self,
        request: Request<SaveFromFileRequest>,
    ) -> Result<Response<GenericResponse>, Status> {
        let req = request.into_inner();
        let path = req.path;
        let step = req.step;

        let guard = self.runtime_ref().await;
        let runtime = Self::require_runtime(&guard)?;
        let manager = runtime.shared_manager();
        tokio::task::spawn_blocking(move || {
            let bytes = read_checkpoint_file(&path).map_err(Status::invalid_argument)?;
            manager
                .save_checkpoint(step, &bytes)
                .map_err(|error| Status::internal(error.to_string()))
        })
        .await
        .map_err(|error| Status::internal(error.to_string()))??;
        drop(guard);

        Ok(Response::new(GenericResponse {
            ok: true,
            message: format!("saved checkpoint step {step} from file"),
            error: String::new(),
        }))
    }

    async fn enqueue_worker_from_file(
        &self,
        request: Request<EnqueueWorkerFromFileRequest>,
    ) -> Result<Response<GenericResponse>, Status> {
        let req = request.into_inner();
        let bytes = read_checkpoint_file(&req.path).map_err(Status::invalid_argument)?;

        let guard = self.runtime_ref().await;
        let runtime = Self::require_runtime(&guard)?;
        runtime
            .enqueue_worker_checkpoint(req.worker_id, req.local_step, req.step, bytes)
            .await
            .map_err(|error| Status::internal(error.to_string()))?;
        drop(guard);

        Ok(Response::new(GenericResponse {
            ok: true,
            message: format!(
                "queued worker {} checkpoint local_step {} (step {})",
                req.worker_id, req.local_step, req.step
            ),
            error: String::new(),
        }))
    }

    async fn latest_for_worker(
        &self,
        request: Request<LatestForWorkerRequest>,
    ) -> Result<Response<LatestForWorkerResponse>, Status> {
        let worker_id = request.into_inner().worker_id;

        let guard = self.runtime_ref().await;
        let runtime = Self::require_runtime(&guard)?;
        let checkpoint = runtime
            .latest_checkpoint_for_worker(worker_id)
            .map_err(|error| Status::internal(error.to_string()))?;
        drop(guard);

        Ok(Response::new(LatestForWorkerResponse {
            ok: true,
            error: String::new(),
            checkpoint: checkpoint.map(to_proto_checkpoint),
        }))
    }

    async fn status(
        &self,
        request: Request<StatusRequest>,
    ) -> Result<Response<StatusResponse>, Status> {
        let step = request.into_inner().step;

        let guard = self.runtime_ref().await;
        let runtime = Self::require_runtime(&guard)?;
        let status = runtime.checkpoint_status(step).await;
        drop(guard);

        match status {
            Some(job_status) => Ok(Response::new(StatusResponse {
                ok: true,
                error: String::new(),
                status: format_job_status(job_status),
            })),
            None => Ok(Response::new(StatusResponse {
                ok: false,
                error: format!("no status for step {step}"),
                status: String::new(),
            })),
        }
    }

    async fn metrics(
        &self,
        _request: Request<MetricsRequest>,
    ) -> Result<Response<MetricsResponse>, Status> {
        let guard = self.runtime_ref().await;
        let runtime = Self::require_runtime(&guard)?;
        let metrics = runtime.metrics().await;
        drop(guard);

        Ok(Response::new(MetricsResponse {
            ok: true,
            error: String::new(),
            total_enqueued: metrics.total_enqueued,
            total_committed: metrics.total_committed,
            total_failed: metrics.total_failed,
            total_dropped: metrics.total_dropped,
            total_bytes_written: metrics.total_bytes_written,
            total_write_time_ms: metrics.total_write_time_ms as u64,
            average_write_time_ms: metrics.average_write_time_ms(),
        }))
    }

    async fn shutdown(
        &self,
        _request: Request<ShutdownRequest>,
    ) -> Result<Response<GenericResponse>, Status> {
        let mut guard = self.runtime.lock().await;
        let was_running = guard.is_some();
        if let Some(runtime) = guard.take() {
            runtime
                .shutdown()
                .await
                .map_err(|error| Status::internal(error.to_string()))?;
        }

        if let Some(tx) = self.server_shutdown.lock().await.take() {
            let _ = tx.send(());
        }

        let message = if was_running {
            "shutting down"
        } else {
            "already shut down"
        };
        Ok(Response::new(GenericResponse {
            ok: true,
            message: message.to_string(),
            error: String::new(),
        }))
    }
}

fn to_proto_checkpoint(entry: RustCheckpointEntry) -> CheckpointEntry {
    CheckpointEntry {
        step: entry.step,
        path: entry.path,
        status: entry.status,
        worker_id: entry.worker_id,
        local_step: entry.local_step,
    }
}

pub fn default_queue_capacity() -> usize {
    DEFAULT_QUEUE_CAPACITY
}

/// Run the gRPC server until it is stopped.
pub async fn run_grpc_server(
    addr: SocketAddr,
    checkpoint_dir: PathBuf,
    queue_capacity: usize,
    write_delay_ms: u64,
) -> Result<()> {
    let manager =
        CheckpointManager::new_with_delay(checkpoint_dir, "checkpoints", write_delay_ms);
    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel();
    let service = FaultlineGrpc::new(manager, queue_capacity, shutdown_tx).await?;

    eprintln!("Faultline gRPC listening on {addr}");

    Server::builder()
        .add_service(FaultlineServiceServer::new(service))
        .serve_with_shutdown(addr, async move {
            let _ = shutdown_rx.await;
        })
        .await
        .context("gRPC server failed")?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn proto_checkpoint_round_trip_fields() {
        let entry = RustCheckpointEntry {
            step: 1_000_010,
            path: "checkpoints/step_1000010.ckpt".to_string(),
            status: "committed".to_string(),
            worker_id: Some(1),
            local_step: Some(10),
        };
        let proto = to_proto_checkpoint(entry.clone());
        assert_eq!(proto.step, entry.step);
        assert_eq!(proto.worker_id, Some(1));
        assert_eq!(proto.local_step, Some(10));
    }
}
