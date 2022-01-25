#include <iostream>

using namespace std;

int main() {
  freopen("cipher.inp", "r", stdin);
  freopen("cipher.out", "w", stdout);
  string command, data;
  cin >> command >> data;
  if (command == "ENCODE") {
    cout << "aaaaaaaaa" << endl;
  } else {
    cout << "bbbbbbbbb" << endl;
  }
  return 0;
}
