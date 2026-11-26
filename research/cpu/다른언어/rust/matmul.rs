// double-precision matrix multiply 500 x 500 (i-k-j order) -- line-by-line port of ../../matmul.c (pair: ../../matmul.gl).
// Rust never fuses a multiply and an add (no mul_add here), like the C built with -ffp-contract=off.
fn main() {
    let n: i64 = 500;
    let mut a: Vec<f64> = vec![0.0; (n * n) as usize]; // C: double *a = malloc(n * n * 8)
    let mut b: Vec<f64> = vec![0.0; (n * n) as usize];
    let mut c: Vec<f64> = vec![0.0; (n * n) as usize];
    let mut i: i64 = 0;
    while i < n * n {
        a[i as usize] = ((i % 7) as f64) * 0.5;
        b[i as usize] = ((i % 11) as f64) * 0.25;
        c[i as usize] = 0.0;
        i += 1;
    }
    let mut i: i64 = 0;
    while i < n {
        let mut k: i64 = 0;
        while k < n {
            let aik: f64 = a[(i * n + k) as usize];
            let mut j: i64 = 0;
            while j < n {
                c[(i * n + j) as usize] = c[(i * n + j) as usize] + aik * b[(k * n + j) as usize];
                j += 1;
            }
            k += 1;
        }
        i += 1;
    }
    let mut sum: f64 = 0.0;
    let mut q: i64 = 0;
    while q < n * n {
        sum = sum + c[q as usize];
        q += 1;
    }
    println!("{:.6}", sum); // C: printf("%f\n", sum)
}
