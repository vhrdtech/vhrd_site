//! The signups, one line each in a plain text file outside the web root:
//!
//! ```text
//! 2026-11-05T14:03:09Z<TAB>donguru<TAB>someone@example.com<TAB>2026-11-05
//! ```
//!
//! time (UTC), list, address, consent text version. A signup is appended and fsynced before the visitor hears it
//! worked; the same address on the same list is kept out. A last line without its newline is a write that never
//! finished (a full disk, a crash): reads leave it out and the next signup cuts it off. Deleting an address (a GDPR request) is the one rewrite:
//! the file without its lines goes to a temporary file, is fsynced and renamed over the old one.
//!
//! The service and the CLI both take an exclusive lock on a lock file beside it (never on the store itself, which a
//! delete replaces), so a delete never loses a signup made at the same moment.

use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};

use crate::email::Email;

/// A list name or a consent version: short, plain ASCII, so it can never break a line or a column.
pub fn is_token(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 32
        && s.bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

/// One line of the store.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Signup {
    pub time: String,
    pub list: String,
    pub email: String,
    pub consent: String,
}

impl Signup {
    fn line(&self) -> String {
        format!("{}\t{}\t{}\t{}\n", self.time, self.list, self.email, self.consent)
    }

    fn parse(line: &str) -> Option<Signup> {
        let mut f = line.split('\t');
        let s = Signup {
            time: f.next()?.into(),
            list: f.next()?.into(),
            email: f.next()?.into(),
            consent: f.next()?.into(),
        };
        f.next().is_none().then_some(s)
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum Added {
    /// Written; the store now holds this many lines.
    New(usize),
    /// Already on that list: nothing written.
    Duplicate,
    /// The store holds `max` lines already: nothing written.
    Full,
}

pub struct Store {
    path: PathBuf,
    lock: PathBuf,
}

/// Held while the store is read or changed; dropping it unlocks.
struct Guard(#[allow(dead_code)] File);

impl Store {
    pub fn new(path: impl Into<PathBuf>) -> Store {
        let path = path.into();
        let mut lock = path.clone().into_os_string();
        lock.push(".lock");
        Store {
            path,
            lock: lock.into(),
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

    /// Every line, in the order they came. A missing file is an empty store; a line that does not parse is an
    /// error, never skipped silently.
    pub fn read(&self) -> io::Result<Vec<Signup>> {
        let _g = self.locked()?;
        Ok(self.read_unlocked()?.0)
    }

    /// The complete lines, and the length of the file up to the end of the last one.
    fn read_unlocked(&self) -> io::Result<(Vec<Signup>, u64)> {
        let mut bytes = Vec::new();
        match File::open(&self.path) {
            Ok(mut f) => f.read_to_end(&mut bytes)?,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok((Vec::new(), 0)),
            Err(e) => return Err(e),
        };
        let complete = bytes.iter().rposition(|b| *b == b'\n').map_or(0, |i| i + 1);
        let text = std::str::from_utf8(&bytes[..complete]).map_err(|_| self.broken(None))?;
        let mut out = Vec::new();
        for (n, line) in text.lines().enumerate() {
            out.push(Signup::parse(line).ok_or_else(|| self.broken(Some(n + 1)))?);
        }
        Ok((out, complete as u64))
    }

    fn broken(&self, line: Option<usize>) -> io::Error {
        let at = line.map(|n| format!(":{n}")).unwrap_or_default();
        io::Error::new(
            io::ErrorKind::InvalidData,
            format!("{}{at}: not a signup line", self.path.display()),
        )
    }

    /// Appends a signup unless the address is on that list already or the store holds `max` lines. Returns once
    /// the line is on disk. A duplicate takes an fsync too, so its answer takes as long as a new one's.
    pub fn add(&self, email: &Email, list: &str, consent: &str, time: &str, max: usize) -> io::Result<Added> {
        if !is_token(list) || !is_token(consent) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "list or consent is not a plain token",
            ));
        }
        let _g = self.locked()?;
        let (all, complete) = self.read_unlocked()?;
        let new = !self.path.exists();
        let mut f = OpenOptions::new()
            .create(true)
            .append(true)
            .mode(0o600)
            .open(&self.path)?;
        if all.iter().any(|s| s.list == list && s.email == email.as_str()) {
            f.sync_all()?;
            return Ok(Added::Duplicate);
        }
        if all.len() >= max {
            return Ok(Added::Full);
        }
        // an unfinished last line goes first, so the new one starts on a line of its own
        if f.metadata()?.len() != complete {
            f.set_len(complete)?;
        }
        let line = Signup {
            time: time.into(),
            list: list.into(),
            email: email.as_str().into(),
            consent: consent.into(),
        }
        .line();
        if let Err(e) = f.write_all(line.as_bytes()).and_then(|()| f.sync_all()) {
            // leave no half line behind (best effort: the next signup cuts it off otherwise)
            let _ = f.set_len(complete);
            return Err(e);
        }
        if new {
            sync_dir(&self.path)?;
        }
        Ok(Added::New(all.len() + 1))
    }

    /// Removes every line of this address (on any list). Returns how many went.
    pub fn delete(&self, email: &Email) -> io::Result<usize> {
        let _g = self.locked()?;
        let (all, _) = self.read_unlocked()?;
        let (gone, keep): (Vec<_>, Vec<_>) = all.into_iter().partition(|s| s.email == email.as_str());
        if gone.is_empty() {
            return Ok(0);
        }
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
            for s in &keep {
                f.write_all(s.line().as_bytes())?;
            }
            f.sync_all()?;
        }
        fs::rename(&tmp, &self.path)?;
        sync_dir(&self.path)?;
        Ok(gone.len())
    }
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

    fn e(s: &str) -> Email {
        Email::parse(s).unwrap()
    }

    #[test]
    fn add_keeps_duplicates_out() {
        let (dir, st) = temp_store("dup");
        let t = "2026-11-05T14:03:09Z";
        assert_eq!(
            st.add(&e("a@b.no"), "donguru", "2026-11-05", t, 10).unwrap(),
            Added::New(1)
        );
        assert_eq!(
            st.add(&e("A@B.no"), "donguru", "2026-11-05", t, 10).unwrap(),
            Added::Duplicate
        );
        assert_eq!(
            st.add(&e("a@b.no"), "other", "2026-11-05", t, 10).unwrap(),
            Added::New(2)
        );
        let text = fs::read_to_string(st.path()).unwrap();
        assert_eq!(
            text,
            "2026-11-05T14:03:09Z\tdonguru\ta@b.no\t2026-11-05\n2026-11-05T14:03:09Z\tother\ta@b.no\t2026-11-05\n"
        );
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn full_store_refuses() {
        let (dir, st) = temp_store("full");
        let t = "2026-11-05T14:03:09Z";
        assert_eq!(st.add(&e("a@b.no"), "donguru", "v1", t, 1).unwrap(), Added::New(1));
        assert_eq!(st.add(&e("c@d.no"), "donguru", "v1", t, 1).unwrap(), Added::Full);
        assert_eq!(st.read().unwrap().len(), 1);
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn delete_removes_every_line_of_the_address() {
        let (dir, st) = temp_store("del");
        let t = "2026-11-05T14:03:09Z";
        for (m, l) in [("a@b.no", "donguru"), ("c@d.no", "donguru"), ("a@b.no", "other")] {
            st.add(&e(m), l, "v1", t, 10).unwrap();
        }
        assert_eq!(st.delete(&e("A@b.no")).unwrap(), 2);
        assert_eq!(st.delete(&e("a@b.no")).unwrap(), 0);
        let left: Vec<_> = st.read().unwrap().into_iter().map(|s| s.email).collect();
        assert_eq!(left, ["c@d.no"]);
        assert!(!dir.join("signups.tsv.tmp").exists());
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(fs::metadata(st.path()).unwrap().permissions().mode() & 0o777, 0o600);
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_broken_line_is_an_error() {
        let (dir, st) = temp_store("broken");
        fs::write(st.path(), "not a line\n").unwrap();
        assert_eq!(st.read().unwrap_err().kind(), io::ErrorKind::InvalidData);
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn an_unfinished_last_line_is_left_out_and_cut_off() {
        let (dir, st) = temp_store("torn");
        let t = "2026-11-05T14:03:09Z";
        st.add(&e("a@b.no"), "donguru", "v1", t, 10).unwrap();
        let mut f = OpenOptions::new().append(true).open(st.path()).unwrap();
        f.write_all(b"2026-11-05T14:04:00Z\tdong").unwrap();
        drop(f);
        assert_eq!(st.read().unwrap().len(), 1);
        assert_eq!(st.add(&e("c@d.no"), "donguru", "v1", t, 10).unwrap(), Added::New(2));
        let text = fs::read_to_string(st.path()).unwrap();
        assert_eq!(text.lines().count(), 2);
        assert!(text.ends_with("\tc@d.no\tv1\n"), "{text}");
        fs::remove_dir_all(dir).unwrap();
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
