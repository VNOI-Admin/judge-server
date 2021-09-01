#include <csignal>
#include <fcntl.h>
#include <iostream>
#include <unistd.h>

using namespace std;

// Exits at a different stage of connecting the two user processes depending on
// the mode read from the test input. The judge must resolve every mode into the
// manager's verdict, promptly, however far the manager got: a process it never
// engaged is excluded from the verdict and ended, rather than left to block or
// to run out its own limits.
//
// Mode 6 is the exception, and the reason to engage a process only once you
// mean to use it: there the manager did engage the process, so it counts, and
// what it does with the EOF that follows is its own time limit to run out.
//
//   0: talk to both processes                                   -> AC
//   1: exit connecting nothing                                  -> WA
//   2: talk to process 0, never touch process 1                 -> WA
//   3: open process 0's stdin only, exit                        -> WA
//   4: like 0, after a delay                                    -> AC
//   5: talk to process 0, open process 1's stdin only, exit     -> WA
//   6: talk to process 0, connect process 1, send nothing, exit -> the
//      submission's own doing

[[noreturn]] void finish(const char *score, const char *message) {
    cout << score << '\n';
    cerr << message << '\n';
    exit(0);
}

[[noreturn]] void accepted() { finish("1.0", "translate:success"); }

[[noreturn]] void wrong() { finish("0.0", "translate:wrong"); }

// Sandbox open order is stdin before stdout, so open the write end first.
void connectProcess(char **argv, int process, int &readFd, int &writeFd) {
    writeFd = open(argv[2 * process + 2], O_WRONLY);
    readFd = open(argv[2 * process + 1], O_RDONLY);
}

bool talkTo(int readFd, int writeFd) {
    ssize_t unused = write(writeFd, "ping\n", 5);
    (void) unused;
    close(writeFd);
    char buf[64];
    ssize_t got = read(readFd, buf, sizeof buf);
    close(readFd);
    return got == 5 && buf[0] == 'p';  // expect "pong\n"
}

int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    if (argc < 5) wrong();

    int mode;
    cin >> mode;

    if (mode == 1) wrong();

    if (mode == 3) {
        open(argv[2], O_WRONLY);
        wrong();
    }

    if (mode == 4) {
        for (volatile long i = 0; i < 20000000; i++)
            ;
    }

    int readFd, writeFd;
    connectProcess(argv, 0, readFd, writeFd);
    if (!talkTo(readFd, writeFd)) wrong();

    if (mode == 2) wrong();

    if (mode == 5) {
        open(argv[4], O_WRONLY);
        wrong();
    }

    connectProcess(argv, 1, readFd, writeFd);

    if (mode == 6) wrong();

    if (!talkTo(readFd, writeFd)) wrong();

    accepted();
}
