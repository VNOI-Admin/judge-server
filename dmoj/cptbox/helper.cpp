#include "helper.h"
#include "landlock_helpers.h"
#include "notify_helper.h"
#include "ptbox.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#ifdef __FreeBSD__
#include <sys/param.h>
#include <sys/queue.h>
#include <sys/socket.h>
#include <sys/sysctl.h>

#include <libprocstat.h>
#else
#include <sched.h>
// No ASLR on FreeBSD... not as of 11.0, anyway
#include <sys/personality.h>
#include <sys/prctl.h>
#endif

#if defined(__FreeBSD__) || (defined(__APPLE__) && defined(__MACH__))
#define FD_DIR "/dev/fd"
#else
#define FD_DIR "/proc/self/fd"
#endif

inline void setrlimit2(int resource, rlim_t cur, rlim_t max) {
    rlimit limit;
    limit.rlim_cur = cur;
    limit.rlim_max = max;
    setrlimit(resource, &limit);
}

inline void setrlimit2(int resource, rlim_t limit) {
    setrlimit2(resource, limit, limit);
}

static inline void cptbox_close_fd(int fd) {
    while (close(fd) < 0 && errno == EINTR)
        ;
}

static inline bool fd_kept(int fd, const int *keep_fds);

#if !PTBOX_FREEBSD
// Send a single fd over a connected unix socket via SCM_RIGHTS. Returns 0 on success, -1 on error.
static int send_one_fd(int socket, int fd) {
    char dummy = 0;
    struct iovec io = { .iov_base = &dummy, .iov_len = 1 };
    union {
        char buf[CMSG_SPACE(sizeof(int))];
        struct cmsghdr align;
    } u;
    memset(&u, 0, sizeof u);
    struct msghdr msg = {};
    msg.msg_iov = &io;
    msg.msg_iovlen = 1;
    msg.msg_control = u.buf;
    msg.msg_controllen = sizeof u.buf;
    struct cmsghdr *cmsg = CMSG_FIRSTHDR(&msg);
    cmsg->cmsg_level = SOL_SOCKET;
    cmsg->cmsg_type = SCM_RIGHTS;
    cmsg->cmsg_len = CMSG_LEN(sizeof(int));
    memcpy(CMSG_DATA(cmsg), &fd, sizeof(int));
    while (sendmsg(socket, &msg, 0) < 0)
        if (errno != EINTR)
            return -1;
    return 0;
}
#endif

int cptbox_child_run(const struct child_config *config) {
#ifndef __FreeBSD__
    // There is no ASLR on FreeBSD, but disable it elsewhere
    if (config->personality > 0)
        personality(config->personality);

    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0))
        return PTBOX_SPAWN_FAIL_NO_NEW_PRIVS;

    if (!config->use_ptrace) {
        // Ptrace-less: there is no PTRACE_O_EXITKILL to clean us up, so ask the kernel to SIGKILL
        // this child if the supervisor (our parent) dies. This persists across execve of a normal
        // binary under no_new_privs. Best-effort, and only covers this (the group-leader) process --
        // PDEATHSIG is cleared on fork, so forked children rely on the supervisor's group teardown.
        prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0);
    }

#ifdef PR_SET_SPECULATION_CTRL  // Since Linux 4.17
    // Turn off Spectre Variant 4 protection in case it is turned on; we don't
    // care if submissions shoot themselves in the foot. Let this be a
    // best-effort attempt, and don't stop the submission from running if the
    // prctl fails.
    prctl(PR_SET_SPECULATION_CTRL, PR_SPEC_STORE_BYPASS, PR_SPEC_ENABLE, 0, 0);
#endif
#endif

    if (config->use_ptrace && ptrace_traceme()) {
        perror("ptrace");
        return PTBOX_SPAWN_FAIL_TRACEME;
    }

    if (config->cpu_affinity_mask) {
#if PTBOX_FREEBSD
        return PTBOX_SPAWN_FAIL_SETAFFINITY;
#else
        cpu_set_t cpuset;
        CPU_ZERO(&cpuset);

        for (size_t i = 0; i < sizeof(config->cpu_affinity_mask) * 8; i++) {
            if (config->cpu_affinity_mask & (1 << i)) {
                CPU_SET(i, &cpuset);
            }
        }

        if (sched_setaffinity(getpid(), sizeof(cpuset), &cpuset)) {
            perror("sched_setaffinity");
            return PTBOX_SPAWN_FAIL_SETAFFINITY;
        }
#endif
    }

    kill(getpid(), SIGSTOP);

#if !PTBOX_FREEBSD
    // Landlock filesystem enforcement, applied after NO_NEW_PRIVS and before execve; restrictions
    // are inherited across execve and only ever get stricter. Requires ABI 3 (Linux 6.2), the
    // first version that governs the whole filesystem surface (truncation cannot be denied before
    // it). No-op where Landlock is unavailable or disabled (older kernel, DMOJ_SANDBOX_MODE=
    // ptrace+seccomp, or blocked by an outer seccomp filter e.g. Docker), leaving ptrace+seccomp
    // in charge.
    if (get_landlock_version() < 3) {
        // Landlock unavailable or too old; leave ptrace+seccomp in charge.
        goto seccomp_setup;
    }
    {
        struct landlock_ruleset_attr ruleset_attr = {
            .handled_access_fs =
                LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_READ_FILE |
                LANDLOCK_ACCESS_FS_READ_DIR | LANDLOCK_ACCESS_FS_REMOVE_DIR | LANDLOCK_ACCESS_FS_REMOVE_FILE |
                LANDLOCK_ACCESS_FS_MAKE_CHAR | LANDLOCK_ACCESS_FS_MAKE_DIR | LANDLOCK_ACCESS_FS_MAKE_REG |
                LANDLOCK_ACCESS_FS_MAKE_SOCK | LANDLOCK_ACCESS_FS_MAKE_FIFO | LANDLOCK_ACCESS_FS_MAKE_BLOCK |
                LANDLOCK_ACCESS_FS_MAKE_SYM | LANDLOCK_ACCESS_FS_REFER | LANDLOCK_ACCESS_FS_TRUNCATE,
        };
        int ruleset_fd = landlock_create_ruleset(&ruleset_attr, sizeof(ruleset_attr), 0);
        if (ruleset_fd < 0) {
            perror("landlock_create_ruleset");
            return PTBOX_SPAWN_FAIL_LANDLOCK;
        }

        // WRITE must imply READ: one rule must grant both, else an O_RDWR open fails even when
        // separate rules grant read and write.
        __u64 read_file = LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_EXECUTE;
        __u64 read_dir = LANDLOCK_ACCESS_FS_READ_DIR;
        __u64 read_recursive = LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_READ_DIR;
        __u64 write_file = LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_WRITE_FILE |
                           LANDLOCK_ACCESS_FS_TRUNCATE;
        __u64 write_dir = LANDLOCK_ACCESS_FS_READ_DIR;
        __u64 write_recursive =
            LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_READ_DIR |
            LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_TRUNCATE | LANDLOCK_ACCESS_FS_REMOVE_DIR |
            LANDLOCK_ACCESS_FS_REMOVE_FILE | LANDLOCK_ACCESS_FS_MAKE_REG | LANDLOCK_ACCESS_FS_MAKE_DIR |
            LANDLOCK_ACCESS_FS_MAKE_SYM | LANDLOCK_ACCESS_FS_MAKE_CHAR | LANDLOCK_ACCESS_FS_MAKE_SOCK |
            LANDLOCK_ACCESS_FS_MAKE_FIFO | LANDLOCK_ACCESS_FS_MAKE_BLOCK | LANDLOCK_ACCESS_FS_REFER;

        if (landlock_add_rules(ruleset_fd, config->landlock_read_exact_files, read_file) ||
            landlock_add_rules(ruleset_fd, config->landlock_read_exact_dirs, read_dir) ||
            landlock_add_rules(ruleset_fd, config->landlock_read_recursive_dirs, read_recursive) ||
            landlock_add_rules(ruleset_fd, config->landlock_write_exact_files, write_file) ||
            landlock_add_rules(ruleset_fd, config->landlock_write_exact_dirs, write_dir) ||
            landlock_add_rules(ruleset_fd, config->landlock_write_recursive_dirs, write_recursive)) {
            close(ruleset_fd);
            return PTBOX_SPAWN_FAIL_LANDLOCK;
        }

        if (landlock_restrict_self(ruleset_fd, 0)) {
            perror("landlock_restrict_self");
            close(ruleset_fd);
            return PTBOX_SPAWN_FAIL_LANDLOCK;
        }
        close(ruleset_fd);
    }

seccomp_setup:
    // Ptrace mode traps unknown syscalls to the tracer. Ptrace-less defaults to NOTIFY (when a
    // supervisor is attached) so a disallowed syscall in ANY process -- including a forked child the
    // leader reaps before we could see it -- reaches the supervisor, which records the violation
    // (with the syscall name) and kills the group, matching ptrace's per-task fault. Without a
    // supervisor (no notify), default to KILL_PROCESS (fail-closed).
    scmp_filter_ctx ctx =
        seccomp_init(config->use_ptrace ? SCMP_ACT_TRACE(0)
                                        : (config->notify_fd_socket >= 0 ? SCMP_ACT_NOTIFY : SCMP_ACT_KILL_PROCESS));
    if (!ctx) {
        fprintf(stderr, "Failed to initialize seccomp context!");
        goto seccomp_init_fail;
    }

    int rc;
    // By default, the native architecture is added to the filter already, so we add all the non-native ones.
    // This will bloat the filter due to additional architectures, but a few extra compares in the BPF matters
    // very little when syscalls are rare and other overhead is expensive.
    for (uint32_t *arch = pt_debugger::seccomp_non_native_arch_list; *arch; ++arch) {
        if ((rc = seccomp_arch_add(ctx, *arch))) {
            fprintf(stderr, "seccomp_arch_add(%u): %s\n", *arch, strerror(-rc));
            // This failure is not fatal, it'll just cause the syscall to trap anyway.
        }
    }

    for (int syscall = 0; syscall < MAX_SYSCALL; syscall++) {
        int handler = config->seccomp_handlers[syscall];
        if (handler == 0) {
            if ((rc = seccomp_rule_add(ctx, SCMP_ACT_ALLOW, syscall, 0))) {
                fprintf(stderr, "seccomp_rule_add(..., SCMP_ACT_ALLOW, %d): %s\n", syscall, strerror(-rc));
                // This failure is not fatal, it'll just cause the syscall to trap anyway.
            }
        } else if (handler > 0) {
            if ((rc = seccomp_rule_add(ctx, SCMP_ACT_ERRNO(handler), syscall, 0))) {
                fprintf(stderr, "seccomp_rule_add(..., SCMP_ACT_ERRNO(%d), %d): %s\n", handler, syscall, strerror(-rc));
                // This failure is not fatal, it'll just cause the syscall to trap anyway.
            }
        } else if (handler == PTBOX_SECCOMP_NOTIFY) {
            // Ptrace-less dynamic syscall: notify the supervisor (seccomp user-notification).
            if ((rc = seccomp_rule_add(ctx, SCMP_ACT_NOTIFY, syscall, 0))) {
                fprintf(stderr, "seccomp_rule_add(..., SCMP_ACT_NOTIFY, %d): %s\n", syscall, strerror(-rc));
            }
        }
    }

    if (!config->use_ptrace) {
        // In ptrace mode the monitor allows every syscall before the program's first execve, which
        // covers cptbox's own post-seccomp_load setup (the closefrom() sweep, setrlimit, execve).
        // A static filter has no such phase, so handle those setup syscalls. setrlimit must stay
        // after seccomp_load (a tight RLIMIT_AS set first can OOM the filter install).
        seccomp_rule_add(ctx, SCMP_ACT_ALLOW, SCMP_SYS(setrlimit), 0);
        if (config->notify_fd_socket >= 0) {
            // We hand the notify listener fd to the supervisor with sendmsg() below, after the
            // filter is loaded; allow it. The submission cannot create sockets, so this is inert
            // to it, and the handoff socket is closed before execve regardless.
            seccomp_rule_add(ctx, SCMP_ACT_ALLOW, SCMP_SYS(sendmsg), 0);
            // Notify on execve: the supervisor allows the program's first execve (and learns the
            // program started -- its was_initialized signal) and denies any later re-exec by the
            // submission, matching ptrace mode.
            seccomp_rule_add(ctx, SCMP_ACT_NOTIFY, SCMP_SYS(execve), 0);
        } else {
            // No supervisor: allow execve statically (the still-fully-sandboxed submission may then
            // re-exec -- a divergence from ptrace mode, only in the notify-less fallback).
            seccomp_rule_add(ctx, SCMP_ACT_ALLOW, SCMP_SYS(execve), 0);
        }
    }

    if ((rc = seccomp_load(ctx))) {
        fprintf(stderr, "seccomp_load: %s\n", strerror(-rc));
        goto seccomp_load_fail;
    }

    if (!config->use_ptrace && config->notify_fd_socket >= 0) {
        // Hand the seccomp user-notification listener fd to the supervisor over the inherited
        // socketpair (then drop both fds, before the closefrom sweep). Done here, after load, so
        // the listener exists. If the policy installed no NOTIFY rules, seccomp_notify_fd() returns
        // -1; we just close the socket so the supervisor sees EOF and runs without a listener.
        int notify_listener = seccomp_notify_fd(ctx);
        if (notify_listener >= 0) {
            if (send_one_fd(config->notify_fd_socket, notify_listener) < 0) {
                perror("send seccomp notify fd");
                // Close the socket so the supervisor's recv sees EOF and tears us down: we cannot
                // exit cleanly here -- exit_group is NOTIFY-trapped and no service thread is running
                // (it only starts once the supervisor has this fd), so a clean return would block
                // forever. The supervisor's killpg then frees us.
                close(config->notify_fd_socket);
                close(notify_listener);
                seccomp_release(ctx);
                return PTBOX_SPAWN_FAIL_SECCOMP_NOTIFY;
            }
            close(notify_listener);
        }
        close(config->notify_fd_socket);
    }

    seccomp_release(ctx);
#endif

    if (config->stdin_ >= 0)
        dup2(config->stdin_, 0);
    if (config->stdout_ >= 0)
        dup2(config->stdout_, 1);
    if (config->stderr_ >= 0)
        dup2(config->stderr_, 2);
    if (config->fd_3_ >= 0)
        dup2(config->fd_3_, 3);
    else if (!fd_kept(3, config->keep_open_fds))
        cptbox_close_fd(3);
    if (config->fd_4_ >= 0)
        dup2(config->fd_4_, 4);
    else if (!fd_kept(4, config->keep_open_fds))
        cptbox_close_fd(4);
    cptbox_closefrom(5, config->keep_open_fds);

    // All these limits should be dropped after initializing seccomp, since seccomp allocates
    // memory, and if an arena isn't sufficiently free it could force seccomp into an OOM
    // situation where we'd fail to initialize.
    if (config->address_space)
        setrlimit2(RLIMIT_AS, config->address_space);

    if (config->memory)
        setrlimit2(RLIMIT_DATA, config->memory);

    if (config->cpu_time)
        setrlimit2(RLIMIT_CPU, config->cpu_time, config->cpu_time + 1);

    if (config->nproc >= 0)
        setrlimit2(RLIMIT_NPROC, config->nproc);

    if (config->fsize >= 0)
        setrlimit2(RLIMIT_FSIZE, config->fsize);

    if (config->dir && *config->dir)
        chdir(config->dir);

    setrlimit2(RLIMIT_STACK, RLIM_INFINITY);
    setrlimit2(RLIMIT_CORE, 0);

    execve(config->file, config->argv, config->envp);
    perror("execve");
    return PTBOX_SPAWN_FAIL_EXECVE;

#if !PTBOX_FREEBSD
seccomp_init_fail:
    seccomp_release(ctx);

seccomp_load_fail:
    return PTBOX_SPAWN_FAIL_SECCOMP;
#endif
}

int get_landlock_version() {
#if !PTBOX_FREEBSD
    const char *sandbox_mode = getenv("DMOJ_SANDBOX_MODE");
    if (sandbox_mode != nullptr && strcmp(sandbox_mode, "ptrace+seccomp") == 0) {
        // Allow forcing Landlock off.
        return 0;
    }

    int version = landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
    if (version >= 0)
        return version;
    // ENOSYS: kernel too old / Landlock not built in. EOPNOTSUPP: Landlock disabled at boot.
    // EPERM/EACCES: blocked by an outer seccomp filter (e.g. Docker's default profile).
    if (errno == ENOSYS || errno == EOPNOTSUPP || errno == EPERM || errno == EACCES)
        return 0;
    return -1;
#else
    return 0;  // FreeBSD has no Landlock.
#endif
}

// From python's _posixsubprocess
static int pos_int_from_ascii(char *name) {
    int num = 0;
    while (*name >= '0' && *name <= '9') {
        num = num * 10 + (*name - '0');
        ++name;
    }
    if (*name)
        return -1; /* Non digit found, not a number. */
    return num;
}

static inline bool fd_kept(int fd, const int *keep_fds) {
    if (keep_fds)
        for (const int *k = keep_fds; *k >= 0; ++k)
            if (*k == fd)
                return true;
    return false;
}

static void cptbox_closefrom_brute(int lowfd, const int *keep_fds) {
    int max_fd = sysconf(_SC_OPEN_MAX);
    if (max_fd < 0)
        max_fd = 16384;
    for (; lowfd <= max_fd; ++lowfd)
        if (!fd_kept(lowfd, keep_fds))
            cptbox_close_fd(lowfd);
}

static inline void cptbox_closefrom_dirent(int lowfd, const int *keep_fds) {
    DIR *d = opendir(FD_DIR);
    dirent *dir;

    if (d) {
        int fd_dirent = dirfd(d);
        errno = 0;
        while ((dir = readdir(d))) {
            int fd = pos_int_from_ascii(dir->d_name);
            if (fd < lowfd || fd == fd_dirent || fd_kept(fd, keep_fds))
                continue;
            cptbox_close_fd(fd);
            errno = 0;
        }
        if (errno)
            cptbox_closefrom_brute(lowfd, keep_fds);
        closedir(d);
    } else
        cptbox_closefrom_brute(lowfd, keep_fds);
}

// Borrowing some SYS_getdents64 magic from python's _posixsubprocess.
// Look there for explanation. We don't actually need O_CLOEXEC,
// since this process is single-threaded after fork, and could not
// possibly be exec'd before we close the fd. If it is, we have
// bigger problems than leaking the directory fd.
#ifdef __linux__
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/syscall.h>

struct linux_dirent64 {
    unsigned long long d_ino;
    long long d_off;
    unsigned short d_reclen;
    unsigned char d_type;
    char d_name[256];
};

static inline void cptbox_closefrom_getdents(int lowfd, const int *keep_fds) {
    int fd_dir = open(FD_DIR, O_RDONLY, 0);
    if (fd_dir == -1) {
        cptbox_closefrom_brute(lowfd, keep_fds);
    } else {
        char buffer[sizeof(struct linux_dirent64)];
        int bytes;
        while ((bytes = syscall(SYS_getdents64, fd_dir, (struct linux_dirent64 *) buffer, sizeof(buffer))) > 0) {
            struct linux_dirent64 *entry;
            int offset;
            for (offset = 0; offset < bytes; offset += entry->d_reclen) {
                int fd;
                entry = (struct linux_dirent64 *) (buffer + offset);
                if ((fd = pos_int_from_ascii(entry->d_name)) < 0)
                    continue; /* Not a number. */
                if (fd != fd_dir && fd >= lowfd && !fd_kept(fd, keep_fds))
                    cptbox_close_fd(fd);
            }
        }
        close(fd_dir);
    }
}
#endif

void cptbox_closefrom(int lowfd, const int *keep_fds) {
#if defined(__FreeBSD__)
    // closefrom(2) can't skip individual fds; fall back to the manual sweep when some must be kept.
    if (keep_fds && keep_fds[0] >= 0)
        cptbox_closefrom_dirent(lowfd, keep_fds);
    else
        closefrom(lowfd);
#elif defined(__linux__)
    cptbox_closefrom_getdents(lowfd, keep_fds);
#else
    cptbox_closefrom_dirent(lowfd, keep_fds);
#endif
}

char *bsd_get_proc_fd(pid_t pid, int fdflags, int fdno) {
#ifdef __FreeBSD__
    int err = 0;
    char *buf = NULL;

    unsigned kp_cnt;
    struct procstat *procstat;
    struct kinfo_proc *kp;
    struct filestat_list *head;
    struct filestat *fst;

    procstat = procstat_open_sysctl();
    if (procstat) {
        kp = procstat_getprocs(procstat, KERN_PROC_PID, pid, &kp_cnt);
        if (kp) {
            head = procstat_getfiles(procstat, kp, 0);
            if (head) {
                err = EPERM;  // Most likely you have no access
                STAILQ_FOREACH(fst, head, next) {
                    if ((fdflags && fst->fs_uflags & fdflags) || (!fdflags && fst->fs_fd == fdno)) {
                        buf = (char *) malloc(strlen(fst->fs_path) + 1);
                        if (buf)
                            strcpy(buf, fst->fs_path);
                        err = buf ? 0 : ENOMEM;
                        break;
                    }
                }
            } else
                err = errno;
            procstat_freeprocs(procstat, kp);
        } else
            err = errno;
        procstat_close(procstat);
        errno = err;
    }
    return buf;
#else
    errno = EOPNOTSUPP;
    return NULL;
#endif
}

char *bsd_get_proc_cwd(pid_t pid) {
#ifdef __FreeBSD__
    return bsd_get_proc_fd(pid, PS_FST_UFLAG_CDIR, 0);
#else
    errno = EOPNOTSUPP;
    return NULL;
#endif
}

char *bsd_get_proc_fdno(pid_t pid, int fdno) {
    return bsd_get_proc_fd(pid, 0, fdno);
}

int cptbox_memfd_create(void) {
#ifdef __FreeBSD__
    errno = ENOSYS;
    return -1;
#else
    return memfd_create("cptbox memory_fd", MFD_ALLOW_SEALING);
#endif
}

int cptbox_memfd_seal(int fd) {
#ifdef __FreeBSD__
    errno = ENOSYS;
    return -1;
#else
    return fcntl(fd, F_ADD_SEALS, F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_WRITE);
#endif
}
