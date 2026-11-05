//! Mail out: composing our two kinds of mail and handing one to the mail server over SMTP submission.
//!
//! - The confirmation mail (`mail/confirm.txt`, compiled in) carries the confirm link and the remove link, and
//!   `Auto-Submitted: auto-generated`.
//! - A list mail (`vhrd_notify send`) carries the remove link and the one-click unsubscribe of RFC 8058:
//!   `List-Unsubscribe` with an https URL and a mailto, and `List-Unsubscribe-Post: List-Unsubscribe=One-Click`.
//!
//! No text a visitor wrote goes into a mail: the address only in To and the envelope, everything else is ours.
//!
//! The connection is TLS from the first byte (port 465) through rustls with graviola's crypto. MAIL, RCPT and DATA
//! go one by one, so an answer can be told apart by the command it came for: only a 550, 551 or 553 to RCPT says
//! the address does not exist. A failure before RCPT (no connection, TLS, the login, the sender refused) is the mail
//! server's or ours and says nothing about the address: [`Fail::Down`]. The log gets codes, never the server's text,
//! which can quote the address.

use std::time::Duration;

use lettre::message::header::{ContentTransferEncoding, ContentType, HeaderName, HeaderValue};
use lettre::message::{Body, Mailbox, Message};
use lettre::transport::smtp::authentication::{Credentials, Mechanism};
use lettre::transport::smtp::client::{AsyncSmtpConnection, TlsParameters};
use lettre::transport::smtp::commands::{Data, Mail as MailCmd, Rcpt};
use lettre::transport::smtp::extension::ClientId;

use crate::config::{Mail, MailTls};
use crate::email::Email;
use crate::token::read_secret;

const CONFIRM: &str = include_str!("../mail/confirm.txt");

/// Why a mail did not go out.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Fail {
    /// Nothing to do with this address: no connection, TLS, the login, the sender refused. The worker stops the
    /// round and waits; the mail keeps its tries.
    Down(String),
    /// A 4xx for this mail: try it again later.
    Later(u16),
    /// The mail server says the address does not exist (550, 551 or 553 to RCPT).
    NoSuchAddress(u16),
    /// Another 5xx for this mail: it will never go.
    Refused(u16),
}

pub struct Mailer {
    cfg: Mail,
    password: String,
    tls: Option<TlsParameters>,
}

impl std::fmt::Debug for Mailer {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Mailer({}@{}:{})", self.cfg.user, self.cfg.host, self.cfg.port)
    }
}

/// The CPU features graviola needs on x86_64: without them it would fail at the first mail, so the start fails
/// instead.
#[cfg(target_arch = "x86_64")]
fn cpu_check() -> Result<(), String> {
    let missing: Vec<&str> = [
        ("aes", std::arch::is_x86_feature_detected!("aes")),
        ("ssse3", std::arch::is_x86_feature_detected!("ssse3")),
        ("avx", std::arch::is_x86_feature_detected!("avx")),
        ("avx2", std::arch::is_x86_feature_detected!("avx2")),
        ("adx", std::arch::is_x86_feature_detected!("adx")),
        ("bmi2", std::arch::is_x86_feature_detected!("bmi2")),
        ("pclmulqdq", std::arch::is_x86_feature_detected!("pclmulqdq")),
    ]
    .into_iter()
    .filter_map(|(n, ok)| (!ok).then_some(n))
    .collect();
    if missing.is_empty() {
        Ok(())
    } else {
        Err(format!(
            "this CPU lacks {} that graviola's TLS crypto needs",
            missing.join(", ")
        ))
    }
}

#[cfg(not(target_arch = "x86_64"))]
fn cpu_check() -> Result<(), String> {
    Ok(())
}

impl Mailer {
    /// Reads the password and readies TLS. Fails (the service then exits 78) when the password file is missing,
    /// readable by others or empty, or the CPU can't run the TLS crypto.
    pub fn new(cfg: &Mail) -> Result<Mailer, String> {
        let password = read_secret(&cfg.password_file).map_err(|e| format!("mail.password_file: {e}"))?;
        let tls = match cfg.tls {
            MailTls::Implicit => {
                cpu_check()?;
                // a second Mailer in one process finds the provider there already
                let _ = rustls_graviola::default_provider().install_default();
                Some(
                    TlsParameters::builder(cfg.host.clone())
                        .build_rustls()
                        .map_err(|e| format!("mail: TLS: {e}"))?,
                )
            }
            MailTls::None => None,
        };
        Ok(Mailer {
            cfg: cfg.clone(),
            password,
            tls,
        })
    }

    pub fn from(&self) -> Email {
        Email::parse(&self.cfg.from).expect("checked by Config::check")
    }

    /// Sends one composed mail to `to`.
    pub async fn send(&self, to: &Email, message: &[u8]) -> Result<(), Fail> {
        let timeout = Duration::from_secs(self.cfg.timeout_secs);
        match tokio::time::timeout(timeout, self.send_inner(to, message, timeout)).await {
            Ok(r) => r,
            Err(_) => Err(Fail::Down("timed out".into())),
        }
    }

    async fn send_inner(&self, to: &Email, message: &[u8], timeout: Duration) -> Result<(), Fail> {
        let down = |what: &str, e: lettre::transport::smtp::Error| Fail::Down(format!("{what}: {}", describe(&e)));
        let mut conn = AsyncSmtpConnection::connect_tokio1(
            (self.cfg.host.as_str(), self.cfg.port),
            Some(timeout),
            &ClientId::Domain(self.cfg.hello.clone()),
            self.tls.clone(),
            None,
        )
        .await
        .map_err(|e| down("connect", e))?;
        let creds = Credentials::new(self.cfg.user.clone(), self.password.clone());
        conn.auth(&[Mechanism::Plain], &creds)
            .await
            .map_err(|e| down("login", e))?;
        let from =
            lettre::Address::new(user(&self.from()), domain(&self.from())).map_err(|_| Fail::Down("from".into()))?;
        let rcpt = lettre::Address::new(user(to), domain(to)).map_err(|_| Fail::Refused(0))?;
        conn.command(MailCmd::new(Some(from), vec![]))
            .await
            .map_err(|e| down("sender", e))?;
        let result = async {
            conn.command(Rcpt::new(rcpt, vec![]))
                .await
                .map_err(|e| match code(&e) {
                    Some(c @ (550 | 551 | 553)) => Fail::NoSuchAddress(c),
                    Some(c) if c >= 500 => Fail::Refused(c),
                    Some(c) => Fail::Later(c),
                    None => Fail::Down(format!("recipient: {}", describe(&e))),
                })?;
            conn.command(Data).await.map_err(per_mail)?;
            conn.message(message).await.map_err(per_mail)?;
            Ok(())
        }
        .await;
        let _ = conn.quit().await;
        result
    }

    /// The confirmation mail, ready to send.
    pub fn confirm_mail(&self, to: &Email, links: &Links) -> Result<Vec<u8>, String> {
        let text = fill(CONFIRM, links);
        let (subject, body) = text
            .split_once('\n')
            .ok_or("confirm.txt: subject line, then the text")?;
        self.compose(to, subject, body, &[("Auto-Submitted", "auto-generated".into())])
    }

    /// A list mail, with the remove link filled in and the one-click unsubscribe headers.
    pub fn list_mail(&self, to: &Email, subject: &str, text: &str, links: &Links) -> Result<Vec<u8>, String> {
        let body = fill(text, links);
        let list_id = format!("{} <{}.vhrd.tech>", links.title, links.list);
        let unsubscribe = format!("<{}>, <mailto:{}?subject=unsubscribe>", links.one_click, self.cfg.from);
        self.compose(
            to,
            subject,
            &body,
            &[
                ("List-Id", list_id),
                ("List-Unsubscribe", unsubscribe),
                ("List-Unsubscribe-Post", "List-Unsubscribe=One-Click".into()),
            ],
        )
    }

    fn compose(
        &self,
        to: &Email,
        subject: &str,
        body: &str,
        extra: &[(&'static str, String)],
    ) -> Result<Vec<u8>, String> {
        let from: Mailbox = format!("{} <{}>", self.cfg.from_name, self.cfg.from)
            .parse()
            .map_err(|e| format!("mail.from: {e}"))?;
        let to: Mailbox = to.as_str().parse().map_err(|e| format!("to: {e}"))?;
        let mut id = [0u8; 16];
        getrandom::fill(&mut id).map_err(|e| format!("random: {e}"))?;
        let id: String = id.iter().map(|b| format!("{b:02x}")).collect();
        let sender = self.from();
        let domain = domain(&sender);
        let mut b = Message::builder()
            .from(from)
            .to(to)
            .subject(subject)
            .date_now()
            .message_id(Some(format!("<{id}@{domain}>")))
            .header(ContentType::TEXT_PLAIN);
        for (name, value) in extra {
            b = b.raw_header(HeaderValue::new(HeaderName::new_from_ascii_str(name), value.clone()));
        }
        let body = plain_body(body)?;
        let m = b.body(body).map_err(|e| format!("compose: {e}"))?;
        Ok(m.formatted())
    }
}

/// What the placeholders of a mail text are filled with.
pub struct Links {
    pub list: String,
    pub title: String,
    pub confirm: String,
    pub remove: String,
    /// The RFC 8058 URL, the remove token in its query.
    pub one_click: String,
    pub privacy: String,
    pub days: u32,
}

/// The text as a 7bit body (8bit when it is not ASCII), never quoted-printable, which would break a link over two
/// lines in the raw mail. RFC 5322 allows lines up to 998 characters; CRLF line ends, no NUL.
fn plain_body(text: &str) -> Result<Body, String> {
    let text = text.replace("\r\n", "\n").replace('\r', "\n");
    let mut out = String::with_capacity(text.len() + text.len() / 32);
    for line in text.lines() {
        if line.len() > 998 || line.contains('\0') {
            return Err("a line over 998 characters, or a NUL".into());
        }
        out.push_str(line);
        out.push_str("\r\n");
    }
    let encoding = if out.is_ascii() {
        ContentTransferEncoding::SevenBit
    } else {
        ContentTransferEncoding::EightBit
    };
    Ok(Body::dangerous_pre_encoded(out.into_bytes(), encoding))
}

fn fill(text: &str, l: &Links) -> String {
    text.replace("{title}", &l.title)
        .replace("{confirm}", &l.confirm)
        .replace("{remove}", &l.remove)
        .replace("{privacy}", &l.privacy)
        .replace("{days}", &l.days.to_string())
}

fn per_mail(e: lettre::transport::smtp::Error) -> Fail {
    match code(&e) {
        Some(c) if c >= 500 => Fail::Refused(c),
        Some(c) => Fail::Later(c),
        None => Fail::Down(format!("data: {}", describe(&e))),
    }
}

fn code(e: &lettre::transport::smtp::Error) -> Option<u16> {
    let c = e.status()?;
    let s = format!("{c}");
    s.parse().ok()
}

/// An error for the log: the code when the server answered (its text can quote the address), else the kind.
fn describe(e: &lettre::transport::smtp::Error) -> String {
    match code(e) {
        Some(c) => format!("the server answered {c}"),
        None if e.is_timeout() => "timed out".into(),
        None if e.is_tls() => "TLS failed".into(),
        None => {
            let s = e.to_string();
            // an io or client error names no address; still cut it short
            s.chars().take(120).collect()
        }
    }
}

fn user(e: &Email) -> &str {
    e.as_str().split_once('@').expect("an Email has one @").0
}

fn domain(e: &Email) -> &str {
    e.as_str().split_once('@').expect("an Email has one @").1
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mailer() -> Mailer {
        Mailer {
            cfg: Mail::default(),
            password: "x".into(),
            tls: None,
        }
    }

    fn links() -> Links {
        Links {
            list: "donguru".into(),
            title: "Donguru".into(),
            confirm: "https://vhrd.tech/notify/confirm/#CCC".into(),
            remove: "https://vhrd.tech/notify/remove/#RRR".into(),
            one_click: "https://vhrd.tech/api/notify/unsubscribe?t=RRR".into(),
            privacy: "https://vhrd.tech/privacy/".into(),
            days: 7,
        }
    }

    #[test]
    fn the_confirmation_mail() {
        let to = Email::parse("someone@example.com").unwrap();
        let m = String::from_utf8(mailer().confirm_mail(&to, &links()).unwrap()).unwrap();
        for want in [
            "From: VHRD <donguru@vhrd.tech>\r\n",
            "To: someone@example.com\r\n",
            "Subject: Confirm your Donguru signup\r\n",
            "Auto-Submitted: auto-generated\r\n",
            "Content-Type: text/plain; charset=utf-8\r\n",
            "https://vhrd.tech/notify/confirm/#CCC",
            "https://vhrd.tech/notify/remove/#RRR",
            "deleted in 7 days",
        ] {
            assert!(m.contains(want), "{want:?} not in\n{m}");
        }
        assert!(m.contains("Message-ID: <") && m.contains("@vhrd.tech>\r\n"), "{m}");
        assert!(!m.contains('{'), "a placeholder left: {m}");
        assert!(m.contains("Content-Transfer-Encoding: 7bit\r\n"), "{m}");
    }

    #[test]
    fn a_list_mail_has_the_one_click_headers() {
        let to = Email::parse("someone@example.com").unwrap();
        let m = mailer()
            .list_mail(
                &to,
                "Donguru is live",
                "It's here.\n\nLeave the list: {remove}\n",
                &links(),
            )
            .unwrap();
        // long headers are folded onto a second line; unfolded, they read as one
        let m = String::from_utf8(m).unwrap().replace("\r\n ", " ");
        for want in [
            "List-Unsubscribe: <https://vhrd.tech/api/notify/unsubscribe?t=RRR>, <mailto:donguru@vhrd.tech?subject=unsubscribe>\r\n",
            "List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n",
            "List-Id: Donguru <donguru.vhrd.tech>\r\n",
            "Leave the list: https://vhrd.tech/notify/remove/#RRR",
        ] {
            assert!(m.contains(want), "{want:?} not in\n{m}");
        }
        assert!(!m.contains("Auto-Submitted"));
    }
}
