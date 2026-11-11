pub mod core;
pub mod json;
pub mod sha256;
pub mod tv_system;
pub mod vocab;

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
        "tv_system.layout" => {
            let top = input.get("common").and_then(|c| c.get("cabinetTop")).and_then(Json::f64);
            let style = match input.get("style").and_then(|s| s.str()) { None => tv_system::Style::Columns,
                Some(s) => tv_system::Style::parse(s).ok_or(format!("unknown style '{}'", s))? };
            let panel = !matches!(input.get("panel"), Some(Json::Bool(false)));
            let mods = tv_system::layout(num(input, "length")?, top, style, panel);
            let f = Json::Float;
            Ok(obj(vec![
                ("modules", Json::Arr(mods.iter().map(|m| Json::Arr(vec![Json::Str(m.kind.to_string()), f(m.s), f(m.width), f(m.y), f(m.height)])).collect())),
                ("tv", Json::Arr(mods.iter().filter_map(|m| m.tv_model.clone().map(Json::Str)).collect())),
                ("panel", Json::Arr(mods.iter().filter_map(|m| m.back_panel.as_ref().map(|p|
                    obj(vec![("s0", f(p.s0)), ("s1", f(p.s1)), ("y0", f(p.y0)), ("y1", f(p.y1))]))).collect())),
            ]))
        }
        "vocab.to_english" => {
            let text = input.get("text").and_then(|t| t.str()).ok_or("missing text")?;
            Ok(obj(vec![("english", Json::Str(vocab::to_english(text))),
                        ("color", vocab::color(text).map_or(Json::Null, |c| Json::Str(c.to_string())))]))
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
