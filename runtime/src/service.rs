use std::io::{self, BufRead, BufReader, Write};
use std::path::Path;

use base64::Engine;
use serde::Serialize;

use crate::checkpoint_manager::CheckpointManager;
use crate::metadata::CheckpointEntry;

/// Incoming newline-delimited JSON command from a client.
#[derive(Debug, serde::Deserialize, PartialEq, Eq)]
#[serde(tag = "cmd", rename_all = "snake_case")]
pub enum ServiceCommand {
    #[serde(rename = "save")]
    Save { step: u64, data: String },
    #[serde(rename = "save_from_file")]
    SaveFromFile { step: u64, path: String },
    #[serde(rename = "save_worker_from_file")]
    SaveWorkerFromFile {
        worker_id: u64,
        local_step: u64,
        step: u64,
        path: String,
    },
    #[serde(rename = "list")]
    List,
    #[serde(rename = "latest")]
    Latest,
    #[serde(rename = "load_latest")]
    LoadLatest,
    #[serde(rename = "latest_for_worker")]
    LatestForWorker { worker_id: u64 },
    #[serde(rename = "load_latest_for_worker")]
    LoadLatestForWorker { worker_id: u64 },
    #[serde(rename = "prune")]
    Prune { keep_last: usize },
    #[serde(rename = "prune_per_worker")]
    PrunePerWorker { keep_last_per_worker: usize },
    #[serde(rename = "shutdown")]
    Shutdown,
}

/// JSON response written to stdout (one line per command).
#[derive(Debug, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub struct ServiceResponse {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub checkpoints: Option<Vec<CheckpointEntry>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub checkpoint: Option<Option<CheckpointEntry>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Option<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub deleted: Option<usize>,
}

impl ServiceResponse {
    pub fn error(message: impl Into<String>) -> Self {
        Self {
            ok: false,
            message: None,
            error: Some(message.into()),
            checkpoints: None,
            checkpoint: None,
            data: None,
            deleted: None,
        }
    }

    pub fn saved(step: u64) -> Self {
        Self {
            ok: true,
            message: Some(format!("saved checkpoint step {step}")),
            error: None,
            checkpoints: None,
            checkpoint: None,
            data: None,
            deleted: None,
        }
    }

    pub fn saved_from_file(step: u64) -> Self {
        Self {
            ok: true,
            message: Some(format!("saved checkpoint step {step} from file")),
            error: None,
            checkpoints: None,
            checkpoint: None,
            data: None,
            deleted: None,
        }
    }

    pub fn list(checkpoints: Vec<CheckpointEntry>) -> Self {
        Self {
            ok: true,
            message: None,
            error: None,
            checkpoints: Some(checkpoints),
            checkpoint: None,
            data: None,
            deleted: None,
        }
    }

    pub fn latest(checkpoint: Option<CheckpointEntry>) -> Self {
        Self {
            ok: true,
            message: None,
            error: None,
            checkpoints: None,
            checkpoint: Some(checkpoint),
            data: None,
            deleted: None,
        }
    }

    pub fn load_latest(data: Option<String>) -> Self {
        Self {
            ok: true,
            message: None,
            error: None,
            checkpoints: None,
            checkpoint: None,
            data: Some(data),
            deleted: None,
        }
    }

    pub fn saved_worker(worker_id: u64, local_step: u64, step: u64) -> Self {
        Self {
            ok: true,
            message: Some(format!(
                "saved worker {worker_id} checkpoint local_step {local_step} (step {step})"
            )),
            error: None,
            checkpoints: None,
            checkpoint: None,
            data: None,
            deleted: None,
        }
    }

    pub fn pruned(deleted: usize) -> Self {
        Self {
            ok: true,
            message: None,
            error: None,
            checkpoints: None,
            checkpoint: None,
            data: None,
            deleted: Some(deleted),
        }
    }

    pub fn shutting_down() -> Self {
        Self {
            ok: true,
            message: Some("shutting down".to_string()),
            error: None,
            checkpoints: None,
            checkpoint: None,
            data: None,
            deleted: None,
        }
    }
}

/// Read checkpoint bytes from a file path on disk.
pub fn read_checkpoint_file(path: &str) -> Result<Vec<u8>, String> {
    let trimmed = path.trim();
    if trimmed.is_empty() {
        return Err("invalid path".to_string());
    }

    let file_path = Path::new(trimmed);
    if !file_path.exists() {
        return Err(format!("missing file: {trimmed}"));
    }

    std::fs::read(file_path).map_err(|error| format!("unreadable file {trimmed}: {error}"))
}

/// Encode checkpoint bytes for the JSON `data` field in service mode.
/// ASCII UTF-8 text (JSON or base64 pickle written via `save`) is returned as-is.
/// Binary payloads (e.g. from `save_from_file`) are base64-encoded for safe transport.
pub fn encode_checkpoint_data_for_json(bytes: &[u8]) -> String {
    match std::str::from_utf8(bytes) {
        Ok(text) if text.is_empty() || text.bytes().all(|byte| byte.is_ascii()) => {
            text.to_string()
        }
        _ => base64::engine::general_purpose::STANDARD.encode(bytes),
    }
}

/// Handle one parsed command. Returns (response, should_shutdown).
pub fn handle_command(
    manager: &CheckpointManager,
    command: ServiceCommand,
) -> (ServiceResponse, bool) {
    match command {
        ServiceCommand::Save { step, data } => match manager.save_checkpoint(step, data.as_bytes()) {
            Ok(()) => (ServiceResponse::saved(step), false),
            Err(error) => (ServiceResponse::error(error.to_string()), false),
        },
        ServiceCommand::SaveFromFile { step, path } => {
            match read_checkpoint_file(&path).and_then(|bytes| {
                manager
                    .save_checkpoint(step, &bytes)
                    .map_err(|error| error.to_string())
            }) {
                Ok(()) => (ServiceResponse::saved_from_file(step), false),
                Err(error) => (ServiceResponse::error(error), false),
            }
        }
        ServiceCommand::SaveWorkerFromFile {
            worker_id,
            local_step,
            step,
            path,
        } => match read_checkpoint_file(&path).and_then(|bytes| {
            manager
                .save_worker_checkpoint(worker_id, local_step, step, &bytes)
                .map_err(|error| error.to_string())
        }) {
            Ok(()) => (ServiceResponse::saved_worker(worker_id, local_step, step), false),
            Err(error) => (ServiceResponse::error(error), false),
        },
        ServiceCommand::List => match manager.list_checkpoints() {
            Ok(checkpoints) => (ServiceResponse::list(checkpoints), false),
            Err(error) => (ServiceResponse::error(error.to_string()), false),
        },
        ServiceCommand::Latest => match manager.latest_checkpoint() {
            Ok(checkpoint) => (ServiceResponse::latest(checkpoint), false),
            Err(error) => (ServiceResponse::error(error.to_string()), false),
        },
        ServiceCommand::LoadLatest => match manager.load_latest() {
            Ok(Some(bytes)) => (
                ServiceResponse::load_latest(Some(encode_checkpoint_data_for_json(&bytes))),
                false,
            ),
            Ok(None) => (ServiceResponse::load_latest(None), false),
            Err(error) => (ServiceResponse::error(error.to_string()), false),
        },
        ServiceCommand::LatestForWorker { worker_id } => {
            match manager.latest_checkpoint_for_worker(worker_id) {
                Ok(checkpoint) => (ServiceResponse::latest(checkpoint), false),
                Err(error) => (ServiceResponse::error(error.to_string()), false),
            }
        }
        ServiceCommand::LoadLatestForWorker { worker_id } => {
            match manager.load_latest_for_worker(worker_id) {
                Ok(Some(bytes)) => (
                    ServiceResponse::load_latest(Some(encode_checkpoint_data_for_json(&bytes))),
                    false,
                ),
                Ok(None) => (ServiceResponse::load_latest(None), false),
                Err(error) => (ServiceResponse::error(error.to_string()), false),
            }
        }
        ServiceCommand::Prune { keep_last } => match manager.prune_checkpoints(keep_last) {
            Ok(deleted) => (ServiceResponse::pruned(deleted), false),
            Err(error) => (ServiceResponse::error(error.to_string()), false),
        },
        ServiceCommand::PrunePerWorker { keep_last_per_worker } => {
            match manager.prune_checkpoints_per_worker(keep_last_per_worker) {
                Ok(deleted) => (ServiceResponse::pruned(deleted), false),
                Err(error) => (ServiceResponse::error(error.to_string()), false),
            }
        }
        ServiceCommand::Shutdown => (ServiceResponse::shutting_down(), true),
    }
}

/// Parse a JSON line and dispatch to the checkpoint manager.
pub fn handle_line(manager: &CheckpointManager, line: &str) -> (ServiceResponse, bool) {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return (
            ServiceResponse::error("empty command line"),
            false,
        );
    }

    match serde_json::from_str::<ServiceCommand>(trimmed) {
        Ok(command) => handle_command(manager, command),
        Err(error) => {
            let message = if is_unknown_command_error(&error) {
                "unknown command".to_string()
            } else {
                format!("invalid JSON: {error}")
            };
            (ServiceResponse::error(message), false)
        }
    }
}

fn is_unknown_command_error(error: &serde_json::Error) -> bool {
    error.is_data() && error.to_string().contains("unknown variant")
}

pub fn write_response(writer: &mut impl Write, response: &ServiceResponse) -> io::Result<()> {
    let json = serde_json::to_string(response).map_err(io::Error::other)?;
    writeln!(writer, "{json}")?;
    writer.flush()?;
    Ok(())
}

/// Run the long-lived JSON line service on stdin/stdout.
pub fn run_service(manager: CheckpointManager) -> io::Result<()> {
    let stdin = io::stdin();
    let mut stdout = io::stdout();
    let reader = BufReader::new(stdin.lock());

    for line in reader.lines() {
        let line = match line {
            Ok(line) => line,
            Err(error) => {
                eprintln!("failed to read stdin: {error}");
                break;
            }
        };

        let (response, shutdown) = handle_line(&manager, &line);
        write_response(&mut stdout, &response)?;
        if shutdown {
            break;
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    fn manager_in_temp_dir(dir: &Path) -> CheckpointManager {
        CheckpointManager::new(dir.to_path_buf(), "checkpoints")
    }

    #[test]
    fn save_list_latest_load_latest_via_handler() {
        let temp = tempfile::tempdir().unwrap();
        let manager = manager_in_temp_dir(temp.path());

        let line = r#"{"cmd":"save","step":1,"data":"hello from service"}"#;
        let (response, shutdown) = handle_line(&manager, line);
        assert!(!shutdown);
        assert!(response.ok);
        assert_eq!(
            response.message.as_deref(),
            Some("saved checkpoint step 1")
        );

        let (response, _) = handle_line(&manager, r#"{"cmd":"list"}"#);
        assert!(response.ok);
        let checkpoints = response.checkpoints.expect("checkpoints");
        assert_eq!(checkpoints.len(), 1);
        assert_eq!(checkpoints[0].step, 1);

        let (response, _) = handle_line(&manager, r#"{"cmd":"latest"}"#);
        assert!(response.ok);
        let latest = response.checkpoint.expect("checkpoint field");
        assert_eq!(latest.as_ref().map(|e| e.step), Some(1));

        let (response, _) = handle_line(&manager, r#"{"cmd":"load_latest"}"#);
        assert!(response.ok);
        assert_eq!(
            response.data.as_ref().and_then(|value| value.as_deref()),
            Some("hello from service")
        );
    }

    #[test]
    fn prune_and_shutdown() {
        let temp = tempfile::tempdir().unwrap();
        let manager = manager_in_temp_dir(temp.path());

        handle_line(
            &manager,
            r#"{"cmd":"save","step":1,"data":"one"}"#,
        );
        handle_line(
            &manager,
            r#"{"cmd":"save","step":2,"data":"two"}"#,
        );

        let (response, _) = handle_line(&manager, r#"{"cmd":"prune","keep_last":1}"#);
        assert!(response.ok);
        assert_eq!(response.deleted, Some(1));

        let (response, shutdown) = handle_line(&manager, r#"{"cmd":"shutdown"}"#);
        assert!(response.ok);
        assert_eq!(response.message.as_deref(), Some("shutting down"));
        assert!(shutdown);
    }

    #[test]
    fn encode_checkpoint_data_for_json_binary_uses_base64() {
        let bytes = vec![0x80, 0x81, 0xff, 0x00];
        let encoded = encode_checkpoint_data_for_json(&bytes);
        assert_eq!(
            encoded,
            base64::engine::general_purpose::STANDARD.encode(&bytes)
        );
    }

    #[test]
    fn save_from_file_binary_round_trips_via_load_latest() {
        let temp = tempfile::tempdir().unwrap();
        let manager = manager_in_temp_dir(temp.path());
        let payload_file = temp.path().join("payload.bin");
        let binary = vec![0x80, 0x81, 0xff, 0x00, 0x9d, 0x42];
        std::fs::write(&payload_file, &binary).unwrap();

        let path_json = serde_json::to_string(&payload_file.to_string_lossy()).unwrap();
        let save_line = format!(r#"{{"cmd":"save_from_file","step":3,"path":{path_json}}}"#);
        let (response, _) = handle_line(&manager, &save_line);
        assert!(response.ok);

        let (response, _) = handle_line(&manager, r#"{"cmd":"load_latest"}"#);
        assert!(response.ok);
        let data = response
            .data
            .expect("data")
            .expect("checkpoint data");
        let decoded = base64::engine::general_purpose::STANDARD
            .decode(data)
            .expect("base64 data");
        assert_eq!(decoded, binary);
    }

    #[test]
    fn save_from_file_reads_payload_bytes() {
        let temp = tempfile::tempdir().unwrap();
        let manager = manager_in_temp_dir(temp.path());
        let payload_file = temp.path().join("payload.bin");
        std::fs::write(&payload_file, b"checkpoint bytes from file").unwrap();

        let path_json = serde_json::to_string(&payload_file.to_string_lossy()).unwrap();
        let line = format!(r#"{{"cmd":"save_from_file","step":7,"path":{path_json}}}"#);
        let (response, shutdown) = handle_line(&manager, &line);

        assert!(!shutdown);
        assert!(response.ok);
        assert_eq!(
            response.message.as_deref(),
            Some("saved checkpoint step 7 from file")
        );

        let (response, _) = handle_line(&manager, r#"{"cmd":"load_latest"}"#);
        assert_eq!(
            response.data.as_ref().and_then(|value| value.as_deref()),
            Some("checkpoint bytes from file")
        );
    }

    #[test]
    fn save_from_file_missing_file_returns_error() {
        let temp = tempfile::tempdir().unwrap();
        let manager = manager_in_temp_dir(temp.path());
        let missing = temp.path().join("does-not-exist.bin");
        let path_json = serde_json::to_string(&missing.to_string_lossy()).unwrap();
        let line = format!(r#"{{"cmd":"save_from_file","step":1,"path":{path_json}}}"#);

        let (response, _) = handle_line(&manager, &line);
        assert!(!response.ok);
        assert!(response.error.unwrap().starts_with("missing file:"));
    }

    #[test]
    fn save_worker_from_file_and_latest_for_worker() {
        let temp = tempfile::tempdir().unwrap();
        let manager = manager_in_temp_dir(temp.path());
        let payload_file = temp.path().join("worker.bin");
        std::fs::write(&payload_file, b"worker payload").unwrap();
        let path_json = serde_json::to_string(&payload_file.to_string_lossy()).unwrap();
        let save_line = format!(
            r#"{{"cmd":"save_worker_from_file","worker_id":1,"local_step":10,"step":1000010,"path":{path_json}}}"#
        );
        let (response, _) = handle_line(&manager, &save_line);
        assert!(response.ok);

        let (response, _) =
            handle_line(&manager, r#"{"cmd":"latest_for_worker","worker_id":1}"#);
        assert!(response.ok);
        let checkpoint = response.checkpoint.expect("checkpoint").expect("entry");
        assert_eq!(checkpoint.worker_id, Some(1));
        assert_eq!(checkpoint.local_step, Some(10));

        let (response, _) =
            handle_line(&manager, r#"{"cmd":"load_latest_for_worker","worker_id":1}"#);
        assert_eq!(
            response.data.as_ref().and_then(|value| value.as_deref()),
            Some("worker payload")
        );
    }

    #[test]
    fn invalid_json_and_unknown_command() {
        let temp = tempfile::tempdir().unwrap();
        let manager = manager_in_temp_dir(temp.path());

        let (response, _) = handle_line(&manager, "not json");
        assert!(!response.ok);
        assert!(response.error.unwrap().starts_with("invalid JSON:"));

        let (response, _) = handle_line(&manager, r#"{"cmd":"nope"}"#);
        assert!(!response.ok);
        assert_eq!(response.error.as_deref(), Some("unknown command"));
    }
}
