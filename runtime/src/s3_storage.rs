use std::sync::{Arc, OnceLock};

use anyhow::{Context, Result};
use aws_config::BehaviorVersion;
use aws_credential_types::Credentials;
use aws_sdk_s3::config::{Builder as S3ConfigBuilder, Region};
use aws_sdk_s3::primitives::ByteStream;
use aws_sdk_s3::Client;

use crate::storage::StorageBackend;

const CHECKPOINTS_SEGMENT: &str = "checkpoints";
const METADATA_OBJECT_NAME: &str = "metadata.json";
const PATH_PREFIX: &str = "checkpoints";

/// Configuration for an S3-compatible object store (AWS S3, MinIO, etc.).
#[derive(Debug, Clone)]
pub struct S3StorageConfig {
    pub endpoint_url: String,
    pub bucket: String,
    pub access_key: String,
    pub secret_key: String,
    pub region: String,
    pub prefix: String,
}

/// Object-store checkpoint backend (S3 API; works with MinIO without real AWS credentials).
pub struct S3StorageBackend {
    client: Client,
    bucket: String,
    prefix: String,
    path_prefix: String,
}

impl S3StorageBackend {
    pub fn new(config: S3StorageConfig) -> Result<Arc<dyn StorageBackend>> {
        let client = build_s3_client(&config)?;
        Ok(Arc::new(Self {
            client,
            bucket: config.bucket,
            prefix: normalize_prefix(&config.prefix),
            path_prefix: PATH_PREFIX.to_string(),
        }))
    }

    pub fn bucket(&self) -> &str {
        &self.bucket
    }

    pub fn prefix(&self) -> &str {
        &self.prefix
    }

    pub fn path_prefix(&self) -> &str {
        &self.path_prefix
    }

    /// Metadata-relative path returned to the checkpoint manager (same shape as local disk).
    pub fn metadata_path_for(&self, file_name: &str) -> String {
        format!(
            "{}/{}",
            self.path_prefix.trim_end_matches('/'),
            file_name
        )
    }

    /// Object key for a checkpoint blob: `<prefix>/checkpoints/<final_name>`.
    pub fn blob_object_key(&self, final_name: &str) -> String {
        object_key(&self.prefix, &[CHECKPOINTS_SEGMENT, final_name])
    }

    /// Object key for metadata: `<prefix>/metadata.json`.
    pub fn metadata_object_key(&self) -> String {
        object_key(&self.prefix, &[METADATA_OBJECT_NAME])
    }

    /// Map a metadata-relative path (e.g. `checkpoints/step_0001.ckpt`) to an object key.
    pub fn blob_object_key_from_metadata_path(&self, metadata_path: &str) -> String {
        object_key(&self.prefix, &[metadata_path.trim_start_matches('/')])
    }

    fn block_on<F: std::future::Future>(&self, future: F) -> F::Output {
        s3_runtime().block_on(future)
    }
}

impl StorageBackend for S3StorageBackend {
    fn ensure_dir(&self) -> Result<()> {
        self.block_on(async {
            self.client
                .head_bucket()
                .bucket(&self.bucket)
                .send()
                .await
                .with_context(|| {
                    format!(
                        "S3 bucket {:?} is not reachable (create it first, e.g. via docker compose)",
                        self.bucket
                    )
                })?;
            Ok::<(), anyhow::Error>(())
        })
    }

    /// Writes directly to the final object key (no rename). Metadata is written separately
    /// by the checkpoint manager only after this succeeds.
    fn write_atomic(&self, final_name: &str, data: &[u8]) -> Result<String> {
        self.ensure_dir()?;
        let key = self.blob_object_key(final_name);
        let body = ByteStream::from(data.to_vec());
        self.block_on(async {
            self.client
                .put_object()
                .bucket(&self.bucket)
                .key(&key)
                .body(body)
                .send()
                .await
                .with_context(|| format!("failed to put checkpoint object s3://{}/{}", self.bucket, key))?;
            Ok::<(), anyhow::Error>(())
        })?;
        Ok(self.metadata_path_for(final_name))
    }

    fn read(&self, path: &str) -> Result<Vec<u8>> {
        let key = self.blob_object_key_from_metadata_path(path);
        self.block_on(async {
            let response = self
                .client
                .get_object()
                .bucket(&self.bucket)
                .key(&key)
                .send()
                .await
                .with_context(|| format!("failed to get checkpoint object s3://{}/{}", self.bucket, key))?;
            let bytes = response
                .body
                .collect()
                .await
                .context("failed to read checkpoint object body")?
                .into_bytes()
                .to_vec();
            Ok(bytes)
        })
    }

    fn delete(&self, path: &str) -> Result<bool> {
        let key = self.blob_object_key_from_metadata_path(path);
        if !self.exists(path) {
            return Ok(false);
        }
        self.block_on(async {
            self.client
                .delete_object()
                .bucket(&self.bucket)
                .key(&key)
                .send()
                .await
                .with_context(|| {
                    format!("failed to delete checkpoint object s3://{}/{}", self.bucket, key)
                })?;
            Ok::<(), anyhow::Error>(())
        })?;
        Ok(true)
    }

    fn exists(&self, path: &str) -> bool {
        let key = self.blob_object_key_from_metadata_path(path);
        self.block_on(async {
            self.client
                .head_object()
                .bucket(&self.bucket)
                .key(&key)
                .send()
                .await
                .is_ok()
        })
    }

    fn read_metadata(&self) -> Result<Option<Vec<u8>>> {
        if !self.metadata_exists() {
            return Ok(None);
        }
        let key = self.metadata_object_key();
        self.block_on(async {
            let response = self
                .client
                .get_object()
                .bucket(&self.bucket)
                .key(&key)
                .send()
                .await
                .with_context(|| format!("failed to get metadata object s3://{}/{}", self.bucket, key))?;
            let bytes = response
                .body
                .collect()
                .await
                .context("failed to read metadata object body")?
                .into_bytes()
                .to_vec();
            Ok(Some(bytes))
        })
    }

    fn write_metadata(&self, data: &[u8]) -> Result<()> {
        self.ensure_dir()?;
        let key = self.metadata_object_key();
        let body = ByteStream::from(data.to_vec());
        self.block_on(async {
            self.client
                .put_object()
                .bucket(&self.bucket)
                .key(&key)
                .body(body)
                .send()
                .await
                .with_context(|| format!("failed to put metadata object s3://{}/{}", self.bucket, key))?;
            Ok::<(), anyhow::Error>(())
        })?;
        Ok(())
    }

    fn metadata_exists(&self) -> bool {
        let key = self.metadata_object_key();
        self.block_on(async {
            self.client
                .head_object()
                .bucket(&self.bucket)
                .key(&key)
                .send()
                .await
                .is_ok()
        })
    }
}

fn build_s3_client(config: &S3StorageConfig) -> Result<Client> {
    s3_runtime().block_on(async {
        let credentials = Credentials::new(
            &config.access_key,
            &config.secret_key,
            None,
            None,
            "faultline",
        );
        let shared_config = aws_config::defaults(BehaviorVersion::latest())
            .credentials_provider(credentials)
            .region(Region::new(config.region.clone()))
            .load()
            .await;
        let s3_config = S3ConfigBuilder::from(&shared_config)
            .endpoint_url(config.endpoint_url.clone())
            .force_path_style(true)
            .build();
        Ok(Client::from_conf(s3_config))
    })
}

fn s3_runtime() -> &'static tokio::runtime::Runtime {
    static RUNTIME: OnceLock<tokio::runtime::Runtime> = OnceLock::new();
    RUNTIME.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("failed to create S3 storage tokio runtime")
    })
}

fn normalize_prefix(prefix: &str) -> String {
    prefix.trim().trim_matches('/').to_string()
}

fn object_key(prefix: &str, segments: &[&str]) -> String {
    let joined = segments
        .iter()
        .map(|segment| segment.trim_matches('/'))
        .filter(|segment| !segment.is_empty())
        .collect::<Vec<_>>()
        .join("/");
    if prefix.is_empty() {
        joined
    } else {
        format!("{prefix}/{joined}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct KeyFixture {
        prefix: String,
    }

    impl KeyFixture {
        fn new(prefix: &str) -> Self {
            Self {
                prefix: normalize_prefix(prefix),
            }
        }

        fn blob_key(&self, final_name: &str) -> String {
            object_key(&self.prefix, &[CHECKPOINTS_SEGMENT, final_name])
        }

        fn metadata_key(&self) -> String {
            object_key(&self.prefix, &[METADATA_OBJECT_NAME])
        }

        fn blob_key_from_path(&self, metadata_path: &str) -> String {
            object_key(&self.prefix, &[metadata_path.trim_start_matches('/')])
        }
    }

    #[test]
    fn s3_object_keys_with_prefix() {
        let fixture = KeyFixture::new("faultline");
        assert_eq!(
            fixture.blob_key("step_0001.ckpt"),
            "faultline/checkpoints/step_0001.ckpt"
        );
        assert_eq!(fixture.metadata_key(), "faultline/metadata.json");
        assert_eq!(
            fixture.blob_key_from_path("checkpoints/step_0001.ckpt"),
            "faultline/checkpoints/step_0001.ckpt"
        );
    }

    #[test]
    fn s3_object_keys_without_prefix() {
        let fixture = KeyFixture::new("");
        assert_eq!(fixture.blob_key("step_0002.ckpt"), "checkpoints/step_0002.ckpt");
        assert_eq!(fixture.metadata_key(), "metadata.json");
    }

    #[test]
    fn metadata_path_for_matches_local_layout() {
        let backend_keys = KeyFixture::new("p");
        let metadata_path = format!("{}/{}", PATH_PREFIX, "step_0003.ckpt");
        assert_eq!(metadata_path, "checkpoints/step_0003.ckpt");
        assert_eq!(
            backend_keys.blob_key_from_path(&metadata_path),
            "p/checkpoints/step_0003.ckpt"
        );
    }
}
