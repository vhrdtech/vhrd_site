//! The service's settings, one TOML file (`deploy/notify.toml` is the server's). Every field has its default here;
//! a missing file means all defaults. Relative paths are taken from the file's own folder.

use std::collections::BTreeMap;
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
    /// Signups one network may send in 24 hours. Each can cost a confirmation mail, and the mail budget
    /// (`mail.per_day`) is shared by everyone: at this cap one network takes at most a share of it.
    pub rate_limit_network_day: u32,
    pub rate_window_secs: u64,
    /// Presses of the confirm and remove buttons one client, and one network, may send in `rate_window_secs`.
    pub link_rate_limit: u32,
    pub link_rate_limit_network: u32,
    /// One-click unsubscribes (RFC 8058) per client and per network in `rate_window_secs`. They come from the mail
    /// providers' servers, many people's from one address, so this is high.
    pub one_click_rate_limit: u32,
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
    /// The key the links in our mails are made with ([`crate::token`]): made by the service when missing, mode 0600,
    /// never shipped. Keep it outside the folder releases are installed into.
    pub token_key: PathBuf,
    /// Each list's name as the mails say it.
    pub titles: BTreeMap<String, String>,
    /// How mail goes out. Without this table no mail is sent: the outbox only fills (a test or a local service).
    pub mail: Option<Mail>,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum MailTls {
    /// TLS from the first byte (SMTP submission on port 465), the server's certificate checked against the system's
    /// roots.
    Implicit,
    /// No TLS at all: only to a loopback address (a test's mail server).
    None,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Mail {
    pub host: String,
    pub port: u16,
    pub tls: MailTls,
    /// The login on the mail server. Its password is in `password_file`, never here.
    pub user: String,
    /// One line, the SMTP password; mode 0600, outside the folder releases are installed into.
    pub password_file: PathBuf,
    /// The sender, in From and in the envelope (bounces come back to it).
    pub from: String,
    pub from_name: String,
    /// The name this host gives itself in EHLO.
    pub hello: String,
    /// The longest one mail may take, connection included, in seconds.
    pub timeout_secs: u64,
    /// Confirmation mails sent at most in an hour and in a day, for all addresses together. Past that they wait.
    pub per_hour: u32,
    pub per_day: u32,
    /// List mails (`vhrd_notify send`) sent at most in a minute.
    pub list_per_minute: u32,
}

impl Default for Mail {
    fn default() -> Mail {
        Mail {
            host: "mail.vhrd.tech".into(),
            port: 465,
            tls: MailTls::Implicit,
            user: "notify-sender@vhrd.tech".into(),
            password_file: "smtp-password".into(),
            from: "donguru@vhrd.tech".into(),
            from_name: "VHRD".into(),
            hello: "vhrd.tech".into(),
            timeout_secs: 30,
            per_hour: 60,
            per_day: 300,
            list_per_minute: 20,
        }
    }
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
            rate_limit_network_day: 40,
            rate_window_secs: 3600,
            link_rate_limit: 20,
            link_rate_limit_network: 100,
            one_click_rate_limit: 2000,
            rate_clients: 10_000,
            max_signups: 50_000,
            pending_days: 7,
            resend_hours: 24,
            max_confirm_mails: 3,
            max_pending: 5000,
            retry_secs: vec![60, 300, 1800, 7200, 21600],
            max_intake_bytes: 1 << 20,
            client_ip_header: "x-real-ip".into(),
            token_key: "token-key".into(),
            titles: BTreeMap::from([("donguru".into(), "Donguru".into())]),
            mail: None,
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
        if let Some(dir) = path.parent() {
            for p in [
                Some(&mut c.store),
                Some(&mut c.token_key),
                c.mail.as_mut().map(|m| &mut m.password_file),
            ]
            .into_iter()
            .flatten()
            {
                if p.is_relative() {
                    *p = dir.join(&*p);
                }
            }
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
        for l in &self.lists {
            if !self.titles.contains_key(l) {
                return Err(format!("titles: no title for the list {l:?}"));
            }
        }
        for t in self.titles.values() {
            if t.is_empty() || t.len() > 64 || t.chars().any(char::is_control) {
                return Err("titles: a plain name of up to 64 characters".into());
            }
        }
        if let Some(m) = &self.mail {
            if crate::Email::parse(&m.from).is_err() || m.user.is_empty() || m.user.chars().any(char::is_control) {
                return Err("mail.from: an address; mail.user: the login".into());
            }
            if m.from_name.is_empty() || !m.from_name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b' ') {
                return Err("mail.from_name: letters, digits and spaces".into());
            }
            let host_ok = |h: &str| !h.is_empty() && h.bytes().all(|b| b.is_ascii_alphanumeric() || b".-".contains(&b));
            if !host_ok(&m.host) || !host_ok(&m.hello) || m.port == 0 || m.timeout_secs == 0 {
                return Err("mail: host and hello are host names, port and timeout_secs more than 0".into());
            }
            if m.tls == MailTls::None && !m.host.parse::<std::net::IpAddr>().is_ok_and(|ip| ip.is_loopback()) {
                return Err(
                    "mail.tls = \"none\" only to a loopback address: a password never goes out in the clear".into(),
                );
            }
            if m.per_hour == 0 || m.per_day == 0 || m.list_per_minute == 0 {
                return Err("mail: per_hour, per_day and list_per_minute more than 0".into());
            }
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
        assert!(c.token_key.starts_with("/home/vhrd-notify/.config/"));
        let m = c.mail.expect("the server sends mail");
        assert_eq!(
            (m.host.as_str(), m.port, m.tls),
            ("mail.vhrd.tech", 465, MailTls::Implicit)
        );
        assert!(m.password_file.starts_with("/home/vhrd-notify/.config/"));
        assert!(c.consent_versions.contains(&"2026-11-06".to_string()));
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
        assert!(bad(|c| c.lists.push("other".into())));
        let mail = |f: fn(&mut Mail)| {
            let mut m = Mail::default();
            f(&mut m);
            let c = Config {
                mail: Some(m),
                ..Config::default()
            };
            c.check().is_err()
        };
        assert!(!mail(|_| {}));
        assert!(mail(|m| m.tls = MailTls::None));
        assert!(!mail(|m| {
            m.tls = MailTls::None;
            m.host = "127.0.0.1".into();
        }));
        assert!(mail(|m| m.from = "not an address".into()));
        assert!(mail(|m| m.from_name = "VHRD\r\nBcc: x@y.no".into()));
        assert!(mail(|m| m.host = "mail.vhrd.tech:25".into()));
    }
}
