import logging
import os
from typing import Any, Optional

log = logging.getLogger(__name__)


class S3ProblemStorage:
    """
    Problem storage backed by an S3 bucket, laid out as `<prefix>/<problem_id>/init.yml` plus data files.

    Problems are downloaded on demand into a local directory, so the rest of the judge can keep treating
    problems as directories on disk.
    """

    def __init__(
        self,
        id: str,
        bucket: str,
        prefix: str = '',
        endpoint_url: Optional[str] = None,
        region: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        client: Any = None,
    ) -> None:
        self.id = id
        self.bucket = bucket
        self.prefix = prefix.strip('/')
        self.endpoint_url = endpoint_url
        self.region = region
        self.access_key = access_key
        self.secret_key = secret_key
        self._client = client
        self._client_pid: Optional[int] = os.getpid() if client is not None else None

    @property
    def client(self) -> Any:
        # boto3 clients are not fork-safe, so create one per process.
        if self._client is None or self._client_pid != os.getpid():
            try:
                import boto3
            except ImportError:
                raise RuntimeError('boto3 is required for S3 problem storage, install with `pip install .[s3]`')

            self._client = boto3.client(
                's3',
                endpoint_url=self.endpoint_url,
                region_name=self.region,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
            )
            self._client_pid = os.getpid()
        return self._client

    def _problem_prefix(self, problem_id: str) -> str:
        return f'{self.prefix}/{problem_id}/' if self.prefix else f'{problem_id}/'

    def download(self, problem_id: str, dest_dir: str) -> bool:
        """
        Downloads all files of `problem_id` into `dest_dir`.
        :return: whether the problem exists in this storage.
        """
        if not problem_id or '/' in problem_id or problem_id in ('.', '..'):
            return False

        key_prefix = self._problem_prefix(problem_id)
        dest_root = os.path.realpath(dest_dir)

        keys = []
        paginator = self.client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=self.bucket, Prefix=key_prefix):
            for obj in page.get('Contents', []):
                key = obj['Key']
                if key.endswith('/'):
                    continue
                keys.append(key)

        if key_prefix + 'init.yml' not in keys:
            return False

        for key in keys:
            relative = key[len(key_prefix) :]
            target = os.path.realpath(os.path.join(dest_root, relative))
            if os.path.commonpath([dest_root, target]) != dest_root:
                log.warning('Skipping S3 key outside of problem directory: %s', key)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            self.client.download_file(self.bucket, key, target)

        log.info('Downloaded problem %s from s3://%s/%s (%d files)', problem_id, self.bucket, key_prefix, len(keys))
        return True
