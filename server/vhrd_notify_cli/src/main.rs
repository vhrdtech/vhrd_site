//! `vhrd_notify`: serves the signup endpoint behind the site's forms, and lists, counts, exports and deletes the
//! signups (AGENTS.md "Notify service").

use std::path::PathBuf;
use std::process::ExitCode;

use clap::{Parser, Subcommand};
use vhrd_notify::store::{Record, Status};
use vhrd_notify::{Config, Email, Store, config::EXIT_CONFIG, list, utc};

const VERSION: &str = concat!(
    env!("CARGO_PKG_VERSION"),
    " (",
    env!("GIT_SHA"),
    ", ",
    env!("BUILD_TIME"),
    ")"
);

#[derive(Parser)]
#[command(name = "vhrd_notify", version = VERSION, about = "The e-mail signup behind vhrd.tech's Get notified forms")]
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
    /// Every record, pending ones too: status, list, address, signed up, consent version, confirmed, mails sent,
    /// tab-separated
    List {
        /// Only this list
        #[arg(long)]
        list: Option<String>,
    },
    /// How many confirmed and pending records each list has
    Count,
    /// The confirmed records as CSV (email,list,signed_up,consent,confirmed)
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
    let err = |e: std::io::Error| format!("{}: {e}", store.path().display());
    // the signups not folded in yet count too: every command sees the list as the service will
    let rules = cfg.rules();
    let read = || {
        store
            .transact(|intake, st| {
                let f = list::fold(&mut st.records, intake, &rules, vhrd_notify::store::Id::random)?;
                Ok((f.new + f.queued_again > 0, st.records.clone()))
            })
            .map_err(err)
    };
    let of = |list: &Option<String>, r: &Record| list.as_ref().is_none_or(|l| *l == r.list);
    let opt = |t: Option<i64>| t.map_or("-".into(), utc::format);
    match cmd {
        Cmd::Serve => {
            let rt = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()
                .map_err(|e| e.to_string())?;
            rt.block_on(vhrd_notify::server::serve(cfg, env!("GIT_SHA")))
                .map_err(|e| e.to_string())?;
        }
        Cmd::List { list } => {
            for r in read()?.iter().filter(|r| of(&list, r)) {
                let status = if r.status == Status::Confirmed {
                    "confirmed"
                } else {
                    "pending"
                };
                println!(
                    "{status}\t{}\t{}\t{}\t{}\t{}\t{}",
                    r.list,
                    r.email,
                    utc::format(r.signed_up),
                    r.consent,
                    opt(r.confirmed),
                    r.mails
                );
            }
        }
        Cmd::Count => {
            let all = read()?;
            let mut lists: Vec<&str> = cfg.lists.iter().map(String::as_str).collect();
            for r in &all {
                if !lists.contains(&r.list.as_str()) {
                    lists.push(&r.list);
                }
            }
            for l in lists {
                let n = |s: Status| all.iter().filter(|r| r.list == l && r.status == s).count();
                println!(
                    "{l}\t{} confirmed\t{} pending",
                    n(Status::Confirmed),
                    n(Status::Pending)
                );
            }
        }
        Cmd::Export { list } => {
            println!("email,list,signed_up,consent,confirmed");
            for r in read()?.iter().filter(|r| of(&list, r) && r.status == Status::Confirmed) {
                println!(
                    "{},{},{},{},{}",
                    r.email,
                    r.list,
                    utc::format(r.signed_up),
                    r.consent,
                    opt(r.confirmed)
                );
            }
        }
        Cmd::Delete { address } => {
            let email = Email::parse(&address).map_err(|e| format!("{e}: no such address can be stored"))?;
            let n = store
                .transact(|intake, st| {
                    list::fold(&mut st.records, intake, &rules, vhrd_notify::store::Id::random)?;
                    let n = list::delete_address(&mut st.records, &email);
                    Ok((n > 0, n))
                })
                .map_err(err)?;
            println!("{email}: {n} record(s) deleted");
        }
    }
    Ok(())
}
