use std::time::Instant;

struct Node {
    value: i32,
    next: Option<Box<Node>>,
}

fn main() {
    let start = Instant::now();

    // Part 1: 1000 batches of 1000 alloc/free cycles = 1M total
    for _ in 0..1000 {
        for _ in 0..1000 {
            let v: Vec<u8> = Vec::with_capacity(64);
            drop(v);
        }
    }

    // Part 2: Build 100,000-node linked list, traverse, free
    let mut head: Option<Box<Node>> = None;
    for i in 0..100_000 {
        head = Some(Box::new(Node { value: i, next: head }));
    }

    let mut sum: i64 = 0;
    let mut cur = &head;
    while let Some(ref node) = cur {
        sum += node.value as i64;
        cur = &node.next;
    }

    drop(head);

    let ms = start.elapsed().as_secs_f64() * 1000.0;

    println!("allocs: 1000000, list sum: {}", sum);
    println!("RESULT:{:.3}", ms);
}
