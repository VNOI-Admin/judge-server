#include "testlib.h"

int main(int argc, char *argv[]) {
  registerInteraction(argc, argv);
  int N, guesses = 0;
  long long guess;
  N = inf.readInt();
  while (guess != N) {
    guess = ouf.readInt(1, 2000000000);
    if (guess == N) {
      std::cout << "OK" << std::endl;
    } else if (guess > N) {
      std::cout << "FLOATS" << std::endl;
    } else {
      std::cout << "SINKS" << std::endl;
    }
    guesses++;
    if (guesses > 31) {
      quitf(_wa, "too many guesses %d", guesses);
    }
  }
  if (guesses <= 31) {
    quitf(_ok, "ok %d guesses", guesses);
  }
}
