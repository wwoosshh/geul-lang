use std::time::Instant;

fn main() {
    let limit = 1_000_000usize;

    let start = Instant::now();

    let mut sieve = vec![true; limit + 1];
    sieve[0] = false;
    sieve[1] = false;

    let mut i = 2;
    while i * i <= limit {
        if sieve[i] {
            let mut j = i * i;
            while j <= limit {
                sieve[j] = false;
                j += i;
            }
        }
        i += 1;
    }

    let count = sieve[2..=limit].iter().filter(|&&x| x).count();

    let ms = start.elapsed().as_secs_f64() * 1000.0;

    println!("primes up to 1000000: {}", count);
    println!("RESULT:{:.3}", ms);
}
