//! The service's folder, `~/vhrd_notify`: the releases, the symlink to the live one, the settings, the history and
//! the activator's state. Every path is a plain name inside a folder opened once, never followed through a symlink.

use std::fs::File;
use std::io::{Read, Write};
use std::os::fd::{AsFd, OwnedFd};

use rustix::fs::{
    AtFlags, FileType, Mode, OFlags, fchmod, fsync, openat, readlinkat, renameat, statat, symlinkat, unlinkat,
};
use rustix::io::Errno;
use serde::{Deserialize, Serialize};

use crate::upload::release_git;
use crate::{BIN, KEEP, log};

/// `~/vhrd_notify/activate.toml`.
pub const STATE: &str = "activate.toml";
/// The settings of the release before the one being activated, for a rollback.
pub const PREV_CONFIG: &str = "notify.toml.prev";

#[derive(Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct State {
    /// The highest upload seq tried, whatever came of it.
    pub last_seq: u64,
    /// An activation that has switched but not finished its check: a run that finds it was cut off (a crash, a
    /// reboot, a kill) and checks that release again, or goes back to `previous`.
    pub pending: Option<Pending>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Pending {
    pub release: String,
    pub previous: Option<String>,
}

fn io(what: &str, e: impl std::fmt::Display) -> String {
    format!("{what}: {e}")
}

/// Writes a file under a temporary name, fsyncs it and renames it over `name`, all inside `dir`.
pub fn write_atomic(dir: &OwnedFd, name: &str, data: &[u8], mode: u32) -> Result<(), String> {
    let tmp = format!(".{name}.tmp");
    match unlinkat(dir, tmp.as_str(), AtFlags::empty()) {
        Ok(()) | Err(Errno::NOENT) => {}
        Err(e) => return Err(io(&tmp, e)),
    }
    let fd = openat(
        dir,
        tmp.as_str(),
        OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::from_raw_mode(mode),
    )
    .map_err(|e| io(&tmp, e))?;
    let written = (|| {
        fchmod(&fd, Mode::from_raw_mode(mode)).map_err(|e| io(&tmp, e))?;
        let mut f = File::from(fd);
        f.write_all(data).map_err(|e| io(&tmp, e))?;
        f.sync_all().map_err(|e| io(&tmp, e))?;
        drop(f);
        renameat(dir, tmp.as_str(), dir, name).map_err(|e| io(name, e))
    })();
    if written.is_err() {
        // a full disk must not leave a 64 MB half-file behind
        let _ = unlinkat(dir, tmp.as_str(), AtFlags::empty());
    }
    written?;
    fsync(dir).map_err(|e| io("fsync of the folder", e))
}

/// A file's bytes, or None when it is not there. A symlink is an error, not followed.
pub fn read_file(dir: &OwnedFd, name: &str) -> Result<Option<Vec<u8>>, String> {
    let fd = match openat(
        dir,
        name,
        OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::empty(),
    ) {
        Ok(fd) => fd,
        Err(Errno::NOENT) => return Ok(None),
        Err(e) => return Err(io(name, e)),
    };
    let mut data = Vec::new();
    File::from(fd).read_to_end(&mut data).map_err(|e| io(name, e))?;
    Ok(Some(data))
}

pub fn remove(dir: &OwnedFd, name: &str) -> Result<(), String> {
    match unlinkat(dir, name, AtFlags::empty()) {
        Ok(()) | Err(Errno::NOENT) => Ok(()),
        Err(e) => Err(io(name, e)),
    }
}

pub fn load_state(home: &OwnedFd) -> Result<State, String> {
    match read_file(home, STATE)? {
        None => Ok(State::default()),
        Some(raw) => std::str::from_utf8(&raw)
            .ok()
            .and_then(|t| toml::from_str(t).ok())
            .ok_or_else(|| format!("~/vhrd_notify/{STATE} is broken: fix or remove it by hand")),
    }
}

pub fn save_state(home: &OwnedFd, state: &State) -> Result<(), String> {
    let text = toml::to_string(state).map_err(|e| io(STATE, e))?;
    write_atomic(home, STATE, text.as_bytes(), 0o600)
}

/// The release the symlink names, or None (no symlink yet, or one that is not `releases/<a release name>`).
pub fn current(home: &OwnedFd) -> Option<String> {
    let target = readlinkat(home, BIN, Vec::new()).ok()?.into_string().ok()?;
    let name = target.strip_prefix("releases/")?;
    release_git(name).map(|_| name.to_string())
}

/// Points `~/vhrd_notify/vhrd_notify` at `releases/<release>` in one rename.
pub fn switch(home: &OwnedFd, release: &str) -> Result<(), String> {
    let tmp = format!("{BIN}.new");
    remove(home, &tmp)?;
    symlinkat(format!("releases/{release}").as_str(), home, tmp.as_str()).map_err(|e| io(&tmp, e))?;
    renameat(home, tmp.as_str(), home, BIN).map_err(|e| io(BIN, e))?;
    fsync(home).map_err(|e| io("fsync of the folder", e))
}

/// One line in `releases/history`, in tpm ship's form: `TIME how NEW from OLD`.
pub fn history(rel: &OwnedFd, how: &str, new: &str, old: Option<&str>) -> Result<(), String> {
    let line = format!("{} {how} {new} from {}\n", utc_now(), old.unwrap_or("-"));
    let fd = openat(
        rel,
        "history",
        OFlags::WRONLY | OFlags::APPEND | OFlags::CREATE | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::from_raw_mode(0o600),
    )
    .map_err(|e| io("history", e))?;
    let mut f = File::from(fd);
    f.write_all(line.as_bytes()).map_err(|e| io("history", e))?;
    f.sync_all().map_err(|e| io("history", e))
}

/// Keeps the newest `KEEP` releases, and always those in `keep`.
pub fn prune(rel: &OwnedFd, keep: &[Option<&str>]) -> Result<(), String> {
    let mut rels = Vec::new();
    for entry in rustix::fs::Dir::read_from(rel.as_fd()).map_err(|e| io("releases", e))? {
        let entry = entry.map_err(|e| io("releases", e))?;
        let Ok(name) = entry.file_name().to_str() else { continue };
        if release_git(name).is_none() {
            continue;
        }
        let st = statat(rel, name, AtFlags::SYMLINK_NOFOLLOW).map_err(|e| io(name, e))?;
        if FileType::from_raw_mode(st.st_mode) == FileType::RegularFile {
            rels.push((st.st_mtime, st.st_mtime_nsec, name.to_string()));
        }
    }
    rels.sort_by(|a, b| b.cmp(a));
    for (_, _, name) in rels.into_iter().skip(KEEP) {
        if !keep.contains(&Some(name.as_str())) {
            remove(rel, &name)?;
            log(&format!("removed the old release {name}"));
        }
    }
    Ok(())
}

/// `2026-11-05T07:00:00Z`, without a date crate (civil date from days since 1970, Howard Hinnant's algorithm).
pub fn utc_now() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let (days, rest) = (secs.div_euclid(86400), secs.rem_euclid(86400));
    let z = days + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        rest / 3600,
        rest % 3600 / 60,
        rest % 60
    )
}
