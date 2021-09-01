#include <csignal>
#include <fstream>
#include <iostream>
#include <vector>

using namespace std;

// Fans the payload out to every process and expects it echoed back with the
// process's index appended. Exercises grading with many user processes: one
// FIFO pair and one submission copy per process.
int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    int processes = (argc - 1) / 2;

    string payload;
    cin >> payload;

    // Sandbox open order is stdin before stdout, process 0 first.
    vector<ofstream> to(processes);
    vector<ifstream> from(processes);
    for (int i = 0; i < processes; i++) {
        to[i].open(argv[2 * i + 2]);
        from[i].open(argv[2 * i + 1]);
    }

    for (int i = 0; i < processes; i++) {
        to[i] << payload << ' ' << i << endl;
        to[i].close();
    }

    for (int i = 0; i < processes; i++) {
        string got;
        from[i] >> got;
        if (got != payload + "_" + to_string(i)) {
            cout << "0.0\n";
            cerr << "translate:wrong\n";
            return 0;
        }
    }

    cout << "1.0\n";
    cerr << "translate:success\n";
    return 0;
}
