#ifndef __FreeBSD__

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include "landlock_helpers.h"

static int landlock_add_path(struct landlock_path_beneath_attr &rule, const int ruleset_fd, const char *path) {
    rule.parent_fd = open(path, O_PATH | O_CLOEXEC);

    if (rule.parent_fd < 0) {
        if (errno == ENOENT)
            return 0;  // missing files are ignored
        fprintf(stderr, "Failed to open path '%s' for rule: %s\n", path, strerror(errno));
        return -1;
    }
    if (landlock_add_rule(ruleset_fd, LANDLOCK_RULE_PATH_BENEATH, &rule, 0)) {
        // EBADFD means the path resolves to an anonymous/disconnected inode that Landlock can't
        // govern by path -- our memfd-backed input (MemfdIO.to_path -> /proc/self/fd/<n>), or a
        // pipe/socket used by the File-IO and communication graders. No rule is needed: Landlock
        // lets a process open its own such descriptors via /proc/self/fd regardless. So skip it
        // rather than failing the whole sandbox setup.
        if (errno == EBADFD) {
            close(rule.parent_fd);
            return 0;
        }
        fprintf(stderr, "Failed to add rule '%s' to ruleset: %s\n", path, strerror(errno));
        close(rule.parent_fd);
        return -1;
    }
    close(rule.parent_fd);
    return 0;
}

int landlock_add_rules(const int ruleset_fd, const char **paths, __u64 allowed_access) {
    if (!paths)
        return 0;

    struct landlock_path_beneath_attr rule = {
        .allowed_access = allowed_access,
        .parent_fd = -1,
    };

    for (const char **pathptr = paths; *pathptr; pathptr++) {
        if (landlock_add_path(rule, ruleset_fd, *pathptr))
            return -1;
    }
    return 0;
}

#endif
