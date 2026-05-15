use std::time::Instant;

fn main() {
    let n = 30000usize;
    let mut arr = vec![0i32; n];

    // LCG matching C stdlib srand(42)/rand() pattern
    let mut seed: u32 = 42;
    for i in 0..n {
        seed = seed.wrapping_mul(1103515245).wrapping_add(12345);
        arr[i] = ((seed >> 16) & 0x7fff) as i32;
    }

    let start = Instant::now();
    for i in 0..n - 1 {
        for j in 0..n - i - 1 {
            if arr[j] > arr[j + 1] {
                arr.swap(j, j + 1);
            }
        }
    }
    let ms = start.elapsed().as_secs_f64() * 1000.0;

    println!("sorted[0]={} sorted[{}]={}", arr[0], n - 1, arr[n - 1]);
    println!("RESULT:{:.3}", ms);
}
