#include <csignal>
#include <fstream>
#include <iostream>

using namespace std;

ifstream fifoEncoderToManager;
ofstream fifoManagerToEncoder;
ifstream fifoDecoderToManager;
ofstream fifoManagerToDecoder;

int main(int argc, char **argv) {
  if (argc < 5) {
    cerr << "Insufficient #args for manager" << endl;
    return 0;
  }

  {  //Keep alive on broken pipes
    struct sigaction sa;
    sa.sa_handler = SIG_IGN;
    sigaction(SIGPIPE, &sa, NULL);
  }

  // When the sandbox opens the other endpoints of these FIFOs to redirect
  // them to to stdin/out it does so first for stdin and then for stdout.
  // We must match that order as otherwise we would deadlock.
  // So DO NOT change the order of the next 4 lines.
  fifoManagerToEncoder.open(argv[2]);
  fifoEncoderToManager.open(argv[1]);
  fifoManagerToDecoder.open(argv[4]);
  fifoDecoderToManager.open(argv[3]);

  // Read input
  string plaintext;
  cin >> plaintext;

  // Encoding phase
  fifoManagerToEncoder << "ENCODE " << plaintext << endl;
  fifoManagerToEncoder.flush();

  string ciphertext;
  fifoEncoderToManager >> ciphertext;

  // Decoding phase
  fifoManagerToDecoder << "DECODE " << ciphertext << endl;
  fifoManagerToDecoder.flush();

  string decrypted;
  fifoDecoderToManager >> decrypted;

  // Close FIFOs
  fifoEncoderToManager.close();
  fifoManagerToEncoder.close();
  fifoDecoderToManager.close();
  fifoManagerToDecoder.close();

  cout << decrypted << '\n';

  return 0;
}
