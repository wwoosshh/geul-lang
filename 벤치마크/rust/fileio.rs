use std::env;
use std::fs;
use std::process;
use std::time::Instant;

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage: fileio <filepath>");
        process::exit(1);
    }

    let data = match fs::read(&args[1]) {
        Ok(d) => d,
        Err(e) => {
            eprintln!("Cannot open {}: {}", args[1], e);
            process::exit(1);
        }
    };

    let start = Instant::now();

    let mut words: i64 = 0;
    let mut in_word = false;
    for &b in &data {
        if b == b' ' || b == b'\t' || b == b'\n' || b == b'\r' || b == 0x0b || b == 0x0c {
            in_word = false;
        } else {
            if !in_word {
                words += 1;
                in_word = true;
            }
        }
    }

    let ms = start.elapsed().as_secs_f64() * 1000.0;

    println!("words: {}", words);
    println!("RESULT:{:.3}", ms);
}
