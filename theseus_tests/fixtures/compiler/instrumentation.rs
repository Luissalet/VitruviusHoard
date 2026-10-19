use std::io::{self, BufRead, Write};

#[unsafe(no_mangle)]
#[inline(never)]
pub extern "C" fn measure(value: i32) -> i32 {
    if value < 0 { 0 } else if value > 255 { 255 } else { value + 3 }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(|s| s.as_str()) == Some("--ticker") {
        for index in 0..3600 {
            std::fs::write(&args[2], format!("{}", measure(index % 260 - 2))).unwrap();
            std::thread::sleep(std::time::Duration::from_millis(250));
        }
        return;
    }
    if args.get(1).map(|s| s.as_str()) == Some("--marker") {
        std::fs::write(&args[2], b"original process resumed").unwrap();
        std::thread::sleep(std::time::Duration::from_secs(3));
        return;
    }
    for line in io::stdin().lock().lines() {
        if let Ok(value) = line.unwrap().parse::<i32>() {
            println!("{}", measure(value));
            io::stdout().flush().unwrap();
        }
    }
}
