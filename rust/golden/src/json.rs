//! Minimal JSON value, parser and canonical writer (sorted keys, compact, non-ASCII kept as is) matching Python's
//! ``json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":"))`` for the value kinds the golden files use.
use std::collections::BTreeMap;

#[derive(Clone, Debug, PartialEq)]
pub enum Json {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    Arr(Vec<Json>),
    Obj(BTreeMap<String, Json>),
}

impl Json {
    pub fn get(&self, k: &str) -> Option<&Json> {
        if let Json::Obj(m) = self { m.get(k) } else { None }
    }
    pub fn f64(&self) -> Option<f64> {
        match self { Json::Int(i) => Some(*i as f64), Json::Float(f) => Some(*f), _ => None }
    }
    pub fn str(&self) -> Option<&str> {
        if let Json::Str(s) = self { Some(s) } else { None }
    }
}

pub fn parse(text: &str) -> Result<Json, String> {
    let mut p = P { b: text.as_bytes(), i: 0 };
    let v = p.value()?;
    p.ws();
    if p.i != p.b.len() { return Err(format!("trailing data at {}", p.i)); }
    Ok(v)
}

struct P<'a> { b: &'a [u8], i: usize }

impl<'a> P<'a> {
    fn ws(&mut self) { while self.i < self.b.len() && matches!(self.b[self.i], b' ' | b'\n' | b'\r' | b'\t') { self.i += 1; } }
    fn eat(&mut self, c: u8) -> Result<(), String> {
        if self.i < self.b.len() && self.b[self.i] == c { self.i += 1; Ok(()) } else { Err(format!("expected '{}' at {}", c as char, self.i)) }
    }
    fn lit(&mut self, s: &str, v: Json) -> Result<Json, String> {
        if self.b[self.i..].starts_with(s.as_bytes()) { self.i += s.len(); Ok(v) } else { Err(format!("bad literal at {}", self.i)) }
    }
    fn value(&mut self) -> Result<Json, String> {
        self.ws();
        match self.b.get(self.i) {
            None => Err("unexpected end".into()),
            Some(b'n') => self.lit("null", Json::Null),
            Some(b't') => self.lit("true", Json::Bool(true)),
            Some(b'f') => self.lit("false", Json::Bool(false)),
            Some(b'"') => Ok(Json::Str(self.string()?)),
            Some(b'[') => {
                self.i += 1;
                let mut a = vec![];
                self.ws();
                if self.b.get(self.i) == Some(&b']') { self.i += 1; return Ok(Json::Arr(a)); }
                loop {
                    a.push(self.value()?);
                    self.ws();
                    match self.b.get(self.i) {
                        Some(b',') => self.i += 1,
                        Some(b']') => { self.i += 1; return Ok(Json::Arr(a)); }
                        _ => return Err(format!("bad array at {}", self.i)),
                    }
                }
            }
            Some(b'{') => {
                self.i += 1;
                let mut m = BTreeMap::new();
                self.ws();
                if self.b.get(self.i) == Some(&b'}') { self.i += 1; return Ok(Json::Obj(m)); }
                loop {
                    self.ws();
                    let k = self.string()?;
                    self.ws();
                    self.eat(b':')?;
                    m.insert(k, self.value()?);
                    self.ws();
                    match self.b.get(self.i) {
                        Some(b',') => self.i += 1,
                        Some(b'}') => { self.i += 1; return Ok(Json::Obj(m)); }
                        _ => return Err(format!("bad object at {}", self.i)),
                    }
                }
            }
            Some(_) => self.number(),
        }
    }
    fn number(&mut self) -> Result<Json, String> {
        let s = self.i;
        while self.i < self.b.len() && matches!(self.b[self.i], b'-' | b'+' | b'.' | b'e' | b'E' | b'0'..=b'9') { self.i += 1; }
        let t = std::str::from_utf8(&self.b[s..self.i]).map_err(|e| e.to_string())?;
        if t.is_empty() { return Err(format!("unexpected character at {}", s)); }
        if !t.contains(['.', 'e', 'E']) {
            if let Ok(i) = t.parse::<i64>() { return Ok(Json::Int(i)); }
        }
        t.parse::<f64>().map(Json::Float).map_err(|e| format!("{}: {}", t, e))
    }
    fn string(&mut self) -> Result<String, String> {
        self.eat(b'"')?;
        let mut out: Vec<u8> = vec![];
        loop {
            let c = *self.b.get(self.i).ok_or("unterminated string")?;
            self.i += 1;
            match c {
                b'"' => return String::from_utf8(out).map_err(|e| e.to_string()),
                b'\\' => {
                    let e = *self.b.get(self.i).ok_or("bad escape")?;
                    self.i += 1;
                    match e {
                        b'"' => out.push(b'"'), b'\\' => out.push(b'\\'), b'/' => out.push(b'/'),
                        b'b' => out.push(8), b'f' => out.push(12), b'n' => out.push(b'\n'), b'r' => out.push(b'\r'), b't' => out.push(b'\t'),
                        b'u' => {
                            let mut cp = self.hex4()?;
                            if (0xD800..0xDC00).contains(&cp) && self.b[self.i..].starts_with(b"\\u") {
                                self.i += 2;
                                let lo = self.hex4()?;
                                cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                            }
                            let ch = char::from_u32(cp).ok_or("bad code point")?;
                            let mut buf = [0u8; 4];
                            out.extend_from_slice(ch.encode_utf8(&mut buf).as_bytes());
                        }
                        _ => return Err("bad escape".into()),
                    }
                }
                _ => out.push(c),
            }
        }
    }
    fn hex4(&mut self) -> Result<u32, String> {
        let s = std::str::from_utf8(self.b.get(self.i..self.i + 4).ok_or("short \\u")?).map_err(|e| e.to_string())?;
        self.i += 4;
        u32::from_str_radix(s, 16).map_err(|e| e.to_string())
    }
}

fn float_repr(f: f64) -> String {
    // Python repr: integral values keep ".0"; exponent form only below 1e-4 or from 1e16.
    if f.is_finite() && f == f.trunc() && f.abs() < 1e16 { return format!("{:.1}", f); }
    format!("{:?}", f)
}

pub fn canonical(v: &Json, out: &mut String) {
    match v {
        Json::Null => out.push_str("null"),
        Json::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Json::Int(i) => out.push_str(&i.to_string()),
        Json::Float(f) => out.push_str(&float_repr(*f)),
        Json::Str(s) => {
            out.push('"');
            for c in s.chars() {
                match c {
                    '"' => out.push_str("\\\""), '\\' => out.push_str("\\\\"),
                    '\n' => out.push_str("\\n"), '\r' => out.push_str("\\r"), '\t' => out.push_str("\\t"),
                    '\u{8}' => out.push_str("\\b"), '\u{c}' => out.push_str("\\f"),
                    c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
                    c => out.push(c),
                }
            }
            out.push('"');
        }
        Json::Arr(a) => {
            out.push('[');
            for (i, x) in a.iter().enumerate() { if i > 0 { out.push(','); } canonical(x, out); }
            out.push(']');
        }
        Json::Obj(m) => {
            out.push('{');
            for (i, (k, x)) in m.iter().enumerate() {
                if i > 0 { out.push(','); }
                canonical(&Json::Str(k.clone()), out);
                out.push(':');
                canonical(x, out);
            }
            out.push('}');
        }
    }
}
