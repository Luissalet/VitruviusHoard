//! One synchronous signature scan, without the upstream CLI worker queue.
use binwalk::{AnalysisResults, Binwalk};
use std::{collections::HashMap, env, error::Error, fs, io::Write, path::PathBuf};

fn run() -> Result<(), Box<dyn Error>> {
    let mut args = env::args().skip(1);
    let mut input = None;
    let mut output = None;
    let mut search_all = false;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--version" if input.is_none() && output.is_none() => {
                if args.next().is_some() { return Err("Version takes no other arguments".into()); }
                println!("Theseus firmware scanner 0.1.0 (Binwalk library 3.1.0)");
                return Ok(());
            }
            "--quiet" => (),
            "--search-all" => search_all = true,
            "--threads" => {
                if args.next().as_deref() != Some("1") {
                    return Err("The synchronous scanner accepts --threads 1 only".into());
                }
            }
            "--log" if output.is_none() => output = Some(PathBuf::from(args.next().ok_or("Missing log path")?)),
            value if !value.starts_with('-') && input.is_none() => input = Some(PathBuf::from(value)),
            _ => return Err(format!("Unknown or repeated argument: {arg}").into()),
        }
    }
    let input = input.ok_or("Missing input file")?;
    let output = output.ok_or("Missing log path")?;
    let bytes = fs::read(&input)?;
    let scanner = Binwalk::configure(None, None, None, None, None, search_all)
        .map_err(|_| "Could not initialize signature readers")?;
    let result = AnalysisResults {
        file_path: input.to_string_lossy().into_owned(),
        file_map: scanner.scan(&bytes),
        extractions: HashMap::new(),
    };
    // The parent waits for exit before consuming this new, job-local file.
    // Creating it exclusively also prevents appending to an older observation.
    let mut file = fs::OpenOptions::new().write(true).create_new(true).open(output)?;
    serde_json::to_writer_pretty(&mut file, &serde_json::json!([{"Analysis": result}]))?;
    file.flush()?;
    file.sync_all()?;
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("Firmware scan failed: {error}");
        std::process::exit(1);
    }
}
