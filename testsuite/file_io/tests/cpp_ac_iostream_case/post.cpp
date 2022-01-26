#include <fstream>

using namespace std;

int main() {
  ifstream cin("PoSt.InP");
  ofstream cout("PoSt.OuT");
  int a, b;
  cin >> a >> b;
  cout << (a + b) << '\n';
  return 0;
}
