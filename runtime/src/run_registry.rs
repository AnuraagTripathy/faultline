use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};

use crate::dataset_registry::current_time_ms;
use crate::event_log::{record_event, EventLevel, EventLog, RuntimeEventInput};

/// Lifecycle status for a training run / session.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RunStatus {
    Running,
    Completed,
    Failed,
    Stopped,
}

impl RunStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Running => "running",
            Self::Completed => "completed",
            Self::Failed => "failed",
            Self::Stopped => "stopped",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value.trim().to_lowercase().as_str() {
            "running" => Some(Self::Running),
            "completed" => Some(Self::Completed),
            "failed" => Some(Self::Failed),
            "stopped" => Some(Self::Stopped),
            _ => None,
        }
    }
}

/// Latest scalar metrics logged for a run (loss, LR, throughput).
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct RunLoggedMetrics {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub loss: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub learning_rate: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub throughput: Option<f64>,
}

impl RunLoggedMetrics {
    pub fn is_empty(&self) -> bool {
        self.loss.is_none() && self.learning_rate.is_none() && self.throughput.is_none()
    }

    pub fn from_map(metrics: &HashMap<String, f64>) -> Self {
        Self {
            loss: metrics.get("loss").copied(),
            learning_rate: metrics.get("learning_rate").copied(),
            throughput: metrics.get("throughput").copied(),
        }
    }
}

/// One historical metric sample for a run (chart / audit trail).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RunMetricPoint {
    pub run_id: String,
    pub step: u64,
    pub timestamp_ms: u64,
    pub metrics: HashMap<String, f64>,
}

/// Training run / experiment session metadata.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RunMetadata {
    pub run_id: String,
    pub project_name: String,
    pub run_name: String,
    pub created_at_ms: u64,
    pub status: RunStatus,
    pub total_workers_seen: u64,
    pub latest_step: u64,
    pub latest_checkpoint_step: u64,
    #[serde(default)]
    pub latest_metric_at_ms: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub latest_loss: Option<f64>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tags: Vec<String>,
    #[serde(default, skip_serializing_if = "RunLoggedMetrics::is_empty")]
    pub metrics: RunLoggedMetrics,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
struct RunRecord {
    metadata: RunMetadata,
    workers_seen: Vec<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
struct RegistryState {
    runs: Vec<RunRecord>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
struct RunMetricsFile {
    run_id: String,
    points: Vec<RunMetricPoint>,
}

/// Persistent registry of training runs under `runs/registry.json`.
pub struct RunRegistry {
    registry_path: PathBuf,
    metrics_dir: PathBuf,
    state: Mutex<RegistryState>,
    event_log: Option<Arc<EventLog>>,
}

impl RunRegistry {
    pub fn new(registry_dir: impl AsRef<Path>) -> Result<Self> {
        Self::new_with_event_log(registry_dir, None)
    }

    pub fn new_with_event_log(
        registry_dir: impl AsRef<Path>,
        event_log: Option<Arc<EventLog>>,
    ) -> Result<Self> {
        let registry_dir = registry_dir.as_ref().to_path_buf();
        fs::create_dir_all(&registry_dir)
            .with_context(|| format!("create run registry dir {}", registry_dir.display()))?;
        let metrics_dir = registry_dir.join("metrics");
        fs::create_dir_all(&metrics_dir)
            .with_context(|| format!("create run metrics dir {}", metrics_dir.display()))?;
        let registry_path = registry_dir.join("registry.json");
        let state = if registry_path.is_file() {
            let bytes = fs::read(&registry_path)
                .with_context(|| format!("read {}", registry_path.display()))?;
            serde_json::from_slice(&bytes).context("parse runs/registry.json")?
        } else {
            RegistryState::default()
        };

        Ok(Self {
            registry_path,
            metrics_dir,
            state: Mutex::new(state),
            event_log,
        })
    }

    pub fn create_run(
        &self,
        project_name: &str,
        run_name: &str,
        tags: Vec<String>,
    ) -> Result<RunMetadata> {
        let project_name = project_name.trim();
        let run_name = run_name.trim();
        if project_name.is_empty() {
            return Err(anyhow!("project_name must not be empty"));
        }
        if run_name.is_empty() {
            return Err(anyhow!("run_name must not be empty"));
        }

        let created_at_ms = current_time_ms();
        let run_id = format!("{project_name}__{run_name}__{created_at_ms}");
        let metadata = RunMetadata {
            run_id: run_id.clone(),
            project_name: project_name.to_string(),
            run_name: run_name.to_string(),
            created_at_ms,
            status: RunStatus::Running,
            total_workers_seen: 0,
            latest_step: 0,
            latest_checkpoint_step: 0,
            latest_metric_at_ms: 0,
            latest_loss: None,
            tags,
            metrics: RunLoggedMetrics::default(),
        };

        let mut guard = self.state.lock().expect("run registry lock poisoned");
        if guard.runs.iter().any(|record| record.metadata.run_id == run_id) {
            return Err(anyhow!("run already exists: {run_id}"));
        }
        guard.runs.push(RunRecord {
            metadata: metadata.clone(),
            workers_seen: Vec::new(),
        });
        self.persist(&guard)?;
        record_event(
            &self.event_log,
            RuntimeEventInput::new(
                EventLevel::Info,
                "run_created",
                format!("created run {run_id} (project={project_name}, name={run_name})"),
            ),
        );
        Ok(metadata)
    }

    pub fn list_runs(&self) -> Result<Vec<RunMetadata>> {
        let guard = self.state.lock().expect("run registry lock poisoned");
        let mut runs: Vec<RunMetadata> = guard
            .runs
            .iter()
            .map(|record| record.metadata.clone())
            .collect();
        runs.sort_by(|left, right| right.created_at_ms.cmp(&left.created_at_ms));
        Ok(runs)
    }

    pub fn get_run(&self, run_id: &str) -> Result<Option<RunMetadata>> {
        let guard = self.state.lock().expect("run registry lock poisoned");
        Ok(guard
            .runs
            .iter()
            .find(|record| record.metadata.run_id == run_id)
            .map(|record| record.metadata.clone()))
    }

    pub fn update_run_status(&self, run_id: &str, status: RunStatus) -> Result<RunMetadata> {
        let mut guard = self.state.lock().expect("run registry lock poisoned");
        let record = guard
            .runs
            .iter_mut()
            .find(|record| record.metadata.run_id == run_id)
            .ok_or_else(|| anyhow!("unknown run: {run_id}"))?;
        record.metadata.status = status;
        let metadata = record.metadata.clone();
        self.persist(&guard)?;
        record_event(
            &self.event_log,
            RuntimeEventInput::new(
                EventLevel::Info,
                "run_status_updated",
                format!("run {run_id} status -> {}", status.as_str()),
            ),
        );
        Ok(metadata)
    }

    /// Update latest scalar fields on the run (no history append).
    pub fn update_run_metrics(
        &self,
        run_id: &str,
        latest_step: u64,
        latest_loss: Option<f64>,
        logged: RunLoggedMetrics,
    ) -> Result<RunMetadata> {
        let mut guard = self.state.lock().expect("run registry lock poisoned");
        let record = guard
            .runs
            .iter_mut()
            .find(|record| record.metadata.run_id == run_id)
            .ok_or_else(|| anyhow!("unknown run: {run_id}"))?;
        record.metadata.latest_step = latest_step;
        if let Some(loss) = latest_loss {
            record.metadata.latest_loss = Some(loss);
        }
        if logged.loss.is_some() {
            record.metadata.metrics.loss = logged.loss;
        }
        if logged.learning_rate.is_some() {
            record.metadata.metrics.learning_rate = logged.learning_rate;
        }
        if logged.throughput.is_some() {
            record.metadata.metrics.throughput = logged.throughput;
        }
        if record.metadata.latest_loss.is_none() {
            record.metadata.latest_loss = record.metadata.metrics.loss;
        }
        let metadata = record.metadata.clone();
        self.persist(&guard)?;
        Ok(metadata)
    }

    /// Append a metric history point and refresh latest fields on the run.
    pub fn append_run_metrics(
        &self,
        run_id: &str,
        step: u64,
        metrics: HashMap<String, f64>,
    ) -> Result<(RunMetadata, RunMetricPoint)> {
        self.require_run(run_id)?;
        let logged = RunLoggedMetrics::from_map(&metrics);
        let latest_loss = metrics.get("loss").copied();
        self.update_run_metrics(run_id, step, latest_loss, logged)?;

        let point = RunMetricPoint {
            run_id: run_id.to_string(),
            step,
            timestamp_ms: current_time_ms(),
            metrics,
        };
        self.append_metric_point(&point)?;
        let metadata = self.set_latest_metric_at(run_id, point.timestamp_ms)?;
        Ok((metadata, point))
    }

    /// Return up to `limit` most recent metric points (by step, ascending).
    pub fn list_run_metrics(&self, run_id: &str, limit: usize) -> Result<Vec<RunMetricPoint>> {
        self.require_run(run_id)?;
        let mut points = self.load_metric_points(run_id)?;
        points.sort_by_key(|point| point.step);
        if limit > 0 && points.len() > limit {
            points = points.split_off(points.len() - limit);
        }
        Ok(points)
    }

    pub fn attach_worker_to_run(&self, run_id: &str, worker_id: u64) -> Result<RunMetadata> {
        let mut guard = self.state.lock().expect("run registry lock poisoned");
        let record = guard
            .runs
            .iter_mut()
            .find(|record| record.metadata.run_id == run_id)
            .ok_or_else(|| anyhow!("unknown run: {run_id}"))?;
        if !record.workers_seen.contains(&worker_id) {
            record.workers_seen.push(worker_id);
            record.workers_seen.sort_unstable();
            record.metadata.total_workers_seen = record.workers_seen.len() as u64;
        }
        let metadata = record.metadata.clone();
        self.persist(&guard)?;
        Ok(metadata)
    }

    pub fn update_checkpoint_step(&self, run_id: &str, checkpoint_step: u64) -> Result<RunMetadata> {
        let mut guard = self.state.lock().expect("run registry lock poisoned");
        let record = guard
            .runs
            .iter_mut()
            .find(|record| record.metadata.run_id == run_id)
            .ok_or_else(|| anyhow!("unknown run: {run_id}"))?;
        if checkpoint_step > record.metadata.latest_checkpoint_step {
            record.metadata.latest_checkpoint_step = checkpoint_step;
        }
        let metadata = record.metadata.clone();
        self.persist(&guard)?;
        Ok(metadata)
    }

    fn set_latest_metric_at(&self, run_id: &str, timestamp_ms: u64) -> Result<RunMetadata> {
        let mut guard = self.state.lock().expect("run registry lock poisoned");
        let record = guard
            .runs
            .iter_mut()
            .find(|record| record.metadata.run_id == run_id)
            .ok_or_else(|| anyhow!("unknown run: {run_id}"))?;
        if timestamp_ms >= record.metadata.latest_metric_at_ms {
            record.metadata.latest_metric_at_ms = timestamp_ms;
        }
        let metadata = record.metadata.clone();
        self.persist(&guard)?;
        Ok(metadata)
    }

    fn require_run(&self, run_id: &str) -> Result<()> {
        let guard = self.state.lock().expect("run registry lock poisoned");
        if guard
            .runs
            .iter()
            .any(|record| record.metadata.run_id == run_id)
        {
            Ok(())
        } else {
            Err(anyhow!("unknown run: {run_id}"))
        }
    }

    fn metrics_path(&self, run_id: &str) -> PathBuf {
        self.metrics_dir.join(format!("{run_id}.json"))
    }

    fn load_metric_points(&self, run_id: &str) -> Result<Vec<RunMetricPoint>> {
        let path = self.metrics_path(run_id);
        if !path.is_file() {
            return Ok(Vec::new());
        }
        let bytes =
            fs::read(&path).with_context(|| format!("read {}", path.display()))?;
        let file: RunMetricsFile =
            serde_json::from_slice(&bytes).context("parse run metrics file")?;
        Ok(file.points)
    }

    fn append_metric_point(&self, point: &RunMetricPoint) -> Result<()> {
        let path = self.metrics_path(&point.run_id);
        let mut file = if path.is_file() {
            let bytes =
                fs::read(&path).with_context(|| format!("read {}", path.display()))?;
            serde_json::from_slice::<RunMetricsFile>(&bytes).context("parse run metrics file")?
        } else {
            RunMetricsFile {
                run_id: point.run_id.clone(),
                points: Vec::new(),
            }
        };
        file.points.push(point.clone());
        let bytes = serde_json::to_vec_pretty(&file).context("serialize run metrics file")?;
        fs::write(&path, bytes).with_context(|| format!("write {}", path.display()))?;
        Ok(())
    }

    fn persist(&self, state: &RegistryState) -> Result<()> {
        let bytes = serde_json::to_vec_pretty(state).context("serialize run registry")?;
        fs::write(&self.registry_path, bytes)
            .with_context(|| format!("write {}", self.registry_path.display()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn create_and_list_runs() -> Result<()> {
        let dir = tempdir()?;
        let registry = RunRegistry::new(dir.path())?;
        let run = registry.create_run("protein-model", "exp-1", vec!["baseline".to_string()])?;
        assert_eq!(run.project_name, "protein-model");
        assert_eq!(run.status, RunStatus::Running);
        assert_eq!(run.tags, vec!["baseline"]);

        let runs = registry.list_runs()?;
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0].run_id, run.run_id);
        Ok(())
    }

    #[test]
    fn get_run_and_update_metrics() -> Result<()> {
        let dir = tempdir()?;
        let registry = RunRegistry::new(dir.path())?;
        let run = registry.create_run("p", "r", vec![])?;
        let fetched = registry.get_run(&run.run_id)?.expect("run");
        assert_eq!(fetched.run_name, "r");

        let updated = registry.update_run_metrics(
            &run.run_id,
            10,
            Some(0.5),
            RunLoggedMetrics {
                loss: Some(0.5),
                learning_rate: Some(0.01),
                throughput: Some(100.0),
            },
        )?;
        assert_eq!(updated.latest_step, 10);
        assert_eq!(updated.latest_loss, Some(0.5));
        assert_eq!(updated.metrics.learning_rate, Some(0.01));
        Ok(())
    }

    #[test]
    fn append_and_list_run_metrics() -> Result<()> {
        let dir = tempdir()?;
        let registry = RunRegistry::new(dir.path())?;
        let run = registry.create_run("p", "r", vec![])?;

        let mut step_one = HashMap::new();
        step_one.insert("loss".to_string(), 1.0);
        registry.append_run_metrics(&run.run_id, 1, step_one)?;

        let mut step_two = HashMap::new();
        step_two.insert("loss".to_string(), 0.5);
        let (_, point) = registry.append_run_metrics(&run.run_id, 2, step_two)?;
        assert_eq!(point.step, 2);

        let history = registry.list_run_metrics(&run.run_id, 0)?;
        assert_eq!(history.len(), 2);
        assert_eq!(history[0].metrics.get("loss"), Some(&1.0));
        assert_eq!(history[1].metrics.get("loss"), Some(&0.5));

        let latest = registry.get_run(&run.run_id)?.expect("run");
        assert_eq!(latest.latest_step, 2);
        assert_eq!(latest.latest_loss, Some(0.5));
        assert!(latest.latest_metric_at_ms > 0);

        let limited = registry.list_run_metrics(&run.run_id, 1)?;
        assert_eq!(limited.len(), 1);
        assert_eq!(limited[0].step, 2);

        assert!(dir.path().join("metrics").join(format!("{}.json", run.run_id)).is_file());
        Ok(())
    }

    #[test]
    fn attach_worker_and_complete() -> Result<()> {
        let dir = tempdir()?;
        let registry = RunRegistry::new(dir.path())?;
        let run = registry.create_run("p", "r", vec![])?;
        let with_worker = registry.attach_worker_to_run(&run.run_id, 2)?;
        assert_eq!(with_worker.total_workers_seen, 1);
        registry.attach_worker_to_run(&run.run_id, 2)?;
        let again = registry.get_run(&run.run_id)?.expect("run");
        assert_eq!(again.total_workers_seen, 1);

        let completed = registry.update_run_status(&run.run_id, RunStatus::Completed)?;
        assert_eq!(completed.status, RunStatus::Completed);
        Ok(())
    }
}
