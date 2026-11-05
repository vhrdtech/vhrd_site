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

#[cfg(test)]
mod tests {
    #[test]
    fn known_times() {
        assert_eq!(super::format(0), "1970-01-01T00:00:00Z");
        assert_eq!(super::format(951_782_400), "2000-02-29T00:00:00Z");
        assert_eq!(super::format(1_793_973_789), "2026-11-06T14:03:09Z");
    }
}
