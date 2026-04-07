use std::time::Instant;

fn main() {
    let n = 500usize;
    let mut a = vec![0.0f64; n * n];
    let mut b = vec![0.0f64; n * n];
    let mut c = vec![0.0f64; n * n];

    for i in 0..n * n {
        a[i] = (i % 100) as f64;
        b[i] = ((i * 7) % 100) as f64;
    }

    let start = Instant::now();

    // ikj loop order for cache efficiency
    for i in 0..n {
        for k in 0..n {
            let a_ik = a[i * n + k];
            for j in 0..n {
                c[i * n + j] += a_ik * b[k * n + j];
            }
        }
    }

    let ms = start.elapsed().as_secs_f64() * 1000.0;

    println!("C[0][0]={:.0} C[499][499]={:.0}", c[0], c[499 * n + 499]);
    println!("RESULT:{:.3}", ms);
}
