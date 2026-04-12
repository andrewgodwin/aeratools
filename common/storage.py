"""
Storage abstraction - S3 or a local filesystem for development
"""

import fcntl
import hashlib
import json
import os
import shutil

import boto3
from botocore.exceptions import ClientError


class StorageConflictError(ValueError):
    """
    Raised when a conditional store fails due to an ETag mismatch.
    """

    pass


class S3Storage:
    """
    S3-backed storage abstraction.
    """

    def __init__(
        self, access_key: str, secret_key: str, endpoint_url: str | None, bucket: str
    ):
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def _path(self, user_id: str, file: str):
        return f"users/{user_id[:3]}/{user_id}/{file}"

    def retrieve(self, user_id: str, file: str) -> tuple[dict, str] | None:
        """
        Fetch a stored object.

        Returns (content, etag) or None if not found. The etag can be passed to store()
        to enable optimistic concurrency.
        """
        try:
            response = self.client.get_object(
                Bucket=self.bucket,
                Key=self._path(user_id, file),
            )
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise
        content = json.loads(response["Body"].read())
        etag = response["ETag"]
        return content, etag

    def store(self, user_id: str, file: str, content: dict, version: str | None = None):
        """
        Store an object.

        If version (ETag) is provided, the write is conditional and raises
        StorageConflictError if the object has been modified since retrieval.
        """
        kwargs = dict(
            Bucket=self.bucket,
            Key=self._path(user_id, file),
            Body=json.dumps(content),
            ContentType="application/json",
        )
        if version is not None:
            kwargs["IfMatch"] = version
        try:
            self.client.put_object(**kwargs)
        except ClientError as e:
            if e.response["Error"]["Code"] in (
                "PreconditionFailed",
                "ConditionalRequestConflict",
            ):
                raise StorageConflictError(
                    f"Conflict storing {file} for user {user_id}: object was modified"
                ) from e
            raise

    def delete(self, user_id: str, file: str):
        """
        Delete a stored object.

        No-ops if the object does not exist.
        """
        self.client.delete_object(
            Bucket=self.bucket,
            Key=self._path(user_id, file),
        )

    def list(self, user_id: str, prefix: str | None = None) -> list[str]:
        """
        List filenames stored for user_id, optionally filtered by prefix.
        """
        base = self._path(user_id, "")
        key_prefix = self._path(user_id, prefix or "")
        paginator = self.client.get_paginator("list_objects_v2")
        files = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=key_prefix):
            for obj in page.get("Contents", []):
                files.append(obj["Key"][len(base) :])
        return files

    def store_bytes(
        self,
        user_id: str,
        file: str,
        stream,
        content_type: str = "application/octet-stream",
    ):
        """
        Store binary data from a file-like stream.
        """
        self.client.upload_fileobj(
            stream,
            self.bucket,
            self._path(user_id, file),
            ExtraArgs={"ContentType": content_type},
        )

    def retrieve_bytes(self, user_id: str, file: str):
        """
        Return a readable binary stream, or None if not found.
        """
        try:
            response = self.client.get_object(
                Bucket=self.bucket,
                Key=self._path(user_id, file),
            )
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise
        return response["Body"]


class LocalStorage:
    """
    Local filesystem storage for development.

    Uses sha256 of file contents as the etag.
    """

    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir

    def _path(self, user_id: str, file: str) -> str:
        return os.path.join(self.storage_dir, "users", user_id[:3], user_id, file)

    def retrieve(self, user_id: str, file: str) -> tuple[dict, str] | None:
        path = self._path(user_id, file)
        try:
            with open(path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            return None
        etag = hashlib.sha256(data).hexdigest()
        return json.loads(data), etag

    def store(self, user_id: str, file: str, content: dict, version: str | None = None):
        path = self._path(user_id, file)
        if version is not None:
            try:
                with open(path, "r+b") as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    current = f.read()
                    if hashlib.sha256(current).hexdigest() != version:
                        raise StorageConflictError(
                            f"Conflict storing {file} for user {user_id}: object was modified"
                        )
                    f.seek(0)
                    f.write(json.dumps(content).encode())
                    f.truncate()
            except FileNotFoundError:
                raise StorageConflictError(
                    f"Conflict storing {file} for user {user_id}: object no longer exists"
                )
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(content, f)

    def delete(self, user_id: str, file: str):
        """
        Delete a stored object.

        No-ops if the object does not exist.
        """
        try:
            os.remove(self._path(user_id, file))
        except FileNotFoundError:
            pass

    def list(self, user_id: str, prefix: str | None = None) -> list[str]:
        """
        List filenames stored for user_id, optionally filtered by prefix.
        """
        dir_path = os.path.join(self.storage_dir, "users", user_id[:3], user_id)
        try:
            files = os.listdir(dir_path)
        except FileNotFoundError:
            return []
        if prefix is not None:
            files = [f for f in files if f.startswith(prefix)]
        return sorted(files)

    def store_bytes(
        self,
        user_id: str,
        file: str,
        stream,
        content_type: str = "application/octet-stream",
    ):
        """
        Store binary data from a file-like stream.
        """
        path = self._path(user_id, file)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            shutil.copyfileobj(stream, f)

    def retrieve_bytes(self, user_id: str, file: str):
        """
        Return a readable binary stream, or None if not found.
        """
        path = self._path(user_id, file)
        try:
            return open(path, "rb")
        except FileNotFoundError:
            return None


def get_storage():
    """
    Returns the appropriate storage class for the current environment.
    """
    if "STORAGE_DIR" in os.environ:
        return LocalStorage(os.environ["STORAGE_DIR"])
    else:
        return S3Storage(
            access_key=os.environ["AWS_ACCESS_KEY_ID"],
            secret_key=os.environ["AWS_SECRET_ACCESS_KEY"],
            endpoint_url=os.environ.get("S3_ENDPOINT_URL"),
            bucket=os.environ["S3_BUCKET"],
        )
