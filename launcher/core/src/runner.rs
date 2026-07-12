use std::io;
use std::path::Path;
use std::process::Command;

/// Result of running an external process, normalized so callers never have to deal with
/// platform-specific exit code representations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommandOutput {
    pub success: bool,
    pub stdout: String,
    pub stderr: String,
}

/// Abstraction over "run a program and get its output", so the orchestration logic in
/// `orchestrator.rs` can be unit-tested without ever invoking a real `docker` binary.
pub trait CommandRunner {
    fn run(&self, program: &str, args: &[&str], cwd: &Path) -> io::Result<CommandOutput>;
}

/// Real implementation, shells out via `std::process::Command`.
pub struct SystemCommandRunner;

impl CommandRunner for SystemCommandRunner {
    fn run(&self, program: &str, args: &[&str], cwd: &Path) -> io::Result<CommandOutput> {
        let output = Command::new(program).args(args).current_dir(cwd).output()?;
        Ok(CommandOutput {
            success: output.status.success(),
            stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
            stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
        })
    }
}

#[cfg(test)]
pub mod testing {
    use super::*;
    use std::cell::RefCell;

    /// Scripted stand-in for `docker`/`docker compose` invocations. Each call to `run` pops
    /// the next expected response off the front of the queue; tests assert the queue is
    /// fully drained (or intentionally leave extra entries for polling loops).
    pub struct FakeCommandRunner {
        responses: RefCell<Vec<io::Result<CommandOutput>>>,
        pub calls: RefCell<Vec<(String, Vec<String>)>>,
    }

    impl FakeCommandRunner {
        pub fn new(responses: Vec<io::Result<CommandOutput>>) -> Self {
            Self {
                responses: RefCell::new(responses),
                calls: RefCell::new(Vec::new()),
            }
        }

        pub fn ok(stdout: &str) -> io::Result<CommandOutput> {
            Ok(CommandOutput {
                success: true,
                stdout: stdout.to_string(),
                stderr: String::new(),
            })
        }

        pub fn failure(stderr: &str) -> io::Result<CommandOutput> {
            Ok(CommandOutput {
                success: false,
                stdout: String::new(),
                stderr: stderr.to_string(),
            })
        }

        pub fn not_found() -> io::Result<CommandOutput> {
            Err(io::Error::new(
                io::ErrorKind::NotFound,
                "docker: command not found",
            ))
        }
    }

    impl CommandRunner for FakeCommandRunner {
        fn run(&self, program: &str, args: &[&str], _cwd: &Path) -> io::Result<CommandOutput> {
            self.calls.borrow_mut().push((
                program.to_string(),
                args.iter().map(|s| s.to_string()).collect(),
            ));
            let mut responses = self.responses.borrow_mut();
            if responses.is_empty() {
                panic!("FakeCommandRunner ran out of scripted responses for `{program} {args:?}`");
            }
            responses.remove(0)
        }
    }
}
