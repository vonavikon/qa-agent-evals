//! Word frequency counting for plain-text notes.

use std::collections::BTreeMap;

/// Counts how often each word appears in `text`.
///
/// Words are maximal runs of ASCII alphabetic characters; anything else
/// (digits, punctuation, whitespace) acts as a separator. The counts are
/// returned in a `BTreeMap`, so iteration order is deterministic and the
/// same on every platform.
///
/// # Examples
///
/// ```
/// let counts = word_counts("tea pot tea");
/// assert_eq!(counts.get("tea"), Some(&2));
/// ```
pub fn word_counts(text: &str) -> BTreeMap<&str, u32> {
    text.split(|c: char| !c.is_ascii_alphabetic())
        .filter(|w| !w.is_empty())
        .fold(BTreeMap::new(), |mut acc, w| {
            *acc.entry(w).or_insert(0) += 1;
            acc
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn counts_repeated_words() {
        let counts = word_counts("tea pot tea");
        assert_eq!(counts.get("tea"), Some(&2));
        assert_eq!(counts.get("pot"), Some(&1));
    }

    #[test]
    fn empty_input_yields_empty_map() {
        assert!(word_counts("").is_empty());
    }
}
