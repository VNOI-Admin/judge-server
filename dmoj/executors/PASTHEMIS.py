from typing import List

from dmoj.executors.PAS import Executor as PASExecutor


class Executor(PASExecutor):
    command = 'fpc-themis'
    command_paths = ['fpc']

    def get_compile_args(self) -> List[str]:
        command = self.get_command()
        assert command is not None
        assert self._code is not None
        return [command, '-Fe/dev/stderr', '-dTHEMIS', '-O2', '-XS', '-Sg', '-Cs66060288', *self.flags, self._code]
