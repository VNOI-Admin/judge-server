#include <iostream>

using namespace std;

int main() {
    string s;
    if (!(cin >> s)) {
        for (volatile long i = 0;; i++)
            ;
    }
    cout << "pong" << endl;
    return 0;
}
