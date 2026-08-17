//! Fetching the one file too big to ship inside anything else: the YOLO weight.
//!
//! `weights/best.pt` is 114 MB and deliberately untracked, which today means an install step
//! that reads "run this `gdown` command" — something an operator will never do. The launcher
//! downloads it on first run instead, which is only bearable if the window can show progress
//! while it happens; hence a trait, so the orchestrator can report bytes as they arrive and
//! tests can drive the whole flow without a network.

use std::io::Read;
use std::path::Path;

use sha2::{Digest, Sha256};

/// Called with (bytes received so far, total if the server declared one).
pub type ProgressFn<'a> = &'a mut dyn FnMut(u64, Option<u64>);

pub trait Downloader {
    fn download(&self, url: &str, dest: &Path, progress: ProgressFn<'_>) -> Result<(), String>;
}

pub struct UreqDownloader {
    pub timeout: std::time::Duration,
}

impl Default for UreqDownloader {
    fn default() -> Self {
        Self {
            // Generous: a 114 MB file over a slow line, not a health poll.
            timeout: std::time::Duration::from_secs(60 * 30),
        }
    }
}

impl Downloader for UreqDownloader {
    fn download(&self, url: &str, dest: &Path, progress: ProgressFn<'_>) -> Result<(), String> {
        if let Some(parent) = dest.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|err| format!("Could not create {}: {err}", parent.display()))?;
        }

        let agent = ureq::AgentBuilder::new().timeout_read(self.timeout).build();
        let response = agent
            .get(url)
            .call()
            .map_err(|err| format!("Could not download {url}: {err}"))?;
        let total: Option<u64> = response
            .header("Content-Length")
            .and_then(|value| value.parse().ok());

        // Written under a temporary name and renamed only once the last byte has arrived, so an
        // interrupted download can never be mistaken for a model file on the next launch (the
        // same rule the weight upload endpoint applies, backend/app/settings/models_service.py).
        let partial = dest.with_extension("part");
        let mut file = std::fs::File::create(&partial)
            .map_err(|err| format!("Could not write {}: {err}", partial.display()))?;
        let mut reader = response.into_reader();
        let mut buffer = vec![0u8; 256 * 1024];
        let mut received: u64 = 0;
        progress(0, total);

        loop {
            let read = reader
                .read(&mut buffer)
                .map_err(|err| format!("Download of {url} was interrupted: {err}"))?;
            if read == 0 {
                break;
            }
            std::io::Write::write_all(&mut file, &buffer[..read])
                .map_err(|err| format!("Could not write {}: {err}", partial.display()))?;
            received += read as u64;
            progress(received, total);
        }
        drop(file);

        if let Some(total) = total {
            if received != total {
                let _ = std::fs::remove_file(&partial);
                return Err(format!(
                    "Download of {url} ended early: {received} of {total} bytes."
                ));
            }
        }

        // A byte count matching the server's own Content-Length proves the transfer wasn't cut
        // short, not that the bytes are the ones that were meant to be there. A checksum
        // published next to the asset (the same file name with `.sha256` appended, the
        // convention `sha256sum` output already follows) catches a swapped or corrupted asset
        // that a length check alone would wave through. Not every release publishes one — a
        // request that 404s or otherwise fails is treated as "nothing to check against", not an
        // error — so this only strengthens the guarantee where the asset actually offers it.
        if let Ok(response) = agent.get(&format!("{url}.sha256")).call() {
            if let Ok(body) = response.into_string() {
                if let Some(expected) = parse_published_checksum(&body) {
                    let actual = sha256_hex_of_file(&partial)
                        .map_err(|err| format!("Could not verify {}: {err}", partial.display()))?;
                    if !actual.eq_ignore_ascii_case(&expected) {
                        let _ = std::fs::remove_file(&partial);
                        return Err(format!(
                            "Downloaded {url} does not match its published checksum \
                             (expected {expected}, got {actual}) — the file may be corrupted \
                             or the release asset may have changed."
                        ));
                    }
                }
            }
        }

        std::fs::rename(&partial, dest)
            .map_err(|err| format!("Could not finish writing {}: {err}", dest.display()))
    }
}

/// Pulls the hex digest out of a checksum file's body, accepting either a bare digest or the
/// `<digest>  <filename>` format `sha256sum` writes. Anything that isn't 64 hex characters is
/// not a checksum this can act on.
fn parse_published_checksum(body: &str) -> Option<String> {
    let token = body.split_whitespace().next()?;
    (token.len() == 64 && token.bytes().all(|b| b.is_ascii_hexdigit()))
        .then(|| token.to_lowercase())
}

fn sha256_hex_of_file(path: &Path) -> Result<String, String> {
    let mut file = std::fs::File::open(path)
        .map_err(|err| format!("Could not open {}: {err}", path.display()))?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; 256 * 1024];
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|err| format!("Could not read {}: {err}", path.display()))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_a_bare_digest() {
        let digest = "a".repeat(64);
        assert_eq!(parse_published_checksum(&digest), Some(digest));
    }

    #[test]
    fn parses_the_sha256sum_output_format() {
        let digest = "b".repeat(64);
        assert_eq!(
            parse_published_checksum(&format!("{digest}  best.pt\n")),
            Some(digest)
        );
    }

    #[test]
    fn uppercase_digests_are_normalized() {
        let digest = "C".repeat(64);
        assert_eq!(parse_published_checksum(&digest), Some("c".repeat(64)));
    }

    #[test]
    fn rejects_anything_that_is_not_a_64_character_hex_string() {
        assert_eq!(parse_published_checksum(""), None);
        assert_eq!(parse_published_checksum("not a checksum"), None);
        assert_eq!(parse_published_checksum(&"a".repeat(63)), None);
        assert_eq!(parse_published_checksum(&"g".repeat(64)), None);
    }

    #[test]
    fn hashes_a_file_to_its_known_sha256() {
        let path =
            std::env::temp_dir().join(format!("pcb-launcher-sha256-test-{}", std::process::id()));
        std::fs::write(&path, b"hello world").unwrap();

        let digest = sha256_hex_of_file(&path).unwrap();

        std::fs::remove_file(&path).unwrap();
        assert_eq!(
            digest,
            "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        );
    }
}

#[cfg(test)]
pub mod testing {
    use super::*;
    use std::cell::RefCell;

    /// Writes fixed contents instead of making a request, recording every URL it was asked for
    /// so a test can assert the download was skipped when the file was already there.
    pub struct FakeDownloader {
        contents: Result<Vec<u8>, String>,
        pub requested: RefCell<Vec<String>>,
    }

    impl FakeDownloader {
        pub fn serving(contents: &[u8]) -> Self {
            Self {
                contents: Ok(contents.to_vec()),
                requested: RefCell::new(Vec::new()),
            }
        }

        pub fn failing(error: &str) -> Self {
            Self {
                contents: Err(error.to_string()),
                requested: RefCell::new(Vec::new()),
            }
        }
    }

    impl Downloader for FakeDownloader {
        fn download(&self, url: &str, dest: &Path, progress: ProgressFn<'_>) -> Result<(), String> {
            self.requested.borrow_mut().push(url.to_string());
            let contents = self.contents.clone()?;
            if let Some(parent) = dest.parent() {
                std::fs::create_dir_all(parent).map_err(|err| err.to_string())?;
            }
            let total = contents.len() as u64;
            progress(0, Some(total));
            std::fs::write(dest, &contents).map_err(|err| err.to_string())?;
            progress(total, Some(total));
            Ok(())
        }
    }
}
