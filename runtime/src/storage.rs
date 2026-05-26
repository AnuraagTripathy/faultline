use std::collections::HashMap;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use anyhow::{Context, Result};

use crate::s3_storage::{S3StorageBackend, S3StorageConfig};

const METADATA_FILE_NAME: &str = "metadata.json";

/// Pluggable checkpoint blob storage (local disk today; object stores later).
pub trait StorageBackend: Send + Sync {
    fn ensure_dir(&self) -> Result<()>;
    fn write_atomic(&self, final_name: &str, data: &[u8]) -> Result<String>;
    fn read(&self, path: &str) -> Result<Vec<u8>>;
    fn delete(&self, path: &str) -> Result<bool>;
    fn exists(&self, path: &str) -> bool;
    fn read_metadata(&self) -> Result<Option<Vec<u8>>>;
    fn write_metadata(&self, data: &[u8]) -> Result<()>;
    fn metadata_exists(&self) -> bool;
}

impl StorageBackend for Arc<InMemoryStorageBackend> {
    fn ensure_dir(&self) -> Result<()> {
        (**self).ensure_dir()
    }

    fn write_atomic(&self, final_name: &str, data: &[u8]) -> Result<String> {
        (**self).write_atomic(final_name, data)
    }

    fn read(&self, path: &str) -> Result<Vec<u8>> {
        (**self).read(path)
    }

    fn delete(&self, path: &str) -> Result<bool> {
        (**self).delete(path)
    }

    fn exists(&self, path: &str) -> bool {
        (**self).exists(path)
    }

    fn read_metadata(&self) -> Result<Option<Vec<u8>>> {
        (**self).read_metadata()
    }

    fn write_metadata(&self, data: &[u8]) -> Result<()> {
        (**self).write_metadata(data)
    }

    fn metadata_exists(&self) -> bool {
        (**self).metadata_exists()
    }
}

impl StorageBackend for Arc<dyn StorageBackend> {
    fn ensure_dir(&self) -> Result<()> {
        (**self).ensure_dir()
    }

    fn write_atomic(&self, final_name: &str, data: &[u8]) -> Result<String> {
        (**self).write_atomic(final_name, data)
    }

    fn read(&self, path: &str) -> Result<Vec<u8>> {
        (**self).read(path)
    }

    fn delete(&self, path: &str) -> Result<bool> {
        (**self).delete(path)
    }

    fn exists(&self, path: &str) -> bool {
        (**self).exists(path)
    }

    fn read_metadata(&self) -> Result<Option<Vec<u8>>> {
        (**self).read_metadata()
    }

    fn write_metadata(&self, data: &[u8]) -> Result<()> {
        (**self).write_metadata(data)
    }

    fn metadata_exists(&self) -> bool {
        (**self).metadata_exists()
    }
}

/// Local filesystem storage under a single checkpoint directory.
pub struct LocalStorageBackend {
    root_dir: PathBuf,
    path_prefix: String,
}

impl LocalStorageBackend {
    pub fn new(root_dir: PathBuf, path_prefix: impl Into<String>) -> Self {
        Self {
            root_dir,
            path_prefix: path_prefix.into(),
        }
    }

    pub fn root_dir(&self) -> &Path {
        &self.root_dir
    }

    pub fn path_prefix(&self) -> &str {
        &self.path_prefix
    }

    fn metadata_path_for(&self, file_name: &str) -> String {
        format!(
            "{}/{}",
            self.path_prefix.trim_end_matches('/'),
            file_name
        )
    }

    fn resolve_path(&self, metadata_path: &str) -> PathBuf {
        let file_name = Path::new(metadata_path)
            .file_name()
            .expect("checkpoint path in metadata should include a file name");
        self.root_dir.join(file_name)
    }

    fn metadata_file_path(&self) -> PathBuf {
        self.root_dir.join(METADATA_FILE_NAME)
    }
}

impl StorageBackend for LocalStorageBackend {
    fn ensure_dir(&self) -> Result<()> {
        if self.root_dir.exists() {
            return Ok(());
        }

        fs::create_dir_all(&self.root_dir).with_context(|| {
            format!(
                "failed to create checkpoint directory {}",
                self.root_dir.display()
            )
        })?;
        eprintln!("Created checkpoints directory");
        Ok(())
    }

    fn write_atomic(&self, final_name: &str, data: &[u8]) -> Result<String> {
        self.ensure_dir()?;

        let temp_path = self.root_dir.join(format!("{final_name}.tmp"));
        let final_path = self.root_dir.join(final_name);

        eprintln!("Writing temporary checkpoint");

        let mut file = File::create(&temp_path)
            .with_context(|| format!("failed to create {}", temp_path.display()))?;
        file.write_all(data)
            .with_context(|| format!("failed to write {}", temp_path.display()))?;
        file.flush()
            .with_context(|| format!("failed to flush {}", temp_path.display()))?;
        file.sync_all()
            .with_context(|| format!("failed to sync {}", temp_path.display()))?;

        fs::rename(&temp_path, &final_path).with_context(|| {
            format!(
                "failed to rename {} to {}",
                temp_path.display(),
                final_path.display()
            )
        })?;

        Ok(self.metadata_path_for(final_name))
    }

    fn read(&self, path: &str) -> Result<Vec<u8>> {
        let resolved = self.resolve_path(path);
        fs::read(&resolved).with_context(|| {
            format!("failed to read checkpoint file {}", resolved.display())
        })
    }

    fn delete(&self, path: &str) -> Result<bool> {
        let resolved = self.resolve_path(path);
        if !resolved.exists() {
            return Ok(false);
        }

        fs::remove_file(&resolved).with_context(|| {
            format!("failed to delete checkpoint file {}", resolved.display())
        })?;
        Ok(true)
    }

    fn exists(&self, path: &str) -> bool {
        self.resolve_path(path).exists()
    }

    fn read_metadata(&self) -> Result<Option<Vec<u8>>> {
        let metadata_path = self.metadata_file_path();
        if !metadata_path.exists() {
            return Ok(None);
        }

        let bytes = fs::read(&metadata_path).with_context(|| {
            format!(
                "failed to read metadata file {}",
                metadata_path.display()
            )
        })?;

        Ok(Some(bytes))
    }

    fn write_metadata(&self, data: &[u8]) -> Result<()> {
        self.ensure_dir()?;
        let metadata_path = self.metadata_file_path();
        fs::write(&metadata_path, data).with_context(|| {
            format!(
                "failed to write metadata file {}",
                metadata_path.display()
            )
        })?;
        Ok(())
    }

    fn metadata_exists(&self) -> bool {
        self.metadata_file_path().exists()
    }
}

/// In-memory storage for unit tests and failure simulation (not for production).
pub struct InMemoryStorageBackend {
    path_prefix: String,
    state: Arc<Mutex<InMemoryStorageState>>,
}

struct InMemoryStorageState {
    blobs: HashMap<String, Vec<u8>>,
    metadata: Option<Vec<u8>>,
}

impl InMemoryStorageBackend {
    pub fn new(path_prefix: impl Into<String>) -> Self {
        Self {
            path_prefix: path_prefix.into(),
            state: Arc::new(Mutex::new(InMemoryStorageState {
                blobs: HashMap::new(),
                metadata: None,
            })),
        }
    }

    pub fn path_prefix(&self) -> &str {
        &self.path_prefix
    }

    fn metadata_path_for(&self, file_name: &str) -> String {
        format!(
            "{}/{}",
            self.path_prefix.trim_end_matches('/'),
            file_name
        )
    }

    /// Checkpoint metadata paths currently stored (test helper).
    pub fn stored_paths(&self) -> Vec<String> {
        let state = self.state.lock().expect("in-memory storage lock poisoned");
        let mut paths: Vec<String> = state.blobs.keys().cloned().collect();
        paths.sort();
        paths
    }
}

impl StorageBackend for InMemoryStorageBackend {
    fn ensure_dir(&self) -> Result<()> {
        Ok(())
    }

    fn write_atomic(&self, final_name: &str, data: &[u8]) -> Result<String> {
        let metadata_path = self.metadata_path_for(final_name);
        let mut state = self.state.lock().expect("in-memory storage lock poisoned");
        state.blobs.insert(metadata_path.clone(), data.to_vec());
        Ok(metadata_path)
    }

    fn read(&self, path: &str) -> Result<Vec<u8>> {
        let state = self.state.lock().expect("in-memory storage lock poisoned");
        state
            .blobs
            .get(path)
            .cloned()
            .with_context(|| format!("checkpoint not found in memory: {path}"))
    }

    fn delete(&self, path: &str) -> Result<bool> {
        let mut state = self.state.lock().expect("in-memory storage lock poisoned");
        Ok(state.blobs.remove(path).is_some())
    }

    fn exists(&self, path: &str) -> bool {
        let state = self.state.lock().expect("in-memory storage lock poisoned");
        state.blobs.contains_key(path)
    }

    fn read_metadata(&self) -> Result<Option<Vec<u8>>> {
        let state = self.state.lock().expect("in-memory storage lock poisoned");
        Ok(state.metadata.clone())
    }

    fn write_metadata(&self, data: &[u8]) -> Result<()> {
        let mut state = self.state.lock().expect("in-memory storage lock poisoned");
        state.metadata = Some(data.to_vec());
        Ok(())
    }

    fn metadata_exists(&self) -> bool {
        let state = self.state.lock().expect("in-memory storage lock poisoned");
        state.metadata.is_some()
    }
}

#[derive(Default)]
struct FailureState {
    fail_next_write_atomic: bool,
    write_atomic_failures_remaining: u32,
    fail_next_read: bool,
    fail_next_delete: bool,
    fail_next_write_metadata: bool,
    fail_next_read_metadata: bool,
}

/// Wraps a storage backend and fails selected operations once (tests / reliability simulation).
pub struct FailureInjectingStorageBackend<B: StorageBackend> {
    inner: B,
    state: Arc<Mutex<FailureState>>,
}

impl<B: StorageBackend> FailureInjectingStorageBackend<B> {
    pub fn new(inner: B) -> Self {
        Self {
            inner,
            state: Arc::new(Mutex::new(FailureState::default())),
        }
    }

    pub fn inner(&self) -> &B {
        &self.inner
    }

    pub fn fail_next_write_atomic(&self) {
        self.state.lock().expect("failure injector lock poisoned").fail_next_write_atomic = true;
    }

    /// Fail the next `count` `write_atomic` calls (for retry / chaos tests).
    pub fn set_write_atomic_failures(&self, count: u32) {
        self.state
            .lock()
            .expect("failure injector lock poisoned")
            .write_atomic_failures_remaining = count;
    }

    pub fn fail_next_read(&self) {
        self.state.lock().expect("failure injector lock poisoned").fail_next_read = true;
    }

    pub fn fail_next_delete(&self) {
        self.state.lock().expect("failure injector lock poisoned").fail_next_delete = true;
    }

    pub fn fail_next_write_metadata(&self) {
        self.state
            .lock()
            .expect("failure injector lock poisoned")
            .fail_next_write_metadata = true;
    }

    pub fn fail_next_read_metadata(&self) {
        self.state
            .lock()
            .expect("failure injector lock poisoned")
            .fail_next_read_metadata = true;
    }

    fn take_failure<F>(&self, select: F) -> bool
    where
        F: FnOnce(&mut FailureState) -> &mut bool,
    {
        let mut state = self.state.lock().expect("failure injector lock poisoned");
        let flag = select(&mut state);
        if *flag {
            *flag = false;
            true
        } else {
            false
        }
    }

    fn take_write_atomic_failure(&self) -> bool {
        let mut state = self.state.lock().expect("failure injector lock poisoned");
        if state.write_atomic_failures_remaining > 0 {
            state.write_atomic_failures_remaining -= 1;
            true
        } else {
            false
        }
    }
}

impl<B: StorageBackend> StorageBackend for FailureInjectingStorageBackend<B> {
    fn ensure_dir(&self) -> Result<()> {
        self.inner.ensure_dir()
    }

    fn write_atomic(&self, final_name: &str, data: &[u8]) -> Result<String> {
        if self.take_failure(|state| &mut state.fail_next_write_atomic)
            || self.take_write_atomic_failure()
        {
            return Err(anyhow::anyhow!("injected write_atomic failure"));
        }
        self.inner.write_atomic(final_name, data)
    }

    fn read(&self, path: &str) -> Result<Vec<u8>> {
        if self.take_failure(|state| &mut state.fail_next_read) {
            return Err(anyhow::anyhow!("injected read failure"));
        }
        self.inner.read(path)
    }

    fn delete(&self, path: &str) -> Result<bool> {
        if self.take_failure(|state| &mut state.fail_next_delete) {
            return Err(anyhow::anyhow!("injected delete failure"));
        }
        self.inner.delete(path)
    }

    fn exists(&self, path: &str) -> bool {
        self.inner.exists(path)
    }

    fn read_metadata(&self) -> Result<Option<Vec<u8>>> {
        if self.take_failure(|state| &mut state.fail_next_read_metadata) {
            return Err(anyhow::anyhow!("injected read_metadata failure"));
        }
        self.inner.read_metadata()
    }

    fn write_metadata(&self, data: &[u8]) -> Result<()> {
        if self.take_failure(|state| &mut state.fail_next_write_metadata) {
            return Err(anyhow::anyhow!("injected write_metadata failure"));
        }
        self.inner.write_metadata(data)
    }

    fn metadata_exists(&self) -> bool {
        self.inner.metadata_exists()
    }
}

/// Build the storage backend used by `serve-grpc`.
pub fn build_grpc_storage_backend(
    storage_kind: &str,
    local_checkpoint_dir: PathBuf,
    s3_config: Option<S3StorageConfig>,
) -> Result<Arc<dyn StorageBackend>> {
    match storage_kind {
        "local" => Ok(Arc::new(LocalStorageBackend::new(
            local_checkpoint_dir,
            "checkpoints",
        ))),
        "s3" => {
            let config = s3_config.context(
                "S3 storage requires --s3-endpoint-url, --s3-bucket, --s3-access-key, and --s3-secret-key",
            )?;
            let backend = S3StorageBackend::new(config)?;
            Ok(backend)
        }
        other => anyhow::bail!(
            "unknown --storage value {other:?}; expected \"local\" or \"s3\""
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn backend_in_temp() -> (tempfile::TempDir, LocalStorageBackend) {
        let temp = tempfile::tempdir().unwrap();
        let backend = LocalStorageBackend::new(temp.path().to_path_buf(), "checkpoints");
        (temp, backend)
    }

    #[test]
    fn write_atomic_creates_final_file_and_no_tmp() -> Result<()> {
        let (_temp, backend) = backend_in_temp();

        let metadata_path = backend.write_atomic("step_0001.ckpt", b"hello")?;
        assert_eq!(metadata_path, "checkpoints/step_0001.ckpt");

        let final_path = backend.root_dir().join("step_0001.ckpt");
        let tmp_path = backend.root_dir().join("step_0001.ckpt.tmp");
        assert!(final_path.is_file());
        assert!(!tmp_path.exists());

        let bytes = backend.read(&metadata_path)?;
        assert_eq!(bytes, b"hello");

        Ok(())
    }

    #[test]
    fn delete_returns_true_when_file_existed() -> Result<()> {
        let (_temp, backend) = backend_in_temp();
        let metadata_path = backend.write_atomic("step_0002.ckpt", b"x")?;

        assert!(backend.delete(&metadata_path)?);
        assert!(!backend.exists(&metadata_path));

        Ok(())
    }

    #[test]
    fn delete_returns_false_when_file_missing() -> Result<()> {
        let (_temp, backend) = backend_in_temp();

        assert!(!backend.delete("checkpoints/missing.ckpt")?);

        Ok(())
    }

    #[test]
    fn read_metadata_missing_returns_none() -> Result<()> {
        let (_temp, backend) = backend_in_temp();

        assert!(!backend.metadata_exists());
        assert!(backend.read_metadata()?.is_none());

        Ok(())
    }

    #[test]
    fn write_metadata_then_read_metadata_round_trips_bytes() -> Result<()> {
        let (_temp, backend) = backend_in_temp();
        let payload = br#"{"latest_step":1,"checkpoints":[]}"#;

        backend.write_metadata(payload)?;
        assert!(backend.metadata_exists());

        let read_back = backend
            .read_metadata()?
            .expect("metadata should exist after write");
        assert_eq!(read_back, payload);

        Ok(())
    }

    fn in_memory_backend() -> InMemoryStorageBackend {
        InMemoryStorageBackend::new("checkpoints")
    }

    #[test]
    fn in_memory_write_atomic_and_read() -> Result<()> {
        let backend = in_memory_backend();
        let path = backend.write_atomic("step_0001.ckpt", b"payload")?;
        assert_eq!(path, "checkpoints/step_0001.ckpt");
        assert_eq!(backend.read(&path)?, b"payload");
        assert_eq!(backend.stored_paths(), vec!["checkpoints/step_0001.ckpt".to_string()]);
        Ok(())
    }

    #[test]
    fn in_memory_delete_removes_blob() -> Result<()> {
        let backend = in_memory_backend();
        let path = backend.write_atomic("step_0002.ckpt", b"x")?;
        assert!(backend.delete(&path)?);
        assert!(!backend.exists(&path));
        assert!(backend.stored_paths().is_empty());
        Ok(())
    }

    #[test]
    fn in_memory_metadata_read_write() -> Result<()> {
        let backend = in_memory_backend();
        assert!(!backend.metadata_exists());
        assert!(backend.read_metadata()?.is_none());

        let json = br#"{"latest_step":0,"checkpoints":[]}"#;
        backend.write_metadata(json)?;
        assert!(backend.metadata_exists());
        assert_eq!(backend.read_metadata()?.expect("metadata"), json);

        Ok(())
    }

    #[test]
    fn checkpoint_manager_with_in_memory_save_and_load() -> Result<()> {
        use std::sync::Arc;

        use crate::checkpoint_manager::CheckpointManager;

        let storage = Arc::new(in_memory_backend());
        let manager = CheckpointManager::with_storage(storage, 0);

        manager.save_checkpoint(1, b"in-memory")?;

        let data = manager.load_latest()?.expect("latest checkpoint bytes");
        assert_eq!(data, b"in-memory");

        Ok(())
    }

    #[test]
    fn checkpoint_manager_in_memory_latest_for_worker() -> Result<()> {
        use std::sync::Arc;

        use crate::checkpoint_manager::CheckpointManager;

        let storage = Arc::new(in_memory_backend());
        let manager = CheckpointManager::with_storage(storage, 0);

        manager.save_worker_checkpoint(2, 5, 2_000_005, b"five")?;
        manager.save_worker_checkpoint(2, 10, 2_000_010, b"ten")?;

        let latest = manager
            .latest_checkpoint_for_worker(2)?
            .expect("worker 2 latest");
        assert_eq!(latest.local_step, Some(10));
        assert_eq!(latest.step, 2_000_010);

        let bytes = manager
            .load_latest_for_worker(2)?
            .expect("worker 2 bytes");
        assert_eq!(bytes, b"ten");

        Ok(())
    }

    fn shared_in_memory() -> Arc<InMemoryStorageBackend> {
        Arc::new(in_memory_backend())
    }

    #[test]
    fn write_atomic_failure_prevents_metadata_commit() -> Result<()> {
        let inner = shared_in_memory();
        let failing = FailureInjectingStorageBackend::new(Arc::clone(&inner));
        failing.fail_next_write_atomic();
        let manager =
            crate::checkpoint_manager::CheckpointManager::with_storage(Arc::new(failing), 0);

        assert!(manager.save_checkpoint(1, b"data").is_err());
        assert!(!inner.metadata_exists());
        assert!(inner.stored_paths().is_empty());
        assert!(manager.list_checkpoints()?.is_empty());

        Ok(())
    }

    #[test]
    fn write_metadata_failure_leaves_blob_without_commit() -> Result<()> {
        let inner = shared_in_memory();
        let failing = FailureInjectingStorageBackend::new(Arc::clone(&inner));
        failing.fail_next_write_metadata();
        let manager =
            crate::checkpoint_manager::CheckpointManager::with_storage(Arc::new(failing), 0);

        assert!(manager.save_checkpoint(1, b"orphan blob").is_err());
        assert_eq!(
            inner.stored_paths(),
            vec!["checkpoints/step_0001.ckpt".to_string()]
        );
        assert!(!inner.metadata_exists());
        assert!(manager.list_checkpoints()?.is_empty());

        Ok(())
    }

    #[test]
    fn second_save_succeeds_after_injected_write_failure() -> Result<()> {
        let inner = shared_in_memory();
        let failing = FailureInjectingStorageBackend::new(Arc::clone(&inner));
        failing.fail_next_write_atomic();
        let manager =
            crate::checkpoint_manager::CheckpointManager::with_storage(Arc::new(failing), 0);

        assert!(manager.save_checkpoint(1, b"first").is_err());

        manager.save_checkpoint(2, b"second")?;
        let latest = manager.latest_checkpoint()?.expect("latest");
        assert_eq!(latest.step, 2);
        assert_eq!(manager.load_latest()?.expect("bytes"), b"second");

        Ok(())
    }

    #[test]
    fn read_failure_surfaces_from_load_latest() -> Result<()> {
        let inner = shared_in_memory();
        {
            let failing = FailureInjectingStorageBackend::new(Arc::clone(&inner));
            let manager =
                crate::checkpoint_manager::CheckpointManager::with_storage(Arc::new(failing), 0);
            manager.save_checkpoint(1, b"saved")?;
        }

        let failing = FailureInjectingStorageBackend::new(inner);
        failing.fail_next_read();
        let manager =
            crate::checkpoint_manager::CheckpointManager::with_storage(Arc::new(failing), 0);
        assert!(manager.load_latest().is_err());

        Ok(())
    }

    #[test]
    fn delete_failure_propagates_from_prune() -> Result<()> {
        let inner = shared_in_memory();
        {
            let failing = FailureInjectingStorageBackend::new(Arc::clone(&inner));
            let manager =
                crate::checkpoint_manager::CheckpointManager::with_storage(Arc::new(failing), 0);
            manager.save_checkpoint(1, b"one")?;
            manager.save_checkpoint(2, b"two")?;
            manager.save_checkpoint(3, b"three")?;
        }

        let failing = FailureInjectingStorageBackend::new(inner);
        failing.fail_next_delete();
        let manager =
            crate::checkpoint_manager::CheckpointManager::with_storage(Arc::new(failing), 0);

        let error = manager
            .prune_checkpoints(1)
            .expect_err("prune should fail on injected delete");
        assert!(
            error.to_string().contains("injected delete failure"),
            "unexpected error: {error}"
        );

        Ok(())
    }
}
