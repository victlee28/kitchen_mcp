//! The ported functions. Each mirrors the Python source named in its doc comment, line for line.
use crate::json::{canonical, Json};
use crate::sha256;
use std::collections::BTreeMap;

/// kitchen/numeric.py::round_half_away
pub fn round_half_away(x: f64, ndigits: i32) -> f64 {
    let p = 10f64.powi(ndigits);
    let y = x.abs() * p;
    let t = y.floor();
    let r = if y - t >= 0.5 { t + 1.0 } else { t };
    (r / p).copysign(x)
}

/// kitchen/placement.py::Placement
pub struct Placement { pub yaw: f64, pub ox: f64, pub oz: f64 }

impl Placement {
    fn cs(&self) -> (f64, f64) { let a = self.yaw.to_radians(); (a.cos(), a.sin()) }
    pub fn dir_to_room(&self, x: f64, z: f64) -> (f64, f64) { let (c, s) = self.cs(); (x * c + z * s, -x * s + z * c) }
    pub fn to_room(&self, x: f64, z: f64) -> (f64, f64) { let (dx, dz) = self.dir_to_room(x, z); (dx + self.ox, dz + self.oz) }
    pub fn to_kitchen(&self, x: f64, z: f64) -> (f64, f64) {
        let (c, s) = self.cs();
        let (ux, uz) = (x - self.ox, z - self.oz);
        (ux * c - uz * s, ux * s + uz * c)
    }
}

/// 600.0 and 600 are the same number (a browser turns 600.0 into 600): integral floats become integers before hashing.
fn whole(v: &Json) -> Json {
    match v {
        Json::Float(f) if f.is_finite() && *f == f.trunc() && f.abs() < 9.0e15 => Json::Int(*f as i64),
        Json::Arr(a) => Json::Arr(a.iter().map(whole).collect()),
        Json::Obj(m) => Json::Obj(m.iter().map(|(k, x)| (k.clone(), whole(x))).collect()),
        other => other.clone(),
    }
}

/// kitchen/proposal.py::op_hash
pub fn op_hash(operation: &Json, base_rev: &Json) -> Result<String, String> {
    let Json::Obj(m) = operation else { return Err("operation must be an object".into()) };
    let canon: BTreeMap<String, Json> = m.iter()
        .filter(|(k, v)| **v != Json::Null && !(k.as_str() == "closeGap" && **v == Json::Bool(true)))
        .map(|(k, v)| (k.clone(), v.clone())).collect();
    let mut top = BTreeMap::new();
    top.insert("op".to_string(), whole(&Json::Obj(canon)));
    top.insert("baseRev".to_string(), base_rev.clone());
    let mut text = String::new();
    canonical(&Json::Obj(top), &mut text);
    Ok(sha256::hex(text.as_bytes())[..16].to_string())
}
