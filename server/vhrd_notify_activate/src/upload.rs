//! The upload folder: untrusted files from the uploader, and the manifest that names them.
//!
//! Every file is opened relative to the folder's own descriptor, without following a symlink and without blocking
//! on a FIFO, and taken only when it is a regular file of the uploader with one link and below its size limit. Each
//! is read once into memory; the checks and the writes later use only those bytes, so a file replaced while it is
//! read can't slip past them.

use std::collections::BTreeMap;
use std::fs::File;
use std::io::Read;
use std::os::fd::{AsFd, OwnedFd};
use std::path::Path;

use rustix::fs::{FileType, Mode, OFlags, fstat, openat};
use rustix::io::Errno;
use serde::Deserialize;
use sha2::{Digest, Sha256};

use crate::{BIN, CONFIG, Refused};

pub const MANIFEST: &str = "manifest.toml";

/// What may be uploaded, and how large each may be.
pub const LIMITS: [(&str, u64); 3] = [(MANIFEST, 64 * 1024), (BIN, 64 * 1024 * 1024), (CONFIG, 64 * 1024)];

/// The upload's three files, as read.
pub struct Upload {
    pub manifest: Vec<u8>,
    pub bin: Vec<u8>,
    pub config: Vec<u8>,
}

/// The manifest the workflow writes last: what the release is and the sha256 of each file.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub format: u32,
    pub name: String,
    pub version: String,
    pub git: String,
    pub seq: u64,
    pub files: BTreeMap<String, String>,
}

/// Opens a folder that is not a symlink and that only its owner can write.
pub fn private_dir(path: &Path) -> Result<(OwnedFd, rustix::fs::Stat), Refused> {
    let fd = openat(
        rustix::fs::CWD,
        path,
        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::empty(),
    )
    .map_err(|e| Refused(format!("{}: {}", path.display(), why(e))))?;
    let st = fstat(&fd).map_err(|e| Refused(format!("{}: {e}", path.display())))?;
    if st.st_mode & 0o022 != 0 {
        return Err(Refused(format!(
            "{} is writable by group or others (mode {:o})",
            path.display(),
            st.st_mode & 0o7777
        )));
    }
    Ok((fd, st))
}

fn why(e: Errno) -> String {
    match e {
        Errno::LOOP | Errno::NOTDIR => "a symlink or not a folder".into(),
        Errno::NOENT => "missing".into(),
        e => e.to_string(),
    }
}

/// Reads the three files of an upload. The folder must be the uploader's, its parent root's or ours, and neither
/// writable by others.
pub fn read(incoming: &Path, uploader: u32) -> Result<Upload, Refused> {
    let parent = incoming
        .parent()
        .ok_or_else(|| Refused(format!("{} has no parent folder", incoming.display())))?;
    let (_, pst) = private_dir(parent)?;
    let me = rustix::process::getuid().as_raw();
    if pst.st_uid != 0 && pst.st_uid != me {
        return Err(Refused(format!(
            "the folder above {} belongs to uid {}, not root",
            incoming.display(),
            pst.st_uid
        )));
    }
    let (dir, st) = private_dir(incoming)?;
    if st.st_uid != uploader {
        return Err(Refused(format!(
            "{} belongs to uid {}, not the uploader",
            incoming.display(),
            st.st_uid
        )));
    }
    let [(m, ml), (b, bl), (c, cl)] = LIMITS;
    Ok(Upload {
        manifest: read_one(&dir, m, ml, uploader)?,
        bin: read_one(&dir, b, bl, uploader)?,
        config: read_one(&dir, c, cl, uploader)?,
    })
}

/// The manifest alone, with the same checks (to see whether another upload came in).
pub fn read_manifest(incoming: &Path, uploader: u32) -> Result<Vec<u8>, Refused> {
    let (dir, st) = private_dir(incoming)?;
    if st.st_uid != uploader {
        return Err(Refused(format!(
            "{} belongs to uid {}, not the uploader",
            incoming.display(),
            st.st_uid
        )));
    }
    read_one(&dir, MANIFEST, LIMITS[0].1, uploader)
}

fn read_one(dir: &OwnedFd, name: &str, limit: u64, uploader: u32) -> Result<Vec<u8>, Refused> {
    // NONBLOCK: a FIFO opens at once and is refused below instead of hanging
    let fd = openat(
        dir.as_fd(),
        name,
        OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC,
        Mode::empty(),
    )
    .map_err(|e| match e {
        Errno::NOENT => Refused(format!("{name} is missing")),
        Errno::LOOP => Refused(format!("{name} is a symlink")),
        e => Refused(format!("{name}: {e}")),
    })?;
    let st = fstat(&fd).map_err(|e| Refused(format!("{name}: {e}")))?;
    if FileType::from_raw_mode(st.st_mode) != FileType::RegularFile {
        return Err(Refused(format!("{name} is not a regular file")));
    }
    if st.st_uid != uploader {
        return Err(Refused(format!(
            "{name} belongs to uid {}, not the uploader",
            st.st_uid
        )));
    }
    if st.st_nlink != 1 {
        return Err(Refused(format!("{name} has {} links", st.st_nlink)));
    }
    if st.st_size as u64 > limit {
        return Err(Refused(format!("{name} is {} bytes, more than {limit}", st.st_size)));
    }
    let mut data = Vec::new();
    File::from(fd)
        .take(limit + 1)
        .read_to_end(&mut data)
        .map_err(|e| Refused(format!("{name}: {e}")))?;
    if data.len() as u64 > limit {
        return Err(Refused(format!("{name} grew past {limit} bytes while it was read")));
    }
    Ok(data)
}

pub fn sha256_hex(data: &[u8]) -> String {
    Sha256::digest(data).iter().map(|b| format!("{b:02x}")).collect()
}

fn digits(s: &str, max: usize) -> bool {
    !s.is_empty() && s.len() <= max && s.bytes().all(|b| b.is_ascii_digit())
}

/// `MAJOR.MINOR.PATCH`, digits only.
pub fn version_ok(v: &str) -> bool {
    let p: Vec<&str> = v.split('.').collect();
    p.len() == 3 && digits(p[0], 4) && digits(p[1], 4) && digits(p[2], 6)
}

/// A short git sha: 7 to 12 lower-case hex digits.
pub fn git_ok(g: &str) -> bool {
    (7..=12).contains(&g.len()) && g.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

fn sha_ok(s: &str) -> bool {
    s.len() == 64 && s.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

/// The release's file name, `vhrd_notify-VERSION-SHA` (tpm ship's layout), from parts already checked.
pub fn release_name(m: &Manifest) -> String {
    format!("{BIN}-{}-{}", m.version, m.git)
}

/// A release's file name as tpm ship or this activator writes it, and the git sha its `x-vhrd-release` carries:
/// `vhrd_notify-1.2.3-abc1234`, or tpm ship's `-dirty` build, whose header says `abc1234-dirty` too.
pub fn release_git(name: &str) -> Option<&str> {
    let rest = name.strip_prefix(BIN)?.strip_prefix('-')?;
    let (version, git) = rest.split_once('-')?;
    let sha = git.strip_suffix("-dirty").unwrap_or(git);
    (version_ok(version) && git_ok(sha)).then_some(git)
}

/// Every key and value checked; the version and git sha end up in a file name and on the --version check, so their
/// shapes are narrow.
pub fn parse_manifest(raw: &[u8]) -> Result<Manifest, Refused> {
    let text = std::str::from_utf8(raw).map_err(|_| Refused(format!("{MANIFEST} is not UTF-8")))?;
    let m: Manifest = toml::from_str(text).map_err(|e| Refused(format!("{MANIFEST}: {}", e.message())))?;
    if m.format != 1 || m.name != BIN {
        return Err(Refused(format!("{MANIFEST}: format 1 of {BIN} expected")));
    }
    if !version_ok(&m.version) {
        return Err(Refused(format!("{MANIFEST}: bad version")));
    }
    if !git_ok(&m.git) {
        return Err(Refused(format!("{MANIFEST}: bad git sha")));
    }
    if m.seq == 0 || m.seq >= 1_000_000_000_000_000 {
        return Err(Refused(format!("{MANIFEST}: bad seq")));
    }
    if m.files.len() != 2 || !m.files.contains_key(BIN) || !m.files.contains_key(CONFIG) {
        return Err(Refused(format!("{MANIFEST}: files must name {BIN} and {CONFIG}")));
    }
    if !m.files.values().all(|v| sha_ok(v)) {
        return Err(Refused(format!("{MANIFEST}: bad sha256")));
    }
    Ok(m)
}

/// The upload's files match the manifest.
pub fn check_sums(m: &Manifest, u: &Upload) -> Result<(), Refused> {
    for (name, data) in [(BIN, &u.bin), (CONFIG, &u.config)] {
        if sha256_hex(data) != m.files[name] {
            return Err(Refused(format!(
                "{name} does not match its sha256 in {MANIFEST} (an upload in progress?)"
            )));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names() {
        assert!(version_ok("0.1.0") && !version_ok("1.0") && !version_ok("0.1.0/../x") && !version_ok("a.b.c"));
        assert!(git_ok("abc1234") && !git_ok("ABC1234") && !git_ok("../../x") && !git_ok("abc"));
        assert_eq!(release_git("vhrd_notify-0.1.0-abc1234"), Some("abc1234"));
        assert_eq!(release_git("vhrd_notify-0.1.0-abc1234-dirty"), Some("abc1234-dirty"));
        assert_eq!(release_git("vhrd_notify-0.1.0-abc1234-x"), None);
        assert_eq!(release_git("vhrd_notify-0.1.0-../x"), None);
        assert_eq!(release_git("history"), None);
        assert_eq!(release_git("other-0.1.0-abc1234"), None);
    }

    #[test]
    fn manifest() {
        let ok = format!(
            "format = 1\nname = \"vhrd_notify\"\nversion = \"0.1.0\"\ngit = \"abc1234\"\nseq = 101\n\
             [files]\nvhrd_notify = \"{0}\"\n\"notify.toml\" = \"{0}\"\n",
            "a".repeat(64)
        );
        assert!(parse_manifest(ok.as_bytes()).is_ok());
        assert!(parse_manifest(ok.replace("format = 1", "format = true").as_bytes()).is_err());
        assert!(parse_manifest(format!("{ok}run = \"x\"\n").as_bytes()).is_err());
        assert!(parse_manifest(ok.replace("seq = 101", "seq = -1").as_bytes()).is_err());
        assert!(parse_manifest(ok.replace("seq = 101", "seq = \"101\"").as_bytes()).is_err());
        assert!(parse_manifest(b"[[[[[[[[[[[[[[[[[[[[[[[").is_err());
    }
}
