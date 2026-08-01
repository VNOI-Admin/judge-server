import gc
import os
import shutil
import tempfile
import unittest
from typing import Optional
from unittest import mock

from dmoj.executors.RUST import Executor as RustExecutor
from dmoj.executors.base_executor import BaseExecutor
from dmoj.executors.mixins import NullStdoutMixin


class FakeExecutor(BaseExecutor):
    """A built executor, without the compiler needed to build one."""

    # Matches CompiledExecutor, which the mixed-in fakes below also inherit.
    _executable: Optional[str] = None

    def __init__(self, tempdir: str) -> None:
        self._tempdir = tempdir
        self._dir = tempfile.mkdtemp(dir=tempdir)
        self._executable = os.path.join(self._dir, 'submission')
        with open(self._executable, 'w') as f:
            f.write('artifact')


class ExecutorCloneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tempdir, True)

    def dirs(self):
        return sorted(os.listdir(self.tempdir))

    def test_clone_is_independent(self):
        original = FakeExecutor(self.tempdir)
        clone = original.clone()

        self.assertNotEqual(clone._dir, original._dir)
        # Cached absolute paths follow the copy.
        self.assertEqual(clone._executable, os.path.join(clone._dir, 'submission'))
        self.assertTrue(os.path.exists(clone._executable))

    def test_cleanup_does_not_touch_the_other_copy(self):
        original = FakeExecutor(self.tempdir)
        clone = original.clone()
        original_dir, clone_dir = original._dir, clone._dir

        original.cleanup()
        self.assertFalse(os.path.exists(original_dir))
        self.assertTrue(os.path.exists(clone_dir))

        clone.cleanup()
        self.assertFalse(os.path.exists(clone_dir))

    def test_failed_clone_leaves_nothing_behind(self):
        original = FakeExecutor(self.tempdir)
        before = self.dirs()

        with mock.patch('shutil.copytree', side_effect=OSError(28, 'No space left on device')):
            with self.assertRaises(OSError):
                original.clone()

        # The directory made for the clone must not outlive the failure.
        self.assertEqual(self.dirs(), before)
        self.assertTrue(os.path.exists(original._executable))


class FakeNullStdoutExecutor(NullStdoutMixin, FakeExecutor):
    pass


class NullStdoutCloneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tempdir, True)

    def build(self) -> FakeNullStdoutExecutor:
        # Sidestep CompiledExecutor's metaclass, which would try to compile.
        executor = FakeNullStdoutExecutor.__new__(FakeNullStdoutExecutor)
        executor._devnull = open(os.devnull, 'w')
        FakeExecutor.__init__(executor, self.tempdir)
        return executor

    def test_clone_gets_its_own_devnull(self):
        original = self.build()
        clone = original.clone()

        self.assertIsNot(clone._devnull, original._devnull)
        clone.cleanup()
        # Closing the clone's must leave the original's usable.
        self.assertFalse(original._devnull.closed)


class FakeRustExecutor(RustExecutor, FakeExecutor):
    pass


class RustCloneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tempdir, True)

    def build(self) -> FakeRustExecutor:
        executor = FakeRustExecutor.__new__(FakeRustExecutor)
        FakeExecutor.__init__(executor, self.tempdir)
        # The compiled binary lives in the shared target, not in _dir, and is
        # guarded by a flock held on this fd.
        executor.shared_target = os.path.join(self.tempdir, 'shared-target')
        os.mkdir(executor.shared_target)
        executor.shared_target_dirfd = os.open(executor.shared_target, os.O_RDONLY | os.O_DIRECTORY)
        return executor  # its own cleanup() closes the fd

    def test_clone_dups_the_shared_target_fd(self):
        original = self.build()
        clone = original.clone()

        self.assertNotEqual(clone.shared_target_dirfd, original.shared_target_dirfd)

        del clone
        gc.collect()
        # The lock is held on the open file description, so the original's fd
        # must survive the clone being cleaned up.
        os.fstat(original.shared_target_dirfd)


if __name__ == '__main__':
    unittest.main()
