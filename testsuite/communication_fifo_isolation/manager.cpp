#include <csignal>
#include <fcntl.h>
#include <iostream>
#include <string>
#include <unistd.h>

using namespace std;

// Hands process 1 the path of process 0's stdin FIFO and dares it to write
// there. The FIFOs are the manager's channel to each process; a user process
// must not be able to reach one, or two processes could talk behind the
// manager's back, or forge the other's answers.
//
// The sandbox is expected to stop the attempt, so this manager only ever gets
// to report failure: it scores 0 if the injected bytes arrive.

[[noreturn]] void finish(const char *score, const char *message) {
    cout << score << '\n';
    cerr << message << '\n';
    exit(0);
}

// Sandbox open order is stdin before stdout, so open the write end first.
void connectProcess(char **argv, int process, int &readFd, int &writeFd) {
    writeFd = open(argv[2 * process + 2], O_WRONLY);
    readFd = open(argv[2 * process + 1], O_RDONLY);
}

int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    if (argc < 5) finish("0.0", "translate:wrong");

    int readFd0, writeFd0, readFd1, writeFd1;
    connectProcess(argv, 0, readFd0, writeFd0);
    ssize_t unused = write(writeFd0, "listen\n", 7);

    // argv[2] is process 0's stdin: the one thing process 1 must not reach.
    connectProcess(argv, 1, readFd1, writeFd1);
    string dare = string("inject ") + argv[2] + "\n";
    unused = write(writeFd1, dare.data(), dare.size());
    (void) unused;
    close(writeFd1);

    // Wait for process 1 to be done trying.
    char buf[256];
    while (read(readFd1, buf, sizeof buf) > 0)
        ;
    close(readFd1);

    // Now let process 0 see the end of its input, and say what reached it.
    close(writeFd0);
    string got;
    ssize_t len = read(readFd0, buf, sizeof buf);
    if (len > 0) got.assign(buf, buf + len);
    close(readFd0);

    if (got.find("none") == string::npos) finish("0.0", "translate:wrong");
    finish("1.0", "translate:success");
}
