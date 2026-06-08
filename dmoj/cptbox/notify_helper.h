#pragma once
#ifndef id7F2A9C41_NOTIFY_HELPER_H
#define id7F2A9C41_NOTIFY_HELPER_H

#include <stdint.h>

// A flattened view of one seccomp user-notification request, for the Cython supervisor.
struct cptbox_notif {
    uint64_t id;
    uint32_t pid;
    uint32_t flags;
    int nr;
    uint32_t arch;
    uint64_t instruction_pointer;
    uint64_t args[6];
};

// Block until a notification arrives on the listener `fd`, filling `out`. Returns 0 on success,
// -1 on error (errno set; EINTR is possible and should be retried, ENOENT means the target
// vanished and this id can be skipped).
int cptbox_notify_recv(int fd, struct cptbox_notif *out);

// Respond to the notification `id`: when SECCOMP_USER_NOTIF_FLAG_CONTINUE is set in `flags`, let
// the kernel run the syscall (the args/memory the child currently has); otherwise the syscall is
// skipped and returns `val` on success, or -`error` if `error` is non-zero. Returns 0/-1.
int cptbox_notify_respond(int fd, uint64_t id, int64_t val, int error, uint32_t flags);

// True if `id` still refers to a live, un-responded notification (TOCTOU guard around reads of the
// target's memory). Returns 0 if stale/invalid.
int cptbox_notify_id_valid(int fd, uint64_t id);

// Value of SECCOMP_USER_NOTIF_FLAG_CONTINUE for the Cython layer.
uint32_t cptbox_notify_flag_continue(void);

// The AUDIT_ARCH_* value the kernel reports in seccomp_data.arch for native-arch syscalls, or 0 if
// unknown. The supervisor only dispatches notifications whose arch matches this (raw syscall
// numbers are arch-specific); other arches are denied.
uint32_t cptbox_notify_native_arch(void);

#endif
