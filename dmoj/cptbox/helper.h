#pragma once
#ifndef idABBEC9C1_3EF3_4A45_B187B10060CB9F85
#define idABBEC9C1_3EF3_4A45_B187B10060CB9F85

#include <sys/types.h>

#define PTBOX_SPAWN_FAIL_NO_NEW_PRIVS 202
#define PTBOX_SPAWN_FAIL_SECCOMP      203
#define PTBOX_SPAWN_FAIL_TRACEME      204
#define PTBOX_SPAWN_FAIL_EXECVE       205
#define PTBOX_SPAWN_FAIL_SETAFFINITY  206
#define PTBOX_SPAWN_FAIL_LANDLOCK     207

struct child_config {
    unsigned long memory;
    unsigned long address_space;
    unsigned int cpu_time;
    unsigned long personality;
    int nproc;
    int fsize;
    char *file;
    char *dir;
    char **argv;
    char **envp;
    int stdin_;
    int stdout_;
    int stderr_;
    int fd_3_;
    int fd_4_;
    int *seccomp_handlers;
    // 64 cores ought to be enough for anyone.
    unsigned long cpu_affinity_mask;
    // Landlock filesystem rules: NULL-terminated arrays of paths, by access kind.
    const char **landlock_read_exact_files;
    const char **landlock_read_exact_dirs;
    const char **landlock_read_recursive_dirs;
    const char **landlock_write_exact_files;
    const char **landlock_write_exact_dirs;
    const char **landlock_write_recursive_dirs;
    // -1-terminated list of fds the child should keep open past the closefrom() sweep, so a
    // consumer can access them as its own /proc/self/fd/<n> (which Landlock permits, unlike a
    // cross-process /proc/<pid>/fd/<n>).
    const int *keep_open_fds;
};

// Returns the Landlock ABI version (>=1), 0 if Landlock is unavailable/disabled, or -1 on error.
int get_landlock_version();

void cptbox_closefrom(int lowfd, const int *keep_fds);
int cptbox_child_run(const struct child_config *config);

char *bsd_get_proc_cwd(pid_t pid);
char *bsd_get_proc_fdno(pid_t pid, int fdno);

int cptbox_memfd_create(void);
int cptbox_memfd_seal(int fd);

#endif
