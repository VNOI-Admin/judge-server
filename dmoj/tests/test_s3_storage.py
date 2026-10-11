import os
import tempfile
import unittest
from unittest import mock

from dmoj import judgeenv
from dmoj.utils.s3_storage import S3ProblemStorage


class FakeS3Client:
    def __init__(self, objects):
        self.objects = objects

    def get_paginator(self, name):
        assert name == 'list_objects_v2'
        client = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                keys = sorted(key for key in client.objects if key.startswith(Prefix))
                # Two pages, to make sure pagination is followed.
                yield {'Contents': [{'Key': key} for key in keys[:1]]}
                yield {'Contents': [{'Key': key} for key in keys[1:]]}

        return Paginator()

    def download_file(self, bucket, key, filename):
        with open(filename, 'wb') as f:
            f.write(self.objects[key])


OBJECTS = {
    'problems/aplusb/init.yml': b'archive: tests.zip\n',
    'problems/aplusb/tests.zip': b'zip',
    'problems/aplusb/sub/checker.py': b'pass',
    'problems/aplusb/': b'',
    'problems/aplusb/../evil': b'evil',
    'problems/noinit/data.in': b'1',
}


class S3ProblemStorageTest(unittest.TestCase):
    def setUp(self):
        self.storage = S3ProblemStorage('s3', 'bucket', prefix='problems/', client=FakeS3Client(OBJECTS))
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, 'aplusb')

    def tearDown(self):
        self.tmp.cleanup()

    def test_download(self):
        self.assertTrue(self.storage.download('aplusb', self.dest))
        with open(os.path.join(self.dest, 'init.yml'), 'rb') as f:
            self.assertEqual(f.read(), b'archive: tests.zip\n')
        self.assertTrue(os.path.isfile(os.path.join(self.dest, 'tests.zip')))
        self.assertTrue(os.path.isfile(os.path.join(self.dest, 'sub', 'checker.py')))
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, 'evil')))

    def test_missing(self):
        self.assertFalse(self.storage.download('missing', self.dest))
        self.assertFalse(self.storage.download('noinit', self.dest))
        self.assertFalse(self.storage.download('../problems', self.dest))
        self.assertFalse(self.storage.download('..', self.dest))

    def test_get_problem_root(self):
        cache = judgeenv.StorageNamespaceCache()
        cache.problem_root_cache = {}
        cache.problem_roots_cache = []
        with mock.patch.dict(judgeenv._storage_namespace_cache, {'s3ns': cache}), mock.patch.dict(
            judgeenv.s3_storages, {'s3ns': [self.storage]}
        ), mock.patch.dict(judgeenv.env.raw_config, {'tempdir': self.tmp.name}):
            root = judgeenv.get_problem_root('aplusb', 's3ns')
            self.assertEqual(root, os.path.join(judgeenv.problem_download_dir(os.getpid()), 's3ns', 'aplusb'))
            self.assertTrue(os.path.isfile(os.path.join(root, 'init.yml')))

            # Subsequent lookups in the same process reuse the download.
            with mock.patch.object(self.storage, 'download') as download:
                self.assertEqual(judgeenv.get_problem_root('aplusb', 's3ns'), root)
                download.assert_not_called()

            self.assertIsNone(judgeenv.get_problem_root('missing', 's3ns'))

            judgeenv.cleanup_problem_downloads(os.getpid())
            self.assertFalse(os.path.exists(root))
