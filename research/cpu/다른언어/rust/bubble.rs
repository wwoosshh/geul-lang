// bubble sort of 30,000 integers -- line-by-line port of ../../bubble.c (pair: ../../bubble.gl)
fn main() {
    let n: i64 = 30000;
    let mut a: Vec<i64> = vec![0; n as usize]; // C: int64_t *a = malloc(n * 8)
    let mut x: i64 = 12345;
    let mut i: i64 = 0;
    while i < n {
        x = (x * 1103515245 + 12345) & 2147483647;
        a[i as usize] = x % 100000;
        i += 1;
    }
    let mut i: i64 = 0;
    while i < n - 1 {
        let mut j: i64 = 0;
        while j < n - 1 - i {
            if a[j as usize] > a[(j + 1) as usize] {
                let t: i64 = a[j as usize];
                a[j as usize] = a[(j + 1) as usize];
                a[(j + 1) as usize] = t;
            }
            j += 1;
        }
        i += 1;
    }
    println!("{} {} {}", a[0], a[(n / 2) as usize], a[(n - 1) as usize]);
}
