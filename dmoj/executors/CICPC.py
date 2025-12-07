from typing import List

from dmoj.executors.c_like_executor import CExecutor, GCCMixin


class Executor(GCCMixin, CExecutor):
    command = 'gcc'
    std = 'gnu11'
    command_paths = ['gcc']

    test_program = """
#include <stdio.h>

#if __STDC_VERSION__ == 201112
int main() {
    int ch;
    while ((ch = getchar()) != EOF)
        putchar(ch);
    return 0;
}
#endif
"""

    def get_defines(self) -> List[str]:
        return self.defines

    def get_flags(self) -> List[str]:
        return ['-x', 'c', '-g', '-O2', '-std=gnu11', '-static', '-lm']

    def get_compile_args(self) -> List[str]:
        command = self.get_command()
        assert command is not None
        return (
            [command]
            + (['-fdiagnostics-color=always'] if self.has_color else [])
            + self.source_paths
            + self.get_defines()
            + self.get_flags()
            + [self.get_march_flag()]
            + ['-o', self.get_compiled_file()]
        )
