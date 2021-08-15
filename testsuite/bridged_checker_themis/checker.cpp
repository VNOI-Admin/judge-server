#include "testlib_themis_cms.h"
using namespace std;

int main(int argc, char* argv[]) {
#ifdef THEMIS
    registerTestlibThemis("post.inp", "post.out");
#else
    registerTestlibCmd(argc, argv);
#endif // THEMIS

    int a = inf.readInt(), b = inf.readInt();

    int p = ouf.readInt();
    if (a + b != p)
        quitf(_wa, "%d + %d != %d", a, b, p);
    quitf(_ok, "%d + %d == %d", a, b, p);
    return 0;
}
