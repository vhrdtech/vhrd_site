//! `vhrd_notify_activate`: takes a vhrd_notify release from the Deploy workflow's upload folder (AGENTS.md "Notify
//! service", the crate docs for every check). Run by `vhrd-notify-activate.service` as the vhrd-notify user.

use std::io::Write;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Duration;

use clap::Parser;
use vhrd_notify_activate::{Args, home_dir, run, uid_of};

#[derive(Parser)]
#[command(
    name = "vhrd_notify_activate",
    version,
    about = "Activate a vhrd_notify release the Deploy workflow uploaded"
)]
struct Cli {
    /// The uploader's folder
    #[arg(long, default_value = "/home/ci-notify/incoming")]
    incoming: PathBuf,
    /// The user the uploaded files must belong to (a name or a uid)
    #[arg(long, default_value = "ci-notify")]
    uploader: String,
    /// The folder that holds vhrd_notify/ [default: $HOME]
    #[arg(long)]
    home: Option<PathBuf>,
    /// The service's user unit
    #[arg(long, default_value = "vhrd-notify.service")]
    service: String,
    /// Where the service listens
    #[arg(long, default_value = "127.0.0.1:8471")]
    probe: SocketAddr,
    #[arg(long, default_value = "/usr/bin/systemctl")]
    systemctl: PathBuf,
    /// Seconds a restarted release has to answer
    #[arg(long, default_value_t = 20.0)]
    wait: f64,
    /// Seconds before the second check
    #[arg(long, default_value_t = 5.0)]
    settle: f64,
    /// Seconds the release is watched after that
    #[arg(long, default_value_t = 60.0)]
    watch: f64,
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let uploader = match uid_of(&cli.uploader) {
        Ok(u) => u,
        Err(e) => {
            let _ = writeln!(std::io::stdout(), "<3>{e}");
            return ExitCode::from(1);
        }
    };
    let secs = |s: f64| Duration::from_secs_f64(s.clamp(0.0, 600.0));
    let args = Args {
        incoming: cli.incoming,
        uploader,
        home: cli.home.unwrap_or_else(home_dir),
        service: cli.service,
        probe: cli.probe,
        systemctl: cli.systemctl,
        wait: secs(cli.wait),
        settle: secs(cli.settle),
        watch: secs(cli.watch),
    };
    ExitCode::from(run(&args))
}
