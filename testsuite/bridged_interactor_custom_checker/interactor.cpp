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
      quitf(_wa, "interactor: too many guesses");
    }
  }
  if (guesses <= 31) {
    tout << guesses << std::endl;
    quitf(_ok, "interactor: ok");
  }
}
