# Ptrace-less sandbox (seccomp + Landlock, no ptrace) — design

Status: **implemented** (Stages A+B+C), branch `feat/ptraceless`. Selected by
`DMOJ_SANDBOX_MODE=seccomp+landlock`; falls back to ptrace if Landlock is unavailable. Passes the
C/C++ testsuite at parity with ptrace (incl. bridged interactor/checker/CMS/testlib, File-IO,
fix_case_path, memfd) and is ~1.8x faster on a fork-heavy multiprocess workload. This documents the
design and the empirically-verified facts it rests on, so the security-critical parts can be
reviewed.

## What was built (final)

- `helper.cpp`: `use_ptrace=0` child — no traceme, `KILL_PROCESS`-default seccomp filter, PDEATHSIG,
  hands the notify listener fd to the supervisor (SCM_RIGHTS), `execve` notified (not statically
  allowed) so the supervisor gates it.
- `notify_helper.{cpp,h}` + Cython wrappers: the RECV/SEND/ID_VALID ioctls and native AUDIT_ARCH.
- `seccomp_tracer.py`: `SeccompPopen` supervisor + `NotifyDebugger` + `select_sandbox_popen()`.
- `base_executor.launch` chooses the backend via `select_sandbox_popen()`.

Two design points landed differently than first sketched below, both better:
- **was_initialized**: not a CLOEXEC error-pipe, but the **execve notification** — the first execve
  is the program starting (sets was_initialized + is allowed); later execves are submission re-exec
  and are denied (matching ptrace). One mechanism, two jobs.
- **peak memory**: not just polling — `exit_group` is **notified** so the supervisor reads the final
  `VmHWM` while the process is still alive (the ptrace exit-stop equivalent), with the poller as a
  backstop for killed processes. `ru_maxrss` is deliberately NOT used (it includes the fork-COW
  pages inherited from the large Python judge before execve).
- **violation reporting**: the seccomp **default action is NOTIFY** (when a supervisor is attached),
  so a disallowed syscall in ANY process — including a forked child that the leader reaps before the
  reaper could `wait4` it — reaches the supervisor, which records `protection_fault` (with the
  syscall name) and kills the group. This matches ptrace's per-task fault. Default `KILL_PROCESS`
  only when no supervisor (notify unavailable). (The reaper also flags `WTERMSIG==SIGSYS` as a
  backstop.)
- **multi-arch**: notifications are dispatched per-ABI (native + non-native, e.g. 32-bit on 64-bit).
- **CPU/TLE accounting**: the poller sums utime+stime+cutime+cstime over the whole **process group**
  (scanned from /proc), not just the leader, so a submission can't offload CPU to children while its
  leader idles in `wait()`. RLIMIT_CPU is per-process and only a hard backstop.

## Known limitations (accepted)

- **32-bit-only syscalls** on a 64-bit host (i386 `socketcall`/`stat64`/`mmap2`/…) have no native
  number, so they hit the default action (NOTIFY→reported/killed). Fail-closed but breaks pure
  32-bit submissions under ptrace-less; `select_sandbox_popen()` could fall back to ptrace for them.
- **metadata-check TOCTOU**: a CONTINUE'd metadata syscall (stat/access/readlink) can be path-raced
  by a sibling thread (info-leak only — open/exec are Landlock-gated and TOCTOU-free).
- **setrlimit** is statically ALLOW'd to the submission (cptbox needs it post-`seccomp_load`); inert
  because the hard limits are pinned and `prlimit64`-on-self already grants the same.
- `select_sandbox_popen()` falls back to **ptrace** when Landlock or a notify-capable arch is
  unavailable (never runs ptrace-less with the dynamic checkers statically ALLOW'd).

## Goal

Run submissions under **seccomp + Landlock + rlimits with no ptrace attached**, so multiprocess
programs don't pay the ptrace per-spawn / per-trapped-syscall cost. Landlock is the filesystem
security boundary (kernel-enforced, TOCTOU-free); seccomp is the syscall boundary; rlimits/timers
bound resources. The dynamic, memory-inspecting decisions (path-based metadata checks,
`fix_case_path`, `kill`/`prctl`/`prlimit` argument checks) move from ptrace callbacks to
**seccomp user-notification** (`SECCOMP_RET_USER_NOTIF`).

## Verified foundations (kernel 6.8 / ABI 4, uid 1000, see tests in /tmp during development)

1. `SECCOMP_FILTER_FLAG_NEW_LISTENER` installs **unprivileged** (only `no_new_privs`, no
   `CAP_SYS_ADMIN`). The listener fd is passed to the supervisor via `SCM_RIGHTS`.
2. **One** listener fd receives notifications from the **entire forked tree** (verified 8 children,
   8 distinct pids). So a single supervisor serves a multiprocess submission.
3. `SECCOMP_IOCTL_NOTIF_ID_VALID` works → TOCTOU-safe memory reads (validate id before and after
   reading `/proc/<pid>/mem`).
4. libseccomp 2.5.5 exposes `SCMP_ACT_NOTIFY` + `seccomp_notify_*`, so we reuse cptbox's existing
   libseccomp arch handling.
5. cgroup v2 is **not** delegated in the target (Docker) environment, so resource accounting uses
   `/proc/<pid>/status` (VmHWM) polling + `wait4` rusage — the same sources cptbox already uses,
   minus the ptrace stop that currently triggers the sample.
6. Landlock alone (no ptrace) denies forbidden open/exec/create/remove/rename/truncate, follows
   symlinks to the target inode, and is TOCTOU-immune under a path-swapping race (1.5M races, 0
   leaks). It does NOT govern stat/access/readlink/chdir (metadata) — those need notify or ALLOW.

## Architecture

```
judge (supervisor)                         sandboxed child
------------------                         ---------------
fork ───────────────────────────────────▶ no_new_privs
                                           PR_SET_PDEATHSIG(SIGKILL)
                                           Landlock restrict_self
                                           build seccomp filter:
                                             ALLOW   known-good syscalls
                                             ERRNO   soft-denied
                                             NOTIFY  dynamic (metadata, kill, prctl, casefix)
                                             default KILL_PROCESS (fail-closed)
                                           install w/ NEW_LISTENER  ─┐ listener fd
                       ◀── SCM_RIGHTS over socketpair ──────────────┘
hold listener fd                           (raise SIGSTOP for sync)
record start time, open pidfd
SIGCONT ─────────────────────────────────▶ dup2 fds, closefrom, setrlimit, execve(program)
wait4(-pgid) reaper thread  ◀───────────── program runs (children inherit filter+Landlock)
/proc VmHWM poller thread
timer thread: TLE (cpu/wall) -> killpg
notify service loop (epoll on listener):
  RECV -> NotifyDebugger -> isolate.py handler -> SEND (CONTINUE / errno / kill)
```

### Why the filter must allow cptbox's own setup syscalls

In ptrace mode the monitor allows every syscall before the first `execve`
(`ptproc.cpp:213-224`), so the child's post-`seccomp_load` setup (`closefrom`'s
`openat`/`getdents`/`close`, `setrlimit`, the final `execve`) runs freely. A static filter has no
such phase, so it must ALLOW those. Consequence: `setrlimit` and `execve` become allowed to the
submission too. This is safe — re-`exec` inherits the full sandbox (seccomp+Landlock+rlimits) and
`no_new_privs` neutralizes setuid — but it diverges from ptrace mode (which kills submission
`execve`). Stage B can tighten `execve` to first-exec-only via notify (the supervisor allows the
first `execve` from the root pid and kills later ones, replicating `is_end_of_first_execve`).

Note: `setrlimit` for RLIMIT_AS/DATA must stay AFTER `seccomp_load` (seccomp allocates memory; a
tight AS limit set first can OOM the filter install — see helper.cpp comment).

## seccomp action encoding (extends the existing handler array)

The per-syscall handler ints in `child_config.seccomp_handlers` are extended:
- `0`  -> ALLOW
- `>0` -> ERRNO(n)
- `-1` -> ptrace TRACE (legacy ptrace mode only)
- `-2` -> NOTIFY (ptrace-less)
The filter **default action** is mode-dependent: TRACE (ptrace) vs KILL_PROCESS (ptrace-less).
In Stage A (no notify yet) the dynamic `-2`/`-1` entries are emitted as `0` (ALLOW) so metadata is
temporarily permitted (the leak); Stage B emits `-2` and implements the supervisor.

## Resource accounting without ptrace

- **Peak memory**: poller thread reads `/proc/<pid>/status:VmHWM` for every live tree member (max),
  with `wait4` `ru_maxrss` as a floor. (cptbox already reads VmHWM; we just poll instead of
  sampling at the ptrace exit-stop.)
- **CPU time**: `wait4` rusage (`ru_utime`+`ru_stime`) accumulated across reaped members; plus
  RLIMIT_CPU as the kernel hard stop (SIGXCPU/SIGKILL).
- **Wall time**: `CLOCK_MONOTONIC` from `SIGCONT` to final reap.
- **TLE/wall kill**: timer thread (the existing shocker concept) `killpg`s on exceed.
- **MLE**: RLIMIT_AS/DATA (kernel) + the VmHWM poll for reporting.

## Cleanup / liveness

- `PR_SET_PDEATHSIG(SIGKILL)` in the child (set before `execve`, after the last fork) so the child
  dies if the judge dies — replacing `PTRACE_O_EXITKILL`. Backed by a `pidfd` on the root for the
  judge to `killpg`/poll. (PDEATHSIG is per-thread and cleared across `execve` of a setuid binary;
  with `no_new_privs` it persists. Verify in tests.)
- If the supervisor closes the listener fd, in-flight/future NOTIFY syscalls return `ENOSYS` to the
  child (fail-safe-ish: Landlock + ALLOW/ERRNO/KILL parts still enforce; only the notify'd dynamic
  syscalls degrade to ENOSYS).

## Violation reporting (protection_fault equivalent)

- A syscall hitting the default `KILL_PROCESS` kills with `SIGSYS`; the reaper sees
  `WIFSIGNALED(SIGSYS)` -> report IR. The exact syscall number for the message comes from the
  notify path when a dynamic syscall is denied; for the static `KILL` default we get coarser info
  (SIGSYS). Stage B can route unknowns through notify to recover the syscall number.

## Staging

- **Stage A**: ptrace-less core, NO notify. Static filter (ALLOW/ERRNO/KILL, default KILL),
  metadata ALLOW'd. Parent: reaper + poller + timer + cleanup. Proves spawn/accounting/kill/report.
- **Stage B**: notify supervisor + `NotifyDebugger` backing the `isolate.py` Debugger interface;
  restores metadata restriction, `fix_case_path`, and tight `kill`/`prctl`/`prlimit`/`execve`.
- **Stage C**: mode selection + ptrace fallback, full runtime testsuite, accounting parity vs
  ptrace, multiprocess benchmark, lint/format.

## Mode selection

New `DMOJ_SANDBOX_MODE` value `seccomp+landlock` selects ptrace-less. Falls back to ptrace
(`ptrace+seccomp[+landlock]`) when notify or Landlock is unavailable. `fix_case_path` requires
Stage B (notify) in ptrace-less mode; until then it forces the ptrace backend.
