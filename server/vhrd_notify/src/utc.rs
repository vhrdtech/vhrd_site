//! UTC time stamps for the store, without a date crate: `2026-11-05T14:03:09Z` from seconds since 1970.

use std::time::{SystemTime, UNIX_EPOCH};

/// Seconds since 1970-01-01 UTC, now.
pub fn now_secs() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// RFC 3339 in UTC, to the second.
pub fn format(secs: i64) -> String {
    let (days, rest) = (secs.div_euclid(86400), secs.rem_euclid(86400));
    // civil date from days since 1970-01-01 (Howard Hinnant's algorithm)
    let z = days + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        rest / 3600,
        rest % 3600 / 60,
        rest % 60
    )
}

/// The seconds of a stamp written by [`format`]; anything else is `None`.
pub fn parse(s: &str) -> Option<i64> {
    let b = s.as_bytes();
    if b.len() != 20 || b[4] != b'-' || b[7] != b'-' || b[10] != b'T' || b[13] != b':' || b[16] != b':' || b[19] != b'Z'
    {
        return None;
    }
    let num = |r: std::ops::Range<usize>| -> Option<i64> {
        let t = &s[r];
        t.bytes().all(|c| c.is_ascii_digit()).then(|| t.parse().ok())?
    };
    let (y, mo, d) = (num(0..4)?, num(5..7)?, num(8..10)?);
    let (h, mi, se) = (num(11..13)?, num(14..16)?, num(17..19)?);
    if !(1..=12).contains(&mo) || !(1..=31).contains(&d) || h > 23 || mi > 59 || se > 59 {
        return None;
    }
    // days since 1970-01-01 from the civil date (Howard Hinnant's algorithm), the inverse of the one above
    let y = if mo <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (mo + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146097 + doe - 719468;
    let secs = days * 86400 + h * 3600 + mi * 60 + se;
    // 31 February and the like: only a stamp that formats back to itself
    (format(secs) == s).then_some(secs)
}

#[cfg(test)]
mod tests {
    #[test]
    fn parse_is_the_inverse() {
        for t in [0, 951_782_400, 1_793_973_789, 4_102_444_799] {
            assert_eq!(super::parse(&super::format(t)), Some(t));
        }
        for s in [
            "",
            "2026-02-31T00:00:00Z",
            "2026-11-05T24:00:00Z",
            "2026-11-05 14:03:09Z",
            "+026-11-05T14:03:09Z",
        ] {
            assert_eq!(super::parse(s), None, "{s}");
        }
    }

    #[test]
    fn known_times() {
        assert_eq!(super::format(0), "1970-01-01T00:00:00Z");
        assert_eq!(super::format(951_782_400), "2000-02-29T00:00:00Z");
        assert_eq!(super::format(1_793_973_789), "2026-11-06T14:03:09Z");
    }
}
