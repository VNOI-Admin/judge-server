from dmoj.executors import TEXT

# All logic will be handled in output only grader
# So, a fake executors is all we need
class Executor(TEXT.Executor):
    name = 'OUTPUT'
