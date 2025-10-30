from contextlib import redirect_stdout
from io import BytesIO, StringIO
from typing import TYPE_CHECKING
from zipfile import BadZipFile, ZipFile

from dmoj.error import CompileError
from dmoj.graders.standard import StandardGrader
from dmoj.problem import Problem, TestCase
from dmoj.result import Result
from dmoj.utils.helper_files import download_source_code
from dmoj.utils.unicode import utf8text

if TYPE_CHECKING:
    from dmoj.judge import JudgeWorker


class ArchivedGrader(StandardGrader):
    def __init__(self, judge: 'JudgeWorker', problem: Problem, language: str, source: bytes) -> None:
        super().__init__(judge, problem, language, source)
        assert self.language == 'OUTPUT'
        self.zip_file = self.get_zip_file()

    def get_zip_file(self) -> ZipFile:
        zip_data = download_source_code(utf8text(self.source).strip(), self.problem.meta.get('file-size-limit', 1))
        try:
            return ZipFile(BytesIO(zip_data))
        except BadZipFile as e:
            raise CompileError(repr(e))

    def grade(self, case: TestCase) -> Result:
        result = Result(case)

        result.execution_time = 0

        checker = self.problem.load_checker(self.problem.config['checker'])

        with redirect_stdout(StringIO()) as stream:
            score = float(checker.check(self.problem.problem_data.archive, self.zip_file))
        result.points = case.points * score

        result.result_flag |= [Result.WA, Result.AC][score > 0]
        result.feedback = None
        result.extended_feedback = stream.getvalue()

        return result
