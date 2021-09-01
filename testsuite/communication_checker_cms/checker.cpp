#include <fstream>
#include <iostream>
#include <string>

using namespace std;

int main(int argc, char **argv) {
  ifstream fAns(argv[2]), fOut(argv[3]);
  string answer_string, output_string;
  getline(fAns, answer_string);
  getline(fOut, output_string);
  if (output_string == answer_string) {
    cout << 1;
  } else {
    cout << 0;
  }
  return 0;
}
