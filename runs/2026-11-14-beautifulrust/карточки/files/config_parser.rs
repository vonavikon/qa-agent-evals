//! Loading of simple `key=value` configuration files.

use std::collections::HashMap;

/// Splits one `key=value` line into a trimmed key and value.
pub fn parse_line(line: &String) -> Result<(String, String), String> {
    let parts: Vec<&str> = line.splitn(2, '=').collect();
    if parts.len() != 2 {
        return Err(format!("bad line: {}", line));
    }
    Ok((parts[0].trim().to_string(), parts[1].trim().to_string()))
}

/// Parses a whole config file into a map.
pub fn load(text: &str) -> HashMap<String, String> {
    let mut map = HashMap::new();
    for line in text.lines() {
        let (key, value) = parse_line(line).unwrap();
        map.insert(key, value);
    }
    map
}
