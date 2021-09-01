#include <bits/stdc++.h>
#include <fcntl.h>
#include <unistd.h>
using namespace std;

static string talk(const char *fromP, const char *toP, const string &in) {
    int w = open(toP, O_WRONLY);
    int r = open(fromP, O_RDONLY);
    write(w, in.data(), in.size());
    close(w);
    string out;
    char buf[4096];
    ssize_t g;
    while ((g = read(r, buf, sizeof buf)) > 0)
        out.append(buf, buf + g);
    close(r);
    return out;
}

int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    if (argc < 5) {
        cout << "0.0\n";
        cerr << "translate:wrong\n";
        return 0;
    }
    string resp = talk(argv[1], argv[2], "GO\n");  // process 0 only
    if (resp.find("REJECT") != string::npos) {
        cout << "0.0\n";
        cerr << "translate:wrong\n";
        return 0;  // never opens proc 1 FIFOs
    }
    talk(argv[3], argv[4], "GO\n");
    cout << "1.0\n";
    cerr << "translate:success\n";
    return 0;
}
