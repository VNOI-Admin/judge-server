from dmoj.executors.PAS import Executor as PASExecutor


class Executor(PASExecutor):
    command = 'fpc-themis'
    command_paths = ['fpc']

    def get_compile_args(self):
        return [self.get_command(), '-Fe/dev/stderr', '-dTHEMIS', '-O2', '-XS', '-Sg', '-Cs66060288', self._code]
