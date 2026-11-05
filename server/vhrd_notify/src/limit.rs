//! The rate limit, in memory only (nothing about a visitor is written down for it), counted twice:
//!
//! - per client: an IPv4 address, or an IPv6 /64, since one IPv6 line usually holds a whole /64;
//! - per network: an IPv4 /24 or an IPv6 /48, so a block of addresses cannot sign up thousands of addresses an hour.
//!
//! Each count remembers at most `max_clients` keys; when it is full, the key seen longest ago is forgotten, so a
//! flood of new addresses never locks out a real visitor. Time comes in as an argument, so the tests set it.

use std::collections::{HashMap, VecDeque};
use std::net::IpAddr;
use std::time::{Duration, Instant};

pub struct RateLimit {
    client: Count,
    network: Count,
}

impl RateLimit {
    pub fn new(limit: u32, network_limit: u32, window: Duration, max_clients: usize) -> RateLimit {
        RateLimit {
            client: Count::new(limit, window, max_clients),
            network: Count::new(network_limit, window, max_clients),
        }
    }

    /// Counts one request from `ip` at `now`; false when it is over either limit (then it is not counted).
    pub fn allow(&mut self, ip: IpAddr, now: Instant) -> bool {
        let (client, network) = keys(ip);
        if !self.client.has_room(client, now) || !self.network.has_room(network, now) {
            return false;
        }
        self.client.add(client, now);
        self.network.add(network, now);
        true
    }
}

struct Count {
    limit: usize,
    window: Duration,
    max_keys: usize,
    seen: HashMap<IpAddr, VecDeque<Instant>>,
}

impl Count {
    fn new(limit: u32, window: Duration, max_keys: usize) -> Count {
        Count {
            limit: limit as usize,
            window,
            max_keys: max_keys.max(1),
            seen: HashMap::new(),
        }
    }

    fn has_room(&mut self, key: IpAddr, now: Instant) -> bool {
        let Some(times) = self.seen.get_mut(&key) else {
            return self.limit > 0;
        };
        while times.front().is_some_and(|t| now.duration_since(*t) >= self.window) {
            times.pop_front();
        }
        times.len() < self.limit
    }

    fn add(&mut self, key: IpAddr, now: Instant) {
        if !self.seen.contains_key(&key) && self.seen.len() >= self.max_keys {
            let window = self.window;
            self.seen
                .retain(|_, t| t.back().is_some_and(|last| now.duration_since(*last) < window));
            if self.seen.len() >= self.max_keys {
                let oldest = self.seen.iter().min_by_key(|(_, t)| t.back().copied()).map(|(k, _)| *k);
                if let Some(k) = oldest {
                    self.seen.remove(&k);
                }
            }
        }
        self.seen.entry(key).or_default().push_back(now);
    }
}

/// The client's key and its network's.
fn keys(ip: IpAddr) -> (IpAddr, IpAddr) {
    let ip = match ip {
        IpAddr::V6(v6) => v6.to_ipv4_mapped().map(IpAddr::V4).unwrap_or(ip),
        v4 => v4,
    };
    match ip {
        IpAddr::V4(v4) => {
            let o = v4.octets();
            (ip, IpAddr::from([o[0], o[1], o[2], 0]))
        }
        IpAddr::V6(v6) => {
            let s = v6.segments();
            (
                IpAddr::V6([s[0], s[1], s[2], s[3], 0, 0, 0, 0].into()),
                IpAddr::V6([s[0], s[1], s[2], 0, 0, 0, 0, 0].into()),
            )
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const HOUR: Duration = Duration::from_secs(3600);

    fn ip(s: &str) -> IpAddr {
        s.parse().unwrap()
    }

    #[test]
    fn limit_per_window() {
        let mut r = RateLimit::new(3, 100, HOUR, 100);
        let t0 = Instant::now();
        assert!((0..3).all(|i| r.allow(ip("192.0.2.1"), t0 + Duration::from_secs(i))));
        assert!(!r.allow(ip("192.0.2.1"), t0 + Duration::from_secs(10)));
        assert!(r.allow(ip("192.0.2.2"), t0 + Duration::from_secs(10)));
        // the first one ages out after the window
        assert!(r.allow(ip("192.0.2.1"), t0 + HOUR));
        assert!(!r.allow(ip("192.0.2.1"), t0 + HOUR));
    }

    #[test]
    fn ipv6_counts_by_its_64() {
        let mut r = RateLimit::new(1, 100, HOUR, 100);
        let t0 = Instant::now();
        assert!(r.allow(ip("2001:db8:1:2::1"), t0));
        assert!(!r.allow(ip("2001:db8:1:2:ffff::9"), t0));
        assert!(r.allow(ip("2001:db8:1:3::1"), t0));
        // a mapped IPv4 address is the IPv4 client
        assert!(r.allow(ip("192.0.2.7"), t0));
        assert!(!r.allow(ip("::ffff:192.0.2.7"), t0));
    }

    #[test]
    fn a_network_has_its_own_limit() {
        let mut r = RateLimit::new(5, 3, HOUR, 100);
        let t0 = Instant::now();
        // three /64s of one /48, then the /48 is full; another /48 is not held back
        for i in 0..3 {
            assert!(r.allow(ip(&format!("2001:db8:1:{i}::1")), t0));
        }
        assert!(!r.allow(ip("2001:db8:1:99::1"), t0));
        assert!(r.allow(ip("2001:db8:2::1"), t0));
        // the same for IPv4 /24s
        for i in 1..=3 {
            assert!(r.allow(ip(&format!("198.51.100.{i}")), t0));
        }
        assert!(!r.allow(ip("198.51.100.200"), t0));
        assert!(r.allow(ip("198.51.101.1"), t0));
    }

    #[test]
    fn a_full_table_forgets_the_oldest_instead_of_refusing() {
        let mut r = RateLimit::new(1, 100, HOUR, 2);
        let t0 = Instant::now();
        assert!(r.allow(ip("192.0.2.1"), t0));
        assert!(r.allow(ip("198.51.100.1"), t0 + Duration::from_secs(1)));
        // a new client is let in, the one seen longest ago is forgotten
        assert!(r.allow(ip("203.0.113.1"), t0 + Duration::from_secs(2)));
        assert_eq!(r.client.seen.len(), 2);
        assert!(!r.client.seen.contains_key(&ip("192.0.2.1")));
        // the clients still remembered are still held back
        assert!(!r.allow(ip("203.0.113.1"), t0 + Duration::from_secs(3)));
    }
}
