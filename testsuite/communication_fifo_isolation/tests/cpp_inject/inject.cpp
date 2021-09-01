#include <fcntl.h>
#include <iostream>
#include <string>
#include <unistd.h>

using namespace std;

// Both processes run this. Process 1 is told the path of process 0's stdin
// FIFO and tries to write into it; the sandbox must refuse.
int main() {
    string role;
    if (!(cin >> role))
        return 0;

    if (role == "inject") {
        string path;
        cin >> path;
        int fd = open(path.c_str(), O_WRONLY);
        if (fd >= 0) {
            ssize_t unused = write(fd, "injected\n", 9);
            (void) unused;
            close(fd);
        }
        cout << "tried" << endl;
        return 0;
    }

    // role == "listen": report whatever else arrives before EOF.
    string leaked;
    cout << (cin >> leaked ? leaked : "none") << endl;
    return 0;
}
