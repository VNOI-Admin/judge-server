#include <fstream>

using namespace std;

int main() {
  ifstream cin("POST.INP");
  ofstream cout("POST.OUT");
  int a, b;
  cin >> a >> b;
  cout << (a + b) << '\n';
  return 0;
}
