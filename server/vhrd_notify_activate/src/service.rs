//! The service: restart it through `systemctl --user` and check it answers as the release it should be.
//!
//! Every wait here is bounded: a child process (systemctl, or an uploaded binary's `--version`) runs in its own
//! process group, which is killed at its time limit, and its output is read only until then; a probe has one deadline
//! for connecting, sending and reading, however slowly the other side answers.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::os::unix::process::CommandExt;
use std::process::{Command, ExitStatus, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use crate::{Args, log, log_err};

/// The response header that names the release answering (vhrd_notify's `RELEASE_HEADER`).
pub const RELEASE_HEADER: &str = "x-vhrd-release";

/// How long one systemctl call may take.
const SYSTEMCTL: Duration = Duration::from_secs(30);

pub struct Output {
    pub status: ExitStatus,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
}

/// Runs a command for at most `limit`. Its process group is killed when it ends or times out, so nothing it started
/// keeps running or holds its output open; a timeout is an error.
pub fn run(cmd: &mut Command, limit: Duration) -> Result<Output, String> {
    let mut child = cmd
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0)
        .spawn()
        .map_err(|e| format!("{cmd:?}: {e}"))?;
    let pgid = child.id();
    let reader = |mut pipe: Box<dyn Read + Send>| {
        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || {
            let mut buf = Vec::new();
            let _ = pipe.by_ref().take(64 * 1024).read_to_end(&mut buf);
            let _ = tx.send(buf);
        });
        rx
    };
    let out = reader(Box::new(child.stdout.take().expect("piped")));
    let err = reader(Box::new(child.stderr.take().expect("piped")));
    let start = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(s)) => break Some(s),
            Ok(None) if start.elapsed() < limit => std::thread::sleep(Duration::from_millis(50)),
            Ok(None) => break None,
            Err(e) => return Err(e.to_string()),
        }
    };
    // whatever it left behind in its group goes too
    let _ = Command::new("/bin/kill")
        .args(["-KILL", "--", &format!("-{pgid}")])
        .stderr(Stdio::null())
        .status();
    let Some(status) = status else {
        let _ = child.wait();
        return Err(format!("{cmd:?} did not end within {} s", limit.as_secs()));
    };
    let left = |rx: mpsc::Receiver<Vec<u8>>| rx.recv_timeout(Duration::from_secs(2)).unwrap_or_default();
    Ok(Output {
        status,
        stdout: left(out),
        stderr: left(err),
    })
}

fn systemctl(args: &Args, cmd: &[&str]) -> Result<Output, String> {
    run(Command::new(&args.systemctl).arg("--user").args(cmd), SYSTEMCTL)
}

/// POSTs a body that is not the form (so it uses no rate limit) and returns the status and the release header,
/// or None when nothing answers within 3 s all told.
pub fn probe(addr: SocketAddr) -> Option<(u16, Option<String>)> {
    let deadline = Instant::now() + Duration::from_secs(3);
    let left = || deadline.checked_duration_since(Instant::now()).filter(|d| !d.is_zero());
    let mut s = TcpStream::connect_timeout(&addr, left()?).ok()?;
    s.set_write_timeout(left()).ok()?;
    let body = "probe=1";
    let req = format!(
        "POST /api/notify HTTP/1.1\r\nHost: {addr}\r\nContent-Type: application/x-www-form-urlencoded\r\n\
         Accept: application/json\r\nX-Real-IP: 127.0.0.1\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    s.write_all(req.as_bytes()).ok()?;
    let mut raw = Vec::new();
    let mut chunk = [0u8; 4096];
    // only the head is needed; the deadline holds against an answer that trickles in
    while !raw.windows(4).any(|w| w == b"\r\n\r\n") && raw.len() < 16 * 1024 {
        s.set_read_timeout(Some(left()?)).ok()?;
        match s.read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => raw.extend_from_slice(&chunk[..n]),
            Err(_) => return None,
        }
    }
    let text = String::from_utf8_lossy(&raw);
    let head = text.split("\r\n\r\n").next()?;
    let mut lines = head.split("\r\n");
    let status = lines.next()?.split(' ').nth(1)?.parse().ok()?;
    let release = lines.find_map(|l| {
        let (k, v) = l.split_once(':')?;
        k.trim()
            .eq_ignore_ascii_case(RELEASE_HEADER)
            .then(|| v.trim().to_string())
    });
    Some((status, release))
}

/// The service's main process, from systemd.
fn main_pid(args: &Args) -> Option<u32> {
    let o = systemctl(args, &["show", "-p", "MainPID", "--value", &args.service]).ok()?;
    let pid: u32 = String::from_utf8_lossy(&o.stdout).trim().parse().ok()?;
    (pid != 0).then_some(pid)
}

/// The inode of the socket listening on `addr`, from /proc/net/tcp (IPv4) or tcp6.
fn listening_inode(addr: SocketAddr) -> Option<String> {
    let (file, local) = match addr {
        SocketAddr::V4(a) => (
            "/proc/net/tcp",
            format!("{:08X}:{:04X}", u32::from_le_bytes(a.ip().octets()), a.port()),
        ),
        SocketAddr::V6(a) => {
            let o = a.ip().octets();
            let words: String = o
                .chunks(4)
                .map(|c| format!("{:08X}", u32::from_le_bytes([c[0], c[1], c[2], c[3]])))
                .collect();
            ("/proc/net/tcp6", format!("{words}:{:04X}", a.port()))
        }
    };
    let table = std::fs::read_to_string(file).ok()?;
    table.lines().skip(1).find_map(|l| {
        let f: Vec<&str> = l.split_whitespace().collect();
        // local address, state 0A = LISTEN, inode
        (f.len() > 9 && f[1] == local && f[3] == "0A").then(|| f[9].to_string())
    })
}

/// The port is held by the service's own main process, not by something else that took it while it restarted.
fn port_is_the_services(args: &Args) -> Result<(), String> {
    let pid = main_pid(args).ok_or("systemd names no main process")?;
    let inode = listening_inode(args.probe).ok_or_else(|| format!("nothing listens on {}", args.probe))?;
    let want = format!("socket:[{inode}]");
    let fds = std::fs::read_dir(format!("/proc/{pid}/fd")).map_err(|e| format!("/proc/{pid}/fd: {e}"))?;
    if fds
        .flatten()
        .any(|fd| std::fs::read_link(fd.path()).is_ok_and(|l| l.as_os_str() == want.as_str()))
    {
        Ok(())
    } else {
        Err(format!(
            "{} is held by another process than the service's ({pid})",
            args.probe
        ))
    }
}

fn answers(args: &Args, git: &str) -> Result<(), String> {
    let active = systemctl(args, &["is-active", &args.service])
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_default();
    if active != "active" {
        return Err(format!("{} is {active:?}", args.service));
    }
    let got = probe(args.probe);
    if got != Some((400, Some(git.to_string()))) {
        return Err(format!("probe answered {got:?}"));
    }
    port_is_the_services(args)
}

/// Restarts the service and waits until it answers 400 as release `git` from its own socket, checks it again after
/// `settle`, then keeps watching for `watch`: a release that dies a little later fails too.
pub fn healthy(args: &Args, git: &str) -> bool {
    // a few deploys in a row must not run into the unit's start limit
    let _ = systemctl(args, &["reset-failed", &args.service]);
    match systemctl(args, &["restart", &args.service]) {
        Ok(o) if o.status.success() => {}
        Ok(o) => {
            log_err(&format!(
                "restart failed: {}",
                String::from_utf8_lossy(&o.stderr).trim()
            ));
            return false;
        }
        Err(e) => {
            log_err(&format!("restart failed: {e}"));
            return false;
        }
    }
    let start = Instant::now();
    loop {
        let last = match answers(args, git) {
            Ok(()) => break,
            Err(e) => e,
        };
        if start.elapsed() >= args.wait {
            log_err(&format!(
                "no answer as {git} on {} within {} s (last: {last})",
                args.probe,
                args.wait.as_secs_f32()
            ));
            return false;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    std::thread::sleep(args.settle);
    let watch_end = Instant::now() + args.watch;
    loop {
        if let Err(e) = answers(args, git) {
            log_err(&format!("{} did not stay up as {git}: {e}", args.service));
            return false;
        }
        if Instant::now() >= watch_end {
            break;
        }
        std::thread::sleep(Duration::from_secs(1).min(args.watch));
    }
    log(&format!("{} answers as {git}", args.service));
    true
}
