//! The per-client rate limit, in memory only (nothing about a visitor is written down for it). A client is its
//! IPv4 address, or its IPv6 /64, since one IPv6 line usually holds a whole /64. Time comes in as an argument, so
//! the tests set it.

use std::collections::{HashMap, VecDeque};
use std::net::IpAddr;
use std::time::{Duration, Instant};

pub struct RateLimit {
    limit: u32,
    window: Duration,
    max_clients: usize,
    seen: HashMap<IpAddr, VecDeque<Instant>>,
}

impl RateLimit {
    pub fn new(limit: u32, window: Duration, max_clients: usize) -> RateLimit {
        RateLimit {
            limit,
            window,
            max_clients,
            seen: HashMap::new(),
        }
    }

    /// Counts one request from `ip` at `now`; false when it is over the limit (then it is not counted).
    pub fn allow(&mut self, ip: IpAddr, now: Instant) -> bool {
        let key = client(ip);
        if !self.seen.contains_key(&key) && self.seen.len() >= self.max_clients {
            self.forget_old(now);
            if self.seen.len() >= self.max_clients {
                return false;
            }
        }
        let times = self.seen.entry(key).or_default();
        while times.front().is_some_and(|t| now.duration_since(*t) >= self.window) {
            times.pop_front();
        }
        if times.len() >= self.limit as usize {
            return false;
        }
        times.push_back(now);
        true
    }

    fn forget_old(&mut self, now: Instant) {
        let window = self.window;
        self.seen
            .retain(|_, t| t.back().is_some_and(|last| now.duration_since(*last) < window));
    }
}

fn client(ip: IpAddr) -> IpAddr {
    match ip {
        IpAddr::V6(v6) => match v6.to_ipv4_mapped() {
            Some(v4) => IpAddr::V4(v4),
            None => {
                let s = v6.segments();
                IpAddr::V6([s[0], s[1], s[2], s[3], 0, 0, 0, 0].into())
            }
        },
        v4 => v4,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const HOUR: Duration = Duration::from_secs(3600);

    #[test]
    fn limit_per_window() {
        let mut r = RateLimit::new(3, HOUR, 100);
        let t0 = Instant::now();
        let ip: IpAddr = "192.0.2.1".parse().unwrap();
        assert!((0..3).all(|i| r.allow(ip, t0 + Duration::from_secs(i))));
        assert!(!r.allow(ip, t0 + Duration::from_secs(10)));
        assert!(r.allow("192.0.2.2".parse().unwrap(), t0 + Duration::from_secs(10)));
        // the first one ages out after the window
        assert!(r.allow(ip, t0 + HOUR));
        assert!(!r.allow(ip, t0 + HOUR));
    }

    #[test]
    fn ipv6_counts_by_its_64() {
        let mut r = RateLimit::new(1, HOUR, 100);
        let t0 = Instant::now();
        assert!(r.allow("2001:db8:1:2::1".parse().unwrap(), t0));
        assert!(!r.allow("2001:db8:1:2:ffff::9".parse().unwrap(), t0));
        assert!(r.allow("2001:db8:1:3::1".parse().unwrap(), t0));
        // a mapped IPv4 address is the IPv4 client
        assert!(r.allow("192.0.2.7".parse().unwrap(), t0));
        assert!(!r.allow("::ffff:192.0.2.7".parse().unwrap(), t0));
    }

    #[test]
    fn remembers_at_most_max_clients() {
        let mut r = RateLimit::new(5, HOUR, 2);
        let t0 = Instant::now();
        assert!(r.allow("192.0.2.1".parse().unwrap(), t0));
        assert!(r.allow("192.0.2.2".parse().unwrap(), t0));
        assert!(!r.allow("192.0.2.3".parse().unwrap(), t0));
        // once the others aged out there is room again
        assert!(r.allow("192.0.2.3".parse().unwrap(), t0 + HOUR));
        assert_eq!(r.seen.len(), 1);
    }
}
