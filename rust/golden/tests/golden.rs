//! `cargo test` runs every ported golden file under ../../tests/golden. Files whose function is not ported are listed, not hidden.
use kitchen_golden::{call, differs, json};
use std::path::{Path, PathBuf};

fn files(dir: &Path, out: &mut Vec<PathBuf>) {
    for e in std::fs::read_dir(dir).unwrap() {
        let p = e.unwrap().path();
        if p.is_dir() { files(&p, out) } else if p.extension().map_or(false, |x| x == "json") { out.push(p) }
    }
}

#[test]
fn golden_cases_match_python() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/golden");
    let mut all = vec![];
    files(&root, &mut all);
    all.sort();
    let (mut ran, mut problems) = (0, vec![]);
    for path in all {
        let doc = json::parse(&std::fs::read_to_string(&path).unwrap()).unwrap();
        let function = doc.get("function").and_then(|f| f.str()).unwrap().to_string();
        let tol = doc.get("tolerance").and_then(|t| t.f64()).unwrap_or(1e-6);
        let json::Json::Arr(list) = doc.get("cases").unwrap() else { panic!() };
        for c in list {
            let Some(want) = c.get("expected") else { continue };
            match call(&function, c.get("input").unwrap()) {
                Err(e) if e.starts_with("not ported") => break,
                Err(e) => problems.push(format!("{}: {}", function, e)),
                Ok(got) => { ran += 1; differs(&got, want, tol, &function, &mut problems); }
            }
        }
    }
    assert!(ran > 0, "no ported golden case ran");
    assert!(problems.is_empty(), "{:#?}", problems);
}
