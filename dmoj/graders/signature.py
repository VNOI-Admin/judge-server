import uuid

from dmoj.error import InternalError
from dmoj.executors import executors
from dmoj.executors.base_executor import BaseExecutor
from dmoj.graders.standard import StandardGrader
from dmoj.utils.unicode import utf8bytes


class SignatureGrader(StandardGrader):
    def _generate_binary(self) -> BaseExecutor:
        cpp_siggraders = ('C', 'C11', 'CPP03', 'CPP11', 'CPP14', 'CPP17', 'CPP20', 'CPPTHEMIS', 'CLANG', 'CLANGX')
        java_siggraders = ('JAVA', 'JAVA8', 'JAVA9', 'JAVA10', 'JAVA11', 'JAVA15', 'JAVA17')

        if self.language in cpp_siggraders:
            aux_sources = {}
            handler_data = self.problem.config['signature_grader']

            entry_point = self.problem.problem_data[handler_data['entry']]
            header = self.problem.problem_data[handler_data['header']]

            submission_prefix = f'#include "{handler_data["header"]}"\n'
            if not handler_data.get('allow_main', False):
                submission_prefix += '#define main main_%s\n' % uuid.uuid4().hex

            aux_sources[self.problem.id + '_submission'] = utf8bytes(submission_prefix) + self.source

            aux_sources[handler_data['header']] = header
            entry = entry_point
            return executors[self.language].Executor(
                self.problem.id, entry, aux_sources=aux_sources, defines=['-DSIGNATURE_GRADER']
            )
        elif self.language in java_siggraders:
            aux_sources = {}
            handler_data = self.problem.config['signature_grader']['java']

            entry_point = self.problem.problem_data[handler_data['entry']]

            if not self.problem.config['signature_grader'].get('allow_main', False):
                entry = entry_point
                aux_sources[self.problem.id + '_submission'] = self.source
            else:
                entry = self.source
                aux_sources[self.problem.id + '_lib'] = entry_point

            return executors[self.language].Executor(self.problem.id, entry, aux_sources=aux_sources)
        else:
            raise InternalError('no valid runtime for signature grading %s found' % self.language)
