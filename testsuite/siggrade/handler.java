import java.util.Scanner;

public class Handler {
  public static void main(String []args) {
    Scanner scan = new Scanner(System.in);
    int n = scan.nextInt();
    Validator validator = new Validator();
    if (validator.is_valid(n)) {
      System.out.print("correct");
    }
    else {
      System.out.print("wrong");
    }
  }
}
