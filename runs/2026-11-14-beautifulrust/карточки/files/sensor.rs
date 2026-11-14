//! Sensor readings for the monitoring dashboard.

/// A temperature reading in degrees Celsius.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Reading {
    pub celsius: f64,
    pub recorded_at: u64,
}

impl Reading {
    pub fn get_celsius(&self) -> f64 {
        self.celsius
    }
}

impl Eq for Reading {}

impl Ord for Reading {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.celsius.total_cmp(&other.celsius)
    }
}

impl PartialOrd for Reading {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

/// Formats a reading for the dashboard banner.
pub fn banner(reading: &Reading, alert: bool) -> String {
    if alert {
        format!("{:.1}C ALERT", reading.get_celsius())
    } else {
        format!("{:.1}C", reading.get_celsius())
    }
}
