#include <Python.h>
#include <string>
#define UNREFERENCED_PARAMETER(p)
#if defined(_MSC_VER)
#define inline __declspec(inline)
#pragma warning(disable : 4127)
#undef UNREFERENCED_PARAMETER
#define UNREFERENCED_PARAMETER(p) (p)
#elif !defined(__GNUC__)
#define inline
#endif
static inline int isline(char ch) {
    switch (ch) {
        case '\n':
        case '\r':
            return 1;
    }
    return 0;
}

static inline int iswhite(char ch) {
    switch (ch) {
        case ' ':
        case '\t':
        case '\v':
        case '\f':
        case '\n':
        case '\r':
            return 1;
    }
    return 0;
}

/* Increment *pos to the next non-whitespace character */
static inline void skip_spaces(const char *str, size_t *pos, size_t length) {
    while (*pos < length) {
        if (!iswhite(str[*pos])) {
            break;
        }
        ++*pos;
    }
}

/* Get position of the next Eoln or Eof character */
static inline size_t get_next_Eoln(const char *str, size_t pos, size_t length) {
    while (pos < length && !isline(str[pos]))
        ++pos;
    return pos;
}

inline std::string compress(const std::string &s) {
    if (s.length() <= 64)
        return s;
    else
        return s.substr(0, 30) + "..." + s.substr(s.length() - 31, 31);
}
inline std::string englishEnding(int x) {
    x %= 100;
    if (x / 10 == 1)
        return "th";
    if (x % 10 == 1)
        return "st";
    if (x % 10 == 2)
        return "nd";
    if (x % 10 == 3)
        return "rd";
    return "th";
}
const int BUFFER_SIZE = 1000;
char BUFFER[BUFFER_SIZE + 1];  // always have a \0
#define ACCEPTED     1
#define WRONG_ANSWER 0

#define FMT_TO_RESULT(fmt, ...) PyOS_snprintf(BUFFER, BUFFER_SIZE, fmt, __VA_ARGS__)
#define TO_RESULT(fmt)          PyOS_snprintf(BUFFER, BUFFER_SIZE, fmt)

/* compare sequence of tokens, ignore whitespace*/
static int check_standard(const char *judge, size_t jlen, const char *process, size_t plen) {
    size_t j = 0, p = 0;

    while (j < jlen && iswhite(judge[j]))
        ++j;
    while (p < plen && iswhite(process[p]))
        ++p;
    int cnt_token = 0;
    for (;;) {
        skip_spaces(judge, &j, jlen);
        skip_spaces(process, &p, plen);
        if (j == jlen || p == plen) {
            if (j == jlen && p == plen) {
                FMT_TO_RESULT("%d token(s)", cnt_token);
                return ACCEPTED;
            }
            if (j == jlen) {
                TO_RESULT("Participant's output contains extra tokens");
                return WRONG_ANSWER;
            }
            TO_RESULT("Unexpected EOF in the participant's output");
            return WRONG_ANSWER;
        }

        std::string j_token, p_token;
        while (j < jlen && !iswhite(judge[j])) {
            j_token.push_back(judge[j++]);
        }
        while (p < plen && !iswhite(process[p])) {
            p_token.push_back(process[p++]);
        }
        cnt_token += 1;
        if (j_token != p_token) {
            FMT_TO_RESULT("%d%s token differs - expected: '%s', found: '%s'", cnt_token,
                          englishEnding(cnt_token).c_str(), compress(j_token).c_str(), compress(p_token).c_str());
            return WRONG_ANSWER;
        }
    }
}

static PyObject *checker_standard(PyObject *self, PyObject *args) {
    PyObject *expected, *actual, *result, *check;

    UNREFERENCED_PARAMETER(self);
    if (!PyArg_ParseTuple(args, "OO:standard", &expected, &actual))
        return NULL;

    if (!PyBytes_Check(expected) || !PyBytes_Check(actual)) {
        PyErr_SetString(PyExc_ValueError, "expected strings");
        return NULL;
    }

    Py_INCREF(expected);
    Py_INCREF(actual);
    Py_BEGIN_ALLOW_THREADS check = check_standard(PyBytes_AsString(expected), PyBytes_Size(expected),
                                                  PyBytes_AsString(actual), PyBytes_Size(actual))
                                       ? Py_True
                                       : Py_False;
    Py_END_ALLOW_THREADS result = Py_BuildValue("Oy", check, BUFFER);
    Py_DECREF(expected);
    Py_DECREF(actual);
    Py_INCREF(result);
    return result;
}

/* compare sequence of line, ignore whitespace*/
static int check_linebyline(const char *judge, size_t jlen, const char *process, size_t plen) {
    size_t j = 0, p = 0;
    int cnt_line = 0;
    int cnt_token = 0;
    while (j < jlen && p < plen) {
        skip_spaces(judge, &j, jlen);
        skip_spaces(process, &p, plen);
        if (j == jlen || p == plen) {
            if (j == jlen && p == plen) {
                FMT_TO_RESULT("%d line(s), total %d token(s)", cnt_line, cnt_token);
                return ACCEPTED;
            }
            if (j == jlen) {
                FMT_TO_RESULT("First %d line(s) are correct but participant's output contains extra tokens", cnt_line);
                return WRONG_ANSWER;
            }
            FMT_TO_RESULT("First %d line(s) are correct but unexpected EOF in the participant's output", cnt_line);
            return WRONG_ANSWER;
        }

        size_t j_next_Eoln = get_next_Eoln(judge, j, jlen);
        size_t p_next_Eoln = get_next_Eoln(process, p, plen);
        cnt_line += 1;
        int cnt_inline_token = 0;
        while (true) {
            skip_spaces(judge, &j, j_next_Eoln);
            skip_spaces(process, &p, p_next_Eoln);
            if (j == j_next_Eoln || p == p_next_Eoln) {
                if (j == j_next_Eoln && p == p_next_Eoln)
                    break;
                if (j == j_next_Eoln) {
                    FMT_TO_RESULT("In line %d%s, participant's output has more tokens than judge's output", cnt_line,
                                  englishEnding(cnt_line).c_str());
                }
                FMT_TO_RESULT("In line %d%s, participant's output has less tokens than judge's output", cnt_line,
                              englishEnding(cnt_line).c_str());
                return WRONG_ANSWER;
            }
            std::string j_token, p_token;
            while (j < j_next_Eoln && !iswhite(judge[j])) {
                j_token.push_back(judge[j++]);
            }
            while (p < p_next_Eoln && !iswhite(process[p])) {
                p_token.push_back(process[p++]);
            }
            cnt_inline_token += 1;
            if (j_token != p_token) {
                FMT_TO_RESULT("In line %d%s, %d%s token differs - expected: '%s', found: '%s'", cnt_line,
                              englishEnding(cnt_line).c_str(), cnt_inline_token,
                              englishEnding(cnt_inline_token).c_str(), compress(j_token).c_str(),
                              compress(p_token).c_str());
                return WRONG_ANSWER;
            }
        }
        cnt_token += cnt_inline_token;
    }
}

static PyObject *checker_linebyline(PyObject *self, PyObject *args) {
    PyObject *expected, *actual, *result, *check;

    UNREFERENCED_PARAMETER(self);
    if (!PyArg_ParseTuple(args, "OO:standard", &expected, &actual))
        return NULL;

    if (!PyBytes_Check(expected) || !PyBytes_Check(actual)) {
        PyErr_SetString(PyExc_ValueError, "expected strings");
        return NULL;
    }

    Py_INCREF(expected);
    Py_INCREF(actual);
    Py_BEGIN_ALLOW_THREADS check = check_linebyline(PyBytes_AsString(expected), PyBytes_Size(expected),
                                                    PyBytes_AsString(actual), PyBytes_Size(actual))
                                       ? Py_True
                                       : Py_False;
    Py_END_ALLOW_THREADS result = Py_BuildValue("Oy", check, BUFFER);
    Py_DECREF(expected);
    Py_DECREF(actual);
    Py_INCREF(result);
    return result;
}

static PyMethodDef checker_methods[] = { { "standard", checker_standard, METH_VARARGS, "Standard VNOJ checker." },
                                         { "linecount", checker_linebyline, METH_VARARGS,
                                           "Line by Line VNOJ checker." },
                                         { NULL, NULL, 0, NULL } };

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT, "_checker", NULL, -1, checker_methods, NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC PyInit__checker(void) {
    return PyModule_Create(&moduledef);
}
