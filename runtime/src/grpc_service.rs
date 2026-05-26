use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{Context, Result};
use tokio::sync::Mutex;
use tonic::{transport::Server, Request, Response, Status, Streaming};

use crate::alert_engine::{Alert, AlertEngine};
use crate::async_runtime::AsyncCheckpointRuntime;
use crate::async_service::format_job_status;
use crate::checkpoint_manager::CheckpointManager;
use crate::dataset_registry::{DatasetMetadata, DatasetRegistry, ShardMetadata};
use crate::run_registry::{RunLoggedMetrics, RunMetadata, RunMetricPoint, RunRegistry, RunStatus};
use crate::event_log::{EventLog, RuntimeEvent};
use crate::metadata::CheckpointEntry as RustCheckpointEntry;
use crate::observability::{
    build_runtime_overview, build_worker_summaries, shard_worker_id, RuntimeOverview,
    WorkerSummary,
};
use crate::runtime_metrics::RuntimeMetrics;
use crate::service::read_checkpoint_file;

pub mod proto {
    tonic::include_proto!("faultline");
}

use proto::faultline_service_server::{FaultlineService, FaultlineServiceServer};
use proto::{
    CheckpointChunk, CheckpointEntry, ClaimNextShardRequest, ClaimNextShardResponse,
    CompleteShardRequest, CompleteShardResponse, DatasetMetadataMsg, EnqueueWorkerBytesRequest,
    EnqueueWorkerFromFileRequest, EnqueueResponse, GenericResponse, LatestForWorkerRequest,
    LatestForWorkerResponse, ListDatasetsRequest, ListDatasetsResponse, MetricsRequest,
    AsyncMetricsMsg, GetRuntimeOverviewRequest, GetRuntimeOverviewResponse, ListShardsRequest,
    ListEventsRequest, ListEventsResponse, ListShardsResponse, ListWorkersRequest,
    ListWorkersResponse, MetricsResponse, RegisterDatasetRequest, RegisterDatasetResponse,
    ReleaseStaleShardsRequest, ReleaseStaleShardsResponse, RuntimeEventMsg,
    SaveFromFileRequest, ShutdownRequest, ShardMetadataMsg, ShardViewMsg, StatusRequest,
    StatusResponse, WorkerInfoMsg, CreateRunRequest, CreateRunResponse, ListRunsRequest,
    ListRunsResponse, GetRunRequest, GetRunResponse, UpdateRunMetricsRequest,
    UpdateRunMetricsResponse, CompleteRunRequest, CompleteRunResponse, RunMetadataMsg,
    LogRunMetricsRequest, LogRunMetricsResponse, ListRunMetricsRequest, ListRunMetricsResponse,
    RunMetricPointMsg, ListAlertsRequest, ListAlertsResponse, EvaluateAlertsRequest,
    EvaluateAlertsResponse, AlertMsg,
};

const DEFAULT_QUEUE_CAPACITY: usize = 8;
/// Upper bound for streamed checkpoint assembly (512 MiB).
const MAX_STREAM_CHECKPOINT_BYTES: usize = 512 * 1024 * 1024;

/// gRPC front-end sharing one async runtime and its checkpoint manager.
pub struct FaultlineGrpc {
    runtime: Arc<Mutex<Option<AsyncCheckpointRuntime>>>,
    dataset_registry: Arc<DatasetRegistry>,
    run_registry: Arc<RunRegistry>,
    event_log: Arc<EventLog>,
    alert_engine: Arc<AlertEngine>,
    server_shutdown: Mutex<Option<tokio::sync::oneshot::Sender<()>>>,
}

impl FaultlineGrpc {
    pub async fn new(
        manager: CheckpointManager,
        dataset_registry: Arc<DatasetRegistry>,
        run_registry: Arc<RunRegistry>,
        event_log: Arc<EventLog>,
        alert_engine: Arc<AlertEngine>,
        queue_capacity: usize,
        server_shutdown: tokio::sync::oneshot::Sender<()>,
    ) -> Result<Self> {
        let runtime = AsyncCheckpointRuntime::start(manager, queue_capacity).await;
        Ok(Self {
            runtime: Arc::new(Mutex::new(Some(runtime))),
            dataset_registry,
            run_registry,
            event_log,
            alert_engine,
            server_shutdown: Mutex::new(Some(server_shutdown)),
        })
    }

    async fn evaluate_alerts_inner(&self) -> Result<Vec<Alert>, Status> {
        let run_registry = Arc::clone(&self.run_registry);
        let event_log = Arc::clone(&self.event_log);
        let alert_engine = Arc::clone(&self.alert_engine);
        let alerts = tokio::task::spawn_blocking(move || {
            let runs = run_registry.list_runs().map_err(|error| error.to_string())?;
            let events = event_log.list_events(crate::event_log::DEFAULT_EVENT_LOG_CAPACITY);
            let now_ms = crate::dataset_registry::current_time_ms();
            Ok(alert_engine.evaluate(
                &runs,
                &events,
                |run_id| {
                    run_registry
                        .list_run_metrics(run_id, 1000)
                        .unwrap_or_default()
                },
                now_ms,
            ))
        })
        .await
        .map_err(|error| Status::internal(error.to_string()))?
        .map_err(|error: String| Status::internal(error))?;
        Ok(alerts)
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
        let event_log = Arc::clone(&self.event_log);
        tokio::task::spawn_blocking(move || {
            let bytes = read_checkpoint_file(&path).map_err(Status::invalid_argument)?;
            manager
                .save_checkpoint(step, &bytes)
                .map_err(|error| Status::internal(error.to_string()))?;
            crate::event_log::record_event(
                &Some(event_log),
                crate::event_log::RuntimeEventInput::new(
                    crate::event_log::EventLevel::Info,
                    "checkpoint_committed",
                    format!("checkpoint step {step} committed (sync save_from_file)"),
                )
                .step(step),
            );
            Ok::<(), Status>(())
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
            total_retries: metrics.total_retries,
            total_permanent_failures: metrics.total_permanent_failures,
        }))
    }

    async fn register_dataset(
        &self,
        request: Request<RegisterDatasetRequest>,
    ) -> Result<Response<RegisterDatasetResponse>, Status> {
        let req = request.into_inner();
        let registry = Arc::clone(&self.dataset_registry);
        let metadata = tokio::task::spawn_blocking(move || {
            registry.register_dataset(&req.name, req.total_samples, req.shard_size)
        })
        .await
        .map_err(|error| Status::internal(error.to_string()))?
        .map_err(|error| Status::invalid_argument(error.to_string()))?;

        Ok(Response::new(RegisterDatasetResponse {
            ok: true,
            error: String::new(),
            dataset: Some(to_proto_dataset(metadata)),
        }))
    }

    async fn list_datasets(
        &self,
        _request: Request<ListDatasetsRequest>,
    ) -> Result<Response<ListDatasetsResponse>, Status> {
        let registry = Arc::clone(&self.dataset_registry);
        let datasets = tokio::task::spawn_blocking(move || registry.list_datasets())
            .await
            .map_err(|error| Status::internal(error.to_string()))?
            .map_err(|error| Status::internal(error.to_string()))?;

        Ok(Response::new(ListDatasetsResponse {
            ok: true,
            error: String::new(),
            datasets: datasets.into_iter().map(to_proto_dataset).collect(),
        }))
    }

    async fn claim_next_shard(
        &self,
        request: Request<ClaimNextShardRequest>,
    ) -> Result<Response<ClaimNextShardResponse>, Status> {
        let req = request.into_inner();
        let registry = Arc::clone(&self.dataset_registry);
        let dataset_name = req.dataset_name.clone();
        let shard = tokio::task::spawn_blocking(move || {
            registry.claim_next_shard(req.worker_id, &dataset_name)
        })
        .await
        .map_err(|error| Status::internal(error.to_string()))?
        .map_err(|error| Status::internal(error.to_string()))?;

        match shard {
            Some(claimed) => Ok(Response::new(ClaimNextShardResponse {
                ok: true,
                error: String::new(),
                claimed: true,
                shard: Some(to_proto_shard(claimed)),
            })),
            None => Ok(Response::new(ClaimNextShardResponse {
                ok: true,
                error: String::new(),
                claimed: false,
                shard: None,
            })),
        }
    }

    async fn complete_shard(
        &self,
        request: Request<CompleteShardRequest>,
    ) -> Result<Response<CompleteShardResponse>, Status> {
        let req = request.into_inner();
        let registry = Arc::clone(&self.dataset_registry);
        let dataset_name = req.dataset_name.clone();
        let shard = tokio::task::spawn_blocking(move || {
            registry.complete_shard(req.worker_id, &dataset_name, req.shard_id)
        })
        .await
        .map_err(|error| Status::internal(error.to_string()))?
        .map_err(|error| Status::failed_precondition(error.to_string()))?;

        Ok(Response::new(CompleteShardResponse {
            ok: true,
            error: String::new(),
            shard: Some(to_proto_shard(shard)),
        }))
    }

    async fn create_run(
        &self,
        request: Request<CreateRunRequest>,
    ) -> Result<Response<CreateRunResponse>, Status> {
        let req = request.into_inner();
        let registry = Arc::clone(&self.run_registry);
        let run = tokio::task::spawn_blocking(move || {
            registry.create_run(&req.project_name, &req.run_name, req.tags)
        })
        .await
        .map_err(|error| Status::internal(error.to_string()))?
        .map_err(|error| Status::invalid_argument(error.to_string()))?;

        Ok(Response::new(CreateRunResponse {
            ok: true,
            error: String::new(),
            run: Some(to_proto_run(run)),
        }))
    }

    async fn list_runs(
        &self,
        _request: Request<ListRunsRequest>,
    ) -> Result<Response<ListRunsResponse>, Status> {
        let registry = Arc::clone(&self.run_registry);
        let runs = tokio::task::spawn_blocking(move || registry.list_runs())
            .await
            .map_err(|error| Status::internal(error.to_string()))?
            .map_err(|error| Status::internal(error.to_string()))?;

        Ok(Response::new(ListRunsResponse {
            ok: true,
            error: String::new(),
            runs: runs.into_iter().map(to_proto_run).collect(),
        }))
    }

    async fn get_run(
        &self,
        request: Request<GetRunRequest>,
    ) -> Result<Response<GetRunResponse>, Status> {
        let run_id = request.into_inner().run_id;
        let lookup_id = run_id.clone();
        let registry = Arc::clone(&self.run_registry);
        let run = tokio::task::spawn_blocking(move || registry.get_run(&lookup_id))
            .await
            .map_err(|error| Status::internal(error.to_string()))?
            .map_err(|error| Status::internal(error.to_string()))?;

        match run {
            Some(metadata) => Ok(Response::new(GetRunResponse {
                ok: true,
                error: String::new(),
                run: Some(to_proto_run(metadata)),
            })),
            None => Ok(Response::new(GetRunResponse {
                ok: false,
                error: format!("unknown run: {run_id}"),
                run: None,
            })),
        }
    }

    async fn update_run_metrics(
        &self,
        request: Request<UpdateRunMetricsRequest>,
    ) -> Result<Response<UpdateRunMetricsResponse>, Status> {
        let req = request.into_inner();
        let registry = Arc::clone(&self.run_registry);
        let run = tokio::task::spawn_blocking(move || {
            if let Some(worker_id) = req.worker_id {
                registry.attach_worker_to_run(&req.run_id, worker_id)?;
            }
            if let Some(checkpoint_step) = req.latest_checkpoint_step {
                registry.update_checkpoint_step(&req.run_id, checkpoint_step)?;
            }
            registry.update_run_metrics(
                &req.run_id,
                req.latest_step,
                req.latest_loss,
                RunLoggedMetrics {
                    loss: req.loss,
                    learning_rate: req.learning_rate,
                    throughput: req.throughput,
                },
            )
        })
        .await
        .map_err(|error| Status::internal(error.to_string()))?
        .map_err(|error| Status::invalid_argument(error.to_string()))?;

        Ok(Response::new(UpdateRunMetricsResponse {
            ok: true,
            error: String::new(),
            run: Some(to_proto_run(run)),
        }))
    }

    async fn log_run_metrics(
        &self,
        request: Request<LogRunMetricsRequest>,
    ) -> Result<Response<LogRunMetricsResponse>, Status> {
        let req = request.into_inner();
        let registry = Arc::clone(&self.run_registry);
        let run_id = req.run_id.clone();
        let step = req.step;
        let metrics: std::collections::HashMap<String, f64> = req.metrics;
        let worker_id = req.worker_id;
        let run = tokio::task::spawn_blocking(move || {
            if let Some(worker_id) = worker_id {
                registry.attach_worker_to_run(&run_id, worker_id)?;
            }
            registry
                .append_run_metrics(&run_id, step, metrics)
                .map(|(metadata, _point)| metadata)
        })
        .await
        .map_err(|error| Status::internal(error.to_string()))?
        .map_err(|error| Status::invalid_argument(error.to_string()))?;

        Ok(Response::new(LogRunMetricsResponse {
            ok: true,
            error: String::new(),
            run: Some(to_proto_run(run)),
        }))
    }

    async fn list_run_metrics(
        &self,
        request: Request<ListRunMetricsRequest>,
    ) -> Result<Response<ListRunMetricsResponse>, Status> {
        let req = request.into_inner();
        let run_id = req.run_id.clone();
        let limit = req.limit as usize;
        let registry = Arc::clone(&self.run_registry);
        let points = tokio::task::spawn_blocking(move || {
            registry.list_run_metrics(&run_id, limit)
        })
        .await
        .map_err(|error| Status::internal(error.to_string()))?
        .map_err(|error| Status::invalid_argument(error.to_string()))?;

        Ok(Response::new(ListRunMetricsResponse {
            ok: true,
            error: String::new(),
            points: points.into_iter().map(to_proto_run_metric_point).collect(),
        }))
    }

    async fn complete_run(
        &self,
        request: Request<CompleteRunRequest>,
    ) -> Result<Response<CompleteRunResponse>, Status> {
        let req = request.into_inner();
        let status = RunStatus::parse(&req.status).ok_or_else(|| {
            Status::invalid_argument(format!("unknown run status: {}", req.status))
        })?;
        let registry = Arc::clone(&self.run_registry);
        let run = tokio::task::spawn_blocking(move || {
            registry.update_run_status(&req.run_id, status)
        })
        .await
        .map_err(|error| Status::internal(error.to_string()))?
        .map_err(|error| Status::invalid_argument(error.to_string()))?;

        Ok(Response::new(CompleteRunResponse {
            ok: true,
            error: String::new(),
            run: Some(to_proto_run(run)),
        }))
    }

    async fn list_alerts(
        &self,
        _request: Request<ListAlertsRequest>,
    ) -> Result<Response<ListAlertsResponse>, Status> {
        let alert_engine = Arc::clone(&self.alert_engine);
        let alerts = tokio::task::spawn_blocking(move || alert_engine.list_alerts())
            .await
            .map_err(|error| Status::internal(error.to_string()))?;
        let active_count = alerts.len() as u64;
        Ok(Response::new(ListAlertsResponse {
            ok: true,
            error: String::new(),
            alerts: alerts.into_iter().map(to_proto_alert).collect(),
            active_count,
        }))
    }

    async fn evaluate_alerts(
        &self,
        _request: Request<EvaluateAlertsRequest>,
    ) -> Result<Response<EvaluateAlertsResponse>, Status> {
        let alerts = self.evaluate_alerts_inner().await?;
        let active_count = alerts.len() as u64;
        Ok(Response::new(EvaluateAlertsResponse {
            ok: true,
            error: String::new(),
            alerts: alerts.into_iter().map(to_proto_alert).collect(),
            active_count,
        }))
    }

    async fn release_stale_shards(
        &self,
        request: Request<ReleaseStaleShardsRequest>,
    ) -> Result<Response<ReleaseStaleShardsResponse>, Status> {
        let timeout_ms = request.into_inner().timeout_ms;
        let registry = Arc::clone(&self.dataset_registry);
        let released_count = tokio::task::spawn_blocking(move || {
            registry.release_stale_shards(timeout_ms)
        })
        .await
        .map_err(|error| Status::internal(error.to_string()))?
        .map_err(|error| Status::internal(error.to_string()))?;

        Ok(Response::new(ReleaseStaleShardsResponse {
            ok: true,
            error: String::new(),
            released_count,
        }))
    }

    async fn get_runtime_overview(
        &self,
        _request: Request<GetRuntimeOverviewRequest>,
    ) -> Result<Response<GetRuntimeOverviewResponse>, Status> {
        let guard = self.runtime_ref().await;
        let runtime = Self::require_runtime(&guard)?;
        let metrics = runtime.metrics().await;
        let manager = runtime.shared_manager();
        drop(guard);

        let registry = Arc::clone(&self.dataset_registry);
        let overview = tokio::task::spawn_blocking(move || {
            let checkpoints = manager
                .list_checkpoints()
                .map_err(|error| error.to_string())?;
            Ok::<RuntimeOverview, String>(build_runtime_overview(
                &registry,
                &checkpoints,
                metrics,
            ))
        })
        .await
        .map_err(|error| Status::internal(error.to_string()))?
        .map_err(|error| Status::internal(error))?;

        Ok(Response::new(to_proto_overview(overview)))
    }

    async fn list_workers(
        &self,
        _request: Request<ListWorkersRequest>,
    ) -> Result<Response<ListWorkersResponse>, Status> {
        let guard = self.runtime_ref().await;
        let runtime = Self::require_runtime(&guard)?;
        let manager = runtime.shared_manager();
        drop(guard);

        let registry = Arc::clone(&self.dataset_registry);
        let workers = tokio::task::spawn_blocking(move || {
            let checkpoints = manager
                .list_checkpoints()
                .map_err(|error| error.to_string())?;
            Ok::<Vec<WorkerSummary>, String>(build_worker_summaries(&registry, &checkpoints))
        })
        .await
        .map_err(|error| Status::internal(error.to_string()))?
        .map_err(|error| Status::internal(error))?;

        Ok(Response::new(ListWorkersResponse {
            ok: true,
            error: String::new(),
            workers: workers.into_iter().map(to_proto_worker).collect(),
        }))
    }

    async fn list_shards(
        &self,
        request: Request<ListShardsRequest>,
    ) -> Result<Response<ListShardsResponse>, Status> {
        let req = request.into_inner();
        let status_filter = req.status.filter(|value| !value.is_empty());
        let registry = Arc::clone(&self.dataset_registry);
        let dataset_name = req.dataset_name.clone();

        let shards = tokio::task::spawn_blocking(move || {
            registry
                .list_shards(&dataset_name, status_filter.as_deref())
                .map_err(|error| error.to_string())
        })
        .await
        .map_err(|error| Status::internal(error.to_string()))?
        .map_err(|error| Status::invalid_argument(error))?;

        Ok(Response::new(ListShardsResponse {
            ok: true,
            error: String::new(),
            shards: shards.into_iter().map(to_proto_shard_view).collect(),
        }))
    }

    async fn list_events(
        &self,
        request: Request<ListEventsRequest>,
    ) -> Result<Response<ListEventsResponse>, Status> {
        let limit = request.into_inner().limit;
        let limit = if limit == 0 { 100 } else { limit as usize };
        let event_log = Arc::clone(&self.event_log);
        let events = tokio::task::spawn_blocking(move || event_log.list_events(limit))
            .await
            .map_err(|error| Status::internal(error.to_string()))?;

        Ok(Response::new(ListEventsResponse {
            ok: true,
            error: String::new(),
            events: events.into_iter().map(to_proto_event).collect(),
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

fn to_proto_dataset(metadata: DatasetMetadata) -> DatasetMetadataMsg {
    DatasetMetadataMsg {
        name: metadata.name,
        total_samples: metadata.total_samples,
        shard_size: metadata.shard_size,
        total_shards: metadata.total_shards,
    }
}

fn to_proto_shard(shard: ShardMetadata) -> ShardMetadataMsg {
    ShardMetadataMsg {
        shard_id: shard.shard_id,
        dataset_name: shard.dataset_name,
        start_sample: shard.start_sample,
        end_sample: shard.end_sample,
        status: shard.status.as_str().to_string(),
        claimed_by: shard.claimed_by,
        claimed_at_ms: shard.claimed_at_ms,
        updated_at_ms: shard.updated_at_ms,
    }
}

fn to_proto_overview(overview: RuntimeOverview) -> GetRuntimeOverviewResponse {
    GetRuntimeOverviewResponse {
        ok: true,
        error: String::new(),
        total_datasets: overview.total_datasets,
        total_shards: overview.total_shards,
        pending_shards: overview.pending_shards,
        claimed_shards: overview.claimed_shards,
        completed_shards: overview.completed_shards,
        failed_shards: overview.failed_shards,
        total_checkpoints: overview.total_checkpoints,
        workers_seen: overview.workers_seen,
        async_metrics: Some(to_proto_async_metrics(overview.async_metrics)),
    }
}

fn to_proto_async_metrics(metrics: RuntimeMetrics) -> AsyncMetricsMsg {
    AsyncMetricsMsg {
        total_enqueued: metrics.total_enqueued,
        total_committed: metrics.total_committed,
        total_failed: metrics.total_failed,
        total_dropped: metrics.total_dropped,
        total_bytes_written: metrics.total_bytes_written,
        average_write_time_ms: metrics.average_write_time_ms(),
        total_retries: metrics.total_retries,
        total_permanent_failures: metrics.total_permanent_failures,
    }
}

fn to_proto_worker(worker: WorkerSummary) -> WorkerInfoMsg {
    WorkerInfoMsg {
        worker_id: worker.worker_id,
        latest_checkpoint_step: worker.latest_checkpoint_step,
        latest_local_step: worker.latest_local_step,
        committed_checkpoints: worker.committed_checkpoints,
        claimed_shards: worker.claimed_shards,
        completed_shards: worker.completed_shards,
    }
}

fn to_proto_event(event: RuntimeEvent) -> RuntimeEventMsg {
    RuntimeEventMsg {
        event_id: event.event_id,
        timestamp_ms: event.timestamp_ms,
        level: event.level.as_str().to_string(),
        event_type: event.event_type,
        worker_id: event.worker_id,
        dataset_name: event.dataset_name,
        shard_id: event.shard_id,
        step: event.step,
        message: event.message,
    }
}

fn to_proto_run_metric_point(point: RunMetricPoint) -> RunMetricPointMsg {
    RunMetricPointMsg {
        run_id: point.run_id,
        step: point.step,
        timestamp_ms: point.timestamp_ms,
        metrics: point.metrics,
    }
}

fn to_proto_alert(alert: Alert) -> AlertMsg {
    AlertMsg {
        alert_id: alert.alert_id,
        rule_id: alert.rule_id,
        alert_type: alert.alert_type,
        severity: alert.severity,
        run_id: alert.run_id,
        message: alert.message,
        timestamp_ms: alert.timestamp_ms,
        event_id: alert.event_id,
    }
}

fn to_proto_run(run: RunMetadata) -> RunMetadataMsg {
    RunMetadataMsg {
        run_id: run.run_id,
        project_name: run.project_name,
        run_name: run.run_name,
        created_at_ms: run.created_at_ms,
        status: run.status.as_str().to_string(),
        total_workers_seen: run.total_workers_seen,
        latest_step: run.latest_step,
        latest_checkpoint_step: run.latest_checkpoint_step,
        latest_metric_at_ms: run.latest_metric_at_ms,
        latest_loss: run.latest_loss,
        tags: run.tags,
        loss: run.metrics.loss,
        learning_rate: run.metrics.learning_rate,
        throughput: run.metrics.throughput,
    }
}

fn to_proto_shard_view(shard: ShardMetadata) -> ShardViewMsg {
    ShardViewMsg {
        shard_id: shard.shard_id,
        start: shard.start_sample,
        end: shard.end_sample,
        status: shard.status.as_str().to_string(),
        worker_id: shard_worker_id(&shard),
        updated_at_ms: shard.updated_at_ms,
    }
}

pub fn default_queue_capacity() -> usize {
    DEFAULT_QUEUE_CAPACITY
}

/// Run the gRPC server until it is stopped.
pub async fn run_grpc_server(
    addr: SocketAddr,
    storage: Arc<dyn crate::storage::StorageBackend>,
    dataset_registry_dir: PathBuf,
    run_registry_dir: PathBuf,
    queue_capacity: usize,
    write_delay_ms: u64,
) -> Result<()> {
    let event_log = Arc::new(EventLog::new(crate::event_log::DEFAULT_EVENT_LOG_CAPACITY));
    let manager = CheckpointManager::with_storage_and_event_log(
        storage,
        write_delay_ms,
        Some(Arc::clone(&event_log)),
    );
    let dataset_registry = Arc::new(DatasetRegistry::new_with_event_log(
        dataset_registry_dir,
        Some(Arc::clone(&event_log)),
    )?);
    let run_registry = Arc::new(RunRegistry::new_with_event_log(
        run_registry_dir,
        Some(Arc::clone(&event_log)),
    )?);
    let alert_engine = Arc::new(AlertEngine::with_defaults());
    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel();
    let service = FaultlineGrpc::new(
        manager,
        dataset_registry,
        run_registry,
        event_log,
        alert_engine,
        queue_capacity,
        shutdown_tx,
    )
    .await?;

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
    async fn list_events_returns_dataset_register_event() -> Result<()> {
        let dir = tempdir()?;
        let manager = CheckpointManager::new(dir.path().join("checkpoints"), "checkpoints");
        let event_log = Arc::new(EventLog::new(100));
        let registry = Arc::new(
            DatasetRegistry::new_with_event_log(dir.path().join("datasets"), Some(event_log.clone()))
                .unwrap(),
        );
        let (shutdown_tx, _shutdown_rx) = tokio::sync::oneshot::channel();
        let run_registry = Arc::new(
            RunRegistry::new_with_event_log(dir.path().join("runs"), Some(event_log.clone()))?,
        );
        let service = FaultlineGrpc::new(
            manager,
            registry,
            run_registry,
            event_log,
            Arc::new(AlertEngine::with_defaults()),
            8,
            shutdown_tx,
        )
        .await?;

        service
            .register_dataset(Request::new(RegisterDatasetRequest {
                name: "train".to_string(),
                total_samples: 20,
                shard_size: 10,
            }))
            .await?;

        let events = service
            .list_events(Request::new(ListEventsRequest { limit: 10 }))
            .await?
            .into_inner();
        assert!(events.ok);
        assert!(events
            .events
            .iter()
            .any(|event| event.event_type == "dataset_registered"));

        let mut guard = service.runtime.lock().await;
        if let Some(runtime) = guard.take() {
            runtime.shutdown().await?;
        }
        Ok(())
    }

    #[tokio::test]
    async fn observability_apis_reflect_dataset_and_workers() -> Result<()> {
        let dir = tempdir()?;
        let manager = CheckpointManager::new(dir.path().join("checkpoints"), "checkpoints");
        let registry = Arc::new(DatasetRegistry::new(dir.path().join("datasets")).unwrap());
        let (shutdown_tx, _shutdown_rx) = tokio::sync::oneshot::channel();
        let event_log = Arc::new(EventLog::new(100));
        let run_registry = Arc::new(
            RunRegistry::new_with_event_log(dir.path().join("runs"), Some(event_log.clone()))?,
        );
        let service = FaultlineGrpc::new(
            manager,
            registry,
            run_registry,
            event_log,
            Arc::new(AlertEngine::with_defaults()),
            8,
            shutdown_tx,
        )
        .await?;

        service
            .register_dataset(Request::new(RegisterDatasetRequest {
                name: "train".to_string(),
                total_samples: 30,
                shard_size: 10,
            }))
            .await?;

        let overview = service
            .get_runtime_overview(Request::new(GetRuntimeOverviewRequest {}))
            .await?
            .into_inner();
        assert!(overview.ok);
        assert_eq!(overview.total_datasets, 1);
        assert_eq!(overview.total_shards, 3);
        assert_eq!(overview.pending_shards, 3);

        service
            .claim_next_shard(Request::new(ClaimNextShardRequest {
                worker_id: 1,
                dataset_name: "train".to_string(),
            }))
            .await?;

        let pending = service
            .list_shards(Request::new(ListShardsRequest {
                dataset_name: "train".to_string(),
                status: Some("pending".to_string()),
            }))
            .await?
            .into_inner();
        assert_eq!(pending.shards.len(), 2);

        let claimed = service
            .list_shards(Request::new(ListShardsRequest {
                dataset_name: "train".to_string(),
                status: Some("claimed".to_string()),
            }))
            .await?
            .into_inner();
        assert_eq!(claimed.shards.len(), 1);
        assert_eq!(claimed.shards[0].worker_id, Some(1));

        service
            .enqueue_worker_bytes(Request::new(EnqueueWorkerBytesRequest {
                worker_id: 1,
                local_step: 5,
                step: 1_000_005,
                data: b"obs".to_vec(),
            }))
            .await?;

        let guard = service.runtime_ref().await;
        let runtime = FaultlineGrpc::require_runtime(&guard)?;
        wait_until_committed(runtime, 1_000_005).await?;
        drop(guard);

        let workers = service
            .list_workers(Request::new(ListWorkersRequest {}))
            .await?
            .into_inner();
        assert!(workers.workers.iter().any(|worker| worker.worker_id == 1));

        let mut guard = service.runtime.lock().await;
        if let Some(runtime) = guard.take() {
            runtime.shutdown().await?;
        }
        Ok(())
    }

    #[tokio::test]
    async fn dataset_register_claim_complete_round_trip() -> Result<()> {
        let dir = tempdir()?;
        let manager = CheckpointManager::new(dir.path().join("checkpoints"), "checkpoints");
        let registry = Arc::new(DatasetRegistry::new(dir.path().join("datasets")).unwrap());
        let (shutdown_tx, _shutdown_rx) = tokio::sync::oneshot::channel();
        let event_log = Arc::new(EventLog::new(100));
        let run_registry = Arc::new(
            RunRegistry::new_with_event_log(dir.path().join("runs"), Some(event_log.clone()))?,
        );
        let service = FaultlineGrpc::new(
            manager,
            registry,
            run_registry,
            event_log,
            Arc::new(AlertEngine::with_defaults()),
            8,
            shutdown_tx,
        )
        .await?;

        let register = service
            .register_dataset(Request::new(RegisterDatasetRequest {
                name: "train".to_string(),
                total_samples: 25,
                shard_size: 10,
            }))
            .await?
            .into_inner();
        assert!(register.ok);
        assert_eq!(register.dataset.as_ref().map(|d| d.total_shards), Some(3));

        let claim = service
            .claim_next_shard(Request::new(ClaimNextShardRequest {
                worker_id: 1,
                dataset_name: "train".to_string(),
            }))
            .await?
            .into_inner();
        assert!(claim.claimed);
        let shard_id = claim.shard.as_ref().map(|s| s.shard_id).unwrap_or(0);

        let complete = service
            .complete_shard(Request::new(CompleteShardRequest {
                worker_id: 1,
                dataset_name: "train".to_string(),
                shard_id,
            }))
            .await?
            .into_inner();
        assert!(complete.ok);
        assert_eq!(
            complete.shard.as_ref().map(|s| s.status.as_str()),
            Some("completed")
        );

        let mut guard = service.runtime.lock().await;
        if let Some(runtime) = guard.take() {
            runtime.shutdown().await?;
        }
        Ok(())
    }

    #[tokio::test]
    async fn enqueue_worker_bytes_commits_checkpoint() -> Result<()> {
        let dir = tempdir()?;
        let manager = CheckpointManager::new(dir.path().to_path_buf(), "checkpoints");
        let (shutdown_tx, _shutdown_rx) = tokio::sync::oneshot::channel();
        let registry = Arc::new(DatasetRegistry::new(dir.path().join("datasets")).unwrap());
        let event_log = Arc::new(EventLog::new(100));
        let run_registry = Arc::new(
            RunRegistry::new_with_event_log(dir.path().join("runs"), Some(event_log.clone()))?,
        );
        let service = FaultlineGrpc::new(
            manager,
            registry,
            run_registry,
            event_log,
            Arc::new(AlertEngine::with_defaults()),
            8,
            shutdown_tx,
        )
        .await?;

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
        let registry = Arc::new(DatasetRegistry::new(dir.path().join("datasets")).unwrap());
        let event_log = Arc::new(EventLog::new(100));
        let run_registry = Arc::new(
            RunRegistry::new_with_event_log(dir.path().join("runs"), Some(event_log.clone()))?,
        );
        let service = FaultlineGrpc::new(
            manager,
            registry,
            run_registry,
            event_log,
            Arc::new(AlertEngine::with_defaults()),
            8,
            shutdown_tx,
        )
        .await?;

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
