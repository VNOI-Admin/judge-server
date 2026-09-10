#include "landlock_header.h"

// Add a LANDLOCK_RULE_PATH_BENEATH rule for each NUL-terminated path in `paths`
// (a NULL-terminated array), granting `allowed_access`. Missing paths are ignored.
// Returns 0 on success, -1 on failure (errors are logged to stderr).
int landlock_add_rules(const int ruleset_fd, const char **paths, __u64 allowed_access);
