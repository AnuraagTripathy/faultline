use std::collections::VecDeque;
use std::sync::Mutex;

use crate::dataset_registry::current_time_ms;

pub const DEFAULT_EVENT_LOG_CAPACITY: usize = 500;

/// Severity for a runtime event.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EventLevel {
    Info,
    Warn,
    Error,
}

impl EventLevel {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Info => "INFO",
            Self::Warn => "WARN",
            Self::Error => "ERROR",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "INFO" => Some(Self::Info),
            "WARN" => Some(Self::Warn),
            "ERROR" => Some(Self::Error),
            _ => None,
        }
    }
}

/// One append-only runtime observability event.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeEvent {
    pub event_id: u64,
    pub timestamp_ms: u64,
    pub level: EventLevel,
    pub event_type: String,
    pub worker_id: Option<u64>,
    pub dataset_name: Option<String>,
    pub shard_id: Option<u64>,
    pub step: Option<u64>,
    pub message: String,
}

/// Fields supplied when recording an event (`event_id` and `timestamp_ms` are assigned).
#[derive(Debug, Clone)]
pub struct RuntimeEventInput {
    pub level: EventLevel,
    pub event_type: String,
    pub worker_id: Option<u64>,
    pub dataset_name: Option<String>,
    pub shard_id: Option<u64>,
    pub step: Option<u64>,
    pub message: String,
}

impl RuntimeEventInput {
    pub fn new(
        level: EventLevel,
        event_type: impl Into<String>,
        message: impl Into<String>,
    ) -> Self {
        Self {
            level,
            event_type: event_type.into(),
            worker_id: None,
            dataset_name: None,
            shard_id: None,
            step: None,
            message: message.into(),
        }
    }

    pub fn worker_id(mut self, worker_id: u64) -> Self {
        self.worker_id = Some(worker_id);
        self
    }

    pub fn dataset_name(mut self, dataset_name: impl Into<String>) -> Self {
        self.dataset_name = Some(dataset_name.into());
        self
    }

    pub fn shard_id(mut self, shard_id: u64) -> Self {
        self.shard_id = Some(shard_id);
        self
    }

    pub fn step(mut self, step: u64) -> Self {
        self.step = Some(step);
        self
    }
}

/// In-memory ring buffer of recent runtime events (newest retained on overflow).
pub struct EventLog {
    capacity: usize,
    next_id: Mutex<u64>,
    events: Mutex<VecDeque<RuntimeEvent>>,
}

impl EventLog {
    pub fn new(capacity: usize) -> Self {
        Self {
            capacity: capacity.max(1),
            next_id: Mutex::new(1),
            events: Mutex::new(VecDeque::new()),
        }
    }

    pub fn record(&self, input: RuntimeEventInput) {
        let event_id = {
            let mut next = self.next_id.lock().expect("event log id lock poisoned");
            let id = *next;
            *next += 1;
            id
        };

        let event = RuntimeEvent {
            event_id,
            timestamp_ms: current_time_ms(),
            level: input.level,
            event_type: input.event_type,
            worker_id: input.worker_id,
            dataset_name: input.dataset_name,
            shard_id: input.shard_id,
            step: input.step,
            message: input.message,
        };

        let mut events = self.events.lock().expect("event log lock poisoned");
        events.push_back(event);
        while events.len() > self.capacity {
            events.pop_front();
        }
    }

    /// Return up to `limit` most recent events (newest first).
    pub fn list_events(&self, limit: usize) -> Vec<RuntimeEvent> {
        let events = self.events.lock().expect("event log lock poisoned");
        let take = limit.min(events.len());
        events.iter().rev().take(take).cloned().collect()
    }

    pub fn len(&self) -> usize {
        self.events.lock().expect("event log lock poisoned").len()
    }
}

pub fn record_event(log: &Option<std::sync::Arc<EventLog>>, input: RuntimeEventInput) {
    if let Some(log) = log {
        log.record(input);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ring_buffer_drops_oldest() {
        let log = EventLog::new(3);
        for index in 0..5 {
            log.record(RuntimeEventInput::new(
                EventLevel::Info,
                "test",
                format!("event {index}"),
            ));
        }
        let events = log.list_events(10);
        assert_eq!(events.len(), 3);
        assert_eq!(events[0].message, "event 4");
        assert_eq!(events[2].message, "event 2");
    }

    #[test]
    fn dataset_register_claim_complete_events() -> anyhow::Result<()> {
        use crate::dataset_registry::DatasetRegistry;
        use tempfile::tempdir;

        let dir = tempdir()?;
        let event_log = std::sync::Arc::new(EventLog::new(100));
        let registry = DatasetRegistry::new_with_event_log(dir.path(), Some(event_log.clone()))?;

        registry.register_dataset("train", 20, 10)?;
        let shard = registry
            .claim_next_shard(1, "train")?
            .expect("expected shard");
        registry.complete_shard(1, "train", shard.shard_id)?;

        let types: Vec<String> = event_log
            .list_events(10)
            .into_iter()
            .map(|event| event.event_type)
            .collect();

        assert!(types.iter().any(|t| t == "dataset_registered"));
        assert!(types.iter().any(|t| t == "shard_claimed"));
        assert!(types.iter().any(|t| t == "shard_completed"));
        Ok(())
    }
}
