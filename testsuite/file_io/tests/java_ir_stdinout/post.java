import java.util.*;
import java.io.*;

public class post {
    public static void main(String args[]) throws IOException {
        BufferedReader cin = new BufferedReader(new InputStreamReader(System.in));
        String[] line = cin.readLine().split(" ");
        System.out.println(Integer.parseInt(line[0]) + Integer.parseInt(line[1]));
        cin.close();
    }
}
