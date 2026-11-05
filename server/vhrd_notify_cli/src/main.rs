//! `vhrd_notify`: serves the signup endpoint behind the site's forms, and lists, counts, exports and deletes the
//! signups (README "Notify service").

use std::path::PathBuf;
use std::process::ExitCode;

use clap::{Parser, Subcommand};
use vhrd_notify::{Config, Email, Store, config::EXIT_CONFIG};

const VERSION: &str = concat!(
    env!("CARGO_PKG_VERSION"),
    " (",
    env!("GIT_SHA"),
    ", ",
    env!("BUILD_TIME"),
    ")"
);

#[derive(Parser)]
#[command(version = VERSION, about = "The e-mail signup behind vhrd.tech's Get notified forms")]
struct Cli {
    /// The settings file [default: $VHRD_NOTIFY_CONFIG, else ~/vhrd_notify/notify.toml]
    #[arg(long, global = true)]
    config: Option<PathBuf>,
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Serve POST /api/notify until SIGTERM
    Serve,
    /// Every signup: time, list, address, consent version, tab-separated
    List {
        /// Only this list
        #[arg(long)]
        list: Option<String>,
    },
    /// How many signups each list has
    Count,
    /// The signups as CSV (email,list,time,consent), for the one launch mail
    Export {
        /// Only this list
        #[arg(long)]
        list: Option<String>,
    },
    /// Remove an address from every list (a removal request)
    Delete {
        /// The address, as the person wrote it (case does not matter)
        address: String,
    },
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let path = cli
        .config
        .or_else(|| std::env::var_os("VHRD_NOTIFY_CONFIG").map(PathBuf::from))
        .unwrap_or_else(|| PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join("vhrd_notify/notify.toml"));
    let cfg = match Config::load(&path) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("vhrd_notify: {e}; fix the settings file, then start it again");
            return ExitCode::from(EXIT_CONFIG as u8);
        }
    };
    match run(cli.cmd, cfg) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("vhrd_notify: {e}");
            ExitCode::FAILURE
        }
    }
}

fn run(cmd: Cmd, cfg: Config) -> Result<(), String> {
    let store = Store::new(&cfg.store);
    let read = || store.read().map_err(|e| format!("{}: {e}", store.path().display()));
    match cmd {
        Cmd::Serve => {
            let rt = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()
                .map_err(|e| e.to_string())?;
            rt.block_on(vhrd_notify::server::serve(cfg))
                .map_err(|e| e.to_string())?;
        }
        Cmd::List { list } => {
            for s in read()?.iter().filter(|s| list.as_ref().is_none_or(|l| *l == s.list)) {
                println!("{}\t{}\t{}\t{}", s.time, s.list, s.email, s.consent);
            }
        }
        Cmd::Count => {
            let all = read()?;
            let mut lists: Vec<&str> = cfg.lists.iter().map(String::as_str).collect();
            for s in &all {
                if !lists.contains(&s.list.as_str()) {
                    lists.push(&s.list);
                }
            }
            for l in lists {
                println!("{l}\t{}", all.iter().filter(|s| s.list == l).count());
            }
        }
        Cmd::Export { list } => {
            println!("email,list,time,consent");
            for s in read()?.iter().filter(|s| list.as_ref().is_none_or(|l| *l == s.list)) {
                println!("{},{},{},{}", s.email, s.list, s.time, s.consent);
            }
        }
        Cmd::Delete { address } => {
            let email = Email::parse(&address).map_err(|e| format!("{e}: no such address can be stored"))?;
            let n = store
                .delete(&email)
                .map_err(|e| format!("{}: {e}", store.path().display()))?;
            println!("{email}: {n} signup(s) deleted");
        }
    }
    Ok(())
}
