use std::time::Instant;

fn fib(n: i32) -> i32 {
    if n <= 1 { return n; }
    fib(n - 1) + fib(n - 2)
}

fn main() {
    let start = Instant::now();
    let result = fib(40);
    let ms = start.elapsed().as_secs_f64() * 1000.0;
    println!("fib(40) = {}", result);
    println!("RESULT:{:.3}", ms);
}
