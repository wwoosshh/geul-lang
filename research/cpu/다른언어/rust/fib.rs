// fib(40) -- line-by-line port of ../../fib.c (pair: ../../fib.gl)
fn fib(n: i64) -> i64 {
    if n < 2 {
        return n;
    }
    return fib(n - 1) + fib(n - 2);
}

fn main() {
    println!("{}", fib(40));
}
