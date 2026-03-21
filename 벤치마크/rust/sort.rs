use std::time::Instant;

fn partition(arr: &mut [i32], lo: usize, hi: usize) -> usize {
    let pivot = arr[hi];
    let mut i = lo as isize - 1;
    for j in lo..hi {
        if arr[j] <= pivot {
            i += 1;
            arr.swap(i as usize, j);
        }
    }
    arr.swap((i + 1) as usize, hi);
    (i + 1) as usize
}

fn quicksort(arr: &mut [i32], lo: isize, hi: isize) {
    if lo < hi {
        let p = partition(arr, lo as usize, hi as usize);
        quicksort(arr, lo, p as isize - 1);
        quicksort(arr, p as isize + 1, hi);
    }
}

fn main() {
    let n = 1_000_000usize;
    let mut arr = Vec::with_capacity(n);

    // Simple LCG matching C's srand(42)/rand() pattern
    let mut seed: u32 = 42;
    for _ in 0..n {
        seed = seed.wrapping_mul(1103515245).wrapping_add(12345);
        arr.push(((seed >> 16) & 0x7fff) as i32);
    }

    let start = Instant::now();
    quicksort(&mut arr, 0, (n - 1) as isize);
    let ms = start.elapsed().as_secs_f64() * 1000.0;

    println!("sorted[0]={} sorted[999999]={}", arr[0], arr[999999]);
    println!("RESULT:{:.3}", ms);
}
