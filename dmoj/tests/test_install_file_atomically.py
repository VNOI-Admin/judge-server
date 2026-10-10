import mmap
import os
import tempfile
import unittest

from dmoj.executors.base_executor import install_file_atomically


class InstallFileAtomicallyTest(unittest.TestCase):
    def test_does_not_modify_file_in_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'src')
            dst = os.path.join(tmp, 'dst')
            with open(src, 'wb') as f:
                f.write(b'new' * 4096)
            with open(dst, 'wb') as f:
                f.write(b'old' * 4096)

            # Stand-in for another process that has `dst` loaded, e.g. as LD_PRELOAD.
            with open(dst, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as loaded:
                install_file_atomically(src, dst)
                self.assertEqual(loaded[:], b'old' * 4096)

            with open(dst, 'rb') as f:
                self.assertEqual(f.read(), b'new' * 4096)
            self.assertEqual(sorted(os.listdir(tmp)), ['dst', 'src'])
