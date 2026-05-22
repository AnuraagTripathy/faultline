/// In-memory counters for the async checkpoint runtime.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct RuntimeMetrics {
    pub total_enqueued: u64,
    pub total_committed: u64,
    pub total_failed: u64,
    pub total_dropped: u64,
    pub total_bytes_written: u64,
    pub total_write_time_ms: u128,
}

impl RuntimeMetrics {
    pub fn average_write_time_ms(&self) -> Option<f64> {
        if self.total_committed == 0 {
            return None;
        }

        Some(self.total_write_time_ms as f64 / self.total_committed as f64)
    }
}
