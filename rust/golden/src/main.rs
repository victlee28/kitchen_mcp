//! `kitchen-golden <file.json>...` runs golden case files; prints one line per file and exits non-zero on any mismatch.
use kitchen_golden::{call, differs, json};

fn main() {
    let (mut cases, mut failed, mut skipped) = (0, 0, 0);
    for path in std::env::args().skip(1) {
        let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {}", path, e));
        let doc = json::parse(&text).unwrap_or_else(|e| panic!("{}: {}", path, e));
        let function = doc.get("function").and_then(|f| f.str()).unwrap().to_string();
        let tol = doc.get("tolerance").and_then(|t| t.f64()).unwrap_or(1e-6);
        let json::Json::Arr(list) = doc.get("cases").unwrap() else { panic!("cases") };
        let (mut ok, mut bad) = (0, 0);
        for c in list {
            let name = c.get("name").and_then(|n| n.str()).unwrap_or("?");
            let Some(want) = c.get("expected") else { continue };   // error cases need typed errors; none ported yet
            match call(&function, c.get("input").unwrap()) {
                Err(e) if e.starts_with("not ported") => { skipped += 1; continue; }
                Err(e) => { bad += 1; println!("  FAIL {}::{}: {}", function, name, e); }
                Ok(got) => {
                    let mut d = vec![];
                    differs(&got, want, tol, "", &mut d);
                    if d.is_empty() { ok += 1 } else { bad += 1; for x in d { println!("  FAIL {}::{}: {}", function, name, x); } }
                }
            }
        }
        cases += ok + bad;
        failed += bad;
        println!("{}: {} ok, {} failed", function, ok, bad);
    }
    println!("total {} cases run, {} failed, {} skipped (not ported)", cases, failed, skipped);
    if failed > 0 { std::process::exit(1); }
}
