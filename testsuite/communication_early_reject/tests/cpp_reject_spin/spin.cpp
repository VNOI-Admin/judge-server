#include <iostream>
using namespace std;

int main() {
    string s;
    if (!(cin >> s)) {
        for (volatile long i = 0;; i++)
            ;
    }
    cout << "REJECT" << endl;
    return 0;
}
