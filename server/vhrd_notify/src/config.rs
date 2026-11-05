//! The service's settings, one TOML file (`deploy/notify.toml` is the server's). Every field has its default here;
//! a missing file means all defaults. Relative paths are taken from the file's own folder.

use std::path::{Path, PathBuf};

use serde::Deserialize;

#[derive(Clone, Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Config {
    /// Address and port to listen on. Loopback: nginx in front of it is the only client.
    pub listen: String,
    /// The signups file (AGENTS.md "Notify service"), outside the web root.
    pub store: PathBuf,
    /// The lists a form may name.
    pub lists: Vec<String>,
    /// The consent text versions a form may carry (the site's `extra.notify_consent`). A new text adds its version
    /// here before the site shows it.
    pub consent_versions: Vec<String>,
    /// Where the site is, scheme and host: the redirects after a form without JavaScript go there, and a request
    /// whose Origin header names another site is refused.
    pub site_origin: String,
    /// The pages a form may come from (the form's `from` field) and their paths, where a form without JavaScript
    /// is sent back to. A `from` not listed goes to the first one.
    pub pages: Vec<Page>,
    /// Largest request body accepted, in bytes.
    pub max_body: usize,
    /// Signups one client may send in `rate_window_secs` (an IPv6 client counts by its /64).
    pub rate_limit: u32,
    /// Signups one network may send in `rate_window_secs`: an IPv4 /24 or an IPv6 /48.
    pub rate_limit_network: u32,
    pub rate_window_secs: u64,
    /// Clients (and networks) the rate limit remembers at once; past that, the one seen longest ago is forgotten.
    pub rate_clients: usize,
    /// Records the store may hold; past that, signups are refused (a full disk is worse). The log warns from 80 %.
    pub max_signups: usize,
    /// Signups waiting for their confirmation are deleted after this many days.
    pub pending_days: u32,
    /// A pending address gets its confirmation mail again at most once in this many hours, however often it signs up.
    pub resend_hours: u32,
    /// Confirmation mails one pending record gets at most.
    pub max_confirm_mails: u32,
    /// Records waiting for their confirmation at most; past that, new signups are refused for everyone.
    pub max_pending: usize,
    /// The pause before each retry of a mail that failed, in seconds; after the last one the mail is given up.
    pub retry_secs: Vec<u32>,
    /// Largest the intake (signups not yet folded into the store) may grow, in bytes.
    pub max_intake_bytes: u64,
    /// The header nginx puts the client's address in. Empty: the connection's own address (no proxy).
    pub client_ip_header: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Page {
    pub name: String,
    pub path: String,
}

impl Default for Config {
    fn default() -> Config {
        Config {
            listen: "127.0.0.1:8471".into(),
            store: "signups.tsv".into(),
            lists: vec!["donguru".into()],
            consent_versions: vec!["2026-11-05".into()],
            site_origin: "https://vhrd.tech".into(),
            pages: vec![
                Page {
                    name: "donguru".into(),
                    path: "/donguru/".into(),
                },
                Page {
                    name: "home".into(),
                    path: "/".into(),
                },
            ],
            max_body: 1024,
            rate_limit: 5,
            rate_limit_network: 20,
            rate_window_secs: 3600,
            rate_clients: 10_000,
            max_signups: 50_000,
            pending_days: 7,
            resend_hours: 24,
            max_confirm_mails: 3,
            max_pending: 5000,
            retry_secs: vec![60, 300, 1800, 7200, 21600],
            max_intake_bytes: 1 << 20,
            client_ip_header: "x-real-ip".into(),
        }
    }
}

/// Exit code for "can't work until someone acts" (bad config): the unit does not restart on it.
pub const EXIT_CONFIG: i32 = 78;

impl Config {
    /// Reads `path`; a file that is not there gives the defaults, with the store beside where it would be.
    pub fn load(path: &Path) -> Result<Config, String> {
        let mut c: Config = match std::fs::read_to_string(path) {
            Ok(text) => toml::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Config::default(),
            Err(e) => return Err(format!("{}: {e}", path.display())),
        };
        if c.store.is_relative()
            && let Some(dir) = path.parent()
        {
            c.store = dir.join(&c.store);
        }
        c.check().map_err(|e| format!("{}: {e}", path.display()))?;
        Ok(c)
    }

    /// The settings a service could not run on: no pages, a list or consent version that could break a line.
    pub fn check(&self) -> Result<(), String> {
        if self.pages.is_empty() {
            return Err("pages: at least one".into());
        }
        for p in &self.pages {
            if !p.path.starts_with('/') || p.path.starts_with("//") || p.path.contains(['\r', '\n', '#', '?']) {
                return Err(format!("pages: {:?} is not a plain path from the site's root", p.path));
            }
        }
        for t in self.lists.iter().chain(&self.consent_versions) {
            if !crate::store::is_token(t) {
                return Err(format!(
                    "{t:?}: lists and consent versions are a-z, 0-9 and -, up to 32"
                ));
            }
        }
        if !(self.site_origin.starts_with("https://") || self.site_origin.starts_with("http://"))
            || self.site_origin.ends_with('/')
            || self.site_origin.contains(['\r', '\n'])
        {
            return Err("site_origin: scheme and host, no trailing /".into());
        }
        if self.max_body == 0 || self.rate_window_secs == 0 || self.pending_days == 0 || self.max_confirm_mails == 0 {
            return Err("max_body, rate_window_secs, pending_days and max_confirm_mails: more than 0".into());
        }
        Ok(())
    }

    /// The limits of [`crate::list`].
    pub fn rules(&self) -> crate::list::Rules {
        crate::list::Rules {
            pending_secs: i64::from(self.pending_days) * 86400,
            resend_secs: i64::from(self.resend_hours) * 3600,
            max_confirm_mails: self.max_confirm_mails,
            max_pending: self.max_pending,
            max_records: self.max_signups,
            retry_secs: self.retry_secs.iter().map(|s| i64::from(*s)).collect(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_pass_the_check() {
        Config::default().check().unwrap();
    }

    #[test]
    fn deploy_config_parses() {
        let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../deploy/notify.toml");
        let c = Config::load(&path).unwrap();
        assert_eq!(c.site_origin, "https://vhrd.tech");
        assert!(c.store.is_absolute());
    }

    #[test]
    fn bad_values_refused() {
        let bad = |f: fn(&mut Config)| {
            let mut c = Config::default();
            f(&mut c);
            c.check().is_err()
        };
        assert!(bad(|c| c.pages.clear()));
        assert!(bad(|c| c.pages[0].path = "https://evil.example/".into()));
        assert!(bad(|c| c.pages[0].path = "//evil.example/".into()));
        assert!(bad(|c| c.lists.push("Two Words".into())));
        assert!(bad(|c| c.consent_versions.push("a\tb".into())));
        assert!(bad(|c| c.site_origin = "https://vhrd.tech/".into()));
        assert!(bad(|c| c.max_body = 0));
    }
}
