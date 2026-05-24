from typing import List

from dmoj.executors.c_like_executor import CPPExecutor, GCCMixin


class Executor(GCCMixin, CPPExecutor):
    command = 'g++'
    command_paths = ['g++-11', 'g++']
    std = 'gnu++20'
    test_program = """
#include <iostream>

#if __cplusplus == 202002
int main() {
    std::strong_ordering comparison = 1 <=> 2;
    auto input = std::cin.rdbuf();
    std::cout << input;
    return 0;
}
#endif
"""

    def get_defines(self) -> List[str]:
        return self.defines

    def get_flags(self) -> List[str]:
        return ['-x', 'c++', '-g', '-O2', '-std=gnu++20', '-static']

    def get_compile_args(self) -> List[str]:
        command = self.get_command()
        assert command is not None
        return (
            [command]
            + (['-fdiagnostics-color=always'] if self.has_color else [])
            + self.source_paths
            + self.get_defines()
            + self.get_flags()
            + ['-o', self.get_compiled_file()]
        )
