//! Activates a vhrd_notify release that the Deploy workflow uploaded (AGENTS.md "Notify service" in this repo).
//!
//! It runs on the web server as the service's user (vhrd-notify), started by `vhrd-notify-activate.path` when the
//! uploader (ci-notify, write-only into its upload folder through rrsync) replaces the manifest, and once when the
//! user's units start (after a reboot). Its own binary is root's, installed by hand, and it is a crate of its own,
//! so no upload ever checks itself. Everything in the upload folder is untrusted input:
//!
//! 1. Each file is taken only when it is a regular file of the uploader with one link and below its size limit,
//!    opened inside the folder without following a symlink ([`upload`]).
//! 2. Each is read once into memory, and only those bytes are hashed and written. The manifest must name every
//!    file with its sha256 and carry a seq above the last one tried (an old upload never comes back) but not too
//!    far above it; the version and git sha have narrow shapes, as they become a file name.
//! 3. The release is written to `~/vhrd_notify/releases/vhrd_notify-VERSION-SHA` (tpm ship's layout); its
//!    `--version` must name that version and sha. A kept release is never overwritten with other bytes. The
//!    previous settings are saved, the activation is recorded as pending, then notify.toml is written, the
//!    `~/vhrd_notify/vhrd_notify` symlink switches in one rename, a history line is added and the service restarts.
//! 4. The service must be active and a probe on loopback must answer 400 with the new sha in `x-vhrd-release`,
//!    twice, a few seconds apart ([`service`]). Any failure from the switch on (an error, a timeout, a panic) goes
//!    back to the previous release and its settings, and checks that one. An activation cut off by a crash, a kill
//!    or a reboot is still pending at the next start: the release is checked again and rolled back if it fails.
//! 5. The newest five releases are kept, and always the current and the previous one.
//!
//! The activator never reads the signups. Each step is one line in the journal (`<6>` info, `<3>` error).

pub mod release;
pub mod service;
pub mod upload;

use std::io::Write;
use std::net::SocketAddr;
use std::os::fd::OwnedFd;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

use rustix::fs::{Mode, OFlags, mkdirat, openat};
use rustix::io::Errno;

use release::Pending;
use upload::Manifest;

pub const BIN: &str = "vhrd_notify";
pub const CONFIG: &str = "notify.toml";
pub const KEEP: usize = 5;
/// A seq may run at most this far ahead of the last one tried (run number * 100 + attempt grows by about 100 a
/// run), so one bad upload can't block every later deploy until the state is fixed by hand.
pub const SEQ_STEP: u64 = 10_000_000;

/// The upload is not taken; nothing on the server changed.
#[derive(Debug)]
pub struct Refused(pub String);

impl From<String> for Refused {
    fn from(s: String) -> Refused {
        Refused(s)
    }
}

// A closed stdout (the journal stream gone) must not panic the activator in the middle of a step.
pub fn log(msg: &str) {
    let _ = writeln!(std::io::stdout(), "<6>{msg}");
}

pub fn log_err(msg: &str) {
    let _ = writeln!(std::io::stdout(), "<3>{msg}");
}

#[derive(Clone, Debug)]
pub struct Args {
    /// The uploader's folder.
    pub incoming: PathBuf,
    /// The uploader's uid.
    pub uploader: u32,
    /// The folder that holds `vhrd_notify/` (the service user's home).
    pub home: PathBuf,
    pub service: String,
    /// Where the service listens (nginx's upstream).
    pub probe: SocketAddr,
    pub systemctl: PathBuf,
    /// How long a restarted release has to answer.
    pub wait: Duration,
    /// The pause before the second check.
    pub settle: Duration,
    /// How long the release is watched after that: one that dies a little later is rolled back too.
    pub watch: Duration,
}

/// No new round of activation starts after this long, so a run stays well inside the unit's TimeoutStartSec.
const ROUNDS_FOR: Duration = Duration::from_secs(240);

/// The whole run: recover a cut-off activation, then activate what was uploaded, and look again (at most three
/// rounds) when another upload came in meanwhile, since the path unit folds a change during a run into that run.
/// Returns the exit code.
pub fn run(args: &Args) -> u8 {
    if rustix::process::geteuid().is_root() {
        log_err("refusing to run as root: it runs as the service's user");
        return 2;
    }
    rustix::process::umask(Mode::from_raw_mode(0o077));
    let dir = args.home.join(BIN);
    let home = match upload::private_dir(&dir) {
        Ok((fd, st)) if st.st_uid == rustix::process::getuid().as_raw() => fd,
        Ok(_) => {
            log_err(&format!("{} is not ours", dir.display()));
            return 1;
        }
        Err(Refused(e)) => {
            log_err(&format!("no folder to activate into: {e}"));
            return 1;
        }
    };
    // one activation at a time (also against a run started by hand), for the whole life of this process
    let lock = match openat(
        &home,
        ".activate.lock",
        OFlags::WRONLY | OFlags::CREATE | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::from_raw_mode(0o600),
    ) {
        Ok(fd) => std::fs::File::from(fd),
        Err(e) => {
            log_err(&format!(".activate.lock: {e}"));
            return 1;
        }
    };
    if let Err(e) = lock.lock() {
        log_err(&format!(".activate.lock: {e}"));
        return 1;
    }
    let mut code = 0;
    let start = Instant::now();
    for _ in 0..3 {
        let seen = manifest_seq(args);
        code = match activate(args, &home) {
            Ok(c) => c,
            Err(Refused(e)) => {
                log_err(&format!("upload refused, the live release is unchanged: {e}"));
                1
            }
        };
        let now = manifest_seq(args);
        if now.is_none() || now == seen {
            break;
        }
        if start.elapsed() > ROUNDS_FOR {
            log_err("another upload came in meanwhile, but this run has taken long enough: the next upload brings it");
            break;
        }
        log("another upload came in meanwhile: looking at it");
    }
    code
}

fn manifest_seq(args: &Args) -> Option<u64> {
    let raw = upload::read_manifest(&args.incoming, args.uploader).ok()?;
    upload::parse_manifest(&raw).ok().map(|m| m.seq)
}

fn releases(home: &OwnedFd) -> Result<OwnedFd, Refused> {
    match mkdirat(home, "releases", Mode::from_raw_mode(0o700)) {
        Ok(()) | Err(Errno::EXIST) => {}
        Err(e) => return Err(Refused(format!("releases: {e}"))),
    }
    let fd = openat(
        home,
        "releases",
        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::empty(),
    )
    .map_err(|e| Refused(format!("releases: {e}")))?;
    let st = rustix::fs::fstat(&fd).map_err(|e| Refused(format!("releases: {e}")))?;
    if st.st_mode & 0o022 != 0 {
        return Err(Refused("releases/ is writable by group or others".into()));
    }
    Ok(fd)
}

/// One activation. `Err` is a refusal before anything changed; `Ok(1)` a release that failed and was rolled back.
fn activate(args: &Args, home: &OwnedFd) -> Result<u8, Refused> {
    let rel = releases(home)?;
    let mut state = release::load_state(home)?;
    if let Some(p) = state.pending.take() {
        recover(args, home, &rel, &p);
        release::save_state(home, &state)?;
    }

    let up = upload::read(&args.incoming, args.uploader)?;
    let m = upload::parse_manifest(&up.manifest)?;
    let name = upload::release_name(&m);
    if m.seq <= state.last_seq {
        log(&format!(
            "upload {} ({name}) is not newer than {}: nothing to do",
            m.seq, state.last_seq
        ));
        return Ok(0);
    }
    if state.last_seq > 0 && m.seq > state.last_seq + SEQ_STEP {
        return Err(Refused(format!(
            "upload {} jumps too far ahead of {}",
            m.seq, state.last_seq
        )));
    }
    upload::check_sums(&m, &up)?;
    // from here on this upload counts as tried, whatever comes of it
    state.last_seq = m.seq;
    release::save_state(home, &state)?;
    log(&format!("upload {}: {name}, checked", m.seq));

    let old = release::current(home);
    let old_config = release::read_file(home, CONFIG)?;
    let kept = release::read_file(&rel, &name)?;
    if old.as_deref() == Some(name.as_str())
        && old_config.as_deref() == Some(up.config.as_slice())
        && kept.as_deref() == Some(up.bin.as_slice())
    {
        log(&format!("{name} is live already"));
        return Ok(0);
    }
    if kept.as_ref().is_some_and(|k| *k != up.bin) {
        // never overwrite a kept release (maybe the live one, the only way back) with other bytes of the same name
        return Err(Refused(format!(
            "{name} is kept already, with other bytes: a rebuild of the same commit?"
        )));
    }
    if old.as_deref() == Some(name.as_str()) {
        return Err(Refused(format!(
            "{name} is live already, with other settings: change them in a new commit"
        )));
    }

    release::write_atomic(&rel, &name, &up.bin, 0o700)?;
    if let Err(e) = version_matches(args, &name, &m) {
        release::remove(&rel, &name)?;
        return Err(Refused(e));
    }

    // what a rollback needs, on disk before the first change
    match &old_config {
        Some(c) => release::write_atomic(home, release::PREV_CONFIG, c, 0o600)?,
        None => release::remove(home, release::PREV_CONFIG)?,
    }
    state.pending = Some(Pending {
        release: name.clone(),
        previous: old.clone(),
    });
    release::save_state(home, &state)?;

    let ok = guarded(&name, || {
        release::write_atomic(home, CONFIG, &up.config, 0o600)?;
        release::switch(home, &name)?;
        release::history(&rel, "ci", &name, old.as_deref())?;
        log(&format!(
            "switched to {name} (from {}), restarting {}",
            old.as_deref().unwrap_or("nothing"),
            args.service
        ));
        Ok(service::healthy(args, &m.git))
    });
    let code = if ok {
        log(&format!("{name} is live"));
        if let Err(e) = release::prune(&rel, &[Some(&name), old.as_deref()]) {
            log_err(&format!("keeping five releases: {e}"));
        }
        0
    } else {
        match &old {
            None => log_err(&format!(
                "{name} failed its check and there is no previous release to go back to"
            )),
            Some(o) => {
                log_err(&format!("{name} failed its check: back to {o}"));
                rollback(args, home, &rel, o, &name);
            }
        }
        1
    };
    state.pending = None;
    release::save_state(home, &state)?;
    Ok(code)
}

/// Runs a step that changes the server; an error or a panic in it counts as a failed check.
fn guarded(what: &str, step: impl FnOnce() -> Result<bool, String>) -> bool {
    match catch_unwind(AssertUnwindSafe(step)) {
        Ok(Ok(ok)) => ok,
        Ok(Err(e)) => {
            log_err(&format!("{what}: {e}"));
            false
        }
        Err(_) => {
            log_err(&format!("{what}: the activator panicked"));
            false
        }
    }
}

fn version_matches(args: &Args, name: &str, m: &Manifest) -> Result<(), String> {
    let path = args.home.join(BIN).join("releases").join(name);
    let out = service::run(
        Command::new(&path).arg("--version").env_clear(),
        Duration::from_secs(10),
    )?;
    let text = String::from_utf8_lossy(&out.stdout);
    let want = format!(" {} ({},", m.version, m.git);
    if out.status.success() && text.contains(&want) {
        Ok(())
    } else {
        let said: String = text.trim().chars().take(200).collect();
        Err(format!("{name} --version says {said:?}, not {} ({}", m.version, m.git))
    }
}

/// Back to `old` and the settings saved before the switch, then the same check for it.
fn rollback(args: &Args, home: &OwnedFd, rel: &OwnedFd, old: &str, failed: &str) {
    let git = upload::release_git(old).unwrap_or_default().to_string();
    let ok = guarded(old, || {
        if let Some(c) = release::read_file(home, release::PREV_CONFIG)? {
            release::write_atomic(home, CONFIG, &c, 0o600)?;
        }
        release::switch(home, old)?;
        release::history(rel, "rollback", old, Some(failed))?;
        Ok(service::healthy(args, &git))
    });
    if ok {
        log(&format!("rolled back: {old} is live again"));
    } else {
        log_err(&format!("rolled back to {old}, but it does not answer either"));
    }
}

/// An activation that was cut off before its check finished: check the release that is live now once more, and
/// go back when it fails.
fn recover(args: &Args, home: &OwnedFd, rel: &OwnedFd, p: &Pending) {
    log_err(&format!(
        "the activation of {} was cut off: checking it again",
        p.release
    ));
    let live = release::current(home);
    let git = live
        .as_deref()
        .and_then(upload::release_git)
        .unwrap_or_default()
        .to_string();
    if live.as_deref() == Some(p.release.as_str()) && service::healthy(args, &git) {
        log(&format!("{} is live", p.release));
        return;
    }
    match &p.previous {
        Some(o) => {
            log_err(&format!("{} failed its check: back to {o}", p.release));
            rollback(args, home, rel, o, &p.release);
        }
        None => log_err(&format!(
            "{} failed its check and there is no previous release",
            p.release
        )),
    }
}

/// The uploader's uid: a number, or a name looked up in /etc/passwd.
pub fn uid_of(user: &str) -> Result<u32, String> {
    if let Ok(n) = user.parse() {
        return Ok(n);
    }
    let passwd = std::fs::read_to_string("/etc/passwd").map_err(|e| format!("/etc/passwd: {e}"))?;
    passwd
        .lines()
        .find_map(|l| {
            let mut f = l.split(':');
            (f.next() == Some(user)).then(|| f.nth(1)?.parse().ok())?
        })
        .ok_or_else(|| format!("no user {user}"))
}

/// The default `--home`: `$HOME`.
pub fn home_dir() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| Path::new("/").into())
}
