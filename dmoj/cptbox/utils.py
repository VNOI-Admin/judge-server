import fcntl
import io
import mmap
import os
from abc import ABCMeta, abstractmethod
from tempfile import NamedTemporaryFile, TemporaryFile
from typing import Optional

from dmoj.cptbox._cptbox import memfd_create, memfd_seal

# The sandbox child (helper.cpp) dup2()s descriptors onto fds 0-4 before execve: stdin/stdout/stderr
# plus the File-IO pipes on fd 3 and 4. A descriptor we hand the child via keep_fds so it can reopen
# it through /proc/self/fd/<n> must therefore sit above that range, or the dup2 would clobber it
# (leaving the child's /proc/self/fd/<n> pointing at the pipe instead of our data).
_MIN_CHILD_KEEP_FD = 5


def _relocate_above_std_fds(fd: int) -> int:
    if fd >= _MIN_CHILD_KEEP_FD:
        return fd
    # F_DUPFD returns the lowest free fd >= _MIN_CHILD_KEEP_FD, and (unlike F_DUPFD_CLOEXEC) leaves
    # it inheritable, which the child needs.
    new_fd = fcntl.fcntl(fd, fcntl.F_DUPFD, _MIN_CHILD_KEEP_FD)
    os.close(fd)
    return new_fd


def _make_fd_readonly(fd):
    new_fd = os.open(f'/proc/self/fd/{fd}', os.O_RDONLY)
    try:
        os.dup2(new_fd, fd)
    finally:
        os.close(new_fd)


class MmapableIO(io.FileIO, metaclass=ABCMeta):
    def __init__(self, fd, *, prefill: Optional[bytes] = None, seal=False) -> None:
        super().__init__(fd, 'r+')

        if prefill:
            self.write(prefill)
        if seal:
            self.seal()

    @classmethod
    @abstractmethod
    def usable_with_name(cls) -> bool: ...

    @abstractmethod
    def seal(self) -> None: ...

    @abstractmethod
    def to_path(self) -> str: ...

    def to_bytes(self) -> bytes:
        try:
            with mmap.mmap(self.fileno(), 0, access=mmap.ACCESS_READ) as f:
                return bytes(f)
        except ValueError as e:
            if e.args[0] == 'cannot mmap an empty file':
                return b''
            raise


class NamedFileIO(MmapableIO):
    _name: str

    def __init__(self, *, prefill: Optional[bytes] = None, seal=False) -> None:
        with NamedTemporaryFile(delete=False) as f:
            self._name = f.name
            super().__init__(os.dup(f.fileno()), prefill=prefill, seal=seal)

    def seal(self) -> None:
        self.seek(0, os.SEEK_SET)

    def close(self) -> None:
        super().close()
        os.unlink(self._name)

    def to_path(self) -> str:
        return self._name

    @classmethod
    def usable_with_name(cls):
        return True


class UnnamedFileIO(MmapableIO):
    def __init__(self, *, prefill: Optional[bytes] = None, seal=False) -> None:
        with TemporaryFile() as f:
            super().__init__(_relocate_above_std_fds(os.dup(f.fileno())), prefill=prefill, seal=seal)

    def seal(self) -> None:
        self.seek(0, os.SEEK_SET)
        _make_fd_readonly(self.fileno())

    def to_path(self) -> str:
        # See MemfdIO.to_path: /proc/self/fd so the consumer accesses its own kept-open descriptor.
        return f'/proc/self/fd/{self.fileno()}'

    @classmethod
    def usable_with_name(cls):
        with cls() as f:
            return os.path.exists(f.to_path())


class MemfdIO(MmapableIO):
    def __init__(self, *, prefill: Optional[bytes] = None, seal=False) -> None:
        super().__init__(_relocate_above_std_fds(memfd_create()), prefill=prefill, seal=seal)

    def seal(self) -> None:
        fd = self.fileno()
        memfd_seal(fd)
        _make_fd_readonly(fd)

    def to_path(self) -> str:
        # Always /proc/self/fd, never /proc/<judgepid>/fd: the consumer is given this fd as one of
        # its own (kept open past closefrom via keep_fds), and Landlock permits a process to access
        # its own special descriptors (pipe/memfd) through /proc/self/fd, but not another process's.
        return f'/proc/self/fd/{self.fileno()}'

    @classmethod
    def usable_with_name(cls):
        try:
            with cls() as f:
                return os.path.exists(f.to_path())
        except OSError:
            return False


# Try to use memfd if possible, otherwise fallback to unlinked temporary files
# (UnnamedFileIO). On FreeBSD and some other systems, /proc/[pid]/fd doesn't
# exist, so to_path() will not work. We fall back to NamedFileIO in that case.
MemoryIO = next((i for i in (MemfdIO, UnnamedFileIO, NamedFileIO) if i.usable_with_name()))
