//! One synchronous signature scan, without the upstream CLI worker queue.
use binwalk::signatures::common::{SignatureError, SignatureResult, CONFIDENCE_HIGH};
use binwalk::{AnalysisResults, Binwalk};
use bzip2::{Decompress, Status};
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
                println!("Theseus firmware scanner 0.1.1 (Binwalk library 3.1.0, bounded bzip2 check)");
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
    let mut scanner = Binwalk::configure(None, None, None, None, None, search_all)
        .map_err(|_| "Could not initialize signature readers")?;
    for signature in scanner.pattern_signature_table.values_mut() {
        if signature.name == "bzip2" {
            signature.parser = bounded_bzip2_parser;
        }
    }
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

/// Binwalk 3.1.0's bzip2 check never returns on a stream cut at the end of the input: the decoder
/// keeps reporting Ok without consuming or producing bytes. This check is the same decode, but it
/// rejects the candidate as soon as a call makes no progress.
fn bounded_bzip2_parser(file_data: &[u8], offset: usize) -> Result<SignatureResult, SignatureError> {
    let data = &file_data[offset..];
    let mut decompressor = Decompress::new(false);
    let mut buffer = vec![0u8; 900 * 1024];
    loop {
        let (consumed, produced) = (decompressor.total_in(), decompressor.total_out());
        match decompressor.decompress(&data[consumed as usize..], &mut buffer) {
            Ok(Status::StreamEnd) => {
                let size = decompressor.total_in() as usize;
                return Ok(SignatureResult {
                    description: format!("bzip2 compressed data, total size: {size} bytes"),
                    offset,
                    size,
                    confidence: CONFIDENCE_HIGH,
                    ..Default::default()
                });
            }
            Ok(Status::Ok) if decompressor.total_in() != consumed || decompressor.total_out() != produced => {}
            _ => return Err(SignatureError),
        }
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("Firmware scan failed: {error}");
        std::process::exit(1);
    }
}
