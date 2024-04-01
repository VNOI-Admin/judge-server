#include <bits/stdc++.h>

using namespace std;

void solve() {
  long long low = 1, high = 2000000000;
  while (low <= high) {
    long long mid = (low + high) / 2;
    string res = ask(mid);
    if (res == "OK")
      return;
    else if (res == "FLOATS")
      high = mid - 1;
    else
      low = mid + 1;
  }
}
