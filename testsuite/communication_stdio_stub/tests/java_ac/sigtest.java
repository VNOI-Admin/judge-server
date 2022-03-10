public class Encoder {
  public String encode(String plaintext) {
    return "lets_pretend_this_is_a_ciphertext_" + plaintext;
  }
  public String decode(String ciphertext) {
    return ciphertext.substring(34);
  }
}
