import java.nio.file.Files;
import java.nio.file.Paths;

public class FileIO {
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: java FileIO <filepath>");
            System.exit(1);
        }

        byte[] data = Files.readAllBytes(Paths.get(args[0]));

        long start = System.nanoTime();

        long words = 0;
        boolean inWord = false;
        for (int i = 0; i < data.length; i++) {
            byte b = data[i];
            if (b == ' ' || b == '\t' || b == '\n' || b == '\r' || b == 0x0b || b == 0x0c) {
                inWord = false;
            } else {
                if (!inWord) {
                    words++;
                    inWord = true;
                }
            }
        }

        double ms = (System.nanoTime() - start) / 1e6;

        System.out.println("words: " + words);
        System.out.printf("RESULT:%.3f%n", ms);
    }
}
