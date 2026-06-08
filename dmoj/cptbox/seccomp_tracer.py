"""
Ptrace-less sandbox supervisor (seccomp + Landlock, no ptrace).

SeccompPopen spawns the child via the shared Process._spawn path with use_ptrace=0 (see
helper.cpp), then supervises it without ptrace: a reaper thread wait4()s the whole process group
for exit + rusage, a poller samples peak memory from /proc, and a timer enforces the wall/CPU
limit. Security is entirely the in-child seccomp filter (default KILL_PROCESS) + Landlock; this
supervisor never makes a security decision.

The dynamic, memory-inspecting syscalls (metadata path-checks, kill/prctl/prlimit, fix_case_path
opens) route to SCMP_ACT_NOTIFY; NotifyDebugger backs the existing isolate.py handler interface so
their logic runs unchanged. execve and exit_group are also notified -- execve to learn the program
started (was_initialized) and to deny submission re-exec, exit_group to read the final peak memory
while the process is still alive. Select with DMOJ_SANDBOX_MODE=seccomp+landlock; see
PTRACELESS_DESIGN.md.
"""

import errno as _errno
import logging
import os
import select
import signal
import socket
import sys
import threading
import time
from typing import Callable, Dict, List, Mapping, Optional, Tuple

from dmoj.cptbox._cptbox import (
    MAX_SYSCALL_NUMBER,
    NATIVE_ABI,
    NOTIFY_FLAG_CONTINUE,
    NOTIFY_NATIVE_ARCH,
    PTBOX_ABI_ARM,
    PTBOX_ABI_ARM64,
    PTBOX_ABI_X64,
    PTBOX_ABI_X86,
    PTBOX_SPAWN_FAIL_EXECVE,
    PTBOX_SPAWN_FAIL_LANDLOCK,
    PTBOX_SPAWN_FAIL_NO_NEW_PRIVS,
    PTBOX_SPAWN_FAIL_SECCOMP,
    PTBOX_SPAWN_FAIL_SECCOMP_NOTIFY,
    PTBOX_SPAWN_FAIL_SETAFFINITY,
    Process,
    SUPPORTED_ABIS,
    notify_id_valid,
    notify_receive,
    notify_respond,
)
from dmoj.cptbox._cptbox import has_landlock
from dmoj.cptbox.filesystem_policies import ExactDir, ExactFile, FilesystemAccessRule, RecursiveDir
from dmoj.cptbox.handlers import ALLOW, ErrnoHandlerCallback
from dmoj.cptbox.syscalls import by_id, sys_execve, sys_exit_group, sys_getpid, translator
from dmoj.cptbox.tracer import (
    BAD_SECCOMP,
    FILE_IO_PIPE,
    MaxLengthExceeded,
    PIPE,
    STDOUT,
    SYSCALL_COUNT,
    TracedPopen,
    _SYSCALL_INDICIES,
    _address_bits,
    _safe_communicate,
)
from dmoj.utils.unicode import utf8bytes, utf8text

log = logging.getLogger('dmoj.security')

# seccomp_handlers[] sentinel matching helper.h PTBOX_SECCOMP_NOTIFY: route this syscall to the
# supervisor via seccomp user-notification.
_NOTIFY = -2

_SIGNED_MASK = 1 << 64

# AUDIT_ARCH_* the kernel reports in seccomp_data.arch, per cptbox ABI. Lets the supervisor dispatch
# notifications from non-native arches too (e.g. a 32-bit binary on a 64-bit host), since raw
# syscall numbers are arch-specific. Stable kernel constants.
_AUDIT_ARCH = {
    PTBOX_ABI_X86: 0x40000003,  # AUDIT_ARCH_I386
    PTBOX_ABI_X64: 0xC000003E,  # AUDIT_ARCH_X86_64
    PTBOX_ABI_ARM: 0x40000028,  # AUDIT_ARCH_ARM
    PTBOX_ABI_ARM64: 0xC00000B7,  # AUDIT_ARCH_AARCH64
}
_ARCH_TO_ABI = {arch: abi for abi, arch in _AUDIT_ARCH.items()}

# Spawn-failure exit codes the child returns before exec'ing the program. Only used as a fallback
# heuristic when notify is unavailable; with notify, was_initialized comes authoritatively from the
# execve notification, so a program legitimately exiting with one of these codes is not misreported.
_SPAWN_FAIL_CODES = frozenset(
    {
        PTBOX_SPAWN_FAIL_NO_NEW_PRIVS,
        PTBOX_SPAWN_FAIL_SECCOMP,
        PTBOX_SPAWN_FAIL_EXECVE,
        PTBOX_SPAWN_FAIL_SETAFFINITY,
        PTBOX_SPAWN_FAIL_LANDLOCK,
        PTBOX_SPAWN_FAIL_SECCOMP_NOTIFY,
    }
)


def _read_proc_vmhwm_kb(pid: int) -> int:
    """Peak resident set size (VmHWM) of `pid` in KB, or 0 if unavailable."""
    try:
        with open(f'/proc/{pid}/status', 'rb') as f:
            for line in f:
                if line.startswith(b'VmHWM:'):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


# Clock ticks per second, for parsing /proc/<pid>/stat CPU fields.
_CLK_TCK = os.sysconf('SC_CLK_TCK')


def _read_proc_tgid(tid: int) -> int:
    """Thread-group id (process pid) of thread `tid`, or `tid` if unavailable. A seccomp
    notification carries the notifying *thread's* tid; the kill/prlimit self-checks compare against
    the process pid (tgid, like the ptrace debugger), so we resolve it."""
    try:
        with open(f'/proc/{tid}/status', 'rb') as f:
            for line in f:
                if line.startswith(b'Tgid:'):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return tid


def _read_group_cpu_seconds(pgid: int) -> float:
    """Total CPU (seconds) consumed by every process in process group `pgid`.

    Sums utime+stime+cutime+cstime over all live group members. cutime/cstime hold the CPU of each
    member's already-reaped descendants, so the sum captures the whole tree's CPU (live + reaped)
    counting each process once -- not just the leader. This catches a submission that offloads work
    to children while its leader idles in wait(), which a leader-only sample (or per-process
    RLIMIT_CPU) would miss. Scans /proc by process group so orphaned-but-still-in-group children
    are included. Returns 0 if /proc is unreadable.
    """
    total = 0
    try:
        for entry in os.listdir('/proc'):
            if not entry.isdigit():
                continue
            try:
                with open('/proc/%s/stat' % entry, 'rb') as f:
                    data = f.read()
            except OSError:
                continue  # process exited between listdir and open
            rparen = data.rfind(b')')
            fields = data[rparen + 2 :].split()
            try:
                # After comm: state=0, ppid=1, pgrp=2, ... utime=11, stime=12, cutime=13, cstime=14.
                if int(fields[2]) != pgid:
                    continue
                total += int(fields[11]) + int(fields[12]) + int(fields[13]) + int(fields[14])
            except (ValueError, IndexError):
                continue
    except OSError:
        return 0.0
    return total / _CLK_TCK


def _signed64(value: int) -> int:
    return value - _SIGNED_MASK if value >= (1 << 63) else value


def _syscall_name(nr: int, index: Optional[int]) -> str:
    if index is None:
        return 'unknown'
    for sid, call in enumerate(translator):
        if nr in call[index]:
            name = by_id[sid]
            return name[4:] if name.startswith('sys_') else name
    return 'unknown'


class NotifyDebugger:
    """Backs the isolate.py handler interface for one seccomp notification, with no ptrace.

    Syscall arguments come from the notification; the child's memory is read/written through
    /proc/<pid>/mem. Handlers neutralize/emulate a syscall by setting .syscall=-1 / .errno /
    .result / .on_return, or rewrite a path via .writestr (fix_case_path); the service loop then
    reads .skip/.error/.result to build the response.
    """

    def __init__(self, pid: int, nr: int, args, listener_fd: int, notif_id: int, abi: int) -> None:
        # The notification carries the notifying *thread's* tid.
        self.tid = pid
        self._tgid: Optional[int] = None
        self.abi = abi
        index = _SYSCALL_INDICIES[abi]
        assert index is not None
        self._index: int = index
        self._nr = nr
        self._args = args
        self._listener_fd = listener_fd
        self._notif_id = notif_id
        self.skip = False
        self.error = 0
        self.result = 0
        self.on_return_callbacks: List[Callable] = []
        self._memfd = -1

    @property
    def uarg0(self) -> int:
        return self._args[0]

    @property
    def uarg1(self) -> int:
        return self._args[1]

    @property
    def uarg2(self) -> int:
        return self._args[2]

    @property
    def uarg3(self) -> int:
        return self._args[3]

    @property
    def uarg4(self) -> int:
        return self._args[4]

    @property
    def uarg5(self) -> int:
        return self._args[5]

    @property
    def arg0(self) -> int:
        return _signed64(self._args[0])

    @property
    def arg1(self) -> int:
        return _signed64(self._args[1])

    @property
    def arg2(self) -> int:
        return _signed64(self._args[2])

    @property
    def arg3(self) -> int:
        return _signed64(self._args[3])

    @property
    def arg4(self) -> int:
        return _signed64(self._args[4])

    @property
    def arg5(self) -> int:
        return _signed64(self._args[5])

    @property
    def pid(self) -> int:
        # The process (tgid), matching the ptrace debugger's .pid -- handle_kill/handle_prlimit
        # compare the syscall's target against this to allow self-signalling. Resolved lazily (only
        # those handlers read it) and cached. NB: distinct from .tid (the notifying thread).
        if self._tgid is None:
            self._tgid = _read_proc_tgid(self.tid)
        return self._tgid

    @property
    def syscall(self) -> int:
        return self._nr

    @syscall.setter
    def syscall(self, value: int) -> None:
        # isolate sets this to -1 (or noop_syscall_id) to skip running the real syscall.
        self.skip = True

    @property
    def errno(self) -> int:
        return self.error

    @errno.setter
    def errno(self, value: int) -> None:
        self.error = value
        self.skip = True

    def on_return(self, callback: Callable) -> None:
        self.on_return_callbacks.append(callback)

    @property
    def noop_syscall_id(self) -> int:
        return translator[sys_getpid][self._index][0]

    @property
    def address_bits(self) -> Optional[int]:
        return _address_bits.get(self.abi)

    @property
    def syscall_name(self) -> str:
        return _syscall_name(self._nr, self._index)

    def _mem(self) -> int:
        if self._memfd < 0:
            # Read the notifying thread's address space (threads share it; this avoids a /proc tgid
            # lookup on the hot path of metadata/path checks).
            self._memfd = os.open('/proc/%d/mem' % self.tid, os.O_RDWR)
        return self._memfd

    def readstr(self, address: int, max_size: int = 4096) -> Optional[str]:
        if self.address_bits == 32:
            address &= 0xFFFFFFFF
        try:
            fd = self._mem()
        except OSError:
            return None
        out = bytearray()
        addr = address
        while len(out) <= max_size:
            try:
                chunk = os.pread(fd, 256, addr)
            except OSError:
                return None
            if not chunk:
                return None
            nul = chunk.find(b'\0')
            if nul >= 0:
                out += chunk[:nul]
                # TOCTOU guard: confirm the request is still live (the child hasn't been replaced).
                if not notify_id_valid(self._listener_fd, self._notif_id):
                    return None
                return utf8text(bytes(out))
            out += chunk
            addr += len(chunk)
        raise MaxLengthExceeded(bytes(out[:max_size]))

    def writestr(self, address: int, value: str) -> None:
        # Raises OSError on fault, which isolate.write_path turns into a denied syscall.
        os.pwrite(self._mem(), utf8bytes(value) + b'\0', address)

    def readbytes(self, address: int, size: int) -> bytes:
        # Raises OSError on fault (do_utimensat catches it).
        return os.pread(self._mem(), size, address)

    def close(self) -> None:
        if self._memfd >= 0:
            try:
                os.close(self._memfd)
            except OSError:
                pass
            self._memfd = -1


class SeccompPopen(Process):
    def __init__(
        self,
        args: List[bytes],
        *,
        executable: bytes,
        security=None,
        time: int = 0,
        memory: int = 0,
        stdin: Optional[int] = PIPE,
        stdout: Optional[int] = PIPE,
        stderr: Optional[int] = None,
        child_stdin: Optional[int] = None,
        child_stdout: Optional[int] = None,
        env: Optional[Mapping[str, Optional[str]]] = None,
        nproc: int = 0,
        fsize: int = 0,
        address_grace: int = 4096,
        data_grace: int = 0,
        personality: int = 0,
        cwd: bytes = b'',
        wall_time: Optional[float] = None,
        cpu_affinity: Optional[List[int]] = None,
        keep_fds: Optional[List[int]] = None,
        use_notify: bool = True,
    ) -> None:
        if BAD_SECCOMP:
            raise RuntimeError(f'Sandbox requires Linux 4.8+ to use seccomp, you have {os.uname().release}')

        self._use_ptrace = False
        self._executable = executable
        self.keep_fds = list(keep_fds or [])
        self._args = args
        self._chdir = cwd
        self._env = [
            utf8bytes(f'{arg}={val}')
            for arg, val in (env if env is not None else os.environ).items()
            if val is not None
        ]
        self._time = time
        self._wall_time = time * 3 if wall_time is None else wall_time
        self._cpu_time = time + 5 if time else 0
        self._memory = memory
        self._child_personality = personality
        self._child_memory = memory * 1024 + data_grace * 1024 if memory else 0
        self._child_address = memory * 1024 + address_grace * 1024 if memory else 0
        self._nproc = nproc
        self._fsize = fsize
        if cpu_affinity:
            for cpu in cpu_affinity:
                self._cpu_affinity_mask |= 1 << cpu

        self._is_tle = False
        self._is_ole = False
        self.protection_fault: Optional[Tuple[int, str, List[int], Optional[int]]] = None

        self._security = security
        if security is not None:
            self.configure_files(security.read_fs, security.write_fs)
        else:
            self.configure_files([], [])

        # Notify supervisor: route the dynamic, memory-inspecting syscalls (metadata path checks,
        # kill/prctl/prlimit, fix_case_path opens) to seccomp user-notification so the existing
        # isolate.py handlers run with no ptrace. Built per ABI so non-native arches work too.
        self._notify_handlers: Dict[int, Dict[int, Callable]] = {}  # abi -> {raw syscall nr: handler}
        self._execve_nr: Dict[int, int] = {}  # abi -> execve syscall nr (special-cased in dispatch)
        self._exit_group_nr: Dict[int, int] = {}  # abi -> exit_group nr (final-memory read at exit)
        if security is not None and use_notify and NOTIFY_NATIVE_ARCH != 0:
            for abi in SUPPORTED_ABIS:
                if abi not in _AUDIT_ARCH:
                    continue
                index = _SYSCALL_INDICIES[abi]
                if index is None:
                    continue
                table: Dict[int, Callable] = {}
                for i in range(SYSCALL_COUNT):
                    handler = security.get(i)
                    # Only the callable checkers become NOTIFY; ALLOW (int) and ErrnoHandlerCallback
                    # are resolved statically in the BPF (see _get_seccomp_handlers).
                    if handler is None or isinstance(handler, (int, ErrnoHandlerCallback)):
                        continue
                    for raw in translator[i][index]:
                        if raw is not None:
                            table[raw] = handler
                self._notify_handlers[abi] = table
                for raw in translator[sys_execve][index]:
                    if raw is not None:
                        self._execve_nr[abi] = raw
                for raw in translator[sys_exit_group][index]:
                    if raw is not None:
                        self._exit_group_nr[abi] = raw
        self._use_notify = any(self._notify_handlers.values())
        self._notify_socket_parent: Optional[socket.socket] = None
        self._notify_thread: Optional[threading.Thread] = None

        self.__init_streams(stdin, stdout, stderr, child_stdin, child_stdout)

        # Supervision state. (Process.returncode/_exited/_exitcode are read-only C-managed fields
        # for the ptrace monitor; we track our own and override the properties below.)
        self._rc: Optional[int] = None
        self._exited_flag = False
        self._was_initialized = False
        self._reached_exec_sync = False
        self._cpu_seconds = 0.0
        self._wall_seconds = 0.0
        self._max_memory_kb = 0
        self._start_monotonic = 0.0
        self._died = threading.Event()
        self._spawned_or_errored = threading.Event()
        self._spawn_error: Optional[BaseException] = None

        # The poller samples peak memory (always) and enforces the soft wall/CPU limit (when set).
        self._poller = threading.Thread(target=self._poller_thread, daemon=True)
        self._poller.start()
        self._worker = threading.Thread(target=self._run_process, daemon=True)
        self._worker.start()

        self._spawned_or_errored.wait()
        if self._spawn_error is not None:
            raise self._spawn_error

    # ---- security policy -> seccomp action table -------------------------------------------------

    def _get_seccomp_handlers(self) -> List[int]:
        # -1 leaves no rule, so the syscall hits the filter default (SCMP_ACT_KILL_PROCESS in the
        # ptrace-less child). 0 -> ALLOW, >0 -> ERRNO(n), -2 -> NOTIFY (Stage B).
        handlers = [-1] * MAX_SYSCALL_NUMBER
        index = _SYSCALL_INDICIES[NATIVE_ABI]
        assert index is not None
        for i in range(SYSCALL_COUNT):
            handler = self._security.get(i)
            if handler is None:
                continue  # not in policy -> KILL by default
            for call in translator[i][index]:
                if call is None:
                    continue
                if isinstance(handler, int):
                    if handler == ALLOW:
                        handlers[call] = 0
                    # DISALLOW -> leave -1 (KILL)
                elif isinstance(handler, ErrnoHandlerCallback):
                    handlers[call] = handler.errno
                else:
                    # Callable checker (FS/metadata path checks, kill/prctl/prlimit). With the
                    # notify supervisor, route to it (NOTIFY); otherwise ALLOW (the Stage A
                    # fallback, which loses metadata restriction and arg checks).
                    handlers[call] = _NOTIFY if self._use_notify else 0
        if self._use_notify:
            # Notify on exit_group so we read the final VmHWM (the program's true peak RSS) while it
            # is still alive -- the ptrace exit-stop equivalent, robust against a fast spike the
            # poller would miss. (execve is forced to NOTIFY in helper.cpp for was_initialized.)
            for call in translator[sys_exit_group][index]:
                if call is not None:
                    handlers[call] = _NOTIFY
        return handlers

    def configure_files(self, read_fs: List[FilesystemAccessRule], write_fs: List[FilesystemAccessRule]) -> None:
        def _paths(source, kind):
            return [utf8bytes(rule.path) for rule in source if isinstance(rule, kind)]

        self.landlock_read_exact_files = _paths(read_fs, ExactFile)
        self.landlock_read_exact_dirs = _paths(read_fs, ExactDir)
        self.landlock_read_recursive_dirs = _paths(read_fs, RecursiveDir)
        self.landlock_write_exact_files = _paths(write_fs, ExactFile)
        self.landlock_write_exact_dirs = _paths(write_fs, ExactDir)
        self.landlock_write_recursive_dirs = _paths(write_fs, RecursiveDir)

    # ---- supervision -----------------------------------------------------------------------------

    def _run_process(self) -> None:
        notify_child_sock: Optional[socket.socket] = None
        if self._use_notify:
            # A socketpair the forked child inherits; it sends the seccomp notify listener fd back
            # over it (SCM_RIGHTS). _spawn passes the child end's fd number to the child config.
            self._notify_socket_parent, notify_child_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            self._notify_fd_socket = notify_child_sock.fileno()
        try:
            # Shared Process._spawn forks (pt_process::spawn) and runs cptbox_child_run with
            # use_ptrace=0; the child stops itself with SIGSTOP after the early setup.
            self._spawn(self._executable, self._args, self._env, self._chdir)
        except BaseException as e:
            self._spawn_error = e if isinstance(e, Exception) else RuntimeError(repr(e))
            self._died.set()
            return
        finally:
            # Close the parent's copies of the child's stdio fds, else the pipes never reach EOF
            # (the parent would still hold a write end) and communicate() would hang.
            if self.stdin_needs_close:
                os.close(self._child_stdin)
            if self.stdout_needs_close:
                os.close(self._child_stdout)
            if self.stderr_needs_close:
                os.close(self._child_stderr)
            if self.fd_3_needs_close:
                os.close(self._child_fd_3)
            if self.fd_4_needs_close:
                os.close(self._child_fd_4)
            if hasattr(self, '_devnull'):
                os.close(self._devnull)
            # The child inherited the socketpair fd via fork; drop the parent's copy of that end.
            if notify_child_sock is not None:
                notify_child_sock.close()
            self._spawned_or_errored.set()

        if self._spawn_error is not None:
            self._died.set()
            return

        pid = self.pid
        self._start_monotonic = time.monotonic()

        try:
            self._reap(pid)
        finally:
            self._wall_seconds = time.monotonic() - self._start_monotonic
            self._exited_flag = True
            self._died.set()

    def _reap(self, pid: int) -> None:
        # 1. Wait for the child's initial SIGSTOP (the sync point), then release it with SIGCONT.
        #    If the child instead exits here, it failed during the pre-SIGSTOP setup.
        wpid, status = os.waitpid(pid, os.WUNTRACED)
        if os.WIFEXITED(status) or os.WIFSIGNALED(status):
            self._rc = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -os.WTERMSIG(status)
            return
        assert os.WIFSTOPPED(status)
        self._reached_exec_sync = True
        os.kill(pid, signal.SIGCONT)

        # 1b. Receive the seccomp notify listener fd the child sends after seccomp_load, and start
        #     the service thread before the program does much (its first notified syscall blocks
        #     until we answer). recv_fds returns no fds if the child had no NOTIFY rules.
        if self._use_notify and self._notify_socket_parent is not None:
            listener_fd = None
            try:
                # The child sends the fd right after seccomp_load (a few ms after SIGCONT); a timeout
                # ensures we never block forever if the handoff stalls, then fall to kill() below.
                self._notify_socket_parent.settimeout(30.0)
                _msg, fds, _flags, _addr = socket.recv_fds(self._notify_socket_parent, 1, 1)
                listener_fd = fds[0] if fds else None
            except OSError:
                listener_fd = None
            finally:
                self._notify_socket_parent.close()
                self._notify_socket_parent = None
            if listener_fd is not None:
                self._notify_thread = threading.Thread(target=self._notify_service, args=(listener_fd,), daemon=True)
                self._notify_thread.start()
            else:
                # The child's seccomp filter defaults to NOTIFY, so with no service thread its first
                # notified syscall would block forever (and the reaper would hang in wait4). If we
                # didn't get the listener fd, the child cannot be supervised -- kill the group so it
                # exits and the reaper reports the failure instead of hanging. (The child has already
                # exited via PTBOX_SPAWN_FAIL_SECCOMP_NOTIFY in the common cause of this.)
                self.kill()

        # 2. Reap the whole process group. The leader's exit gives the program's returncode; we keep
        #    reaping other group members (threads/children) and accumulating their CPU until ECHILD.
        pgid = pid
        cpu = 0.0
        while True:
            try:
                wpid, status, rusage = os.wait4(-pgid, 0)
            except ChildProcessError:
                break
            if os.WIFEXITED(status) or os.WIFSIGNALED(status):
                cpu += rusage.ru_utime + rusage.ru_stime
                # NB: not ru_maxrss for memory -- it is the lifetime peak RSS and so includes the
                # ~tens of MB of fork-COW pages this child inherits from the (large) Python judge
                # before execve. VmHWM (polled post-execve, below) reflects only the program.
                if wpid == pid:
                    if not self._use_notify:
                        # No execve notification to confirm the program started; fall back to a
                        # heuristic (with notify, was_initialized is set authoritatively there).
                        self._was_initialized = self._reached_exec_sync and not (
                            os.WIFEXITED(status) and os.WEXITSTATUS(status) in _SPAWN_FAIL_CODES
                        )
                    if (
                        os.WIFSIGNALED(status)
                        and os.WTERMSIG(status) == signal.SIGSYS
                        and self.protection_fault is None
                    ):
                        # Killed by the seccomp default action (a disallowed syscall) -> report IR.
                        self.protection_fault = (-1, 'disallowed syscall', [0] * 6, None)
                    self._rc = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -os.WTERMSIG(status)
                elif os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGSYS:
                    # A forked child committed a disallowed syscall (static KILL default). Attribute
                    # it and tear down the whole group, matching ptrace (which faults on any task's
                    # violation) -- otherwise a submission could probe forbidden syscalls in
                    # throwaway children while the leader exits cleanly and is never flagged IR.
                    if self.protection_fault is None:
                        self.protection_fault = (-1, 'disallowed syscall', [0] * 6, None)
                    self.kill()
        # wait4(-pgid) only reaps OUR children (the leader); a child the leader forked and did not
        # wait() is reparented to init when the leader exits, escaping our reap loop (ECHILD). Such
        # an orphan stays in the process group, so SIGKILL the whole group to tear down any survivor
        # (init then reaps it) -- otherwise it could spin on after the leader exits. Loop because a
        # survivor can fork() in the window between our scan and the signal; retry until the group is
        # empty (ProcessLookupError) or we hit the bound. A fork bomb under nproc=-1 is the limit of
        # what this best-effort teardown covers; a fully robust kill would need a cgroup. (RLIMIT_CPU
        # still bounds CPU when a time limit is set.)
        for _ in range(64):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                break  # group empty
            except OSError:
                break
            time.sleep(0.001)
        # max() with the poller's live group-CPU reading (the reaper only sees the leader's rusage;
        # forked children are reaped by their own parents, not us).
        self._cpu_seconds = max(self._cpu_seconds, cpu)

    # ---- seccomp user-notification service -------------------------------------------------------

    def _notify_service(self, listener_fd: int) -> None:
        # One supervisor fd serves the whole forked tree. We poll (rather than block) so we notice
        # _died and shut down even with no further notifications pending.
        poller = select.poll()
        poller.register(listener_fd, select.POLLIN)
        try:
            while not self._died.is_set():
                events = poller.poll(50)
                if not events:
                    continue
                if events[0][1] & (select.POLLHUP | select.POLLERR | select.POLLNVAL):
                    break
                notif = notify_receive(listener_fd)
                if notif is None:
                    continue  # target vanished before RECV, or transient error
                try:
                    self._handle_notification(listener_fd, notif)
                except Exception:
                    # One bad notification must not take down supervision for the whole tree. Deny
                    # this syscall (fail-closed) and keep serving.
                    log.exception('ptrace-less notify dispatch crashed; denying notification')
                    try:
                        notify_respond(listener_fd, notif[0], 0, -_errno.EPERM, 0)
                    except OSError:
                        pass
        finally:
            try:
                os.close(listener_fd)
            except OSError:
                pass

    def _handle_notification(self, listener_fd: int, notif) -> None:
        notif_id, pid, nr, arch, args = notif
        abi = _ARCH_TO_ABI.get(arch)
        if abi is None or abi not in self._notify_handlers:
            # Unknown/unsupported arch: deny conservatively (raw nrs are arch-specific).
            notify_respond(listener_fd, notif_id, 0, -_errno.EPERM, 0)
            return
        table = self._notify_handlers[abi]

        # execve is notified so we learn the program started -- its was_initialized signal. The
        # first execve is cptbox exec'ing the program and is always allowed. Later execves are the
        # submission re-exec'ing: if the policy has a custom execve checker (e.g. shell/DART
        # executors that exec a whitelisted helper), fall through to run it; otherwise deny, matching
        # ptrace mode (where the first execve only sets `spawned` and the rest go through the table).
        if nr == self._execve_nr.get(abi):
            if not self._was_initialized:
                self._was_initialized = True
                notify_respond(listener_fd, notif_id, 0, 0, NOTIFY_FLAG_CONTINUE)
                return
            if nr not in table:
                self.protection_fault = (nr, 'execve', list(args), None)
                notify_respond(listener_fd, notif_id, 0, -_errno.EPERM, 0)
                self.kill()
                return
            # else: a custom execve checker is registered -- dispatch to it below.

        # exit_group is notified so we read the program's final VmHWM while it is still alive (the
        # ptrace exit-stop equivalent), then let it exit. This is the authoritative peak-memory
        # reading; the poller is a backstop for processes that are killed instead of exiting.
        if nr == self._exit_group_nr.get(abi):
            hwm = _read_proc_vmhwm_kb(pid)
            if hwm:
                self._max_memory_kb = max(self._max_memory_kb, hwm)
            notify_respond(listener_fd, notif_id, 0, 0, NOTIFY_FLAG_CONTINUE)
            return

        handler = table.get(nr)
        if handler is None:
            # A syscall with no policy entry reached us via the NOTIFY default action: a disallowed
            # syscall (in the leader or any child). Record the violation (with its name) and kill
            # the whole group -- this is the ptrace protection_fault equivalent, and unlike a static
            # KILL it is visible even when a child is reaped by the leader before we could wait4 it.
            if self.protection_fault is None:
                self.protection_fault = (nr, _syscall_name(nr, _SYSCALL_INDICIES[abi]), list(args), None)
            notify_respond(listener_fd, notif_id, 0, -_errno.EPERM, 0)
            self.kill()
            return

        dbg = NotifyDebugger(pid, nr, args, listener_fd, notif_id, abi)
        try:
            allowed = handler(dbg)
            for cb in dbg.on_return_callbacks:
                cb()
        except Exception:
            log.exception('ptrace-less notify handler crashed on syscall %d', nr)
            allowed = False
        finally:
            dbg.close()

        if not allowed:
            # Hard deny (protection_fault): record it and kill the whole group, like the ptrace
            # monitor. Respond too, to unblock the syscall while the kill propagates.
            self.protection_fault = (nr, dbg.syscall_name, list(args), None)
            notify_respond(listener_fd, notif_id, 0, -_errno.EPERM, 0)
            self.kill()
        elif dbg.skip:
            # The handler neutralized the syscall (e.g. ErrnoHandlerCallback). Emulate its result.
            # The response error is the negative errno the syscall should return (kernel ABI).
            if dbg.error:
                notify_respond(listener_fd, notif_id, 0, -dbg.error, 0)
            else:
                notify_respond(listener_fd, notif_id, dbg.result, 0, 0)
        else:
            # Allow: let the kernel run the syscall with the child's current memory (fix_case_path
            # has already rewritten the path). Documented residual: a sibling thread can race the
            # path between our check and the kernel's read (the seccomp-notify TOCTOU). This only
            # affects the *metadata* checks (info-leak protection), never file access -- open/exec
            # are Landlock-gated and TOCTOU-free.
            notify_respond(listener_fd, notif_id, 0, 0, NOTIFY_FLAG_CONTINUE)

    def _poller_thread(self) -> None:
        # Samples peak memory and enforces the soft wall/CPU limits. The hard caps are kernel-side:
        # RLIMIT_CPU (SIGXCPU/SIGKILL) and RLIMIT_AS/DATA. VmHWM is monotonic and resets at execve,
        # so it reflects only the program (not the fork-COW pages ru_maxrss would include); we poll
        # finely so a short-lived memory spike is still captured.
        self._spawned_or_errored.wait()
        if self._spawn_error is not None:
            return
        pid = self.pid  # also the process-group id (the child did setpgid(0, 0))
        last_cpu_check = 0.0
        while not self._died.wait(0.01):
            hwm = _read_proc_vmhwm_kb(pid)
            if hwm:
                self._max_memory_kb = max(self._max_memory_kb, hwm)
            if not (self._time or self._wall_time):
                continue
            now = time.monotonic()
            if self._wall_time and now - self._start_monotonic > self._wall_time:
                self._is_tle = True
                self.kill()
                break
            # The CPU check scans /proc by group, so throttle it (the wall check above is the cheap
            # fast path). 50ms granularity is plenty for a soft time limit.
            if self._time and now - last_cpu_check >= 0.05:
                last_cpu_check = now
                group_cpu = _read_group_cpu_seconds(pid)
                # Record the live group total so the reported execution_time is the whole tree's CPU
                # (the reaper only sees the leader; children are reaped by their own parents).
                self._cpu_seconds = max(self._cpu_seconds, group_cpu)
                if group_cpu > self._time:
                    self._is_tle = True
                    self.kill()
                    break

    # ---- results ---------------------------------------------------------------------------------

    def wait(self) -> int:
        self._died.wait()
        assert self.returncode is not None
        if not self._was_initialized:
            if self.returncode == PTBOX_SPAWN_FAIL_NO_NEW_PRIVS:
                raise RuntimeError('failed to call prctl(PR_SET_NO_NEW_PRIVS)')
            elif self.returncode == PTBOX_SPAWN_FAIL_SECCOMP:
                raise RuntimeError('failed to set up seccomp policy')
            elif self.returncode == PTBOX_SPAWN_FAIL_EXECVE:
                raise RuntimeError('failed to spawn child')
            elif self.returncode == PTBOX_SPAWN_FAIL_SETAFFINITY:
                raise RuntimeError('failed to set child affinity')
            elif self.returncode == PTBOX_SPAWN_FAIL_LANDLOCK:
                raise RuntimeError('failed to set up landlock')
            elif self.returncode == PTBOX_SPAWN_FAIL_SECCOMP_NOTIFY:
                raise RuntimeError('failed to hand off the seccomp notify listener fd')
            elif self.returncode >= 0 and self._reached_exec_sync is False:
                raise RuntimeError('process failed to initialize with unknown exit code: %d' % self.returncode)
        return self.returncode

    def poll(self) -> Optional[int]:
        return self.returncode

    @property
    def returncode(self) -> Optional[int]:
        return self._rc

    @property
    def signal(self) -> Optional[int]:
        # Negative returncode means killed by signal -self._rc (e.g. SIGSYS from a seccomp KILL).
        if self._rc is not None and self._rc < 0:
            return -self._rc
        return None

    @property
    def was_initialized(self) -> bool:
        return self._was_initialized

    @property
    def mle(self) -> int:
        return self._memory

    def mark_ole(self) -> None:
        self._is_ole = True

    @property
    def is_ir(self) -> bool:
        assert self.returncode is not None
        return self.returncode > 0

    @property
    def is_mle(self) -> bool:
        return self._memory != 0 and self.max_memory > self._memory

    @property
    def is_ole(self) -> bool:
        return self._is_ole

    @property
    def is_rte(self) -> bool:
        return self.returncode is None or self.returncode < 0

    @property
    def is_tle(self) -> bool:
        return self._is_tle

    @property
    def execution_time(self) -> float:
        return self._cpu_seconds

    @property
    def cpu_time(self) -> float:
        return self._cpu_seconds

    @property
    def wall_clock_time(self) -> float:
        if self._exited_flag:
            return self._wall_seconds
        return time.monotonic() - self._start_monotonic if self._start_monotonic else 0.0

    @property
    def max_memory(self) -> int:
        # KB, matching the ptrace path's max_memory.
        if not self._exited_flag:
            hwm = _read_proc_vmhwm_kb(self.pid)
            if hwm:
                self._max_memory_kb = max(self._max_memory_kb, hwm)
        return self._max_memory_kb

    def kill(self) -> None:
        # Gate on whole-group liveness (_exited_flag, set only after the reaper has fully drained and
        # killpg'd the group), NOT on the leader's returncode: the group outlives the leader (forked
        # children/orphans), and `_rc` is set the moment the leader is reaped. Gating on `_rc` would
        # make kill() a no-op while children are still alive -- a TLE/wall-limit and protection-fault
        # evasion. While _exited_flag is False at least the reaper is live and the pgid is ours, so
        # killpg is safe; once True the group is gone and we skip it (avoiding a reused-pgid signal).
        # Guard self.pid > 0: on a spawn failure pid is unset (0) and killpg(0) would signal the
        # judge's own process group.
        if self.pid > 0 and not self._exited_flag:
            log.warning('Request the killing of process: %s', self.pid)
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except OSError:
                pass

    def __init_streams(self, stdin, stdout, stderr, child_stdin, child_stdout) -> None:
        self.stdin = self.stdout = self.stderr = None
        self.stdin_needs_close = self.stdout_needs_close = self.stderr_needs_close = False
        self.fd_3_needs_close = self.fd_4_needs_close = False
        self._child_fd_3 = self._child_fd_4 = -1

        if stdin == FILE_IO_PIPE:
            self._child_stdin = (
                child_stdin if isinstance(child_stdin, int) and child_stdin >= 0 else self._get_devnull()
            )
            self._child_fd_3, self._stdin = os.pipe()
            self.stdin = os.fdopen(self._stdin, 'wb')
            self.fd_3_needs_close = True
        elif stdin == PIPE:
            self._child_stdin, self._stdin = os.pipe()
            self.stdin = os.fdopen(self._stdin, 'wb')
            self.stdin_needs_close = True
        elif isinstance(stdin, int):
            self._child_stdin, self._stdin = stdin, -1
        elif stdin is not None:
            self._child_stdin, self._stdin = stdin.fileno(), -1
        else:
            self._child_stdin = self._stdin = -1

        if stdout == FILE_IO_PIPE:
            self._child_stdout = (
                child_stdout if isinstance(child_stdout, int) and child_stdout >= 0 else self._get_devnull()
            )
            self._stdout, self._child_fd_4 = os.pipe()
            self.stdout = os.fdopen(self._stdout, 'rb')
            self.fd_4_needs_close = True
        elif stdout == PIPE:
            self._stdout, self._child_stdout = os.pipe()
            self.stdout = os.fdopen(self._stdout, 'rb')
            self.stdout_needs_close = True
        elif isinstance(stdout, int):
            self._stdout, self._child_stdout = -1, stdout
        elif stdout is not None:
            self._stdout, self._child_stdout = -1, stdout.fileno()
        else:
            self._stdout = self._child_stdout = -1

        if stderr == PIPE:
            self._stderr, self._child_stderr = os.pipe()
            self.stderr = os.fdopen(self._stderr, 'rb')
            self.stderr_needs_close = True
        elif stderr == STDOUT:
            self._stderr, self._child_stderr = -1, self._child_stdout
        elif isinstance(stderr, int):
            self._stderr, self._child_stderr = -1, stderr
        elif stderr is not None:
            self._stderr, self._child_stderr = -1, stderr.fileno()
        else:
            self._stderr = self._child_stderr = -1

    def _get_devnull(self):
        if not hasattr(self, '_devnull'):
            self._devnull = os.open(os.devnull, os.O_RDWR)
        return self._devnull

    communicate = _safe_communicate

    def unsafe_communicate(self, input: Optional[bytes] = None) -> Tuple[bytes, bytes]:
        return _safe_communicate(self, input=input, outlimit=sys.maxsize, errlimit=sys.maxsize)


SECCOMP_LANDLOCK_MODE = 'seccomp+landlock'


def select_sandbox_popen():
    """Choose the sandbox supervisor for a launch.

    Returns SeccompPopen (ptrace-less: seccomp + Landlock + notify) when
    DMOJ_SANDBOX_MODE=seccomp+landlock and Landlock is available, otherwise TracedPopen (ptrace).
    Ptrace-less relies on Landlock for filesystem security, so if Landlock is unavailable we fall
    back to ptrace with a warning rather than running with weaker enforcement.
    """
    if os.environ.get('DMOJ_SANDBOX_MODE') == SECCOMP_LANDLOCK_MODE:
        # Require both Landlock (the filesystem boundary) and a notify-capable arch. Without notify,
        # the dynamic checkers (kill/prctl/prlimit/metadata) would have no supervisor and the filter
        # would have to statically ALLOW them -- a fail-open we must not risk, so use ptrace instead.
        if has_landlock() and NOTIFY_NATIVE_ARCH != 0:
            return SeccompPopen
        log.warning(
            'DMOJ_SANDBOX_MODE=%s but Landlock/seccomp-notify is unavailable; using ptrace',
            SECCOMP_LANDLOCK_MODE,
        )
    return TracedPopen
