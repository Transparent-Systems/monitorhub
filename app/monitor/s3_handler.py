"""
s3_handler.py
Author: John Zoetebier
Date: 2026-01-27

Description:
    This script implements the S3Handler class, which provides functionality
    to copy or delete files and folders using boto3 for S3 compatible storage providers.

Requirements:
- boto3 must be installed.
- S3 credentials and configuration should be set via environment variables
  (access_key_id, access_key_secret, S3_DEFAULT_REGION) or ~/.aws/ files.
- For non-S3 compatible providers, set endpoint_url environment variable.

See: 
    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html
    https://boto3.amazonaws.com/v1/documentation/api/latest/guide/quickstart.html
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

try:
    import boto3
except ImportError:
    print("boto3 not found. Please install it using 'pip install boto3'")
    boto3 = None

from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client
    from mypy_boto3_s3.type_defs import ObjectIdentifierTypeDef

from app.monitor.remote_handler import RemoteHandler
from app.monitor.s3_factory import S3Factory
from app.utils.path_filter import is_excluded


class S3Handler(RemoteHandler):
    """
    A class to copy or delete files and folders using boto3 for S3 compatible storage.
    Mimics RcloneHandler structure.
    """

    PROFILE_TYPE = "s3"
    CATEGORY = "remote"
    DESCRIPTION = "S3 compatible cloud storage (AWS S3, Cloudflare R2, Backblaze B2, etc.)"

    client: "S3Client"

    def __init__(
        self,
        base_monitor_path: str,
        base_remote_path: str,
        profile_config: dict,
        logger: logging.Logger | None = None,
        exclude_patterns: list[str] | None = None,
    ):
        """
        base_monitor_path     : local monitor path
        base_remote_path      : profile:bucket/prefix (e.g., "e2:mybucket/backups")
        profile_config        : profile configuration dictionary
        logger                : logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
        self.base_remote_path = Path(base_remote_path)
        self.base_monitor_path = Path(base_monitor_path)
        self.profile_config = profile_config
        self.exclude_patterns = exclude_patterns or []
    
        # Initializes the client once for the lifetime of the monitor.
        # Get client using S3Factory
        s3_factory = S3Factory(
            logger=self.logger
            )
        self.client = s3_factory.get_s3_client(
            profile_config=self.profile_config
        )

        reliable_performance_transfer_config = TransferConfig(
            # The file size at which to start using multipart uploads
            multipart_threshold=25 * 1024 * 1024,  # 25MB
            
            # The size of each chunk
            multipart_chunksize=5 * 1024 * 1024,  # 5MB
            
            # The maximum number of concurrent threads to use
            max_concurrency=4,
            
            # Use threads to improve speed
            use_threads=True,
            
            # If the transfer fails, how many times to retry the specific chunk
            num_download_attempts=10
            )

        # We may make the transfer config configurable in the future
        self.transfer_config = reliable_performance_transfer_config


    def _get_bucket_and_key(self, full_path: str) -> tuple[str, str]:
        """
        Splits a full path (e.g., "bucket/prefix/file.txt") into bucket and key.
        """
        # Ensure forward slashes
        full_path = full_path.replace("\\", "/")
        # Strip the storage identifier, the part till the first colon
        full_path = full_path.split(':', 1)[1] if ':' in full_path else full_path
        parts = full_path.split('/', 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        return bucket, key

    def _list_objects(self, bucket: str, prefix: str) -> list[dict]:
        """List all objects with the given prefix.

        Raises the underlying exception on failure instead of returning an
        empty list, so callers can distinguish "no objects" from "listing
        failed" and avoid reporting a failed operation as a success.
        """
        objects = []
        paginator = self.client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            if 'Contents' in page:
                objects.extend(page['Contents'])
        return objects

    def _calculate_md5(self, file_path: str) -> str:
        """Calculates the MD5 hash of a file."""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def get_remote_path(self, monitor_path: str) -> str:
        """
        Derives remote path from base monitor path and this monitor path.
        Returns a string path (bucket/prefix/...). 
        """
        monitor_path_obj = Path(monitor_path)
        try:
            relative_path = monitor_path_obj.relative_to(self.base_monitor_path)
        except ValueError:
            # Fallback if path is not relative to base_monitor_path
            relative_path = Path(monitor_path).name
        
        remote_path = self.base_remote_path / relative_path
        return remote_path.as_posix()

  
    def file_exists(self, remote_path: str) -> tuple[int, str]:
        """
        Check if remote path exists
        """
        bucket, key = self._get_bucket_and_key(remote_path)
        
        try:
            self.logger.debug(f"Check if path exists: s3://{bucket}/{key}")
            self.client.head_object(Bucket=bucket, Key=key)
            return (0, "")
        except Exception as e:  # noqa: BLE001
            self.logger.debug(f"Path does not exist: s3://{bucket}/{key}")
            return (1, str(e))

    def copy_file(self, monitor_path: str, remote_path: str | None = None) -> tuple[int, str]:
        """
        Copy monitor_path to remote_path.
        If remote_path is None, the remote_path is derived from the monitor_path
        Returns:
            (result_code, result_output)
        """

        if remote_path is None:
            remote_path = self.get_remote_path(monitor_path=monitor_path)

        bucket, key = self._get_bucket_and_key(remote_path)
        
        # Get file modification time to store as metadata
        mtime = str(int(Path(monitor_path).stat().st_mtime))
        extra_args = {'Metadata': {'mtime': mtime}}

        # Get metadata of object bucket and prefix
        try:
            head_object = self.client.head_object(Bucket=bucket, Key=key)
            size = head_object['ContentLength']
            etag = head_object['ETag'].strip('"')
            meta_data = head_object.get('Metadata') or {}
            # mtime may be absent, so fetch it safely first
            remote_mtime = meta_data.get('mtime')

            # We may have stored mtime in metadata during a previous upload
            if remote_mtime and remote_mtime == str(int(Path(monitor_path).stat().st_mtime)):
                return (0, "")

            # Is size and etag same as the monitor file, then return
            if size == Path(monitor_path).stat().st_size:
                md5 = self._calculate_md5(monitor_path)
                if etag == md5:
                    return (0, "")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == '404':
                pass
               
        try:
            self.logger.debug(f"Uploading {monitor_path} to s3://{bucket}/{key}")
            self.client.upload_file(monitor_path, bucket, key, ExtraArgs=extra_args, Config=self.transfer_config)
            return (0, "")
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"Error uploading file {monitor_path}: {e}")
            return (1, str(e))

    def copy_folder(self, monitor_path: str) -> tuple[int, str]:
        """
        Copy the monitor path to the derived remote path.
        """
        monitor_path_obj = Path(monitor_path)
        if not monitor_path_obj.exists():
            return (1, f"Monitor path {monitor_path} does not exist")

        remote_path = self.get_remote_path(monitor_path=monitor_path)
        bucket, prefix = self._get_bucket_and_key(remote_path)
        if prefix and not prefix.endswith('/'):
            prefix += '/'

        # List all objects in the remote folder to avoid checking each file individually.
        # Listing is only an optimisation: if it fails we still upload every local
        # file (rather than abort the backup), so fall back to an empty map.
        try:
            remote_objects = self._list_objects(bucket, prefix)
        except Exception as e:  # noqa: BLE001
            self.logger.warning(
                f"Could not list remote objects at s3://{bucket}/{prefix} ({e}); "
                "uploading all files without skipping unchanged ones."
            )
            remote_objects = []
        # Create a dictionary for faster lookup: key -> object
        remote_objects_map = {obj['Key']: obj for obj in remote_objects}

        errors = []
        # Walk through the monitor directory
        for root, dirs, files in os.walk(monitor_path):
            # Prune excluded directories before descending into them.
            kept_dirs = []
            for dir_name in dirs:
                dir_path = Path(root) / dir_name
                try:
                    dir_rel = dir_path.relative_to(monitor_path_obj).as_posix()
                except ValueError:
                    dir_rel = dir_path.name
                if not is_excluded(dir_rel, self.exclude_patterns):
                    kept_dirs.append(dir_name)
            dirs[:] = kept_dirs

            for file in files:
                local_file_path = Path(root) / file
                
                # Calculate relative path to construct the key
                try:
                    relative_path = local_file_path.relative_to(monitor_path_obj)
                except ValueError:
                    relative_path = local_file_path.name
                
                # S3 keys use forward slashes
                relative_posix = Path(relative_path).as_posix()
                if is_excluded(relative_posix, self.exclude_patterns):
                    continue

                key = f"{prefix}{relative_posix}"
                
                should_copy = False
                
                if key not in remote_objects_map:
                    should_copy = True
                else:
                    remote_obj = remote_objects_map[key]
                    local_size = local_file_path.stat().st_size
                    remote_size = remote_obj['Size']
                    remote_etag = remote_obj.get('ETag', '').strip('"')
                    
                    # If file size is equal, check ETag (MD5)
                    if local_size == remote_size:
                        # If ETag contains '-', it is a multipart upload and cannot be verified by simple MD5
                        if '-' not in remote_etag:
                            local_md5 = self._calculate_md5(str(local_file_path))
                            should_copy = local_md5 != remote_etag
                        else:
                            # Fallback for multipart files: assume size match is enough
                            should_copy = False
                    else:
                        should_copy = True

                if should_copy:
                    ret, msg = self.copy_file(str(local_file_path))
                    if ret != 0:
                        errors.append(msg)
                else:
                    self.logger.debug(f"Skipping {local_file_path} (metadata match)")
        
        if errors:
            return (1, "\n".join(errors))
        return (0, "")

    def restore_folder(self, remote_path: str) -> tuple[int, str]:
        """
        Restore the remote path (bucket/prefix) to the base monitor path.

        Downloads all objects under the remote prefix to base_monitor_path,
        preserving their relative paths and creating parent directories.
        """
        bucket, prefix = self._get_bucket_and_key(remote_path)
        if prefix and not prefix.endswith('/'):
            prefix += '/'

        errors = []
        try:
            objects = self._list_objects(bucket, prefix)
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"Error listing objects for restore: {e}")
            return (1, str(e))

        for obj in objects:
            key = obj['Key']
            if not key:
                continue

            # Compute the local path relative to the restored prefix.
            relative_key = key[len(prefix):] if prefix else key
            if not relative_key:
                continue

            if is_excluded(relative_key, self.exclude_patterns):
                continue

            local_path = Path(self.base_monitor_path) / relative_key
            local_path = Path(local_path.as_posix())

            try:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                self.logger.debug(f"Restoring s3://{bucket}/{key} to {local_path}")
                self.client.download_file(
                    bucket,
                    key,
                    str(local_path),
                    Config=self.transfer_config,
                )
            except Exception as e:  # noqa: BLE001
                self.logger.error(f"Error restoring s3://{bucket}/{key}: {e}")
                errors.append(str(e))

        if errors:
            return (1, "\n".join(errors))
        return (0, "")

    def delete_file(self, remote_path: str) -> tuple[int, str]:
        """
        Delete file at remote_path.
        remote_path should be the full path returned by get_remote_path.
        """
        bucket, key = self._get_bucket_and_key(remote_path)
        try:
            self.logger.debug(f"Deleting s3://{bucket}/{key}")
            self.client.delete_object(Bucket=bucket, Key=key)
            return (0, "")
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"Error deleting file {remote_path}: {e}")
            return (1, str(e))

    def delete_folder(self, remote_path: str) -> tuple[int, str]:
        """
        Delete objects in remote_path
        This is done in batches to reduce the number of requests.
        """
        bucket, prefix = self._get_bucket_and_key(remote_path)
        # Ensure prefix ends with / to avoid deleting partial matches of other folders if named similarly
        if prefix and not prefix.endswith('/'):
            prefix += '/'

        try:
            objects = self._list_objects(bucket, prefix)
            if not objects:
                return (0, "")

            # Delete in batches of 1000 (S3 limit)
            delete_keys: list[ObjectIdentifierTypeDef] = [{'Key': obj['Key']} for obj in objects]
            
            # Simple batching
            batch_size = 1000
            for i in range(0, len(delete_keys), batch_size):
                batch = delete_keys[i:i+batch_size]
                self.logger.debug(f"Deleting batch of {len(batch)} objects from {bucket}")
                self.client.delete_objects(Bucket=bucket, Delete={'Objects': batch})
            
            return (0, "")
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"Error deleting folder {remote_path}: {e}")
            return (1, str(e))

    def sync_folder(self, monitor_path: str) -> tuple[int, str]:
        """
        Sync the monitor path to the derived remote path.
        Make remote path identical to the monitor path.
        """
        # 1. Copy (Upload) all files from the monitor path
        copy_ret, copy_msg = self.copy_folder(monitor_path)
        if copy_ret != 0:
            return (copy_ret, copy_msg)

        # 2. Delete files in remote that are NOT in the monitor path
        remote_path = self.get_remote_path(monitor_path)
        bucket, prefix = self._get_bucket_and_key(remote_path)
        if prefix and not prefix.endswith('/'):
            prefix += '/'

        try:
            remote_objects = self._list_objects(bucket, prefix)
            
            # Build set of expected keys from the monitor path
            expected_keys = set()
            monitor_path_obj = Path(monitor_path)
            for root, _dirs, files in os.walk(monitor_path):
                for file in files:
                    local_file = Path(root) / file
                    # Calculate relative path from the monitor root
                    rel_path = local_file.relative_to(monitor_path_obj)
                    # Key is prefix + rel_path (normalized to forward slashes)
                    key = f"{prefix}{rel_path.as_posix()}"
                    expected_keys.add(key)

            # Identify objects to delete
            to_delete: list[ObjectIdentifierTypeDef] = []
            for obj in remote_objects:
                if obj['Key'] not in expected_keys:
                    to_delete.append({'Key': obj['Key']})
            
            if to_delete:
                self.logger.info(f"Sync: Deleting {len(to_delete)} extraneous files from remote.")
                # Delete in batches
                batch_size = 1000
                for i in range(0, len(to_delete), batch_size):
                    batch = to_delete[i:i+batch_size]
                    self.client.delete_objects(Bucket=bucket, Delete={'Objects': batch})

            return (0, "")

        except Exception as e:  # noqa: BLE001
            self.logger.error(f"Error during sync cleanup: {e}")
            return (1, str(e))