#include <fstream>

using namespace std;

int main() {
  ifstream cin("post.inp");
  ofstream cout("post.out");
  int a, b;
  cin >> a >> b;
  cout << (a + b) << '\n';
  return 0;
}
