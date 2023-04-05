#include <iostream>

using namespace std;

int main() {
  string command, data;
  cin >> command >> data;
  if (command == "ENCODE") {
    cout << "lets_pretend_this_is_a_ciphertext_" << data << endl;
  } else {
    cout << data.substr(34) << endl;
  }
  return 0;
}
