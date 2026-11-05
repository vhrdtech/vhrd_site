//! The signups on disk: two plain text files outside the web root, both mode 0600.
//!
//! - **The intake** (`<store>.intake`): one line per signup the form accepted, appended and fsynced before the visitor
//!   hears anything, the same work for every address. Time (UTC), list, address, consent version:
//!
//!   ```text
//!   2026-11-05T14:03:09Z<TAB>donguru<TAB>someone@example.com<TAB>2026-11-06
//!   ```
//!
//!   A last line without its newline is a write that never finished: reads leave it out.
//! - **The state** (`<store>`, `signups.tsv`): one [`Record`] per address and list, after a header line naming the
//!   format. It is only ever rewritten whole: the new content goes to a temporary file, is fsynced and renamed over
//!   the old one, and the folder is fsynced. A [`Store::transact`] folds the intake into it first and empties the
//!   intake after the rename, so a crash in between folds the same lines again, which changes nothing the second
//!   time ([`crate::list`]).
//!
//! A state file without the header is the first release's format (time, list, address, consent per line): it is read
//! as records waiting for their confirmation mail, and the next rewrite stores them in the new format. The first
//! release can't read the new format; after a rollback to it every signup fails (503) rather than going on the list
//! unconfirmed.
//!
//! The service and the CLI both take an exclusive lock on a lock file beside it (never on the state itself, which a
//! rewrite replaces), so a change from one never loses a change from the other.

use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};

use crate::email::Email;
use crate::utc;

/// The state file's first line.
pub const HEADER: &str = "# vhrd_notify state 2";

/// A list name or a consent version: short, plain ASCII, so it can never break a line or a column.
pub fn is_token(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 32
        && s.bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

/// One signup the form accepted, not yet folded into the state.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Intake {
    pub time: i64,
    pub list: String,
    pub email: Email,
    pub consent: String,
}

impl Intake {
    fn line(&self) -> String {
        format!(
            "{}\t{}\t{}\t{}\n",
            utc::format(self.time),
            self.list,
            self.email,
            self.consent
        )
    }

    /// Also the first release's state lines, which have the same columns.
    fn parse(line: &str) -> Option<Intake> {
        let mut f = line.split('\t');
        let i = Intake {
            time: utc::parse(f.next()?)?,
            list: token(f.next()?)?,
            email: Email::parse(f.next()?).ok()?,
            consent: token(f.next()?)?,
        };
        f.next().is_none().then_some(i)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Status {
    /// Signed up, the confirmation button not pressed yet.
    Pending,
    /// The address's owner pressed the button in our mail: on the list.
    Confirmed,
}

/// A mail waiting in the outbox for one record.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Outbox {
    /// The confirmation mail.
    Confirm,
    /// A list mail queued by `vhrd_notify send`, by its name (a [`is_token`]).
    Launch(String),
}

/// A random 128-bit value: a record's id and its nonce.
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct Id(pub [u8; 16]);

impl Id {
    pub fn random() -> io::Result<Id> {
        let mut b = [0u8; 16];
        getrandom::fill(&mut b).map_err(|e| io::Error::other(format!("random: {e}")))?;
        Ok(Id(b))
    }

    fn parse(s: &str) -> Option<Id> {
        if s.len() != 32 {
            return None;
        }
        let mut b = [0u8; 16];
        for (i, out) in b.iter_mut().enumerate() {
            *out = u8::from_str_radix(s.get(2 * i..2 * i + 2)?, 16).ok()?;
        }
        // lower case only, so a value has one spelling
        (Id(b).to_string() == s).then_some(Id(b))
    }
}

impl fmt::Display for Id {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.iter().try_for_each(|b| write!(f, "{b:02x}"))
    }
}

impl fmt::Debug for Id {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Id({self})")
    }
}

/// One address on one list.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Record {
    /// Named by the links in our mails, never the address.
    pub id: Id,
    /// Part of every link's MAC ([`crate::token`]), new for each record.
    pub nonce: Id,
    pub list: String,
    pub email: Email,
    pub status: Status,
    /// The first signup that made this record.
    pub signed_up: i64,
    /// The consent text version of the latest signup.
    pub consent: String,
    pub confirmed: Option<i64>,
    /// Mails sent to this address, of any kind.
    pub mails: u32,
    pub last_mail: Option<i64>,
    pub outbox: Option<Outbox>,
    /// Failed tries of the mail in the outbox.
    pub attempts: u32,
    /// When the mail in the outbox is tried next.
    pub next_try: i64,
}

impl Record {
    fn line(&self) -> String {
        let opt = |t: Option<i64>| t.map_or("-".into(), utc::format);
        let outbox = match &self.outbox {
            None => "-".into(),
            Some(Outbox::Confirm) => "confirm".into(),
            Some(Outbox::Launch(n)) => format!("launch:{n}"),
        };
        let status = match self.status {
            Status::Pending => "pending",
            Status::Confirmed => "confirmed",
        };
        format!(
            "{}\t{}\t{}\t{}\t{status}\t{}\t{}\t{}\t{}\t{}\t{outbox}\t{}\t{}\n",
            self.id,
            self.nonce,
            self.list,
            self.email,
            utc::format(self.signed_up),
            self.consent,
            opt(self.confirmed),
            self.mails,
            opt(self.last_mail),
            self.attempts,
            utc::format(self.next_try),
        )
    }

    fn parse(line: &str) -> Option<Record> {
        let mut f = line.split('\t');
        let mut next = || f.next();
        let opt = |s: &str| if s == "-" { Some(None) } else { utc::parse(s).map(Some) };
        let r = Record {
            id: Id::parse(next()?)?,
            nonce: Id::parse(next()?)?,
            list: token(next()?)?,
            email: Email::parse(next()?).ok()?,
            status: match next()? {
                "pending" => Status::Pending,
                "confirmed" => Status::Confirmed,
                _ => return None,
            },
            signed_up: utc::parse(next()?)?,
            consent: token(next()?)?,
            confirmed: opt(next()?)?,
            mails: next()?.parse().ok()?,
            last_mail: opt(next()?)?,
            outbox: match next()? {
                "-" => None,
                "confirm" => Some(Outbox::Confirm),
                o => Some(Outbox::Launch(token(o.strip_prefix("launch:")?)?)),
            },
            attempts: next()?.parse().ok()?,
            next_try: utc::parse(next()?)?,
        };
        if next().is_some() || (r.status == Status::Confirmed) != r.confirmed.is_some() {
            return None;
        }
        Some(r)
    }
}

fn token(s: &str) -> Option<String> {
    is_token(s).then(|| s.to_owned())
}

/// What a [`Store::transact`] hands its closure, and writes back when the closure changed it.
pub struct State {
    pub records: Vec<Record>,
    /// Records of the first release's format, read as pending ones: the state must be rewritten.
    migrated: bool,
}

pub struct Store {
    path: PathBuf,
    intake: PathBuf,
    lock: PathBuf,
}

/// Held while the files are read or changed; dropping it unlocks.
struct Guard(#[allow(dead_code)] File);

impl Store {
    pub fn new(path: impl Into<PathBuf>) -> Store {
        let path = path.into();
        let with = |ext: &str| {
            let mut p = path.clone().into_os_string();
            p.push(ext);
            PathBuf::from(p)
        };
        Store {
            intake: with(".intake"),
            lock: with(".lock"),
            path,
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    fn locked(&self) -> io::Result<Guard> {
        let f = OpenOptions::new()
            .create(true)
            .truncate(false)
            .write(true)
            .mode(0o600)
            .open(&self.lock)?;
        f.lock()?;
        Ok(Guard(f))
    }

    /// Appends one signup to the intake, unless the intake holds `max_bytes` already. Returns once the line is on
    /// disk; the work is the same whatever the address.
    pub fn accept(&self, i: &Intake, max_bytes: u64) -> io::Result<bool> {
        let _g = self.locked()?;
        let new = !self.intake.exists();
        let mut f = OpenOptions::new()
            .create(true)
            .append(true)
            .mode(0o600)
            .open(&self.intake)?;
        let len = f.metadata()?.len();
        if len >= max_bytes {
            return Ok(false);
        }
        // an unfinished last line goes first, so the new one starts on a line of its own
        let complete = complete_len(&self.intake)?;
        if len != complete {
            f.set_len(complete)?;
        }
        if let Err(e) = f.write_all(i.line().as_bytes()).and_then(|()| f.sync_all()) {
            let _ = f.set_len(complete);
            return Err(e);
        }
        if new {
            sync_dir(&self.intake)?;
        }
        Ok(true)
    }

    /// Reads the intake and the state under the lock, hands both to `f`, then writes the state back if `f` says it
    /// changed it (or the intake had lines, or old-format lines were read) and empties the intake. When `f` fails,
    /// nothing is written.
    pub fn transact<R>(&self, f: impl FnOnce(Vec<Intake>, &mut State) -> io::Result<(bool, R)>) -> io::Result<R> {
        let _g = self.locked()?;
        let intake = self.read_intake()?;
        let mut state = self.read_state()?;
        let had_intake = !intake.is_empty();
        let (changed, out) = f(intake, &mut state)?;
        if changed || had_intake || state.migrated {
            self.write_state(&state.records)?;
        }
        if had_intake {
            let f = OpenOptions::new().write(true).open(&self.intake)?;
            f.set_len(0)?;
            f.sync_all()?;
        }
        Ok(out)
    }

    /// The records as they are on disk, the intake not folded in.
    pub fn read(&self) -> io::Result<Vec<Record>> {
        let _g = self.locked()?;
        Ok(self.read_state()?.records)
    }

    fn read_intake(&self) -> io::Result<Vec<Intake>> {
        let text = read_complete(&self.intake)?;
        text.lines()
            .enumerate()
            .map(|(n, l)| Intake::parse(l).ok_or_else(|| broken(&self.intake, n + 1)))
            .collect()
    }

    fn read_state(&self) -> io::Result<State> {
        let text = read_complete(&self.path)?;
        let mut lines = text.lines().enumerate().peekable();
        if lines.peek().is_none_or(|(_, l)| *l == HEADER) {
            lines.next();
            let records = lines
                .map(|(n, l)| Record::parse(l).ok_or_else(|| broken(&self.path, n + 1)))
                .collect::<io::Result<_>>()?;
            return Ok(State {
                records,
                migrated: false,
            });
        }
        // the first release's lines: each one waits for its confirmation mail, like a fresh signup
        let mut records: Vec<Record> = Vec::new();
        for (n, l) in lines {
            let i = Intake::parse(l).ok_or_else(|| broken(&self.path, n + 1))?;
            if records.iter().any(|r| r.list == i.list && r.email == i.email) {
                continue;
            }
            records.push(Record {
                id: Id::random()?,
                nonce: Id::random()?,
                list: i.list,
                email: i.email,
                status: Status::Pending,
                signed_up: i.time,
                consent: i.consent,
                confirmed: None,
                mails: 0,
                last_mail: None,
                outbox: Some(Outbox::Confirm),
                attempts: 0,
                next_try: i.time,
            });
        }
        Ok(State {
            records,
            migrated: true,
        })
    }

    fn write_state(&self, records: &[Record]) -> io::Result<()> {
        let mut tmp = self.path.clone().into_os_string();
        tmp.push(".tmp");
        let tmp = PathBuf::from(tmp);
        {
            let mut f = OpenOptions::new()
                .create(true)
                .write(true)
                .truncate(true)
                .mode(0o600)
                .open(&tmp)?;
            let mut text = format!("{HEADER}\n");
            for r in records {
                text.push_str(&r.line());
            }
            f.write_all(text.as_bytes())?;
            f.sync_all()?;
        }
        fs::rename(&tmp, &self.path)?;
        sync_dir(&self.path)
    }
}

/// The file up to the end of its last complete line; a missing file is empty.
fn read_complete(path: &Path) -> io::Result<String> {
    let mut bytes = Vec::new();
    match File::open(path) {
        Ok(mut f) => f.read_to_end(&mut bytes)?,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(String::new()),
        Err(e) => return Err(e),
    };
    let complete = bytes.iter().rposition(|b| *b == b'\n').map_or(0, |i| i + 1);
    bytes.truncate(complete);
    String::from_utf8(bytes).map_err(|_| broken(path, 0))
}

fn complete_len(path: &Path) -> io::Result<u64> {
    let mut bytes = Vec::new();
    File::open(path)?.read_to_end(&mut bytes)?;
    Ok(bytes.iter().rposition(|b| *b == b'\n').map_or(0, |i| i as u64 + 1))
}

fn broken(path: &Path, line: usize) -> io::Error {
    let at = if line > 0 { format!(":{line}") } else { String::new() };
    io::Error::new(
        io::ErrorKind::InvalidData,
        format!("{}{at}: not a line of this file's format", path.display()),
    )
}

/// fsync the folder, so a new or renamed file's entry survives a crash too.
fn sync_dir(path: &Path) -> io::Result<()> {
    let dir = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    File::open(dir)?.sync_all()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_store(name: &str) -> (PathBuf, Store) {
        let dir = std::env::temp_dir().join(format!("vhrd_notify-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let store = Store::new(dir.join("signups.tsv"));
        (dir, store)
    }

    fn intake(email: &str, time: i64) -> Intake {
        Intake {
            time,
            list: "donguru".into(),
            email: Email::parse(email).unwrap(),
            consent: "2026-11-06".into(),
        }
    }

    fn record(email: &str) -> Record {
        Record {
            id: Id([1; 16]),
            nonce: Id([0xab; 16]),
            list: "donguru".into(),
            email: Email::parse(email).unwrap(),
            status: Status::Confirmed,
            signed_up: 1_793_973_789,
            consent: "2026-11-06".into(),
            confirmed: Some(1_793_973_800),
            mails: 2,
            last_mail: Some(1_793_973_790),
            outbox: Some(Outbox::Launch("donguru-launch".into())),
            attempts: 1,
            next_try: 1_793_973_900,
        }
    }

    #[test]
    fn a_record_line_reads_back() {
        let r = record("a@b.no");
        let line = r.line();
        assert_eq!(Record::parse(line.trim_end()), Some(r.clone()));
        let pending = Record {
            status: Status::Pending,
            confirmed: None,
            outbox: None,
            last_mail: None,
            ..r
        };
        assert_eq!(Record::parse(pending.line().trim_end()), Some(pending));
    }

    #[test]
    fn broken_record_lines_are_refused() {
        let good = record("a@b.no").line();
        let good = good.trim_end();
        let cols: Vec<&str> = good.split('\t').collect();
        // every column replaced by something it must not hold
        for (i, bad) in [
            "XYZ",
            "AB".repeat(16).as_str(),
            "Donguru",
            "a b@c.no",
            "done",
            "yesterday",
            "",
            "-",
            "-1",
            "never",
            "launch:Bad",
            "x",
            "2026",
        ]
        .iter()
        .enumerate()
        {
            let mut c = cols.clone();
            c[i] = bad;
            assert_eq!(Record::parse(&c.join("\t")), None, "column {i} = {bad:?}");
        }
        assert_eq!(Record::parse(&format!("{good}\textra")), None);
    }

    #[test]
    fn accept_then_transact_folds_and_empties_the_intake() {
        let (dir, st) = temp_store("fold");
        assert!(st.accept(&intake("a@b.no", 100), 1 << 20).unwrap());
        assert!(st.accept(&intake("c@d.no", 101), 1 << 20).unwrap());
        let seen = st
            .transact(|i, s| {
                assert!(s.records.is_empty());
                Ok((false, i.len()))
            })
            .unwrap();
        assert_eq!(seen, 2);
        assert_eq!(fs::read_to_string(dir.join("signups.tsv.intake")).unwrap(), "");
        assert_eq!(fs::read_to_string(st.path()).unwrap(), format!("{HEADER}\n"));
        use std::os::unix::fs::PermissionsExt;
        for f in ["signups.tsv", "signups.tsv.intake"] {
            assert_eq!(
                fs::metadata(dir.join(f)).unwrap().permissions().mode() & 0o777,
                0o600,
                "{f}"
            );
        }
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_full_intake_refuses() {
        let (dir, st) = temp_store("intake-full");
        assert!(st.accept(&intake("a@b.no", 100), 10).unwrap());
        assert!(!st.accept(&intake("c@d.no", 100), 10).unwrap());
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn records_written_read_back() {
        let (dir, st) = temp_store("write");
        st.transact(|_, s| {
            s.records.push(record("a@b.no"));
            Ok((true, ()))
        })
        .unwrap();
        assert_eq!(st.read().unwrap(), [record("a@b.no")]);
        assert!(!dir.join("signups.tsv.tmp").exists());
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn an_unfinished_intake_line_is_left_out_and_cut_off() {
        let (dir, st) = temp_store("torn");
        st.accept(&intake("a@b.no", 100), 1 << 20).unwrap();
        let mut f = OpenOptions::new()
            .append(true)
            .open(dir.join("signups.tsv.intake"))
            .unwrap();
        f.write_all(b"2026-11-05T14:04:00Z\tdong").unwrap();
        drop(f);
        st.accept(&intake("c@d.no", 100), 1 << 20).unwrap();
        let got = st.transact(|i, _| Ok((false, i))).unwrap();
        assert_eq!(got, [intake("a@b.no", 100), intake("c@d.no", 100)]);
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_broken_line_is_an_error() {
        let (dir, st) = temp_store("broken");
        fs::write(st.path(), format!("{HEADER}\nnot a line\n")).unwrap();
        assert_eq!(st.read().unwrap_err().kind(), io::ErrorKind::InvalidData);
        fs::write(st.path(), "not a line\n").unwrap();
        assert_eq!(st.read().unwrap_err().kind(), io::ErrorKind::InvalidData);
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn the_first_releases_lines_become_pending_records_with_a_mail_queued() {
        let (dir, st) = temp_store("migrate");
        fs::write(
            st.path(),
            "2026-11-05T14:03:09Z\tdonguru\ta@b.no\t2026-11-05\n2026-11-05T15:00:00Z\tdonguru\ta@b.no\t2026-11-05\n",
        )
        .unwrap();
        let rs = st.read().unwrap();
        assert_eq!(rs.len(), 1);
        let r = &rs[0];
        assert_eq!(
            (r.email.as_str(), r.status, r.consent.as_str()),
            ("a@b.no", Status::Pending, "2026-11-05")
        );
        assert_eq!(r.signed_up, utc::parse("2026-11-05T14:03:09Z").unwrap());
        assert_eq!(r.outbox, Some(Outbox::Confirm));
        assert_ne!(r.id, r.nonce);
        // a transaction that changes nothing still writes the new format, once
        st.transact(|_, _| Ok((false, ()))).unwrap();
        let text = fs::read_to_string(st.path()).unwrap();
        assert!(text.starts_with(HEADER), "{text}");
        let (a, b) = (st.read().unwrap(), st.read().unwrap());
        assert_eq!(a, b);
        assert_eq!(a[0].email.as_str(), "a@b.no");
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn ids_have_one_spelling() {
        let id = Id::random().unwrap();
        assert_eq!(Id::parse(&id.to_string()), Some(id));
        assert_eq!(Id::parse(&"AB".repeat(16)), None);
        assert_eq!(Id::parse(&format!("+{}", "0".repeat(31))), None);
    }

    #[test]
    fn tokens() {
        assert!(is_token("donguru"));
        assert!(is_token("2026-11-05"));
        for s in ["", "Donguru", "a b", "a\tb", "a\nb", "ø", &"a".repeat(33)] {
            assert!(!is_token(s), "{s:?}");
        }
    }
}
