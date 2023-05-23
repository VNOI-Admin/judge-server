#include "testlib.h"

int main(int argc, char * argv[]) {
  registerTestlibCmd(argc, argv);
  int guesses = ouf.readInt(0, 31, "guesses");
  quitf(_ok, "checker: ok");
}
