/// Mirrors the subset of `GET /health` (backend/app/core/health.py::HealthReport) the
/// launcher cares about: is the stack ready to use, or not yet/never.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HealthStatus {
    /// `{"status": "ok"}` — every check passed (an unconfigured LLM reports `not_configured`,
    /// which the backend itself already folds into "ok", per PRD's no-LLM Phase 1 demo).
    Ok,
    /// `{"status": "degraded"}` — server responded, but at least one component (db, redis,
    /// worker, watch_root) is unhealthy. Distinct from "unreachable" because it means the
    /// containers *are* up; something inside them isn't.
    Degraded(String),
    /// Connection refused/timed out/DNS failure — most common early in startup, before the
    /// `api` container has finished booting.
    Unreachable(String),
}

/// Abstraction over "GET a URL and read the body", so orchestration logic can be tested
/// without a real HTTP server.
pub trait HealthClient {
    fn get_health(&self, url: &str) -> HealthStatus;
}

/// Real implementation using `ureq` (blocking, no async runtime needed for a poll loop this
/// simple).
pub struct UreqHealthClient {
    pub timeout: std::time::Duration,
}

impl Default for UreqHealthClient {
    fn default() -> Self {
        Self {
            timeout: std::time::Duration::from_secs(3),
        }
    }
}

impl HealthClient for UreqHealthClient {
    fn get_health(&self, url: &str) -> HealthStatus {
        let agent = ureq::AgentBuilder::new().timeout(self.timeout).build();
        match agent.get(url).call() {
            Ok(response) => match response.into_string() {
                Ok(body) => parse_health_body(&body),
                Err(err) => {
                    HealthStatus::Unreachable(format!("could not read response body: {err}"))
                }
            },
            Err(ureq::Error::Status(code, response)) => {
                let detail = response
                    .into_string()
                    .unwrap_or_else(|_| "<unreadable body>".to_string());
                HealthStatus::Degraded(format!("HTTP {code}: {detail}"))
            }
            Err(err) => HealthStatus::Unreachable(err.to_string()),
        }
    }
}

fn parse_health_body(body: &str) -> HealthStatus {
    match serde_json::from_str::<serde_json::Value>(body) {
        Ok(value) => match value.get("status").and_then(|s| s.as_str()) {
            Some("ok") => HealthStatus::Ok,
            Some(other) => HealthStatus::Degraded(format!("status={other}: {body}")),
            None => HealthStatus::Degraded(format!("no `status` field in response: {body}")),
        },
        Err(err) => HealthStatus::Degraded(format!("invalid JSON from /health: {err}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_ok_status() {
        assert_eq!(parse_health_body(r#"{"status":"ok"}"#), HealthStatus::Ok);
    }

    #[test]
    fn parses_degraded_status() {
        assert!(matches!(
            parse_health_body(r#"{"status":"degraded","db":{"status":"error"}}"#),
            HealthStatus::Degraded(_)
        ));
    }

    #[test]
    fn treats_malformed_body_as_degraded_not_a_crash() {
        assert!(matches!(
            parse_health_body("not json"),
            HealthStatus::Degraded(_)
        ));
    }
}

#[cfg(test)]
pub mod testing {
    use super::*;
    use std::cell::RefCell;

    /// Scripted stand-in for the HTTP client: returns the next entry in the queue on each
    /// call, panicking if the orchestrator polls more times than the test anticipated.
    pub struct FakeHealthClient {
        responses: RefCell<Vec<HealthStatus>>,
    }

    impl FakeHealthClient {
        pub fn new(responses: Vec<HealthStatus>) -> Self {
            Self {
                responses: RefCell::new(responses),
            }
        }

        /// Repeats the last response forever once the scripted queue is drained — handy for
        /// "never becomes healthy" timeout tests without having to enumerate every poll.
        pub fn repeating(final_response: HealthStatus, times: usize) -> Self {
            Self::new(std::iter::repeat_n(final_response, times).collect())
        }
    }

    impl HealthClient for FakeHealthClient {
        fn get_health(&self, _url: &str) -> HealthStatus {
            let mut responses = self.responses.borrow_mut();
            if responses.len() > 1 {
                responses.remove(0)
            } else if let Some(last) = responses.last() {
                last.clone()
            } else {
                panic!("FakeHealthClient ran out of scripted responses");
            }
        }
    }
}
