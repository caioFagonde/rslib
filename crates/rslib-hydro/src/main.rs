use std::io::{self, Read};

fn main() {
    if let Err(error) = run() {
        eprintln!("rslib-hydro: {error}");
        std::process::exit(2);
    }
}

fn run() -> Result<(), String> {
    let mut input = String::new();
    io::stdin()
        .take(64 * 1024 * 1024 + 1)
        .read_to_string(&mut input)
        .map_err(|e| e.to_string())?;
    if input.len() > 64 * 1024 * 1024 {
        return Err("JSON input exceeds 64 MiB".into());
    }
    let problem: rslib_hydro::Problem = serde_json::from_str(&input).map_err(|e| e.to_string())?;
    let result = rslib_hydro::simulate(&problem)?;
    serde_json::to_writer(io::stdout(), &result).map_err(|e| e.to_string())?;
    Ok(())
}
