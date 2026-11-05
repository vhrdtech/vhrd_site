//! The binary's commands on a store made here: export and count see confirmed records only, send queues a list mail
//! only with --yes.

use std::path::PathBuf;
use std::process::Command;

use vhrd_notify::store::{Id, Outbox, Record, Status, Store};
use vhrd_notify::{Email, utc};

fn setup(name: &str) -> (PathBuf, PathBuf) {
    let dir = std::env::temp_dir().join(format!("vhrd_notify-cli-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let cfg = dir.join("notify.toml");
    std::fs::write(&cfg, "store = \"signups.tsv\"\n").unwrap();
    let rec = |email: &str, n: u8, status: Status| Record {
        id: Id([n; 16]),
        nonce: Id([n + 100; 16]),
        list: "donguru".into(),
        email: Email::parse(email).unwrap(),
        status,
        signed_up: 1_793_973_789,
        consent: "2026-11-06".into(),
        confirmed: (status == Status::Confirmed).then_some(1_793_973_800),
        mails: 1,
        last_mail: Some(1_793_973_790),
        outbox: None,
        attempts: 0,
        next_try: 0,
    };
    Store::new(dir.join("signups.tsv"))
        .transact(|_, st| {
            st.records.push(rec("yes@example.com", 1, Status::Confirmed));
            st.records.push(rec("notyet@example.com", 2, Status::Pending));
            Ok((true, ()))
        })
        .unwrap();
    (dir, cfg)
}

fn run(cfg: &PathBuf, args: &[&str]) -> (bool, String, String) {
    let out = Command::new(env!("CARGO_BIN_EXE_vhrd_notify"))
        .arg("--config")
        .arg(cfg)
        .args(args)
        .output()
        .unwrap();
    (
        out.status.success(),
        String::from_utf8(out.stdout).unwrap(),
        String::from_utf8(out.stderr).unwrap(),
    )
}

#[test]
fn export_and_count_see_confirmed_records_only() {
    let (dir, cfg) = setup("export");
    let (ok, out, _) = run(&cfg, &["export"]);
    assert!(ok);
    assert_eq!(
        out,
        format!(
            "email,list,signed_up,consent,confirmed\nyes@example.com,donguru,{},2026-11-06,{}\n",
            utc::format(1_793_973_789),
            utc::format(1_793_973_800)
        )
    );
    let (_, out, _) = run(&cfg, &["count"]);
    assert_eq!(out, "donguru\t1 confirmed\t1 pending\n");
    let (_, out, _) = run(&cfg, &["list"]);
    assert_eq!(out.lines().count(), 2);
    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn send_queues_only_with_yes() {
    let (dir, cfg) = setup("send");
    let text = dir.join("launch.txt");
    std::fs::write(&text, "It's live.\n\nLeave the list: {remove}\n").unwrap();
    let t = text.to_str().unwrap();
    let args = [
        "send",
        "--list",
        "donguru",
        "--name",
        "launch-1",
        "--subject",
        "Donguru is live",
        "--text",
        t,
    ];
    let (ok, out, _) = run(&cfg, &args);
    assert!(ok);
    assert!(out.contains("would go to 1 confirmed"), "{out}");
    let store = Store::new(dir.join("signups.tsv"));
    assert!(store.read().unwrap().iter().all(|r| r.outbox.is_none()));
    let (ok, out, err) = run(&cfg, &[&args[..], &["--yes"]].concat());
    assert!(ok, "{err}");
    assert!(out.contains("1 queued"), "{out}");
    let rs = store.read().unwrap();
    assert_eq!(rs[0].outbox, Some(Outbox::Launch("launch-1".into())));
    assert_eq!(rs[1].outbox, None);
    use std::os::unix::fs::PermissionsExt;
    let kept = dir.join("signups.tsv.mail-launch-1");
    assert_eq!(std::fs::metadata(&kept).unwrap().permissions().mode() & 0o777, 0o600);
    // the same name with another text is refused; a text without the remove link too
    std::fs::write(&text, "Other.\n{remove}\n").unwrap();
    assert!(!run(&cfg, &[&args[..], &["--yes"]].concat()).0);
    std::fs::write(&text, "No link.\n").unwrap();
    let (ok, _, err) = run(
        &cfg,
        &[
            "send",
            "--list",
            "donguru",
            "--name",
            "x",
            "--subject",
            "S",
            "--text",
            t,
            "--yes",
        ],
    );
    assert!(!ok && err.contains("{remove}"), "{err}");
    // --test only to a confirmed address
    std::fs::write(&text, "Hi.\n{remove}\n").unwrap();
    let test = [
        "send",
        "--list",
        "donguru",
        "--name",
        "t",
        "--subject",
        "S",
        "--text",
        t,
        "--test",
    ];
    assert!(!run(&cfg, &[&test[..], &["notyet@example.com"]].concat()).0);
    std::fs::remove_dir_all(dir).unwrap();
}
