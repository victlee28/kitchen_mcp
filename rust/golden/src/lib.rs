pub mod core;
pub mod json;
pub mod sha256;

use json::Json;
use std::collections::BTreeMap;

fn num(i: &Json, k: &str) -> Result<f64, String> { i.get(k).and_then(Json::f64).ok_or(format!("missing number '{}'", k)) }
fn obj(pairs: Vec<(&str, Json)>) -> Json { Json::Obj(pairs.into_iter().map(|(k, v)| (k.to_string(), v)).collect::<BTreeMap<_, _>>()) }

/// One golden function id -> JSON in, JSON out (rule R19). Err = the function is not ported yet or the input is malformed.
pub fn call(function: &str, input: &Json) -> Result<Json, String> {
    let placement = || -> Result<core::Placement, String> { Ok(core::Placement { yaw: num(input, "yaw")?, ox: num(input, "ox")?, oz: num(input, "oz")? }) };
    match function {
        "numeric.round_half_away" => {
            let nd = input.get("ndigits").and_then(Json::f64).unwrap_or(0.0) as i32;
            Ok(obj(vec![("value", Json::Float(core::round_half_away(num(input, "x")?, nd)))]))
        }
        "placement.to_room" => { let (x, z) = placement()?.to_room(num(input, "x")?, num(input, "z")?); Ok(obj(vec![("x", Json::Float(x)), ("z", Json::Float(z))])) }
        "placement.to_kitchen" => { let (x, z) = placement()?.to_kitchen(num(input, "x")?, num(input, "z")?); Ok(obj(vec![("x", Json::Float(x)), ("z", Json::Float(z))])) }
        "proposal.op_hash" => {
            let op = input.get("operation").ok_or("missing operation")?;
            let rev = input.get("baseRev").ok_or("missing baseRev")?;
            Ok(obj(vec![("hash", Json::Str(core::op_hash(op, rev)?))]))
        }
        other => Err(format!("not ported: {}", other)),
    }
}

/// Same comparison as tests/golden_compare.py: numbers within `tol`, everything else equal.
pub fn differs(got: &Json, want: &Json, tol: f64, path: &str, out: &mut Vec<String>) {
    match (got, want) {
        (Json::Obj(a), Json::Obj(b)) => {
            for k in a.keys().chain(b.keys()).collect::<std::collections::BTreeSet<_>>() {
                match (a.get(k), b.get(k)) {
                    (Some(x), Some(y)) => differs(x, y, tol, &format!("{}.{}", path, k), out),
                    _ => out.push(format!("{}.{}: key missing on one side", path, k)),
                }
            }
        }
        (Json::Arr(a), Json::Arr(b)) if a.len() == b.len() => a.iter().zip(b).enumerate().for_each(|(i, (x, y))| differs(x, y, tol, &format!("{}[{}]", path, i), out)),
        _ => match (got.f64(), want.f64()) {
            (Some(x), Some(y)) if (x - y).abs() <= tol => {}
            (Some(_), Some(_)) | (None, _) | (_, None) if got != want => out.push(format!("{}: got {:?}, want {:?}", path, got, want)),
            _ => {}
        },
    }
}
