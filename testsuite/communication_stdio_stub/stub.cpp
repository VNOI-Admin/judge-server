#include <iostream>
#include <string>
#include "header.h"

using namespace std;

int main() {
  string command, data;
  cin >> command >> data;
  if (command == "ENCODE") {
    cout << encode(data) << endl;
  } else {
    cout << decode(data) << endl;
  }
  return 0;
}
