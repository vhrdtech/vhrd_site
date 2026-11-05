//! The address check: a deliberately narrow subset of RFC 5321 that every real signup fits. Anything outside it is
//! refused, never repaired: no trimming, no Unicode, no quoted local parts, no IP literals.
//!
//! - at most 254 bytes in all, exactly one `@`;
//! - the local part: 1 to 64 of ASCII letters, digits and `. _ + -`, no dot at either end and no two dots in a row;
//! - the domain: labels of ASCII letters, digits and `-` (1 to 63 each, no `-` at either end) joined by single dots,
//!   at least two labels, the last one letters only and at least two long.
//!
//! The accepted address is kept in lower case, so `A@B.no` and `a@b.no` are one signup.

use std::fmt;

/// Longest address accepted (RFC 5321's path limit minus the angle brackets).
pub const MAX_LEN: usize = 254;
const MAX_LOCAL: usize = 64;
const MAX_LABEL: usize = 63;

/// A checked address, in lower case. Holds only the characters listed in the module docs, so it is safe to write
/// into the store's tab-separated lines and into HTML as it is.
#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Email(String);

/// Why an address was refused. The reasons never carry the input itself.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Invalid {
    Empty,
    TooLong,
    /// No `@`, or more than one.
    At,
    /// A character outside the allowed set (control, space, Unicode, quote, ...).
    Char,
    LocalPart,
    Domain,
}

impl fmt::Display for Invalid {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Invalid::Empty => "empty address",
            Invalid::TooLong => "address too long",
            Invalid::At => "an address has exactly one @",
            Invalid::Char => "a character not allowed in an address",
            Invalid::LocalPart => "the part before @ is not valid",
            Invalid::Domain => "the domain is not valid",
        })
    }
}

impl std::error::Error for Invalid {}

impl Email {
    pub fn parse(s: &str) -> Result<Email, Invalid> {
        if s.is_empty() {
            return Err(Invalid::Empty);
        }
        if s.len() > MAX_LEN {
            return Err(Invalid::TooLong);
        }
        // characters first, so a line break or a Unicode look-alike is named for what it is
        if !s.bytes().all(|b| b.is_ascii_alphanumeric() || b"._+-@".contains(&b)) {
            return Err(Invalid::Char);
        }
        let (local, domain) = s.split_once('@').ok_or(Invalid::At)?;
        if domain.contains('@') {
            return Err(Invalid::At);
        }
        if !domain.bytes().all(|b| b.is_ascii_alphanumeric() || b".-".contains(&b)) {
            return Err(Invalid::Char);
        }
        if local.is_empty()
            || local.len() > MAX_LOCAL
            || local.starts_with('.')
            || local.ends_with('.')
            || local.contains("..")
        {
            return Err(Invalid::LocalPart);
        }
        let labels: Vec<&str> = domain.split('.').collect();
        let label_ok = |l: &&str| !l.is_empty() && l.len() <= MAX_LABEL && !l.starts_with('-') && !l.ends_with('-');
        let tld = labels.last().copied().unwrap_or("");
        if labels.len() < 2
            || !labels.iter().all(label_ok)
            || tld.len() < 2
            || !tld.bytes().all(|b| b.is_ascii_alphabetic())
        {
            return Err(Invalid::Domain);
        }
        Ok(Email(s.to_ascii_lowercase()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for Email {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn good_addresses() {
        for s in [
            "a@b.no",
            "roman@example.com",
            "first.last@sub.example.co.uk",
            "x+tag@example.org",
            "under_score-dash@my-host.example",
            "0@0.io",
            "UPPER@Example.NO",
        ] {
            assert!(Email::parse(s).is_ok(), "{s} refused");
        }
    }

    #[test]
    fn kept_in_lower_case() {
        assert_eq!(
            Email::parse("Roman@VHRD.Example").unwrap().as_str(),
            "roman@vhrd.example"
        );
    }

    #[test]
    fn at_sign() {
        assert_eq!(Email::parse("no-at.example.com"), Err(Invalid::At));
        assert_eq!(Email::parse("a@b@example.com"), Err(Invalid::At));
        assert_eq!(Email::parse("a@@example.com"), Err(Invalid::At));
    }

    #[test]
    fn local_part() {
        for s in ["@example.com", ".a@example.com", "a.@example.com", "a..b@example.com"] {
            assert_eq!(Email::parse(s), Err(Invalid::LocalPart), "{s}");
        }
        let long = format!("{}@example.com", "a".repeat(65));
        assert_eq!(Email::parse(&long), Err(Invalid::LocalPart));
        assert!(Email::parse(&format!("{}@example.com", "a".repeat(64))).is_ok());
    }

    #[test]
    fn domain() {
        for s in [
            "a@",
            "a@localhost",
            "a@.example.com",
            "a@example.com.",
            "a@example..com",
            "a@-example.com",
            "a@example-.com",
            "a@example.c",
            "a@example.c0m",
            "a@127.0.0.1",
        ] {
            assert_eq!(Email::parse(s), Err(Invalid::Domain), "{s}");
        }
        let label = "a".repeat(64);
        assert_eq!(Email::parse(&format!("a@{label}.com")), Err(Invalid::Domain));
    }

    #[test]
    fn bad_characters() {
        for s in [
            "a b@example.com",
            " a@example.com",
            "a@example.com ",
            "a\t@example.com",
            "a@exa mple.com",
            "a\"b@example.com",
            "<a>@example.com",
            "a@example.com>",
            "a;b@example.com",
            "a,b@example.com",
            "a%b@example.com",
            "a/b@example.com",
            "a_b@ex_ample.com",
            "a+b@ex+ample.com",
            "a@[127.0.0.1]",
        ] {
            assert_eq!(Email::parse(s), Err(Invalid::Char), "{s:?}");
        }
    }

    #[test]
    fn control_characters_and_crlf() {
        for s in [
            "a\r\n@example.com",
            "a@example.com\r\nBcc: x@example.com",
            "a@example.com\n",
            "a\0@example.com",
            "a@exa\u{7f}mple.com",
            "a\u{1b}[31m@example.com",
        ] {
            assert_eq!(Email::parse(s), Err(Invalid::Char), "{s:?}");
        }
    }

    #[test]
    fn unicode() {
        for s in [
            "rømån@example.no",
            "a@exämple.no",
            "a@xn--exmple-cua.no\u{200b}",
            "a\u{ff20}example.com@x.no",
            "a@example.com\u{202e}",
            "\u{feff}a@example.com",
            "a@example.c\u{43e}m",
        ] {
            assert_eq!(Email::parse(s), Err(Invalid::Char), "{s:?}");
        }
        // punycode is plain ASCII and fine
        assert!(Email::parse("a@xn--rmn-0na.no").is_ok());
    }

    #[test]
    fn oversize() {
        assert_eq!(Email::parse(""), Err(Invalid::Empty));
        // 64 + 1 + 189 = 254: the longest accepted
        let domain = format!("{}.{}.{}.com", "d".repeat(61), "e".repeat(61), "f".repeat(61));
        let max = format!("{}@{domain}", "a".repeat(64));
        assert_eq!(max.len(), MAX_LEN);
        assert!(Email::parse(&max).is_ok());
        let over = format!("{}@{domain}x", "a".repeat(64));
        assert_eq!(Email::parse(&over), Err(Invalid::TooLong));
        assert_eq!(Email::parse(&"a".repeat(100_000)), Err(Invalid::TooLong));
    }
}
