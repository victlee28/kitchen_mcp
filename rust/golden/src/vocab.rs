//! kitchen/vocab.py::to_english / color — material and colour names (Vietnamese) to English prompt words and a display colour.
//! Line for line with the Python source. Two differences, both only for text Python itself normalises first:
//! std Rust has no Unicode normalisation, so diacritics are stripped with a table of the Vietnamese letters (Python: NFD + drop marks),
//! and the input is taken as already NFC (the server normalises what the user types).

pub const COLORS: &[(&str, &str, &str)] = &[
    ("xanh rêu", "#7d8a5f", "sage green"), ("xanh olive", "#6b6b3a", "olive green"), ("xanh lá cây", "#4f7a4a", "green"),
    ("xanh lá", "#4f7a4a", "green"), ("xanh lục", "#3f7d4a", "green"), ("xanh lam", "#3c5f8a", "blue"), ("xanh biển", "#2f5f8a", "sea blue"),
    ("xanh navy", "#22324f", "navy blue"), ("xanh dương", "#3c5f8a", "blue"), ("xanh ngọc", "#3f8f8a", "teal"),
    ("xanh than", "#2b3440", "charcoal blue"), ("xanh mint", "#a8d5c2", "mint green"),
    ("xanh", "#5f7f8f", ""),
    ("trắng sữa", "#f3efe4", "off-white"), ("trắng ngà", "#efe8d8", "ivory"), ("trắng", "#f2f2f0", "white"),
    ("kem", "#eadfc8", "cream"), ("be", "#d8c6a8", "beige"), ("ghi", "#9a9a96", "light grey"),
    ("xám đậm", "#4a4a4a", "dark grey"), ("xám nhạt", "#c4c4c0", "light grey"), ("xám", "#8a8a88", "grey"),
    ("đen", "#2a2a2a", "black"), ("nâu đậm", "#4e3526", "dark brown"), ("nâu", "#7a5538", "brown"),
    ("đỏ đô", "#6e1f2a", "burgundy"), ("đỏ", "#a83232", "red"), ("hồng", "#d9a3a8", "pink"),
    ("đồng vàng", "#b5913f", "brushed brass"), ("vàng đồng", "#b5913f", "brushed brass"), ("đồng thau", "#b5913f", "brass"),
    ("đồng đỏ", "#a0583a", "copper"), ("đồng", "#a0703c", "bronze"), ("vàng gold", "#c8a24a", "gold"),
    ("vàng mù tạt", "#c9a03a", "mustard yellow"), ("vàng", "#d9b84a", "yellow"), ("cam", "#d27a3a", "orange"),
    ("tím", "#6b4f7a", "purple"),
];
pub const WOOD: &[(&str, &str, &str)] = &[
    ("óc chó", "#5c3f2c", "walnut wood"), ("sồi", "#c49a6c", "oak wood"), ("tần bì", "#cfb28a", "ash wood"),
    ("xoan đào", "#9a5a3c", "cherry wood"), ("gõ đỏ", "#7a3a24", "red hardwood"), ("teak", "#a7774a", "teak wood"),
];
pub const CHAT: &[(&str, &str)] = &[
    ("vân mây", "with soft cloudy veining"), ("vân đá", "marble veining"), ("vân gỗ", "wood grain"),
    ("mờ", "matte finish"), ("bóng gương", "high-gloss mirror finish"), ("bóng", "glossy finish"), ("sần", "textured finish"),
    ("acrylic", "acrylic"), ("laminate", "laminate"), ("melamine", "melamine"), ("sơn", "painted"), ("veneer", "wood veneer"),
    ("đá nhân tạo", "engineered quartz stone"), ("thạch anh", "quartz"), ("granite", "granite"), ("marble", "marble"),
    ("cẩm thạch", "marble"), ("lacquer", "lacquer"), ("gỗ lạng", "wood veneer"),
    ("đá terrazzo", "terrazzo stone"), ("terrazzo", "terrazzo stone"), ("zellige", "handmade zellige tile"),
    ("đá", "stone"), ("kính", "glass"), ("inox", "stainless steel"), ("nhôm", "aluminium"), ("đồng thau xước", "brushed brass"),
    ("gạch thẻ", "subway tile"), ("xương cá", "herringbone tile pattern"), ("gạch", "ceramic tile"),
    ("veneer", "wood veneer"), ("acrylic", "acrylic finish"), ("sơn mờ", "matte lacquer"),
    ("sơn bóng", "gloss lacquer"), ("gỗ", "wood"),
];

const ACCENTED: [(&str, char); 12] = [
    ("àáảãạăắằẳẵặâấầẩẫậ", 'a'), ("èéẻẽẹêếềểễệ", 'e'), ("ìíỉĩị", 'i'), ("òóỏõọôốồổỗộơớờởỡợ", 'o'), ("ùúủũụưứừửữự", 'u'), ("ỳýỷỹỵ", 'y'),
    ("ÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬ", 'A'), ("ÈÉẺẼẸÊẾỀỂỄỆ", 'E'), ("ÌÍỈĨỊ", 'I'), ("ÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢ", 'O'), ("ÙÚỦŨỤƯỨỪỬỮỰ", 'U'), ("ỲÝỶỸỴ", 'Y'),
];

/// vocab._strip_diacritics: one char in, one char out (so offsets stay the same).
fn strip_char(c: char) -> char {
    match c {
        'đ' => 'd',
        'Đ' => 'D',
        _ => ACCENTED.iter().find(|(set, _)| set.contains(c)).map_or(c, |(_, base)| *base),
    }
}

pub fn strip_diacritics(t: &str) -> String { t.chars().map(strip_char).collect() }

/// " " + lower case, runs of whitespace , ; / as one space + " " (vocab._accented); the plain form is the same stripped (vocab._norm).
fn accented(t: &str) -> Vec<char> {
    let lower = t.to_lowercase();
    let words: Vec<&str> = lower.split(|c: char| c.is_whitespace() || c == ',' || c == ';' || c == '/').filter(|w| !w.is_empty()).collect();
    let (lead, trail) = (lower.starts_with(|c: char| c.is_whitespace() || ",;/".contains(c)), lower.ends_with(|c: char| c.is_whitespace() || ",;/".contains(c)));
    // re.sub(r"[\s,;/]+", " ", ...) keeps a leading / trailing separator as one space
    let body = format!("{}{}{}", if lead { " " } else { "" }, words.join(" "), if trail && !words.is_empty() { " " } else { "" });
    format!(" {} ", body).chars().collect()
}

fn find(hay: &[char], needle: &[char], from: usize) -> Option<usize> {
    if needle.len() > hay.len() { return None; }
    (from..=hay.len() - needle.len()).find(|&i| hay[i..i + needle.len()] == *needle)
}

/// vocab._matches: the key typed without diacritics, or with exactly these diacritics.
fn matches(t: &[char], ta: &[char], key: &str) -> bool {
    let plain: Vec<char> = format!(" {} ", strip_diacritics(key)).chars().collect();
    let word: Vec<char> = format!(" {} ", key.to_lowercase()).chars().collect();
    let mut at = find(t, &plain, 0);
    while let Some(i) = at {
        let typed = &ta[i..i + plain.len()];
        if typed == word.as_slice() || typed == plain.as_slice() { return true; }
        at = find(t, &plain, i + 1);
    }
    false
}

fn forms(text: &str) -> (Vec<char>, Vec<char>) {
    let ta = accented(text);
    let t = ta.iter().map(|c| strip_char(*c)).collect();
    (t, ta)
}

/// vocab.color: the hex colour of the first colour, else wood, named in the text.
pub fn color(text: &str) -> Option<&'static str> {
    let (t, ta) = forms(text);
    COLORS.iter().chain(WOOD.iter()).find(|r| matches(&t, &ta, r.0)).map(|r| r.1)
}

/// vocab.to_english
pub fn to_english(text: &str) -> String {
    if text.is_empty() { return String::new(); }
    let (t, ta) = forms(text);
    let mut used: Vec<&str> = vec![];
    let mut out: Vec<&str> = vec![];
    let rows: Vec<(&str, &str)> = COLORS.iter().map(|r| (r.0, r.2)).chain(WOOD.iter().map(|r| (r.0, r.2))).chain(CHAT.iter().copied()).collect();
    for (k, en) in rows {
        if matches(&t, &ta, k) && !used.iter().any(|u| strip_diacritics(u).contains(&strip_diacritics(k))) {
            used.push(k);
            if !en.is_empty() { out.push(en); }
        }
    }
    let mut res: Vec<&str> = vec![];
    for phrase in out {
        let joined = res.join(" ");
        let have: Vec<&str> = joined.split_whitespace().collect();
        if !phrase.split_whitespace().all(|w| have.contains(&w)) { res.push(phrase); }
    }
    let text = res.join(" ");
    for (generic, specific) in [("stone", &["marble", "quartz", "granite", "terrazzo"][..]), ("ceramic tile", &["subway tile", "zellige tile"][..])] {
        if res.contains(&generic) && specific.iter().any(|x| text.contains(x)) {
            let i = res.iter().position(|r| *r == generic).unwrap();
            res.remove(i);
        }
    }
    let joined = res.join(" ");
    let words: Vec<&str> = joined.split_whitespace().collect();
    words.iter().enumerate().filter(|(i, w)| *i == 0 || **w != words[i - 1]).map(|(_, w)| *w).collect::<Vec<_>>().join(" ")
}
