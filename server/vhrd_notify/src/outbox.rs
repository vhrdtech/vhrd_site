//! The service's worker: folds the accepted signups into the store, deletes the expired ones, and sends the mails
//! waiting in the outbox. It runs beside the endpoint, woken by each signup and every [`SWEEP`] otherwise, so no
//! request ever waits for it.
//!
//! Sending, one mail at a time, the longest waiting first:
//!
//! - Confirmation mails go out at most `mail.per_hour` in an hour and `mail.per_day` in a day, for all addresses
//!   together; list mails at most `mail.list_per_minute` a minute. Past that they wait in the outbox: nothing is lost.
//!   The counts are in memory, so a restart starts them again; the unit's start limit bounds how often.
//! - A mail goes out at least once: the store is changed after the mail server took it, so a crash in between sends
//!   it again.
//! - Each record is read again just before its mail goes: one removed, confirmed or given another mail since the
//!   round began gets none.
//! - When the mail server can't be reached or refuses the login or the sender ([`Fail::Down`]), the round stops,
//!   no mail loses a try, and the worker waits a minute, then doubling up to half an hour. The log says it once per
//!   change.
//! - The log has counts and codes, never an address.

use std::collections::VecDeque;
use std::io;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Duration;

use crate::list::{self, Sent};
use crate::mail::{Fail, Links, Mailer};
use crate::server::App;
use crate::store::{Outbox, Record};
use crate::token::Purpose;
use crate::utc;

/// The longest the worker sleeps without a signup waking it (expiry, retries, waiting mails).
pub const SWEEP: Duration = Duration::from_secs(60);
const DOWN_FIRST: i64 = 60;
const DOWN_MAX: i64 = 1800;

/// Runs until the process ends.
pub async fn run(app: Arc<App>) {
    let mut sender = Sender::default();
    loop {
        let a = app.clone();
        match tokio::task::spawn_blocking(move || tick(&a, utc::now_secs())).await {
            Ok(Ok(())) => {}
            Ok(Err(e)) => eprintln!("vhrd_notify: store: {e}"),
            Err(e) => eprintln!("vhrd_notify: worker: {e}"),
        }
        if let Some(m) = &app.mailer {
            sender.round(&app, m).await;
        }
        tokio::select! {
            _ = app.wake.notified() => {}
            _ = tokio::time::sleep(SWEEP) => {}
        }
    }
}

/// One round: fold the intake, expire, count. Says what it did in the log, in counts only.
pub fn tick(app: &App, now: i64) -> io::Result<()> {
    let rules = app.cfg.rules();
    let (folded, expired, pending, total) = app.store.transact(|intake, st| {
        let folded = list::fold(&mut st.records, intake, &rules, crate::store::Id::random)?;
        let expired = list::expire(&mut st.records, &rules, now);
        let (pending, total) = (list::pending(&st.records), st.records.len());
        let changed = folded.new + folded.queued_again > 0 || expired > 0;
        Ok((changed, (folded, expired, pending, total)))
    })?;
    app.pending.store(pending, Ordering::Relaxed);
    app.records.store(total, Ordering::Relaxed);
    if folded.new > 0 || folded.queued_again > 0 || folded.held > 0 {
        eprintln!(
            "vhrd_notify: {} new, {} confirmation mails queued again, {} held; {pending} pending, {total} in the store",
            folded.new, folded.queued_again, folded.held
        );
    }
    if expired > 0 {
        eprintln!("vhrd_notify: {expired} unconfirmed signups expired and deleted");
    }
    let max = app.cfg.max_signups;
    if folded.new > 0 && total * 5 >= max * 4 {
        eprintln!("vhrd_notify: the store is over 80 % of max_signups ({max})");
    }
    Ok(())
}

/// Changes the records under the lock, the waiting signups folded in first (a transaction empties the intake).
/// `f` says whether it changed anything; the store is rewritten only then (or when signups were folded in).
pub fn change<R>(app: &App, f: impl FnOnce(&mut Vec<Record>) -> (bool, R)) -> io::Result<R> {
    let rules = app.cfg.rules();
    app.store.transact(|intake, st| {
        list::fold(&mut st.records, intake, &rules, crate::store::Id::random)?;
        Ok(f(&mut st.records))
    })
}

/// The file `vhrd_notify send` writes a list mail's subject and text to, beside the store.
pub fn list_text_path(store: &std::path::Path, name: &str) -> PathBuf {
    let mut p = store.as_os_str().to_owned();
    p.push(format!(".mail-{name}"));
    PathBuf::from(p)
}

/// The sending side's memory: what went out lately, and whether the mail server is down.
#[derive(Default)]
struct Sender {
    confirms: VecDeque<i64>,
    lists: VecDeque<i64>,
    down_until: i64,
    down_pause: i64,
    /// The last thing said about the mail server being down, or waiting mails: said once, not every round.
    said: Option<String>,
}

impl Sender {
    fn say(&mut self, what: String) {
        if self.said.as_ref() != Some(&what) {
            eprintln!("vhrd_notify: {what}");
            self.said = Some(what);
        }
    }

    fn room(&mut self, kind: &Outbox, m: &crate::config::Mail, now: i64) -> bool {
        self.confirms.retain(|t| now - t < 86400);
        self.lists.retain(|t| now - t < 60);
        match kind {
            Outbox::Confirm => {
                let hour = self.confirms.iter().filter(|t| now - **t < 3600).count();
                hour < m.per_hour as usize && self.confirms.len() < m.per_day as usize
            }
            Outbox::Launch(_) => self.lists.len() < m.list_per_minute as usize,
        }
    }

    async fn round(&mut self, app: &Arc<App>, m: &Mailer) {
        let mcfg = app.cfg.mail.as_ref().expect("a mailer has its settings");
        let now = utc::now_secs();
        if now < self.down_until {
            return;
        }
        let a = app.clone();
        let records = match tokio::task::spawn_blocking(move || a.store.read()).await {
            Ok(Ok(r)) => r,
            Ok(Err(e)) => return eprintln!("vhrd_notify: store: {e}"),
            Err(e) => return eprintln!("vhrd_notify: worker: {e}"),
        };
        let due = list::due(&records, now);
        let mut waiting = 0;
        for (id, kind) in due {
            let now = utc::now_secs();
            if !self.room(&kind, mcfg, now) {
                waiting += 1;
                continue;
            }
            // the record as it is now, not as the round found it: removed, confirmed or changed meanwhile, it gets
            // no mail
            let a = app.clone();
            let r = match tokio::task::spawn_blocking(move || a.store.read()).await {
                Ok(Ok(rs)) => rs
                    .into_iter()
                    .find(|r| r.id == id && r.outbox.as_ref() == Some(&kind) && r.next_try <= now),
                Ok(Err(e)) => return eprintln!("vhrd_notify: store: {e}"),
                Err(e) => return eprintln!("vhrd_notify: worker: {e}"),
            };
            let Some(r) = r else {
                continue;
            };
            let r = &r;
            let message = match compose(app, m, r, &kind) {
                Ok(msg) => msg,
                Err(e) => {
                    eprintln!("vhrd_notify: a mail could not be composed, given up: {e}");
                    self.book(app, id, kind, Sent::Failed).await;
                    continue;
                }
            };
            match &kind {
                Outbox::Confirm => self.confirms.push_back(now),
                Outbox::Launch(_) => self.lists.push_back(now),
            }
            let how = match m.send(&r.email, &message).await {
                Ok(()) => Sent::Ok,
                Err(Fail::Down(why)) => {
                    self.down_pause = (self.down_pause * 2).clamp(DOWN_FIRST, DOWN_MAX);
                    self.down_until = now + self.down_pause;
                    self.say(format!(
                        "mail server not taking mail ({why}); next try in {} s, no mail loses a try",
                        self.down_pause
                    ));
                    return;
                }
                Err(Fail::Later(c)) => {
                    eprintln!("vhrd_notify: a mail was put off ({c}), tried again later");
                    Sent::Later
                }
                Err(Fail::NoSuchAddress(c)) => {
                    eprintln!("vhrd_notify: the mail server says an address does not exist ({c})");
                    Sent::Never
                }
                Err(Fail::Refused(c)) => {
                    eprintln!("vhrd_notify: a mail was refused for good ({c}), given up");
                    Sent::Failed
                }
            };
            self.down_pause = 0;
            if self.said.as_deref().is_some_and(|s| s.starts_with("mail server")) {
                self.say("mail server takes mail again".into());
            }
            self.book(app, id, kind, how).await;
        }
        if waiting > 0 {
            self.say(format!(
                "{waiting} mails wait for the hourly, daily or per-minute limit"
            ));
        }
    }

    async fn book(&mut self, app: &Arc<App>, id: crate::store::Id, kind: Outbox, how: Sent) {
        let a = app.clone();
        let rules = app.cfg.rules();
        let r = tokio::task::spawn_blocking(move || {
            change(&a, |rs| (true, list::sent(rs, id, &kind, how, &rules, utc::now_secs())))
        })
        .await;
        match r {
            Ok(Ok(list::After::Done)) => eprintln!("vhrd_notify: a mail went out"),
            Ok(Ok(list::After::Deleted)) => eprintln!("vhrd_notify: its record is deleted"),
            Ok(Ok(list::After::GivenUp)) => eprintln!("vhrd_notify: a mail is given up after its last try"),
            Ok(Ok(_)) => {}
            Ok(Err(e)) => eprintln!("vhrd_notify: store: {e}"),
            Err(e) => eprintln!("vhrd_notify: worker: {e}"),
        }
    }
}

/// The links of record `r`.
pub fn links(app: &App, r: &Record) -> Links {
    let origin = &app.cfg.site_origin;
    let remove = app.key.make(Purpose::Remove, &r.id, &r.nonce);
    Links {
        list: r.list.clone(),
        title: app.cfg.titles.get(&r.list).cloned().unwrap_or_else(|| r.list.clone()),
        confirm: format!(
            "{origin}/notify/confirm/#{}",
            app.key.make(Purpose::Confirm, &r.id, &r.nonce)
        ),
        remove: format!("{origin}/notify/remove/#{remove}"),
        one_click: format!("{origin}/api/notify/unsubscribe?t={remove}"),
        privacy: format!("{origin}/privacy/"),
        days: app.cfg.pending_days,
    }
}

fn compose(app: &App, m: &Mailer, r: &Record, kind: &Outbox) -> Result<Vec<u8>, String> {
    let links = links(app, r);
    match kind {
        Outbox::Confirm => m.confirm_mail(&r.email, &links),
        Outbox::Launch(name) => {
            let path = list_text_path(&app.cfg.store, name);
            let text = std::fs::read_to_string(&path).map_err(|e| format!("{}: {e}", path.display()))?;
            let (subject, body) = text
                .split_once('\n')
                .ok_or("a list mail: subject line, then the text")?;
            m.list_mail(&r.email, subject, body, &links)
        }
    }
}
