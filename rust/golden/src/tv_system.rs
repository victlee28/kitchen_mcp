//! kitchen/tv_system.py::layout — the cabinets of a TV wall unit along one line, line for line with the Python source.
//! Only what the golden cases pin down is built: each cabinet's box, the TV model and the panel behind it.
use crate::core::round_half_away;

pub const CONSOLE_HEIGHT_MM: f64 = 450.0;
pub const CONSOLE_MAX_MM: f64 = 1200.0;
pub const COLUMNS_FROM_MM: f64 = 2400.0;
pub const COLUMN_MIN_MM: f64 = 400.0;
pub const COLUMN_MAX_MM: f64 = 600.0;
pub const SHELF_Y_MM: f64 = 1850.0;
pub const SHELF_HEIGHT_MM: f64 = 250.0;
pub const FULL_UPPER_Y_MM: f64 = 1750.0;
pub const SIDE_SHELF_Y_MM: f64 = 1300.0;
pub const SIDE_GAP_MM: f64 = 300.0;
/// (niche from, inches, width, height) in mm, the biggest first.
pub const TVS: [(f64, &str, f64, f64); 3] = [(1700.0, "65", 1450.0, 830.0), (1400.0, "55", 1230.0, 710.0), (0.0, "43", 960.0, 560.0)];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Style { Columns, Shelves, Full }

impl Style {
    pub fn parse(s: &str) -> Option<Style> {
        match s { "columns" => Some(Style::Columns), "shelves" => Some(Style::Shelves), "full" => Some(Style::Full), _ => None }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct BackPanel { pub s0: f64, pub s1: f64, pub y0: f64, pub y1: f64 }

#[derive(Debug, Clone, PartialEq)]
pub struct Laid {
    pub kind: &'static str,
    pub s: f64,
    pub width: f64,
    pub y: f64,
    pub height: f64,
    pub tv_model: Option<String>,
    pub back_panel: Option<BackPanel>,
}

fn round_int(x: f64) -> i64 { round_half_away(x, 0) as i64 }

/// The TV for a niche `niche` mm wide: (model id, width mm).
pub fn tv_for(niche: f64) -> (String, f64) {
    let t = TVS.iter().find(|t| niche >= t.0).unwrap_or(&TVS[2]);
    (format!("tv-{}", t.1), t.2)
}

fn split(length: f64, most: f64) -> Vec<f64> {
    let n = ((length / most - 1e-9).ceil() as i64).max(1);
    let w = (round_int(length / n as f64 / 10.0) * 10) as f64;
    let mut out = vec![w; (n - 1) as usize];
    out.push(length - w * (n - 1) as f64);
    out
}

fn console(at: f64, length: f64) -> Vec<Laid> {
    let mut out = vec![];
    let mut s = at;
    for w in split(length, CONSOLE_MAX_MM) {
        out.push(Laid { kind: "base", s, width: w, y: 0.0, height: CONSOLE_HEIGHT_MM, tv_model: None, back_panel: None });
        s += w;
    }
    out
}

fn put_tv(console: &mut [Laid], center: f64, width: f64, panel: Option<(f64, f64, f64)>) {
    let i = console.iter().position(|c| c.s <= center && center < c.s + c.width).unwrap_or(0);
    let host = &mut console[i];
    host.tv_model = Some(tv_for(width).0);
    if let Some((pw, y0, y1)) = panel {
        host.back_panel = Some(BackPanel { s0: center - pw / 2.0 - host.s, s1: center + pw / 2.0 - host.s, y0, y1 });
    }
}

fn tall(s: f64, width: f64, top: f64) -> Laid { Laid { kind: "tall", s, width, y: 0.0, height: top, tv_model: None, back_panel: None } }

fn shelf(s: f64, width: f64, y: f64) -> Laid { Laid { kind: "upper-open", s, width, y, height: SHELF_HEIGHT_MM, tv_model: None, back_panel: None } }

/// The cabinets of a TV unit `length` mm long; `cabinet_top` is the design's common.cabinetTop (None: 2400).
pub fn layout(length: f64, cabinet_top: Option<f64>, style: Style, panel: bool) -> Vec<Laid> {
    let length = (length / 10.0).floor() * 10.0;
    let top = cabinet_top.filter(|t| *t != 0.0).unwrap_or(2400.0);
    let mut out = vec![];
    match style {
        Style::Full => {
            let mut niche = if length < 2000.0 { length } else { (length - 800.0).min(1200f64.max((round_int(length * 0.45 / 10.0) * 10) as f64)) };
            let side = ((length - niche) / 2.0 / 10.0).floor() * 10.0;
            niche = length - 2.0 * side;
            let sides = if side > 0.0 { split(side, COLUMN_MAX_MM) } else { vec![] };
            let mut at = 0.0;
            for w in &sides { out.push(tall(at, *w, top)); at += w; }
            let mut cons = console(side, niche);
            put_tv(&mut cons, side + niche / 2.0, niche, if panel { Some((niche, CONSOLE_HEIGHT_MM, FULL_UPPER_Y_MM)) } else { None });
            out.extend(cons);
            at = side + niche;
            for w in &sides { out.push(tall(at, *w, top)); at += w; }
            if top - FULL_UPPER_Y_MM >= 250.0 {
                at = side;
                for w in split(niche, 900.0) {
                    out.push(Laid { kind: "upper", s: at, width: w, y: FULL_UPPER_Y_MM, height: top - FULL_UPPER_Y_MM, tv_model: None, back_panel: None });
                    at += w;
                }
            }
        }
        Style::Shelves => {
            let mut cons = console(0.0, length);
            let center = length / 2.0;
            let tv_w = tv_for(length - 900.0).1;
            put_tv(&mut cons, center, length - 900.0, if panel { Some((tv_w + 400.0, CONSOLE_HEIGHT_MM, FULL_UPPER_Y_MM)) } else { None });
            out.extend(cons);
            let side = (length - tv_w) / 2.0 - SIDE_GAP_MM;
            if side >= 450.0 {
                let w = 900f64.min((side / 10.0).floor() * 10.0);
                for s in [center - tv_w / 2.0 - SIDE_GAP_MM - w, center + tv_w / 2.0 + SIDE_GAP_MM] { out.push(shelf(s, w, SIDE_SHELF_Y_MM)); }
            } else if length >= 600.0 {
                out.push(shelf(0.0, length, SHELF_Y_MM));
            }
        }
        Style::Columns => {
            let col = if length >= COLUMNS_FROM_MM {
                COLUMN_MAX_MM.min(COLUMN_MIN_MM.max((round_int(length * 0.15 / 50.0) * 50) as f64))
            } else { 0.0 };
            let niche = length - 2.0 * col;
            if col > 0.0 { out.push(tall(0.0, col, top)); out.push(tall(length - col, col, top)); }
            let mut cons = console(col, niche);
            put_tv(&mut cons, col + niche / 2.0, niche, if panel { Some((niche, CONSOLE_HEIGHT_MM, SHELF_Y_MM)) } else { None });
            out.extend(cons);
            if niche >= 600.0 { out.push(shelf(col, niche, SHELF_Y_MM)); }
        }
    }
    out
}
