from io import BytesIO
from zipfile import BadZipFile, ZipFile

from dmoj.error import CompileError
from dmoj.graders.standard import StandardGrader
from dmoj.result import CheckerResult, Result
from dmoj.utils.helper_files import download_source_code
from dmoj.utils.unicode import utf8text

class OutputOnlyGrader(StandardGrader):
    def __init__(self, judge, problem, language, source):
        if language != 'OUTPUT':
            raise CompileError("Need to use OUTPUT language")
        super().__init__(judge, problem, language, source)
        self.zip_file = self.get_zip_file()

    def _generate_binary(self):
        """
        The super().__init__ uses this function
        """
        return None

    def _interact_with_zipfile(self, result, output_name):
        if output_name not in self.zip_file.namelist():
            result.feedback = "`" + output_name + "` not found in zip file"
            result.result_flag = Result.WA
        else:
            result.proc_output = self.zip_file.open(output_name).read()

    def get_zip_file(self):
        zip_data = download_source_code(
            utf8text(self.source),
            self.problem.meta.get('file-size-limit', 1)
        )
        try:
            return ZipFile(BytesIO(zip_data))
        except BadZipFile as e:
            raise CompileError(repr(e))

    def grade(self, case):
        result = Result(case)

        self._interact_with_zipfile(result, case.config['out'])

        check = self.check_result(case, result)

        # Copy from StandardGrader

        # checkers must either return a boolean (True: full points, False: 0 points)
        # or a CheckerResult, so convert to CheckerResult if it returned bool
        if not isinstance(check, CheckerResult):
            check = CheckerResult(check, case.points if check else 0.0)

        result.result_flag |= [Result.WA, Result.AC][check.passed]
        result.points = check.points
        result.feedback = check.feedback or result.feedback
        result.extended_feedback = check.extended_feedback or result.extended_feedback

        case.free_data()

        return result