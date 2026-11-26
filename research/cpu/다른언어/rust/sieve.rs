// sieve of Eratosthenes up to 50,000,000 -- line-by-line port of ../../sieve.c (pair: ../../sieve.gl)
fn main() {
    let n: i64 = 50000000;
    let mut s: Vec<u8> = vec![0; (n + 1) as usize]; // C: char *s = malloc(n + 1)
    let mut i: i64 = 0;
    while i <= n {
        s[i as usize] = 1;
        i += 1;
    }
    s[0] = 0;
    s[1] = 0;
    let mut p: i64 = 2;
    while p * p <= n {
        if s[p as usize] != 0 {
            let mut j: i64 = p * p;
            while j <= n {
                s[j as usize] = 0;
                j += p;
            }
        }
        p += 1;
    }
    let mut count: i64 = 0;
    let mut k: i64 = 0;
    while k <= n {
        if s[k as usize] != 0 {
            count += 1;
        }
        k += 1;
    }
    println!("{}", count);
}
