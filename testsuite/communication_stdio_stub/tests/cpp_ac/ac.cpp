#include <string>

using namespace std;

string encode(string plaintext) {
  return "lets_pretend_this_is_a_ciphertext_" + plaintext;
}

string decode(string ciphertext) {
  return ciphertext.substr(34);
}
