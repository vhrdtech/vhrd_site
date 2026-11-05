//! The links in our mails: a confirm link and a remove link per record, never stored anywhere.
//!
//! A token is 33 bytes in base64url without padding (44 characters): one purpose byte, the record's id (16 bytes)
//! and the first 16 bytes of HMAC-SHA256 over a fixed label, the purpose, the id and the record's nonce, keyed with
//! the server's token key. So the same record always gets the same links (a retried mail carries the links of the
//! first try), a new record for the same address gets new ones, and nothing in the store opens a link without the
//! key.
//!
//! The key is 32 random bytes in a file only the service's user can read, made by the service on its first start. It
//! never leaves the server: not in the repo, the upload, a log or a message. Losing it only kills the links already
//! sent.

use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::Path;

use base64::Engine;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use hmac::{Hmac, KeyInit, Mac};
use sha2::Sha256;

use crate::store::Id;

/// Fixed so a token of this service can never be a MAC of something else made with the same key.
const LABEL: &[u8] = b"vhrd_notify link v1\0";
const KEY_LEN: usize = 32;
const MAC_LEN: usize = 16;
/// The length of a token in characters.
pub const LEN: usize = 44;

/// What a link does.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Purpose {
    Confirm,
    Remove,
}

impl Purpose {
    fn byte(self) -> u8 {
        match self {
            Purpose::Confirm => b'c',
            Purpose::Remove => b'r',
        }
    }
}

/// The server's token key. Its bytes are never printed: `Debug` says only that it is one.
pub struct Key([u8; KEY_LEN]);

impl std::fmt::Debug for Key {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("Key(..)")
    }
}

impl Key {
    /// Reads the key file, or makes it when there is none. Refuses a file that someone besides its owner may read,
    /// or that does not hold exactly one key.
    pub fn load_or_create(path: &Path) -> Result<Key, String> {
        let at = |e: &dyn std::fmt::Display| format!("token key {}: {e}", path.display());
        match File::open(path) {
            Ok(f) => {
                private(&f).map_err(|e| at(&e))?;
                let mut bytes = Vec::new();
                f.take(KEY_LEN as u64 + 1).read_to_end(&mut bytes).map_err(|e| at(&e))?;
                let key: [u8; KEY_LEN] = bytes.try_into().map_err(|_| at(&"not a key of 32 bytes"))?;
                Ok(Key(key))
            }
            Err(e) if e.kind() == io::ErrorKind::NotFound => {
                let mut key = [0u8; KEY_LEN];
                getrandom::fill(&mut key).map_err(|e| at(&e))?;
                if let Some(dir) = path.parent().filter(|d| !d.as_os_str().is_empty()) {
                    fs::create_dir_all(dir).map_err(|e| at(&e))?;
                }
                // create_new: two starts at once can't both write a key
                let mut f = OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .mode(0o600)
                    .open(path)
                    .map_err(|e| at(&e))?;
                f.write_all(&key).and_then(|()| f.sync_all()).map_err(|e| at(&e))?;
                let dir = path
                    .parent()
                    .filter(|d| !d.as_os_str().is_empty())
                    .unwrap_or(Path::new("."));
                File::open(dir).and_then(|d| d.sync_all()).map_err(|e| at(&e))?;
                eprintln!("vhrd_notify: made a new token key at {}", path.display());
                Ok(Key(key))
            }
            Err(e) => Err(at(&e)),
        }
    }

    /// A key for tests.
    pub fn from_bytes(b: [u8; KEY_LEN]) -> Key {
        Key(b)
    }

    fn mac(&self, purpose: Purpose, id: &Id, nonce: &Id) -> Hmac<Sha256> {
        let mut m = <Hmac<Sha256> as KeyInit>::new_from_slice(&self.0).expect("HMAC takes a key of any length");
        m.update(LABEL);
        m.update(&[purpose.byte()]);
        m.update(&id.0);
        m.update(&nonce.0);
        m
    }

    /// The token for this record's link.
    pub fn make(&self, purpose: Purpose, id: &Id, nonce: &Id) -> String {
        let mac = self.mac(purpose, id, nonce).finalize().into_bytes();
        let mut raw = Vec::with_capacity(1 + 16 + MAC_LEN);
        raw.push(purpose.byte());
        raw.extend_from_slice(&id.0);
        raw.extend_from_slice(&mac[..MAC_LEN]);
        URL_SAFE_NO_PAD.encode(raw)
    }

    /// The record id a token names, if it has the shape of one for `purpose`. The MAC is checked by [`Key::check`]
    /// once the record (and its nonce) is found.
    pub fn id_of(token: &str, purpose: Purpose) -> Option<(Id, [u8; MAC_LEN])> {
        if token.len() != LEN
            || !token
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        {
            return None;
        }
        let raw = URL_SAFE_NO_PAD.decode(token).ok()?;
        if raw.len() != 1 + 16 + MAC_LEN || raw[0] != purpose.byte() {
            return None;
        }
        let id = Id(raw[1..17].try_into().ok()?);
        let mac = raw[17..].try_into().ok()?;
        Some((id, mac))
    }

    /// Whether `mac` is this record's, in constant time.
    pub fn check(&self, purpose: Purpose, id: &Id, nonce: &Id, mac: &[u8; MAC_LEN]) -> bool {
        self.mac(purpose, id, nonce).verify_truncated_left(mac).is_ok()
    }
}

/// A file only its owner may read or write.
fn private(f: &File) -> io::Result<()> {
    let mode = f.metadata()?.permissions().mode();
    if mode & 0o077 != 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            format!("mode {:o}: others may read it; chmod 600 it", mode & 0o777),
        ));
    }
    Ok(())
}

/// Reads a secret from a file only its owner may read: the whole file, one trailing newline taken off. Refuses an
/// empty one or one with control characters, and never puts the content in an error.
pub fn read_secret(path: &Path) -> Result<String, String> {
    let at = |e: &dyn std::fmt::Display| format!("{}: {e}", path.display());
    let f = File::open(path).map_err(|e| at(&e))?;
    private(&f).map_err(|e| at(&e))?;
    let mut s = String::new();
    f.take(4096).read_to_string(&mut s).map_err(|_| at(&"not UTF-8 text"))?;
    let s = s.strip_suffix('\n').unwrap_or(&s);
    if s.is_empty() || s.chars().any(char::is_control) {
        return Err(at(&"empty, or holds control characters"));
    }
    Ok(s.to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!("vhrd_notify-token-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn a_token_checks_only_for_its_record_and_purpose() {
        let k = Key::from_bytes([7; 32]);
        let (id, nonce) = (Id([1; 16]), Id([2; 16]));
        let t = k.make(Purpose::Confirm, &id, &nonce);
        assert_eq!(t.len(), LEN);
        assert_eq!(t, k.make(Purpose::Confirm, &id, &nonce));
        let (got, mac) = Key::id_of(&t, Purpose::Confirm).unwrap();
        assert_eq!(got, id);
        assert!(k.check(Purpose::Confirm, &id, &nonce, &mac));
        // another nonce (a new record for the address), another key, another purpose
        assert!(!k.check(Purpose::Confirm, &id, &Id([3; 16]), &mac));
        assert!(!Key::from_bytes([8; 32]).check(Purpose::Confirm, &id, &nonce, &mac));
        assert!(Key::id_of(&t, Purpose::Remove).is_none());
        let r = k.make(Purpose::Remove, &id, &nonce);
        assert_ne!(r, t);
        let (_, rmac) = Key::id_of(&r, Purpose::Remove).unwrap();
        assert!(!k.check(Purpose::Confirm, &id, &nonce, &rmac));
    }

    #[test]
    fn malformed_tokens_name_nothing() {
        let k = Key::from_bytes([7; 32]);
        let t = k.make(Purpose::Confirm, &Id([1; 16]), &Id([2; 16]));
        for bad in [
            String::new(),
            t[..43].to_owned(),
            format!("{t}A"),
            t.replace(&t[..1], "+"),
            format!("{}=", &t[..43]),
            "A".repeat(44),
            format!("{} ", &t[..43]),
        ] {
            assert!(Key::id_of(&bad, Purpose::Confirm).is_none(), "{bad:?}");
        }
        // a flipped MAC bit names the record but does not check
        let mut raw = URL_SAFE_NO_PAD.decode(&t).unwrap();
        raw[20] ^= 1;
        let (id, mac) = Key::id_of(&URL_SAFE_NO_PAD.encode(raw), Purpose::Confirm).unwrap();
        assert!(!k.check(Purpose::Confirm, &id, &Id([2; 16]), &mac));
    }

    #[test]
    fn the_key_file_is_made_once_and_kept_private() {
        let dir = temp("key");
        let path = dir.join("sub/token-key");
        let a = Key::load_or_create(&path).unwrap();
        let b = Key::load_or_create(&path).unwrap();
        assert_eq!(a.0, b.0);
        assert_eq!(fs::metadata(&path).unwrap().permissions().mode() & 0o777, 0o600);
        assert_eq!(format!("{a:?}"), "Key(..)");
        fs::set_permissions(&path, fs::Permissions::from_mode(0o640)).unwrap();
        assert!(Key::load_or_create(&path).unwrap_err().contains("chmod 600"));
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        fs::write(&path, b"short").unwrap();
        assert!(Key::load_or_create(&path).is_err());
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn secrets_are_read_private_and_never_shown() {
        let dir = temp("secret");
        let path = dir.join("smtp-password");
        let write = |text: &str, mode: u32| {
            fs::write(&path, text).unwrap();
            fs::set_permissions(&path, fs::Permissions::from_mode(mode)).unwrap();
        };
        write("hunter2-long\n", 0o600);
        assert_eq!(read_secret(&path).unwrap(), "hunter2-long");
        write("hunter2-long\n", 0o644);
        let e = read_secret(&path).unwrap_err();
        assert!(!e.contains("hunter2"), "{e}");
        for bad in ["", "\n", "two\nlines\n"] {
            write(bad, 0o600);
            let e = read_secret(&path).unwrap_err();
            assert!(!e.contains("two"), "{e}");
        }
        assert!(read_secret(&dir.join("missing")).is_err());
        fs::remove_dir_all(dir).unwrap();
    }
}
