use std::sync::Mutex;

use crate::event_log::RuntimeEvent;
use crate::run_registry::{RunMetadata, RunMetricPoint, RunStatus};

/// Built-in alert rule kinds.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AlertType {
    CheckpointFailedOrPermanent,
    RunStale,
    MetricThreshold,
}

impl AlertType {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::CheckpointFailedOrPermanent => "checkpoint_failed_or_permanent",
            Self::RunStale => "run_stale",
            Self::MetricThreshold => "metric_threshold",
        }
    }
}

/// Comparison operator for metric threshold rules.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MetricComparison {
    Gt,
    Gte,
    Lt,
    Lte,
    Eq,
}

impl MetricComparison {
    pub fn parse(value: &str) -> Option<Self> {
        match value.trim().to_lowercase().as_str() {
            "gt" | ">" => Some(Self::Gt),
            "gte" | ">=" => Some(Self::Gte),
            "lt" | "<" => Some(Self::Lt),
            "lte" | "<=" => Some(Self::Lte),
            "eq" | "==" => Some(Self::Eq),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Gt => "gt",
            Self::Gte => "gte",
            Self::Lt => "lt",
            Self::Lte => "lte",
            Self::Eq => "eq",
        }
    }

    pub fn matches(self, value: f64, threshold: f64) -> bool {
        match self {
            Self::Gt => value > threshold,
            Self::Gte => value >= threshold,
            Self::Lt => value < threshold,
            Self::Lte => value <= threshold,
            Self::Eq => (value - threshold).abs() < f64::EPSILON,
        }
    }
}

/// Configurable alert rule (in-memory only).
#[derive(Debug, Clone, PartialEq)]
pub struct AlertRule {
    pub rule_id: String,
    pub alert_type: AlertType,
    pub enabled: bool,
    pub severity: String,
    pub stale_threshold_ms: Option<u64>,
    pub metric_name: Option<String>,
    pub threshold: Option<f64>,
    pub comparison: Option<MetricComparison>,
}

impl AlertRule {
    pub fn checkpoint_failures() -> Self {
        Self {
            rule_id: "default-checkpoint-failures".to_string(),
            alert_type: AlertType::CheckpointFailedOrPermanent,
            enabled: true,
            severity: "critical".to_string(),
            stale_threshold_ms: None,
            metric_name: None,
            threshold: None,
            comparison: None,
        }
    }

    pub fn run_stale(threshold_ms: u64) -> Self {
        Self {
            rule_id: "default-run-stale".to_string(),
            alert_type: AlertType::RunStale,
            enabled: true,
            severity: "warning".to_string(),
            stale_threshold_ms: Some(threshold_ms),
            metric_name: None,
            threshold: None,
            comparison: None,
        }
    }

    pub fn metric_threshold(
        rule_id: impl Into<String>,
        metric_name: impl Into<String>,
        threshold: f64,
        comparison: MetricComparison,
        severity: impl Into<String>,
    ) -> Self {
        Self {
            rule_id: rule_id.into(),
            alert_type: AlertType::MetricThreshold,
            enabled: true,
            severity: severity.into(),
            stale_threshold_ms: None,
            metric_name: Some(metric_name.into()),
            threshold: Some(threshold),
            comparison: Some(comparison),
        }
    }
}

/// One active alert produced by evaluation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Alert {
    pub alert_id: String,
    pub rule_id: String,
    pub alert_type: String,
    pub severity: String,
    pub run_id: Option<String>,
    pub message: String,
    pub timestamp_ms: u64,
    pub event_id: Option<u64>,
}

/// In-memory alert rules and last evaluation results.
pub struct AlertEngine {
    rules: Mutex<Vec<AlertRule>>,
    alerts: Mutex<Vec<Alert>>,
}

impl AlertEngine {
    pub fn with_defaults() -> Self {
        Self {
            rules: Mutex::new(vec![
                AlertRule::checkpoint_failures(),
                AlertRule::run_stale(60_000),
                AlertRule::metric_threshold(
                    "default-high-loss",
                    "loss",
                    10.0,
                    MetricComparison::Gt,
                    "warning",
                ),
            ]),
            alerts: Mutex::new(Vec::new()),
        }
    }

    pub fn list_rules(&self) -> Vec<AlertRule> {
        self.rules
            .lock()
            .expect("alert rules lock poisoned")
            .clone()
    }

    pub fn add_rule(&self, rule: AlertRule) {
        self.rules
            .lock()
            .expect("alert rules lock poisoned")
            .push(rule);
    }

    pub fn list_alerts(&self) -> Vec<Alert> {
        self.alerts
            .lock()
            .expect("alert list lock poisoned")
            .clone()
    }

    pub fn active_count(&self) -> u64 {
        self.list_alerts().len() as u64
    }

    pub fn evaluate(
        &self,
        runs: &[RunMetadata],
        events: &[RuntimeEvent],
        metric_points: impl Fn(&str) -> Vec<RunMetricPoint>,
        now_ms: u64,
    ) -> Vec<Alert> {
        let rules = self.list_rules();
        let mut alerts = Vec::new();

        for rule in rules.into_iter().filter(|rule| rule.enabled) {
            match rule.alert_type {
                AlertType::CheckpointFailedOrPermanent => {
                    evaluate_checkpoint_failures(&rule, events, &mut alerts);
                }
                AlertType::RunStale => {
                    let threshold = rule.stale_threshold_ms.unwrap_or(60_000);
                    evaluate_run_stale(&rule, runs, now_ms, threshold, &mut alerts);
                }
                AlertType::MetricThreshold => {
                    evaluate_metric_threshold(&rule, runs, &metric_points, &mut alerts);
                }
            }
        }

        alerts.sort_by(|left, right| right.timestamp_ms.cmp(&left.timestamp_ms));
        *self.alerts.lock().expect("alert list lock poisoned") = alerts.clone();
        alerts
    }
}

fn evaluate_checkpoint_failures(
    rule: &AlertRule,
    events: &[RuntimeEvent],
    alerts: &mut Vec<Alert>,
) {
    for event in events {
        if event.event_type != "checkpoint_failed"
            && event.event_type != "checkpoint_failed_permanent"
        {
            continue;
        }

        let severity = if event.event_type == "checkpoint_failed_permanent" {
            "critical"
        } else {
            rule.severity.as_str()
        };

        alerts.push(Alert {
            alert_id: format!("{}-event-{}", rule.rule_id, event.event_id),
            rule_id: rule.rule_id.clone(),
            alert_type: rule.alert_type.as_str().to_string(),
            severity: severity.to_string(),
            run_id: None,
            message: format!(
                "Checkpoint failure ({}) at step {:?}: {}",
                event.event_type, event.step, event.message
            ),
            timestamp_ms: event.timestamp_ms,
            event_id: Some(event.event_id),
        });
    }
}

fn evaluate_run_stale(
    rule: &AlertRule,
    runs: &[RunMetadata],
    now_ms: u64,
    threshold_ms: u64,
    alerts: &mut Vec<Alert>,
) {
    for run in runs {
        if run.status != RunStatus::Running {
            continue;
        }

        let last_activity = if run.latest_metric_at_ms > 0 {
            run.latest_metric_at_ms
        } else {
            run.created_at_ms
        };

        if now_ms.saturating_sub(last_activity) <= threshold_ms {
            continue;
        }

        let age_ms = now_ms.saturating_sub(last_activity);
        alerts.push(Alert {
            alert_id: format!("{}-{}", rule.rule_id, run.run_id),
            rule_id: rule.rule_id.clone(),
            alert_type: rule.alert_type.as_str().to_string(),
            severity: rule.severity.clone(),
            run_id: Some(run.run_id.clone()),
            message: format!(
                "Run {} is stale: no metrics for {} ms (threshold {} ms)",
                run.run_id, age_ms, threshold_ms
            ),
            timestamp_ms: now_ms,
            event_id: None,
        });
    }
}

fn evaluate_metric_threshold(
    rule: &AlertRule,
    runs: &[RunMetadata],
    metric_points: &impl Fn(&str) -> Vec<RunMetricPoint>,
    alerts: &mut Vec<Alert>,
) {
    let metric_name = match rule.metric_name.as_deref() {
        Some(name) => name,
        None => return,
    };
    let threshold = match rule.threshold {
        Some(value) => value,
        None => return,
    };
    let comparison = match rule.comparison {
        Some(op) => op,
        None => MetricComparison::Gt,
    };

    for run in runs {
        let points = metric_points(&run.run_id);
        for point in points {
            let Some(value) = point.metrics.get(metric_name).copied() else {
                continue;
            };
            if !comparison.matches(value, threshold) {
                continue;
            }

            alerts.push(Alert {
                alert_id: format!(
                    "{}-{}-step-{}",
                    rule.rule_id, run.run_id, point.step
                ),
                rule_id: rule.rule_id.clone(),
                alert_type: rule.alert_type.as_str().to_string(),
                severity: rule.severity.clone(),
                run_id: Some(run.run_id.clone()),
                message: format!(
                    "Run {} metric {}={} {} {} at step {}",
                    run.run_id,
                    metric_name,
                    value,
                    comparison.as_str(),
                    threshold,
                    point.step
                ),
                timestamp_ms: point.timestamp_ms,
                event_id: None,
            });
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event_log::EventLevel;

    fn sample_run(run_id: &str, status: RunStatus, latest_metric_at_ms: u64) -> RunMetadata {
        RunMetadata {
            run_id: run_id.to_string(),
            project_name: "proj".to_string(),
            run_name: "run".to_string(),
            created_at_ms: 1_000,
            status,
            total_workers_seen: 0,
            latest_step: 0,
            latest_checkpoint_step: 0,
            latest_metric_at_ms,
            latest_loss: None,
            tags: Vec::new(),
            metrics: Default::default(),
        }
    }

    #[test]
    fn stale_running_run_produces_alert() {
        let engine = AlertEngine::with_defaults();
        let now_ms = 200_000;
        let runs = vec![sample_run(
            "proj__run__1",
            RunStatus::Running,
            50_000,
        )];

        let alerts = engine.evaluate(&runs, &[], |_| Vec::new(), now_ms);
        assert!(alerts.iter().any(|alert| alert.alert_type == "run_stale"));
        assert!(
            alerts
                .iter()
                .any(|alert| alert.run_id.as_deref() == Some("proj__run__1"))
        );
    }

    #[test]
    fn checkpoint_failure_event_creates_alert() {
        let engine = AlertEngine::with_defaults();
        let event = RuntimeEvent {
            event_id: 42,
            timestamp_ms: 5_000,
            level: EventLevel::Error,
            event_type: "checkpoint_failed".to_string(),
            worker_id: Some(0),
            dataset_name: None,
            shard_id: None,
            step: Some(3),
            message: "write failed".to_string(),
        };

        let alerts = engine.evaluate(&[], &[event], |_| Vec::new(), 10_000);
        assert_eq!(alerts.len(), 1);
        assert_eq!(alerts[0].alert_type, "checkpoint_failed_or_permanent");
        assert_eq!(alerts[0].event_id, Some(42));
        assert!(alerts[0].message.contains("write failed"));
    }

    #[test]
    fn metric_threshold_alert() {
        let engine = AlertEngine::with_defaults();
        engine.add_rule(AlertRule::metric_threshold(
            "high-loss",
            "loss",
            10.0,
            MetricComparison::Gt,
            "warning",
        ));

        let runs = vec![sample_run("proj__run__1", RunStatus::Running, 9_000)];
        let points = vec![RunMetricPoint {
            run_id: "proj__run__1".to_string(),
            step: 5,
            timestamp_ms: 8_000,
            metrics: [("loss".to_string(), 12.5)].into_iter().collect(),
        }];

        let alerts = engine.evaluate(&runs, &[], |_| points.clone(), 9_000);
        assert!(alerts.iter().any(|alert| alert.alert_type == "metric_threshold"));
        assert!(alerts[0].message.contains("loss=12.5"));
    }
}
