"""Object storage for audio and exports: local filesystem (dev) or S3/MinIO (on-prem)."""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

from app.config import get_settings


class Storage(ABC):
    @abstractmethod
    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None: ...

    @abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None: ...

    @abstractmethod
    def get_to_path(self, key: str, dest: Path) -> Path: ...

    @abstractmethod
    def get_bytes(self, key: str) -> bytes: ...

    @abstractmethod
    def size(self, key: str) -> int: ...

    @abstractmethod
    def open_range(self, key: str, start: int, end: int) -> Iterator[bytes]:
        """Yield bytes start..end inclusive (for HTTP Range playback)."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    def put_stream(self, key: str, stream: BinaryIO, content_type: str | None = None) -> None:
        self.put_bytes(key, stream.read(), content_type)


class LocalStorage(Storage):
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("invalid storage key")
        return p

    def put_file(self, key, path, content_type=None):
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)

    def put_bytes(self, key, data, content_type=None):
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def get_to_path(self, key, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._path(key), dest)
        return dest

    def get_bytes(self, key):
        return self._path(key).read_bytes()

    def size(self, key):
        return self._path(key).stat().st_size

    def open_range(self, key, start, end):
        with self._path(key).open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    def exists(self, key):
        return self._path(key).exists()

    def delete(self, key):
        p = self._path(key)
        if p.exists():
            p.unlink()


class S3Storage(Storage):
    def __init__(self):
        import boto3
        from botocore.config import Config

        s = get_settings()
        self.bucket = s.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url,
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
            region_name=s.s3_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self._ensure_bucket()

    def _ensure_bucket(self):
        from botocore.exceptions import ClientError

        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def _extra(self, content_type):
        return {"ContentType": content_type} if content_type else {}

    def put_file(self, key, path, content_type=None):
        self.client.upload_file(str(path), self.bucket, key, ExtraArgs=self._extra(content_type) or None)

    def put_bytes(self, key, data, content_type=None):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **self._extra(content_type))

    def get_to_path(self, key, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(dest))
        return dest

    def get_bytes(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def size(self, key):
        return self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"]

    def open_range(self, key, start, end):
        body = self.client.get_object(Bucket=self.bucket, Key=key, Range=f"bytes={start}-{end}")["Body"]
        yield from body.iter_chunks(65536)

    def exists(self, key):
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "s3":
        return S3Storage()
    return LocalStorage(s.storage_local_root)
