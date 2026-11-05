//! Double opt-in end to end, over real sockets: the service as `vhrd_notify serve` runs it (endpoint and worker),
//! and a small SMTP server in the test that takes the mails. A signup gets one mail; its confirm link confirms only
//! through the button's POST; only confirmed records export; the remove link and the one-click unsubscribe delete
//! the address.

use std::net::SocketAddr;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use vhrd_notify::config::{Mail, MailTls};
use vhrd_notify::store::{Record, Status};
use vhrd_notify::{Config, Store};

/// One mail the fake server took: the RCPT address and the message.
#[derive(Clone, Debug)]
struct Got {
    to: String,
    data: String,
}

/// How the fake server answers.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Mode {
    Take,
    /// 535 to AUTH: the login is wrong.
    BadLogin,
}

/// An SMTP server on loopback: AUTH PLAIN, then MAIL, RCPT, DATA. A recipient starting with `nosuch` gets 550,
/// one starting with `later` gets 451.
async fn smtp(mode: Mode) -> (u16, Arc<Mutex<Vec<Got>>>, Arc<AtomicU32>) {
    let l = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = l.local_addr().unwrap().port();
    let got = Arc::new(Mutex::new(Vec::new()));
    let logins = Arc::new(AtomicU32::new(0));
    let (g, n) = (got.clone(), logins.clone());
    tokio::spawn(async move {
        loop {
            let (s, _) = l.accept().await.unwrap();
            let (g, n) = (g.clone(), n.clone());
            tokio::spawn(async move {
                let (r, mut w) = s.into_split();
                let mut r = BufReader::new(r);
                w.write_all(b"220 fake ESMTP\r\n").await.unwrap();
                let mut to = String::new();
                let mut line = String::new();
                loop {
                    line.clear();
                    if r.read_line(&mut line).await.unwrap() == 0 {
                        return;
                    }
                    let cmd = line.trim_end().to_ascii_uppercase();
                    let answer: &[u8] = if cmd.starts_with("EHLO") {
                        b"250-fake\r\n250 AUTH PLAIN\r\n"
                    } else if cmd.starts_with("AUTH PLAIN") {
                        n.fetch_add(1, Ordering::Relaxed);
                        if mode == Mode::BadLogin {
                            b"535 5.7.8 no\r\n"
                        } else {
                            b"235 ok\r\n"
                        }
                    } else if cmd.starts_with("MAIL FROM") {
                        b"250 ok\r\n"
                    } else if cmd.starts_with("RCPT TO") {
                        to = line.trim_end()[9..].trim_matches(['<', '>', ' ']).to_owned();
                        if to.starts_with("nosuch") {
                            b"550 5.1.1 no such user\r\n"
                        } else if to.starts_with("later") {
                            b"451 4.3.0 later\r\n"
                        } else {
                            b"250 ok\r\n"
                        }
                    } else if cmd == "DATA" {
                        w.write_all(b"354 go\r\n").await.unwrap();
                        let mut data = String::new();
                        loop {
                            line.clear();
                            r.read_line(&mut line).await.unwrap();
                            if line == ".\r\n" {
                                break;
                            }
                            data.push_str(&line);
                        }
                        g.lock().unwrap().push(Got { to: to.clone(), data });
                        b"250 queued\r\n"
                    } else if cmd == "QUIT" {
                        w.write_all(b"221 bye\r\n").await.unwrap();
                        return;
                    } else {
                        b"500 what\r\n"
                    };
                    w.write_all(answer).await.unwrap();
                }
            });
        }
    });
    (port, got, logins)
}

fn temp_dir() -> PathBuf {
    static N: AtomicU32 = AtomicU32::new(0);
    let dir = std::env::temp_dir().join(format!(
        "vhrd_notify-optin-{}-{}",
        std::process::id(),
        N.fetch_add(1, Ordering::Relaxed)
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

/// The service with its mail going to the fake server on `smtp_port`; returns its address and settings.
async fn service(dir: &Path, smtp_port: u16) -> (SocketAddr, Config) {
    let pw = dir.join("smtp-password");
    std::fs::write(&pw, "secret-for-the-test\n").unwrap();
    std::fs::set_permissions(&pw, std::fs::Permissions::from_mode(0o600)).unwrap();
    let port = {
        let l = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        l.local_addr().unwrap().port()
    };
    let cfg = Config {
        listen: format!("127.0.0.1:{port}"),
        store: dir.join("signups.tsv"),
        token_key: dir.join("token-key"),
        client_ip_header: String::new(),
        consent_versions: vec!["2026-11-06".into()],
        retry_secs: vec![1, 1],
        link_rate_limit: 10,
        mail: Some(Mail {
            host: "127.0.0.1".into(),
            port: smtp_port,
            tls: MailTls::None,
            user: "notify-sender@vhrd.tech".into(),
            password_file: pw,
            timeout_secs: 5,
            ..Mail::default()
        }),
        ..Config::default()
    };
    let c = cfg.clone();
    tokio::spawn(async move { vhrd_notify::server::serve(c, "test").await.unwrap() });
    let addr: SocketAddr = cfg.listen.parse().unwrap();
    for _ in 0..200 {
        if tokio::net::TcpStream::connect(addr).await.is_ok() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    (addr, cfg)
}

/// One raw HTTP/1.1 request; the status line and the headers and body as text.
async fn http(addr: SocketAddr, method: &str, path: &str, headers: &[(&str, &str)], body: &str) -> String {
    let mut s = tokio::net::TcpStream::connect(addr).await.unwrap();
    let mut req = format!("{method} {path} HTTP/1.1\r\nHost: vhrd.tech\r\nConnection: close\r\n");
    for (k, v) in headers {
        req.push_str(&format!("{k}: {v}\r\n"));
    }
    req.push_str(&format!("Content-Length: {}\r\n\r\n{body}", body.len()));
    s.write_all(req.as_bytes()).await.unwrap();
    let mut out = String::new();
    s.read_to_string(&mut out).await.unwrap();
    out
}

const FORM: (&str, &str) = ("Content-Type", "application/x-www-form-urlencoded");
const JSON: (&str, &str) = ("Accept", "application/json");

async fn signup(addr: SocketAddr, email: &str) -> String {
    let body = format!(
        "email={}&list=donguru&consent=2026-11-06&from=donguru&leave_empty=",
        email.replace('@', "%40")
    );
    http(
        addr,
        "POST",
        "/api/notify",
        &[FORM, JSON, ("Origin", "https://vhrd.tech")],
        &body,
    )
    .await
}

/// Waits until `f` holds, up to 10 s.
async fn until(what: &str, mut f: impl FnMut() -> bool) {
    for _ in 0..1000 {
        if f() {
            return;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    panic!("timed out waiting for {what}");
}

fn records(cfg: &Config) -> Vec<Record> {
    Store::new(&cfg.store).read().unwrap()
}

/// The token after `marker` in a mail.
fn token_after(mail: &str, marker: &str) -> String {
    let at = mail.find(marker).unwrap_or_else(|| panic!("{marker} not in\n{mail}")) + marker.len();
    mail[at..]
        .chars()
        .take_while(|c| c.is_ascii_alphanumeric() || *c == '-' || *c == '_')
        .collect()
}

#[tokio::test]
async fn sign_up_confirm_export_remove() {
    let dir = temp_dir();
    let (smtp_port, got, _) = smtp(Mode::Take).await;
    let (addr, cfg) = service(&dir, smtp_port).await;

    // a signup: the answer at once, then one mail
    let r = signup(addr, "someone@example.com").await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    until("the confirmation mail", || got.lock().unwrap().len() == 1).await;
    let mail = got.lock().unwrap()[0].clone();
    assert_eq!(mail.to, "someone@example.com");
    assert!(
        mail.data.contains("Subject: Confirm your Donguru signup"),
        "{}",
        mail.data
    );
    let confirm = token_after(&mail.data, "https://vhrd.tech/notify/confirm/#");
    let remove = token_after(&mail.data, "https://vhrd.tech/notify/remove/#");
    assert_eq!((confirm.len(), remove.len()), (44, 44));
    until("the mail booked", || {
        records(&cfg)
            .first()
            .is_some_and(|r| r.mails == 1 && r.outbox.is_none())
    })
    .await;
    assert_eq!(records(&cfg)[0].status, Status::Pending);

    // the same address again within the day: no second mail
    assert!(signup(addr, "someone@example.com").await.starts_with("HTTP/1.1 200"));
    until("the second signup folded", || {
        std::fs::read_to_string(dir.join("signups.tsv.intake"))
            .unwrap_or_default()
            .is_empty()
    })
    .await;
    tokio::time::sleep(Duration::from_millis(300)).await;
    assert_eq!(got.lock().unwrap().len(), 1);

    // a GET of the link's API acts on nothing
    let page = http(addr, "GET", &format!("/api/notify/unsubscribe?t={remove}"), &[], "").await;
    assert!(page.starts_with("HTTP/1.1 303"), "{page}");
    assert!(
        page.contains(&format!("location: https://vhrd.tech/notify/remove/#{remove}\r\n")),
        "{page}"
    );
    let get = http(addr, "GET", &format!("/api/notify/confirm?token={confirm}"), &[], "").await;
    assert!(get.starts_with("HTTP/1.1 405"), "{get}");
    assert_eq!(records(&cfg)[0].status, Status::Pending);

    // a token that is not ours, and a remove token on the confirm button: 404, nothing changes
    let bad = format!("token={}&from=confirm", "A".repeat(44));
    let r = http(addr, "POST", "/api/notify/confirm", &[FORM, JSON], &bad).await;
    assert!(r.starts_with("HTTP/1.1 404"), "{r}");
    let wrong = format!("token={remove}&from=confirm");
    let r = http(addr, "POST", "/api/notify/confirm", &[FORM, JSON], &wrong).await;
    assert!(r.starts_with("HTTP/1.1 404"), "{r}");
    assert_eq!(records(&cfg)[0].status, Status::Pending);

    // the button: confirmed, and a second press says done too
    let press = format!("token={confirm}&from=confirm");
    let r = http(
        addr,
        "POST",
        "/api/notify/confirm",
        &[FORM, JSON, ("Origin", "https://vhrd.tech")],
        &press,
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    let r = http(addr, "POST", "/api/notify/confirm", &[FORM], &press).await;
    assert!(r.starts_with("HTTP/1.1 303"), "{r}");
    assert!(
        r.contains("location: https://vhrd.tech/notify/confirm/#notify-done\r\n"),
        "{r}"
    );
    let rs = records(&cfg);
    assert_eq!(rs[0].status, Status::Confirmed);
    assert!(rs[0].confirmed.is_some());

    // a confirmed address signs up again: no mail
    assert!(signup(addr, "someone@example.com").await.starts_with("HTTP/1.1 200"));
    // an unconfirmed one beside it
    assert!(signup(addr, "other@example.com").await.starts_with("HTTP/1.1 200"));
    until("the other mail", || got.lock().unwrap().len() == 2).await;
    assert_eq!(got.lock().unwrap()[1].to, "other@example.com");

    // one confirmed, one pending (the CLI's export of confirmed records only: vhrd_notify_cli's tests)
    let confirmed: Vec<_> = records(&cfg)
        .into_iter()
        .filter(|r| r.status == Status::Confirmed)
        .collect();
    assert_eq!(confirmed.len(), 1);

    // the remove button deletes the address; again: done, nothing left
    let r = http(
        addr,
        "POST",
        "/api/notify/remove",
        &[FORM, JSON, ("Origin", "https://vhrd.tech")],
        &format!("token={remove}&from=remove"),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    let r = http(
        addr,
        "POST",
        "/api/notify/remove",
        &[FORM, JSON],
        &format!("token={remove}&from=remove"),
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    let left: Vec<String> = records(&cfg).iter().map(|r| r.email.to_string()).collect();
    assert_eq!(left, ["other@example.com"]);
    let text = std::fs::read_to_string(&cfg.store).unwrap();
    assert!(!text.contains("someone@example.com"), "{text}");

    // the other one leaves by the one-click unsubscribe of RFC 8058, as a mail provider sends it
    let other = got.lock().unwrap()[1].data.clone();
    let t = token_after(&other, "https://vhrd.tech/notify/remove/#");
    let r = http(
        addr,
        "POST",
        &format!("/api/notify/unsubscribe?t={t}"),
        &[("Content-Type", "multipart/form-data; boundary=x")],
        "--x\r\nContent-Disposition: form-data; name=\"List-Unsubscribe\"\r\n\r\nOne-Click\r\n--x--\r\n",
    )
    .await;
    assert!(r.starts_with("HTTP/1.1 200"), "{r}");
    assert!(records(&cfg).is_empty());

    // the buttons' own limit: 10 a client, then 429 (the one-click has a far higher one)
    let mut last = String::new();
    for _ in 0..5 {
        last = http(
            addr,
            "POST",
            "/api/notify/remove",
            &[FORM, JSON],
            &format!("token={t}&from=remove"),
        )
        .await;
    }
    assert!(last.starts_with("HTTP/1.1 429"), "{last}");
    std::fs::remove_dir_all(dir).unwrap();
}

#[tokio::test]
async fn the_mail_servers_answers() {
    let dir = temp_dir();
    let (smtp_port, got, _) = smtp(Mode::Take).await;
    let (addr, cfg) = service(&dir, smtp_port).await;
    // no such address: the pending record goes
    assert!(signup(addr, "nosuch@example.com").await.starts_with("HTTP/1.1 200"));
    // a 451: kept, tried again (retry_secs 1, 1), then given up
    assert!(signup(addr, "later@example.com").await.starts_with("HTTP/1.1 200"));
    until("both handled", || {
        let rs = records(&cfg);
        rs.len() == 1 && rs[0].email.as_str() == "later@example.com" && rs[0].attempts >= 1
    })
    .await;
    assert!(got.lock().unwrap().is_empty());
    std::fs::remove_dir_all(dir).unwrap();
}

#[tokio::test]
async fn a_refused_login_costs_no_mail_a_try() {
    let dir = temp_dir();
    let (smtp_port, got, logins) = smtp(Mode::BadLogin).await;
    let (addr, cfg) = service(&dir, smtp_port).await;
    assert!(signup(addr, "someone@example.com").await.starts_with("HTTP/1.1 200"));
    until("the login tried", || logins.load(Ordering::Relaxed) >= 1).await;
    tokio::time::sleep(Duration::from_millis(200)).await;
    let rs = records(&cfg);
    assert_eq!((rs.len(), rs[0].attempts, rs[0].outbox.is_some()), (1, 0, true));
    assert!(got.lock().unwrap().is_empty());
    std::fs::remove_dir_all(dir).unwrap();
}
