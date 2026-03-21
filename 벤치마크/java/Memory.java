public class Memory {
    static class Node {
        int value;
        Node next;
        Node(int value, Node next) {
            this.value = value;
            this.next = next;
        }
    }

    public static void main(String[] args) {
        long start = System.nanoTime();

        // Part 1: 1000 batches of 1000 alloc cycles = 1M total
        for (int batch = 0; batch < 1000; batch++) {
            for (int i = 0; i < 1000; i++) {
                byte[] p = new byte[64];
            }
        }

        // Part 2: Build 100,000-node linked list, traverse
        Node head = null;
        for (int i = 0; i < 100000; i++) {
            head = new Node(i, head);
        }

        long sum = 0;
        Node cur = head;
        while (cur != null) {
            sum += cur.value;
            cur = cur.next;
        }

        double ms = (System.nanoTime() - start) / 1e6;

        System.out.println("allocs: 1000000, list sum: " + sum);
        System.out.printf("RESULT:%.3f%n", ms);
    }
}
