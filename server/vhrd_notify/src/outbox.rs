//! The service's worker: folds the accepted signups into the store, deletes the expired ones, and sends the mails
//! waiting in the outbox. It runs beside the endpoint, woken by each signup and every `sweep` otherwise, so no request
//! ever waits for it.

use std::io;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Duration;

use crate::list;
use crate::server::App;
use crate::utc;

/// The longest the worker sleeps without a signup waking it (expiry, retries).
const SWEEP: Duration = Duration::from_secs(60);

/// Runs until the process ends.
pub async fn run(app: Arc<App>) {
    loop {
        let a = app.clone();
        match tokio::task::spawn_blocking(move || tick(&a, utc::now_secs())).await {
            Ok(Ok(())) => {}
            Ok(Err(e)) => eprintln!("vhrd_notify: store: {e}"),
            Err(e) => eprintln!("vhrd_notify: worker: {e}"),
        }
        tokio::select! {
            _ = app.wake.notified() => {}
            _ = tokio::time::sleep(SWEEP) => {}
        }
    }
}

/// One round: fold the intake, expire, count. Says what it did in the log, in counts only.
pub fn tick(app: &App, now: i64) -> io::Result<()> {
    let rules = app.cfg.rules();
    let (folded, expired, pending, total) = app.store.transact(|intake, st| {
        let folded = list::fold(&mut st.records, intake, &rules, crate::store::Id::random)?;
        let expired = list::expire(&mut st.records, &rules, now);
        let (pending, total) = (list::pending(&st.records), st.records.len());
        let changed = folded.new + folded.queued_again > 0 || expired > 0;
        Ok((changed, (folded, expired, pending, total)))
    })?;
    app.pending.store(pending, Ordering::Relaxed);
    app.records.store(total, Ordering::Relaxed);
    if folded.new > 0 || folded.queued_again > 0 || folded.held > 0 {
        eprintln!(
            "vhrd_notify: {} new, {} confirmation mails queued again, {} held; {pending} pending, {total} in the store",
            folded.new, folded.queued_again, folded.held
        );
    }
    if expired > 0 {
        eprintln!("vhrd_notify: {expired} unconfirmed signups expired and deleted");
    }
    let max = app.cfg.max_signups;
    if folded.new > 0 && total * 5 >= max * 4 {
        eprintln!("vhrd_notify: the store is over 80 % of max_signups ({max})");
    }
    Ok(())
}
