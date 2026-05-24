use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{Context, Result};
use tokio::sync::Mutex;
use tonic::{transport::Server, Request, Response, Status, Streaming};

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
    CheckpointChunk, CheckpointEntry, EnqueueWorkerBytesRequest, EnqueueWorkerFromFileRequest,
    EnqueueResponse, GenericResponse, LatestForWorkerRequest, LatestForWorkerResponse,
    MetricsRequest, MetricsResponse, SaveFromFileRequest, ShutdownRequest, StatusRequest,
    StatusResponse,
};

const DEFAULT_QUEUE_CAPACITY: usize = 8;
/// Upper bound for streamed checkpoint assembly (512 MiB).
const MAX_STREAM_CHECKPOINT_BYTES: usize = 512 * 1024 * 1024;

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

    async fn enqueue_worker_bytes_inner(
        &self,
        worker_id: u64,
        local_step: u64,
        step: u64,
        data: Vec<u8>,
    ) -> Result<String, Status> {
        let guard = self.runtime_ref().await;
        let runtime = Self::require_runtime(&guard)?;
        runtime
            .enqueue_worker_checkpoint(worker_id, local_step, step, data)
            .await
            .map_err(|error| Status::internal(error.to_string()))?;
        drop(guard);

        Ok(format!(
            "queued worker {worker_id} checkpoint local_step {local_step} (step {step})"
        ))
    }
}

struct CheckpointChunkAssembler {
    buffer: Vec<u8>,
    worker_id: Option<u64>,
    local_step: Option<u64>,
    step: Option<u64>,
    expected_index: u64,
    saw_last: bool,
    received_any: bool,
}

impl CheckpointChunkAssembler {
    fn new() -> Self {
        Self {
            buffer: Vec::new(),
            worker_id: None,
            local_step: None,
            step: None,
            expected_index: 0,
            saw_last: false,
            received_any: false,
        }
    }

    fn push(&mut self, chunk: CheckpointChunk) -> Result<(), Status> {
        self.received_any = true;

        match (self.worker_id, self.local_step, self.step) {
            (None, None, None) => {
                self.worker_id = Some(chunk.worker_id);
                self.local_step = Some(chunk.local_step);
                self.step = Some(chunk.step);
            }
            (Some(worker_id), Some(local_step), Some(step)) => {
                if chunk.worker_id != worker_id
                    || chunk.local_step != local_step
                    || chunk.step != step
                {
                    return Err(Status::invalid_argument(
                        "inconsistent worker_id, local_step, or step across chunks",
                    ));
                }
            }
            _ => unreachable!("worker metadata fields advance together"),
        }

        if chunk.chunk_index != self.expected_index {
            return Err(Status::invalid_argument(format!(
                "out-of-order chunk_index: expected {}, got {}",
                self.expected_index, chunk.chunk_index
            )));
        }
        self.expected_index += 1;

        let next_len = self
            .buffer
            .len()
            .checked_add(chunk.data.len())
            .ok_or_else(|| Status::resource_exhausted("checkpoint stream too large"))?;
        if next_len > MAX_STREAM_CHECKPOINT_BYTES {
            return Err(Status::resource_exhausted(format!(
                "checkpoint stream exceeds {MAX_STREAM_CHECKPOINT_BYTES} bytes"
            )));
        }
        self.buffer.extend_from_slice(&chunk.data);

        if chunk.is_last {
            self.saw_last = true;
        }

        Ok(())
    }

    fn finish(self) -> Result<(u64, u64, u64, Vec<u8>), Status> {
        if !self.received_any {
            return Err(Status::invalid_argument("empty checkpoint stream"));
        }
        if !self.saw_last {
            return Err(Status::invalid_argument(
                "missing final chunk with is_last=true",
            ));
        }

        Ok((
            self.worker_id.expect("stream had at least one chunk"),
            self.local_step.expect("stream had at least one chunk"),
            self.step.expect("stream had at least one chunk"),
            self.buffer,
        ))
    }
}

/// Read a client stream of checkpoint chunks and assemble the full payload.
pub(crate) async fn assemble_checkpoint_stream(
    stream: &mut Streaming<CheckpointChunk>,
) -> Result<(u64, u64, u64, Vec<u8>), Status> {
    let mut assembler = CheckpointChunkAssembler::new();

    while let Some(chunk) = stream
        .message()
        .await
        .map_err(|error| Status::internal(error.to_string()))?
    {
        let is_last = chunk.is_last;
        assembler.push(chunk)?;
        if is_last {
            break;
        }
    }

    assembler.finish()
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

        let message = Self::enqueue_worker_bytes_inner(
            self,
            req.worker_id,
            req.local_step,
            req.step,
            bytes,
        )
        .await?;

        Ok(Response::new(GenericResponse {
            ok: true,
            message,
            error: String::new(),
        }))
    }

    async fn enqueue_worker_bytes(
        &self,
        request: Request<EnqueueWorkerBytesRequest>,
    ) -> Result<Response<EnqueueResponse>, Status> {
        let req = request.into_inner();

        let message = Self::enqueue_worker_bytes_inner(
            self,
            req.worker_id,
            req.local_step,
            req.step,
            req.data,
        )
        .await?;

        Ok(Response::new(EnqueueResponse {
            ok: true,
            message,
            error: String::new(),
        }))
    }

    async fn enqueue_worker_bytes_stream(
        &self,
        request: Request<Streaming<CheckpointChunk>>,
    ) -> Result<Response<EnqueueResponse>, Status> {
        let mut stream = request.into_inner();
        let (worker_id, local_step, step, data) = assemble_checkpoint_stream(&mut stream).await?;

        let message = Self::enqueue_worker_bytes_inner(self, worker_id, local_step, step, data).await?;

        Ok(Response::new(EnqueueResponse {
            ok: true,
            message,
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
    use std::time::Duration;

    use crate::async_runtime::CheckpointJobStatus;
    use tempfile::tempdir;
    use tonic::Request;

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

    #[tokio::test]
    async fn enqueue_worker_bytes_commits_checkpoint() -> Result<()> {
        let dir = tempdir()?;
        let manager = CheckpointManager::new(dir.path().to_path_buf(), "checkpoints");
        let (shutdown_tx, _shutdown_rx) = tokio::sync::oneshot::channel();
        let service = FaultlineGrpc::new(manager, 8, shutdown_tx).await?;

        let worker_id = 3_u64;
        let local_step = 4_u64;
        let step = worker_id * 1_000_000 + local_step;
        let payload = b"grpc-bytes-payload".to_vec();

        let response = service
            .enqueue_worker_bytes(Request::new(EnqueueWorkerBytesRequest {
                worker_id,
                local_step,
                step,
                data: payload.clone(),
            }))
            .await?
            .into_inner();
        assert!(response.ok);

        let guard = service.runtime_ref().await;
        let runtime = FaultlineGrpc::require_runtime(&guard)?;
        wait_until_committed(runtime, step).await?;
        let latest = runtime.latest_checkpoint_for_worker(worker_id)?;
        assert_eq!(latest.as_ref().map(|entry| entry.step), Some(step));
        drop(guard);

        let mut guard = service.runtime.lock().await;
        if let Some(runtime) = guard.take() {
            runtime.shutdown().await?;
        }

        Ok(())
    }

    #[tokio::test]
    async fn enqueue_worker_bytes_stream_commits_checkpoint() -> Result<()> {
        let dir = tempdir()?;
        let manager = CheckpointManager::new(dir.path().to_path_buf(), "checkpoints");
        let (shutdown_tx, _shutdown_rx) = tokio::sync::oneshot::channel();
        let service = FaultlineGrpc::new(manager, 8, shutdown_tx).await?;

        let worker_id = 5_u64;
        let local_step = 6_u64;
        let step = worker_id * 1_000_000 + local_step;
        let payload: Vec<u8> = (0..600_000).map(|index| (index % 251) as u8).collect();

        let mut assembler = CheckpointChunkAssembler::new();
        assembler.push(CheckpointChunk {
            worker_id,
            local_step,
            step,
            chunk_index: 0,
            data: payload[..300_000].to_vec(),
            is_last: false,
        })?;
        let (worker_id, local_step, step, assembled) = {
            assembler.push(CheckpointChunk {
                worker_id,
                local_step,
                step,
                chunk_index: 1,
                data: payload[300_000..].to_vec(),
                is_last: true,
            })?;
            assembler.finish()?
        };
        assert_eq!(assembled, payload);

        let message = service
            .enqueue_worker_bytes_inner(worker_id, local_step, step, assembled)
            .await?;
        assert!(message.contains("queued worker"));

        let guard = service.runtime_ref().await;
        let runtime = FaultlineGrpc::require_runtime(&guard)?;
        wait_until_committed(runtime, step).await?;
        let latest = runtime.latest_checkpoint_for_worker(worker_id)?;
        assert_eq!(latest.as_ref().map(|entry| entry.step), Some(step));
        drop(guard);

        let mut guard = service.runtime.lock().await;
        if let Some(runtime) = guard.take() {
            runtime.shutdown().await?;
        }

        Ok(())
    }

    #[test]
    fn stream_out_of_order_chunk_returns_error() {
        let mut assembler = CheckpointChunkAssembler::new();
        assembler
            .push(CheckpointChunk {
                worker_id: 1,
                local_step: 2,
                step: 1_000_002,
                chunk_index: 0,
                data: b"a".to_vec(),
                is_last: false,
            })
            .expect("first chunk should be accepted");

        let error = assembler
            .push(CheckpointChunk {
                worker_id: 1,
                local_step: 2,
                step: 1_000_002,
                chunk_index: 2,
                data: b"b".to_vec(),
                is_last: true,
            })
            .expect_err("out-of-order chunk should fail");

        assert_eq!(error.code(), tonic::Code::InvalidArgument);
        assert!(error.message().contains("out-of-order chunk_index"));
    }

    async fn wait_until_committed(
        runtime: &AsyncCheckpointRuntime,
        step: u64,
    ) -> Result<()> {
        let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
        loop {
            if matches!(
                runtime.checkpoint_status(step).await,
                Some(CheckpointJobStatus::Committed)
            ) {
                return Ok(());
            }
            if tokio::time::Instant::now() >= deadline {
                anyhow::bail!("checkpoint did not commit in time");
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    }

}
