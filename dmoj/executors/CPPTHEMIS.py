from typing import List

from dmoj.executors.c_like_executor import CPPExecutor, GCCMixin


class Executor(GCCMixin, CPPExecutor):
    command = 'g++-themis'
    command_paths = ['g++-8', 'g++']
    std = 'c++14'
    test_program = """
#include <iostream>

auto input() {
    return std::cin.rdbuf();
}

#if __cplusplus == 201402
int main() {
    std::cout << input();
    return 0;
}
#endif
"""

    @classmethod
    def get_march_flag(cls) -> str:
        return ''

    def get_defines(self) -> List[str]:
        return ['-DTHEMIS'] + self.defines

    def get_flags(self) -> List[str]:
        return ['-std=c++14', '-pipe', '-O2', '-s', '-static', '-lm', '-x', 'c++', '-Wl,-z,stack-size=66060288']

    def get_compile_args(self) -> List[str]:
        command = self.get_command()
        assert command is not None
        return (
            [command]
            + (['-fdiagnostics-color=always'] if self.has_color else [])
            + self.source_paths
            + self.get_defines()
            + self.get_flags()
            + self.get_ldflags()
            + ['-o', self.get_compiled_file()]
        )
