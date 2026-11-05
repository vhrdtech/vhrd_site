//! The activator end to end: its binary runs against a scratch upload folder and home, with a fake systemctl that
//! starts a fake vhrd_notify (an HTTP server that answers 400 with its release header, or one that exits at once).
//!
//! Its own harness (libtest-mimic), because this test binary is also both fakes: started with `VHRD_FAKE` set, it
//! acts as one of them instead of running tests. The fakes are reached through small `/bin/sh` wrappers, which are
//! also what the activator uploads and writes as releases. The tests run one at a time (`.config/nextest.toml` for
//! nextest, one test thread by default under `cargo test`), and each fake service listens on a port below the
//! kernel's ephemeral range, checked free first.

use std::fs;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::os::unix::fs::{PermissionsExt, symlink};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::Duration;

use libtest_mimic::{Arguments, Failed, Trial};
use sha2::{Digest, Sha256};

type Test = fn() -> Result<(), Failed>;

fn main() {
    match std::env::var("VHRD_FAKE").as_deref() {
        Ok("notify") => fake_notify(),
        Ok("systemctl") => fake_systemctl(),
        _ => {}
    }
    let tests: &[(&str, Test)] = &[
        ("first_then_second_release", first_then_second_release),
        ("same_upload_twice_does_nothing", same_upload_twice_does_nothing),
        ("older_seq_is_ignored", older_seq_is_ignored),
        ("broken_release_rolls_back", broken_release_rolls_back),
        ("wrong_version_output_is_refused", wrong_version_output_is_refused),
        ("sha_mismatch", sha_mismatch),
        ("bad_values_in_manifest", bad_values_in_manifest),
        ("extra_or_missing_keys", extra_or_missing_keys),
        ("seq_jumping_far_ahead", seq_jumping_far_ahead),
        (
            "same_name_other_bytes_keeps_the_kept_release",
            same_name_other_bytes_keeps_the_kept_release,
        ),
        (
            "rebuild_of_the_live_commit_is_live_already",
            rebuild_of_the_live_commit_is_live_already,
        ),
        ("symlink_instead_of_file", symlink_instead_of_file),
        ("hard_link", hard_link),
        ("fifo", fifo),
        ("missing_file", missing_file),
        ("too_large", too_large),
        ("incoming_writable_by_others", incoming_writable_by_others),
        ("incoming_is_a_symlink", incoming_is_a_symlink),
        (
            "keeps_five_releases_and_the_previous",
            keeps_five_releases_and_the_previous,
        ),
        ("cut_off_activation_rolls_back", cut_off_activation_rolls_back),
        (
            "cut_off_activation_that_is_fine_stays",
            cut_off_activation_that_is_fine_stays,
        ),
        ("files_of_another_user_are_refused", files_of_another_user_are_refused),
        (
            "first_release_that_fails_has_nothing_to_go_back_to",
            first_release_that_fails_has_nothing_to_go_back_to,
        ),
        (
            "the_services_other_files_are_left_alone",
            the_services_other_files_are_left_alone,
        ),
        ("release_that_dies_later_rolls_back", release_that_dies_later_rolls_back),
        (
            "port_taken_by_another_process_fails",
            port_taken_by_another_process_fails,
        ),
        (
            "rolls_back_to_a_dirty_tpm_ship_release",
            rolls_back_to_a_dirty_tpm_ship_release,
        ),
    ];
    let trials = tests.iter().map(|&(name, f)| Trial::test(name, f)).collect();
    let mut args = Arguments::from_args();
    args.test_threads.get_or_insert(1);
    libtest_mimic::run(&args, trials).exit();
}

// ---- the fakes

/// `vhrd_notify --version` or `vhrd_notify serve --config FILE`, as the wrapper's FAKE_* say.
fn fake_notify() -> ! {
    let git = std::env::var("FAKE_GIT").unwrap();
    let version = std::env::var("FAKE_VERSION").unwrap();
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args == ["--version"] {
        println!("vhrd_notify {version} ({git}, 5 Nov 2026 07:00 UTC)");
        std::process::exit(0);
    }
    if std::env::var("FAKE_BROKEN").as_deref() == Ok("1") {
        std::process::exit(1);
    }
    // FAKE_DIE_AFTER=MS: serve, then die that much later
    if let Ok(ms) = std::env::var("FAKE_DIE_AFTER") {
        let ms: u64 = ms.parse().unwrap();
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(ms));
            std::process::exit(1);
        });
    }
    let config = fs::read_to_string(&args[args.iter().position(|a| a == "--config").unwrap() + 1]).unwrap();
    let addr = config
        .lines()
        .find_map(|l| l.strip_prefix("listen = "))
        .unwrap()
        .trim_matches('"')
        .to_string();
    // the old one may still be on its way out; a port someone else holds for good: stay up without it
    let mut listener = None;
    for _ in 0..60 {
        if let Ok(l) = TcpListener::bind(&addr) {
            listener = Some(l);
            break;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    let Some(listener) = listener else {
        loop {
            std::thread::sleep(Duration::from_secs(60));
        }
    };
    for conn in listener.incoming() {
        let Ok(mut s) = conn else { continue };
        let _ = s.set_read_timeout(Some(Duration::from_secs(2)));
        let mut buf = Vec::new();
        let mut chunk = [0u8; 1024];
        while !buf.windows(4).any(|w| w == b"\r\n\r\n") {
            match s.read(&mut chunk) {
                Ok(0) | Err(_) => break,
                Ok(n) => buf.extend_from_slice(&chunk[..n]),
            }
        }
        let resp = format!(
            "HTTP/1.1 400 Bad Request\r\nx-vhrd-release: {git}\r\ncontent-length: 0\r\nconnection: close\r\n\r\n"
        );
        let _ = s.write_all(resp.as_bytes());
    }
    unreachable!()
}

/// `systemctl --user restart|is-active|reset-failed UNIT`, the service's pid in a file in FAKE_HOME.
fn fake_systemctl() -> ! {
    let home = PathBuf::from(std::env::var("FAKE_HOME").unwrap());
    let pidfile = home.join("fake.pid");
    let verb = std::env::args().nth(2).unwrap();
    match verb.as_str() {
        "restart" => {
            if let Some(pid) = live_pid(&pidfile) {
                let _ = Command::new("kill").arg(pid.to_string()).status();
                for _ in 0..100 {
                    if live_pid(&pidfile).is_none() {
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(20));
                }
            }
            let d = home.join("vhrd_notify");
            let child = Command::new(d.join("vhrd_notify"))
                .args(["serve", "--config"])
                .arg(d.join("notify.toml"))
                .process_group(0)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .unwrap();
            fs::write(&pidfile, child.id().to_string()).unwrap();
            std::process::exit(0);
        }
        "show" => {
            println!("{}", live_pid(&pidfile).unwrap_or(0));
            std::process::exit(0);
        }
        "is-active" => {
            let alive = live_pid(&pidfile).is_some();
            println!("{}", if alive { "active" } else { "failed" });
            std::process::exit(if alive { 0 } else { 3 });
        }
        _ => std::process::exit(0),
    }
}

/// The pid in the file, while that process runs (not gone, not a zombie).
fn live_pid(pidfile: &Path) -> Option<u32> {
    let pid: u32 = fs::read_to_string(pidfile).ok()?.trim().parse().ok()?;
    let stat = fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
    let state = stat.rsplit_once(") ")?.1.split(' ').next()?;
    (state != "Z" && state != "X").then_some(pid)
}

// ---- the scratch server

struct Env {
    tmp: PathBuf,
    incoming: PathBuf,
    home: PathBuf,
    port: u16,
    systemctl: PathBuf,
    seq: u64,
}

fn sh_quote(p: &Path) -> String {
    format!("'{}'", p.display().to_string().replace('\'', r"'\''"))
}

/// A port below the ephemeral range (32768 and up), so no socket another test opens with port 0 can take it.
fn free_port() -> u16 {
    static N: AtomicU32 = AtomicU32::new(0);
    loop {
        let n = std::process::id()
            .wrapping_mul(7919)
            .wrapping_add(N.fetch_add(1, Ordering::Relaxed) * 104_729);
        let port = 20_000 + (n % 12_000) as u16;
        if TcpListener::bind(("127.0.0.1", port)).is_ok() {
            return port;
        }
    }
}

impl Env {
    fn new() -> Env {
        static N: AtomicU32 = AtomicU32::new(0);
        let tmp = std::env::temp_dir().join(format!(
            "vhrd-activate-{}-{}",
            std::process::id(),
            N.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();
        fs::set_permissions(&tmp, fs::Permissions::from_mode(0o700)).unwrap();
        let incoming = tmp.join("ci-notify").join("incoming");
        fs::create_dir_all(&incoming).unwrap();
        fs::set_permissions(tmp.join("ci-notify"), fs::Permissions::from_mode(0o755)).unwrap();
        fs::set_permissions(&incoming, fs::Permissions::from_mode(0o750)).unwrap();
        let home = tmp.join("home");
        fs::create_dir_all(home.join("vhrd_notify")).unwrap();
        fs::set_permissions(home.join("vhrd_notify"), fs::Permissions::from_mode(0o700)).unwrap();
        let systemctl = tmp.join("systemctl");
        let exe = std::env::current_exe().unwrap();
        fs::write(
            &systemctl,
            format!(
                "#!/bin/sh\nVHRD_FAKE=systemctl FAKE_HOME={} exec {} \"$@\"\n",
                sh_quote(&home),
                sh_quote(&exe)
            ),
        )
        .unwrap();
        fs::set_permissions(&systemctl, fs::Permissions::from_mode(0o755)).unwrap();
        Env {
            tmp,
            incoming,
            home,
            port: free_port(),
            systemctl,
            seq: 100,
        }
    }

    fn dir(&self) -> PathBuf {
        self.home.join("vhrd_notify")
    }

    fn binary(&self, git: &str, version: &str, broken: bool) -> Vec<u8> {
        fake_binary(git, version, &format!("FAKE_BROKEN={}", u8::from(broken)))
    }

    fn config(&self, git: &str) -> Vec<u8> {
        format!("listen = \"127.0.0.1:{}\"\n# {git}\n", self.port).into_bytes()
    }

    /// Uploads a release as the workflow would: the files, then the manifest. `tamper` changes the manifest's
    /// text (a key = value per line) or the files before they are written.
    fn upload_with(&mut self, git: &str, broken: bool, seq: Option<u64>, tamper: impl FnOnce(&mut Upload)) {
        let seq = seq.unwrap_or_else(|| {
            self.seq += 1;
            self.seq
        });
        let mut u = Upload {
            bin: self.binary(git, "0.1.0", broken),
            config: self.config(git),
            fields: vec![
                ("format".into(), "1".into()),
                ("name".into(), "\"vhrd_notify\"".into()),
                ("version".into(), "\"0.1.0\"".into()),
                ("git".into(), format!("\"{git}\"")),
                ("seq".into(), seq.to_string()),
            ],
            files: vec![],
        };
        u.files = vec![
            ("vhrd_notify".into(), format!("\"{}\"", hex(&u.bin))),
            ("\"notify.toml\"".into(), format!("\"{}\"", hex(&u.config))),
        ];
        tamper(&mut u);
        fs::write(self.incoming.join("vhrd_notify"), &u.bin).unwrap();
        fs::write(self.incoming.join("notify.toml"), &u.config).unwrap();
        let mut m = String::new();
        for (k, v) in &u.fields {
            m += &format!("{k} = {v}\n");
        }
        m += "[files]\n";
        for (k, v) in &u.files {
            m += &format!("{k} = {v}\n");
        }
        fs::write(self.incoming.join("manifest.toml"), m).unwrap();
    }

    fn upload(&mut self, git: &str) {
        self.upload_with(git, false, None, |_| {});
    }

    fn activate(&self) -> (i32, String) {
        self.activate_as(rustix::process::getuid().as_raw())
    }

    fn activate_as(&self, uploader: u32) -> (i32, String) {
        let out = Command::new(env!("CARGO_BIN_EXE_vhrd_notify_activate"))
            .arg("--incoming")
            .arg(&self.incoming)
            .args(["--uploader", &uploader.to_string()])
            .arg("--home")
            .arg(&self.home)
            .args(["--probe", &format!("127.0.0.1:{}", self.port)])
            .arg("--systemctl")
            .arg(&self.systemctl)
            .args(["--wait", "5", "--settle", "0.3", "--watch", "0.5"])
            .output()
            .unwrap();
        let text = String::from_utf8_lossy(&out.stdout).to_string() + &String::from_utf8_lossy(&out.stderr);
        (out.status.code().unwrap_or(-1), text)
    }

    fn link(&self) -> Option<String> {
        fs::read_link(self.dir().join("vhrd_notify"))
            .ok()
            .map(|p| p.display().to_string())
    }

    fn history(&self) -> Vec<String> {
        fs::read_to_string(self.dir().join("releases/history"))
            .unwrap_or_default()
            .lines()
            .map(|l| l.split_once(' ').unwrap().1.to_string())
            .collect()
    }

    fn releases(&self) -> Vec<String> {
        let mut v: Vec<String> = fs::read_dir(self.dir().join("releases"))
            .map(|d| d.map(|e| e.unwrap().file_name().into_string().unwrap()).collect())
            .unwrap_or_default();
        v.retain(|n| n != "history");
        v.sort();
        v
    }

    fn assert_refused(&self, why: &str) -> Result<(), Failed> {
        let (code, out) = self.activate();
        check(code == 1, &out)?;
        check(out.contains("upload refused, the live release is unchanged"), &out)?;
        check(out.contains(why), &format!("no {why:?} in: {out}"))?;
        check(self.link().is_none(), "a release went live")
    }
}

impl Drop for Env {
    fn drop(&mut self) {
        if let Some(pid) = live_pid(&self.home.join("fake.pid")) {
            let _ = Command::new("kill").args(["-9", &pid.to_string()]).status();
        }
        let _ = fs::remove_dir_all(&self.tmp);
    }
}

struct Upload {
    bin: Vec<u8>,
    config: Vec<u8>,
    fields: Vec<(String, String)>,
    files: Vec<(String, String)>,
}

impl Upload {
    fn set(&mut self, key: &str, value: &str) {
        match self.fields.iter_mut().find(|(k, _)| k == key) {
            Some(f) => f.1 = value.into(),
            None => self.fields.push((key.into(), value.into())),
        }
    }
}

fn hex(data: &[u8]) -> String {
    Sha256::digest(data).iter().map(|b| format!("{b:02x}")).collect()
}

fn check(ok: bool, msg: &str) -> Result<(), Failed> {
    if ok { Ok(()) } else { Err(msg.into()) }
}

fn eq<T: PartialEq + std::fmt::Debug>(a: T, b: T, out: &str) -> Result<(), Failed> {
    check(a == b, &format!("{a:?} != {b:?}\n{out}"))
}

const A: &str = "releases/vhrd_notify-0.1.0-aaaaaaa";

// ---- the tests

fn first_then_second_release() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    let (code, out) = e.activate();
    eq(code, 0, &out)?;
    check(out.contains("vhrd_notify-0.1.0-aaaaaaa is live"), &out)?;
    eq(e.link().as_deref(), Some(A), &out)?;
    e.upload("bbbbbbb");
    let (code, out) = e.activate();
    eq(code, 0, &out)?;
    eq(e.link().as_deref(), Some("releases/vhrd_notify-0.1.0-bbbbbbb"), &out)?;
    check(
        fs::read_to_string(e.dir().join("notify.toml"))?.contains("bbbbbbb"),
        "settings not switched",
    )?;
    eq(
        e.history(),
        vec![
            "ci vhrd_notify-0.1.0-aaaaaaa from -".to_string(),
            "ci vhrd_notify-0.1.0-bbbbbbb from vhrd_notify-0.1.0-aaaaaaa".to_string(),
        ],
        &out,
    )?;
    let mode = fs::metadata(e.dir().join("releases/vhrd_notify-0.1.0-bbbbbbb"))?
        .permissions()
        .mode()
        & 0o777;
    eq(mode, 0o700, "release mode")?;
    let state = fs::read_to_string(e.dir().join("activate.toml"))?;
    check(!state.contains("pending"), &state)
}

fn same_upload_twice_does_nothing() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    eq(e.activate().0, 0, "first")?;
    let (code, out) = e.activate();
    eq(code, 0, &out)?;
    check(out.contains("is not newer than"), &out)?;
    eq(e.history().len(), 1, &out)
}

fn older_seq_is_ignored() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload_with("aaaaaaa", false, Some(200), |_| {});
    eq(e.activate().0, 0, "first")?;
    e.upload_with("bbbbbbb", false, Some(150), |_| {});
    let (code, out) = e.activate();
    eq(code, 0, &out)?;
    check(out.contains("not newer"), &out)?;
    eq(e.link().as_deref(), Some(A), &out)
}

fn broken_release_rolls_back() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    eq(e.activate().0, 0, "first")?;
    e.upload_with("ccccccc", true, None, |_| {});
    let (code, out) = e.activate();
    eq(code, 1, &out)?;
    check(out.contains("back to vhrd_notify-0.1.0-aaaaaaa"), &out)?;
    check(
        out.contains("rolled back: vhrd_notify-0.1.0-aaaaaaa is live again"),
        &out,
    )?;
    eq(e.link().as_deref(), Some(A), &out)?;
    check(
        fs::read_to_string(e.dir().join("notify.toml"))?.contains("aaaaaaa"),
        "settings not restored",
    )?;
    eq(
        e.history().last().cloned(),
        Some("rollback vhrd_notify-0.1.0-aaaaaaa from vhrd_notify-0.1.0-ccccccc".to_string()),
        &out,
    )
}

fn wrong_version_output_is_refused() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload_with("aaaaaaa", false, None, |u| u.set("git", "\"ddddddd\""));
    e.assert_refused("--version says")?;
    eq(e.releases(), Vec::<String>::new(), "a refused release was kept")
}

fn sha_mismatch() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload_with("aaaaaaa", false, None, |u| u.bin.extend_from_slice(b"\n# changed"));
    e.assert_refused("does not match its sha256")
}

fn bad_values_in_manifest() -> Result<(), Failed> {
    for (key, value) in [
        ("git", "\"../../x\""),
        ("git", "\"AAAAAAA\""),
        ("version", "\"0.1.0/../../x\""),
        ("version", "\"1.0\""),
        ("seq", "\"101\""),
        ("seq", "-5"),
        ("format", "true"),
        ("name", "\"other\""),
    ] {
        let mut e = Env::new();
        e.upload_with("aaaaaaa", false, None, |u| u.set(key, value));
        e.assert_refused("manifest.toml")
            .map_err(|f| format!("{key} = {value}: {f:?}"))?;
    }
    Ok(())
}

fn extra_or_missing_keys() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload_with("aaaaaaa", false, None, |u| u.set("run", "\"rm -rf /\""));
    e.assert_refused("unknown field")?;
    e.upload_with("aaaaaaa", false, None, |u| {
        u.files.push(("\"../evil\"".into(), format!("\"{}\"", "0".repeat(64))))
    });
    e.assert_refused("files must name")?;
    e.upload_with("aaaaaaa", false, None, |u| u.fields.retain(|(k, _)| k != "seq"));
    e.assert_refused("missing field")
}

fn seq_jumping_far_ahead() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    eq(e.activate().0, 0, "first")?;
    e.upload_with("bbbbbbb", false, Some(100_000_000_000_000), |_| {});
    let (code, out) = e.activate();
    eq(code, 1, &out)?;
    check(out.contains("jumps too far ahead"), &out)?;
    eq(e.link().as_deref(), Some(A), &out)
}

fn same_name_other_bytes_keeps_the_kept_release() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    eq(e.activate().0, 0, "first")?;
    let kept = fs::read(e.dir().join(A))?;
    e.upload_with("aaaaaaa", false, None, |u| {
        u.bin.extend_from_slice(b"\n# rebuilt");
        u.files[0].1 = format!("\"{}\"", hex(&u.bin));
    });
    let (code, out) = e.activate();
    eq(code, 1, &out)?;
    check(out.contains("with other bytes"), &out)?;
    eq(fs::read(e.dir().join(A))?, kept, "the kept release changed")
}

fn rebuild_of_the_live_commit_is_live_already() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    eq(e.activate().0, 0, "first")?;
    e.upload("aaaaaaa");
    let (code, out) = e.activate();
    eq(code, 0, &out)?;
    check(out.contains("is live already"), &out)
}

fn symlink_instead_of_file() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    let target = e.tmp.join("elsewhere");
    fs::copy(e.incoming.join("notify.toml"), &target)?;
    fs::remove_file(e.incoming.join("notify.toml"))?;
    symlink(&target, e.incoming.join("notify.toml"))?;
    e.assert_refused("notify.toml is a symlink")
}

fn hard_link() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    fs::hard_link(e.incoming.join("vhrd_notify"), e.tmp.join("second-name"))?;
    e.assert_refused("has 2 links")
}

fn fifo() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    fs::remove_file(e.incoming.join("notify.toml"))?;
    check(
        Command::new("mkfifo")
            .arg(e.incoming.join("notify.toml"))
            .status()?
            .success(),
        "mkfifo",
    )?;
    e.assert_refused("not a regular file")
}

fn missing_file() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    fs::remove_file(e.incoming.join("vhrd_notify"))?;
    e.assert_refused("vhrd_notify is missing")
}

fn too_large() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    fs::OpenOptions::new()
        .append(true)
        .open(e.incoming.join("notify.toml"))?
        .write_all(&[b'#'; 64 * 1024])?;
    e.assert_refused("more than")
}

fn incoming_writable_by_others() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    fs::set_permissions(&e.incoming, fs::Permissions::from_mode(0o770))?;
    e.assert_refused("writable by group or others")
}

fn incoming_is_a_symlink() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    let real = e.tmp.join("ci-notify/real");
    fs::rename(&e.incoming, &real)?;
    symlink(&real, &e.incoming)?;
    e.assert_refused("a symlink or not a folder")
}

fn keeps_five_releases_and_the_previous() -> Result<(), Failed> {
    let mut e = Env::new();
    for i in 0..8 {
        e.upload(&format!("{i:07x}"));
        let (code, out) = e.activate();
        eq(code, 0, &out)?;
        std::thread::sleep(Duration::from_millis(20));
    }
    let want: Vec<String> = (3..8).map(|i| format!("vhrd_notify-0.1.0-{i:07x}")).collect();
    eq(e.releases(), want, "kept")
}

/// A run killed between the switch and its check: the next start checks the release and goes back.
fn cut_off_activation_rolls_back() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    eq(e.activate().0, 0, "first")?;
    let d = e.dir();
    let broken = "vhrd_notify-0.1.0-ccccccc";
    fs::write(d.join("releases").join(broken), e.binary("ccccccc", "0.1.0", true))?;
    fs::set_permissions(d.join("releases").join(broken), fs::Permissions::from_mode(0o700))?;
    fs::copy(d.join("notify.toml"), d.join("notify.toml.prev"))?;
    fs::write(d.join("notify.toml"), e.config("ccccccc"))?;
    fs::remove_file(d.join("vhrd_notify"))?;
    symlink(format!("releases/{broken}"), d.join("vhrd_notify"))?;
    fs::write(
        d.join("activate.toml"),
        format!(
            "last_seq = {}\n[pending]\nrelease = \"{broken}\"\nprevious = \"vhrd_notify-0.1.0-aaaaaaa\"\n",
            e.seq
        ),
    )?;
    let (code, out) = e.activate();
    eq(code, 0, &out)?;
    check(out.contains("was cut off"), &out)?;
    check(
        out.contains("rolled back: vhrd_notify-0.1.0-aaaaaaa is live again"),
        &out,
    )?;
    eq(e.link().as_deref(), Some(A), &out)?;
    check(
        fs::read_to_string(d.join("notify.toml"))?.contains("aaaaaaa"),
        "settings not restored",
    )?;
    check(
        !fs::read_to_string(d.join("activate.toml"))?.contains("pending"),
        "still pending",
    )
}

fn cut_off_activation_that_is_fine_stays() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    eq(e.activate().0, 0, "first")?;
    e.upload("bbbbbbb");
    eq(e.activate().0, 0, "second")?;
    let d = e.dir();
    fs::write(
        d.join("activate.toml"),
        format!(
            "last_seq = {}\n[pending]\nrelease = \"vhrd_notify-0.1.0-bbbbbbb\"\nprevious = \"vhrd_notify-0.1.0-aaaaaaa\"\n",
            e.seq
        ),
    )?;
    let (code, out) = e.activate();
    eq(code, 0, &out)?;
    check(out.contains("vhrd_notify-0.1.0-bbbbbbb is live"), &out)?;
    eq(e.link().as_deref(), Some("releases/vhrd_notify-0.1.0-bbbbbbb"), &out)
}

/// A fake release: a wrapper that runs this test binary as the fake service, with `env` (FAKE_BROKEN=1, ...).
fn fake_binary(git: &str, version: &str, env: &str) -> Vec<u8> {
    format!(
        "#!/bin/sh\nVHRD_FAKE=notify FAKE_GIT={git} FAKE_VERSION={version} {env} exec {} \"$@\"\n",
        sh_quote(&std::env::current_exe().unwrap())
    )
    .into_bytes()
}

fn files_of_another_user_are_refused() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    let other = rustix::process::getuid().as_raw() + 1;
    let (code, out) = e.activate_as(other);
    eq(code, 1, &out)?;
    check(out.contains("not the uploader"), &out)?;
    check(e.link().is_none(), "a release went live")
}

fn first_release_that_fails_has_nothing_to_go_back_to() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload_with("ccccccc", true, None, |_| {});
    let (code, out) = e.activate();
    eq(code, 1, &out)?;
    check(out.contains("no previous release to go back to"), &out)?;
    check(
        !fs::read_to_string(e.dir().join("activate.toml"))?.contains("pending"),
        "still pending",
    )
}

/// The service keeps its own files beside the releases (the signups, and later others): the activator never
/// touches them, and no address reaches its log.
fn the_services_other_files_are_left_alone() -> Result<(), Failed> {
    let mut e = Env::new();
    let d = e.dir();
    fs::write(
        d.join("signups.tsv"),
        b"2026-11-05T07:00:00Z\tdonguru\tsomeone@example.com\t2026-11-05\n",
    )?;
    fs::write(d.join("intake.tsv"), b"x\n")?;
    fs::create_dir(d.join("other"))?;
    let before: Vec<(&str, Vec<u8>)> = ["signups.tsv", "intake.tsv"]
        .into_iter()
        .map(|n| (n, fs::read(d.join(n)).unwrap()))
        .collect();
    e.upload("aaaaaaa");
    let (_, out1) = e.activate();
    e.upload_with("ccccccc", true, None, |_| {});
    let (_, out2) = e.activate();
    for (n, data) in &before {
        eq(&fs::read(d.join(n))?, data, n)?;
    }
    check(d.join("other").is_dir(), "other/ gone")?;
    check(
        !out1.contains("example.com") && !out2.contains("example.com"),
        "an address in the log",
    )
}

fn release_that_dies_later_rolls_back() -> Result<(), Failed> {
    let mut e = Env::new();
    e.upload("aaaaaaa");
    eq(e.activate().0, 0, "first")?;
    // answers at first, then dies during the watch after the second check
    e.upload_with("ccccccc", false, None, |u| {
        u.bin = fake_binary("ccccccc", "0.1.0", "FAKE_DIE_AFTER=500");
        u.files[0].1 = format!("\"{}\"", hex(&u.bin));
    });
    let (code, out) = e.activate();
    eq(code, 1, &out)?;
    check(out.contains("did not stay up"), &out)?;
    check(
        out.contains("rolled back: vhrd_notify-0.1.0-aaaaaaa is live again"),
        &out,
    )?;
    eq(e.link().as_deref(), Some(A), &out)
}

/// Something else holds the port and answers as the new release: the activator must see that the socket is not
/// the service's.
fn port_taken_by_another_process_fails() -> Result<(), Failed> {
    let mut e = Env::new();
    let squatter = TcpListener::bind(("127.0.0.1", e.port))?;
    std::thread::spawn(move || {
        for conn in squatter.incoming() {
            let Ok(mut s) = conn else { continue };
            let mut buf = [0u8; 1024];
            let _ = s.read(&mut buf);
            let _ = s.write_all(
                b"HTTP/1.1 400 Bad Request\r\nx-vhrd-release: aaaaaaa\r\ncontent-length: 0\r\nconnection: close\r\n\r\n",
            );
        }
    });
    e.upload("aaaaaaa");
    let (code, out) = e.activate();
    eq(code, 1, &out)?;
    check(out.contains("held by another process"), &out)
}

/// tpm ship's release of a dirty tree answers `abc1234-dirty`; going back to it must still pass its check.
fn rolls_back_to_a_dirty_tpm_ship_release() -> Result<(), Failed> {
    let mut e = Env::new();
    let d = e.dir();
    fs::create_dir(d.join("releases"))?;
    fs::set_permissions(d.join("releases"), fs::Permissions::from_mode(0o700))?;
    let dirty = "vhrd_notify-0.1.0-aaaaaaa-dirty";
    fs::write(
        d.join("releases").join(dirty),
        e.binary("aaaaaaa-dirty", "0.1.0", false),
    )?;
    fs::set_permissions(d.join("releases").join(dirty), fs::Permissions::from_mode(0o700))?;
    symlink(format!("releases/{dirty}"), d.join("vhrd_notify"))?;
    fs::write(d.join("notify.toml"), e.config("aaaaaaa"))?;
    e.upload_with("ccccccc", true, None, |_| {});
    let (code, out) = e.activate();
    eq(code, 1, &out)?;
    check(out.contains(&format!("rolled back: {dirty} is live again")), &out)?;
    eq(e.link(), Some(format!("releases/{dirty}")), &out)
}
