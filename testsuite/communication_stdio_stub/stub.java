import java.util.Scanner;

public class Stub {
  public static void main(String []args) {
    Scanner scan = new Scanner(System.in);
    String command = scan.next();
    String data = scan.next();
    Encoder encoder = new Encoder();
    if (command.equals("ENCODE")) {
      System.out.println(encoder.encode(data));
    }
    else {
      System.out.println(encoder.decode(data));
    }
  }
}
