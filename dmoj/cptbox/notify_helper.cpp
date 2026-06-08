#ifndef __FreeBSD__

#include "notify_helper.h"

#include <errno.h>
#include <linux/audit.h>
#include <linux/seccomp.h>
#include <string.h>
#include <sys/ioctl.h>

#ifndef SECCOMP_USER_NOTIF_FLAG_CONTINUE
#define SECCOMP_USER_NOTIF_FLAG_CONTINUE (1UL << 0)
#endif

int cptbox_notify_recv(int fd, struct cptbox_notif *out) {
    struct seccomp_notif req;
    memset(&req, 0, sizeof req);
    while (ioctl(fd, SECCOMP_IOCTL_NOTIF_RECV, &req) < 0) {
        if (errno != EINTR)
            return -1;  // ENOENT: target vanished before RECV; caller skips this id.
        memset(&req, 0, sizeof req);
    }
    out->id = req.id;
    out->pid = req.pid;
    out->flags = req.flags;
    out->nr = req.data.nr;
    out->arch = req.data.arch;
    out->instruction_pointer = req.data.instruction_pointer;
    memcpy(out->args, req.data.args, sizeof out->args);
    return 0;
}

int cptbox_notify_respond(int fd, uint64_t id, int64_t val, int error, uint32_t flags) {
    struct seccomp_notif_resp resp;
    memset(&resp, 0, sizeof resp);
    resp.id = id;
    resp.val = val;
    resp.error = error;
    resp.flags = flags;
    if (ioctl(fd, SECCOMP_IOCTL_NOTIF_SEND, &resp) < 0)
        return -1;
    return 0;
}

int cptbox_notify_id_valid(int fd, uint64_t id) {
    return ioctl(fd, SECCOMP_IOCTL_NOTIF_ID_VALID, &id) == 0;
}

uint32_t cptbox_notify_flag_continue(void) {
    return SECCOMP_USER_NOTIF_FLAG_CONTINUE;
}

uint32_t cptbox_notify_native_arch(void) {
#if defined(__x86_64__)
    return AUDIT_ARCH_X86_64;
#elif defined(__i386__)
    return AUDIT_ARCH_I386;
#elif defined(__aarch64__)
    return AUDIT_ARCH_AARCH64;
#elif defined(__arm__)
    return AUDIT_ARCH_ARM;
#else
    return 0;
#endif
}

#endif
