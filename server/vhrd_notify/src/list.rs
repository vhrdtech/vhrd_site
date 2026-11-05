//! What happens to the records, as plain functions over them (the files are [`crate::store`]'s, the mail
//! [`crate::outbox`]'s). Time comes in as an argument, so the tests set it.
//!
//! - A signup for an address not on the list makes a pending record and queues its confirmation mail, unless
//!   `max_pending` records are pending already or the store holds `max_records`.
//! - A signup for a pending address queues the mail again only when the last one went out `resend_secs` ago or more,
//!   and at most `max_confirm_mails` times for one record. A confirmed address gets nothing: no mail, no change.
//! - Pending records older than `pending_secs` are deleted, as are those whose address does not exist (the mail
//!   server said so).
//! - The confirm link makes a record confirmed; the remove link, the one-click unsubscribe and `vhrd_notify delete`
//!   delete it. No trace of a deleted record is kept.

use crate::email::Email;
use crate::store::{Id, Intake, Outbox, Record, Status};

/// The limits, from the settings ([`crate::Config`]).
#[derive(Clone, Debug)]
pub struct Rules {
    pub pending_secs: i64,
    pub resend_secs: i64,
    pub max_confirm_mails: u32,
    pub max_pending: usize,
    /// Records the store may hold, pending or confirmed.
    pub max_records: usize,
    /// The pause before each retry of a failed mail; after the last one the mail is given up.
    pub retry_secs: Vec<i64>,
}

/// What a [`fold`] did, for the log (counts only, never an address).
#[derive(Debug, Default, PartialEq, Eq)]
pub struct Folded {
    pub new: usize,
    pub queued_again: usize,
    /// Signups left out: too many pending, or the address had its mails already.
    pub held: usize,
}

/// Folds the accepted signups into the records.
pub fn fold(
    records: &mut Vec<Record>,
    intake: Vec<Intake>,
    rules: &Rules,
    mut new_id: impl FnMut() -> std::io::Result<Id>,
) -> std::io::Result<Folded> {
    let mut out = Folded::default();
    for i in intake {
        match records.iter_mut().find(|r| r.list == i.list && r.email == i.email) {
            None => {
                if records.len() >= rules.max_records || pending(records) >= rules.max_pending {
                    out.held += 1;
                    continue;
                }
                records.push(Record {
                    id: new_id()?,
                    nonce: new_id()?,
                    list: i.list,
                    email: i.email,
                    status: Status::Pending,
                    signed_up: i.time,
                    consent: i.consent,
                    confirmed: None,
                    mails: 0,
                    last_mail: None,
                    outbox: Some(Outbox::Confirm),
                    attempts: 0,
                    next_try: i.time,
                });
                out.new += 1;
            }
            Some(r) if r.status == Status::Pending => {
                r.consent = i.consent;
                let rested = r.last_mail.is_none_or(|t| i.time - t >= rules.resend_secs);
                if r.outbox.is_none() && r.mails < rules.max_confirm_mails && rested {
                    r.outbox = Some(Outbox::Confirm);
                    r.attempts = 0;
                    r.next_try = i.time;
                    out.queued_again += 1;
                } else if r.outbox.is_none() {
                    out.held += 1;
                }
            }
            Some(_) => {}
        }
    }
    Ok(out)
}

pub fn pending(records: &[Record]) -> usize {
    records.iter().filter(|r| r.status == Status::Pending).count()
}

/// Deletes the pending records older than `pending_secs`; returns how many.
pub fn expire(records: &mut Vec<Record>, rules: &Rules, now: i64) -> usize {
    let before = records.len();
    records.retain(|r| r.status == Status::Confirmed || now - r.signed_up < rules.pending_secs);
    before - records.len()
}

#[derive(Debug, PartialEq, Eq)]
pub enum Confirmed {
    /// Now on the list.
    Now,
    /// It was already.
    Already,
    /// No such record: expired, removed, or never there.
    Gone,
}

pub fn confirm(records: &mut [Record], id: Id, now: i64) -> Confirmed {
    match records.iter_mut().find(|r| r.id == id) {
        None => Confirmed::Gone,
        Some(r) if r.status == Status::Confirmed => Confirmed::Already,
        Some(r) => {
            r.status = Status::Confirmed;
            r.confirmed = Some(now);
            // a confirmation mail still waiting for a retry is no longer needed
            if r.outbox == Some(Outbox::Confirm) {
                r.outbox = None;
                r.attempts = 0;
            }
            Confirmed::Now
        }
    }
}

/// Deletes the record; false when there was none.
pub fn remove(records: &mut Vec<Record>, id: Id) -> bool {
    let before = records.len();
    records.retain(|r| r.id != id);
    records.len() != before
}

/// Deletes every record of this address, on any list; returns how many.
pub fn delete_address(records: &mut Vec<Record>, email: &Email) -> usize {
    let before = records.len();
    records.retain(|r| r.email != *email);
    before - records.len()
}

/// The mails due at `now`, the longest waiting first.
pub fn due(records: &[Record], now: i64) -> Vec<(Id, Outbox)> {
    let mut d: Vec<&Record> = records
        .iter()
        .filter(|r| r.outbox.is_some() && r.next_try <= now)
        .collect();
    d.sort_by_key(|r| r.next_try);
    d.into_iter()
        .map(|r| (r.id, r.outbox.clone().expect("filtered")))
        .collect()
}

/// How a send ended.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Sent {
    Ok,
    /// Worth another try later (no connection, a 4xx).
    Later,
    /// The mail server says the address does not exist (a 550, 551 or 553 to RCPT).
    Never,
    /// This mail will never go (another 5xx, a text that can't be composed): given up, the record kept.
    Failed,
}

/// What [`sent`] did with the record, for the log.
#[derive(Debug, PartialEq, Eq)]
pub enum After {
    Done,
    Retry,
    GivenUp,
    /// The address does not exist and was pending: the record is deleted.
    Deleted,
    /// The record changed while the mail was out (removed, confirmed, another mail queued): nothing to do.
    Stale,
}

/// Books the result of sending `outbox` to record `id`.
pub fn sent(records: &mut Vec<Record>, id: Id, outbox: &Outbox, how: Sent, rules: &Rules, now: i64) -> After {
    let Some(pos) = records
        .iter()
        .position(|r| r.id == id && r.outbox.as_ref() == Some(outbox))
    else {
        // a confirmation mail that went out although the record was confirmed meanwhile still counts as sent
        if how == Sent::Ok
            && let Some(r) = records.iter_mut().find(|r| r.id == id)
        {
            r.mails += 1;
            r.last_mail = Some(now);
        }
        return After::Stale;
    };
    let r = &mut records[pos];
    match how {
        Sent::Ok => {
            r.mails += 1;
            r.last_mail = Some(now);
            r.outbox = None;
            r.attempts = 0;
            After::Done
        }
        Sent::Never if r.status == Status::Pending => {
            records.remove(pos);
            After::Deleted
        }
        Sent::Later | Sent::Never | Sent::Failed => {
            let pause = if how == Sent::Later {
                rules.retry_secs.get(r.attempts as usize)
            } else {
                None
            };
            match pause {
                Some(p) => {
                    r.attempts += 1;
                    r.next_try = now + p;
                    After::Retry
                }
                None => {
                    r.outbox = None;
                    r.attempts = 0;
                    After::GivenUp
                }
            }
        }
    }
}

/// Queues the list mail `name` for every confirmed record of `list` (only `only`'s, when given). Returns how many
/// were queued and how many were left out because a mail is still waiting for them.
pub fn queue_launch(records: &mut [Record], list: &str, name: &str, only: Option<&Email>, now: i64) -> (usize, usize) {
    let (mut queued, mut busy) = (0, 0);
    for r in records
        .iter_mut()
        .filter(|r| r.list == list && r.status == Status::Confirmed && only.is_none_or(|e| r.email == *e))
    {
        if r.outbox.is_some() {
            busy += 1;
            continue;
        }
        r.outbox = Some(Outbox::Launch(name.into()));
        r.attempts = 0;
        r.next_try = now;
        queued += 1;
    }
    (queued, busy)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rules() -> Rules {
        Rules {
            pending_secs: 7 * 86400,
            resend_secs: 86400,
            max_confirm_mails: 3,
            max_pending: 3,
            max_records: 10,
            retry_secs: vec![60, 300],
        }
    }

    fn ids() -> impl FnMut() -> std::io::Result<Id> {
        let mut n = 0u8;
        move || {
            n += 1;
            Ok(Id([n; 16]))
        }
    }

    fn signup(email: &str, time: i64) -> Intake {
        Intake {
            time,
            list: "donguru".into(),
            email: Email::parse(email).unwrap(),
            consent: "2026-11-06".into(),
        }
    }

    #[test]
    fn a_new_address_waits_for_its_mail() {
        let mut rs = Vec::new();
        let f = fold(&mut rs, vec![signup("a@b.no", 100)], &rules(), ids()).unwrap();
        assert_eq!(
            f,
            Folded {
                new: 1,
                ..Folded::default()
            }
        );
        assert_eq!(rs[0].status, Status::Pending);
        assert_eq!(due(&rs, 100), [(rs[0].id, Outbox::Confirm)]);
        assert_eq!(due(&rs, 99), []);
    }

    #[test]
    fn one_mail_per_resend_period_and_at_most_three() {
        let r = rules();
        let mut rs = Vec::new();
        fold(&mut rs, vec![signup("a@b.no", 0)], &r, ids()).unwrap();
        let id = rs[0].id;
        // again before the mail went: nothing new
        fold(&mut rs, vec![signup("a@b.no", 10)], &r, ids()).unwrap();
        assert_eq!(due(&rs, 10).len(), 1);
        assert_eq!(sent(&mut rs, id, &Outbox::Confirm, Sent::Ok, &r, 20), After::Done);
        // within the day: held
        let f = fold(&mut rs, vec![signup("a@b.no", 3600)], &r, ids()).unwrap();
        assert_eq!(f.held, 1);
        assert!(due(&rs, 3600).is_empty());
        // a day later: once more, and so on up to three mails
        let mut t = 20;
        for _ in 0..2 {
            t += 86400;
            assert_eq!(
                fold(&mut rs, vec![signup("a@b.no", t)], &r, ids())
                    .unwrap()
                    .queued_again,
                1
            );
            sent(&mut rs, id, &Outbox::Confirm, Sent::Ok, &r, t);
        }
        assert_eq!(rs[0].mails, 3);
        let f = fold(&mut rs, vec![signup("a@b.no", t + 86400)], &r, ids()).unwrap();
        assert_eq!(f.held, 1);
        assert!(due(&rs, t + 86400).is_empty());
    }

    #[test]
    fn a_confirmed_address_gets_nothing() {
        let r = rules();
        let mut rs = Vec::new();
        fold(&mut rs, vec![signup("a@b.no", 0)], &r, ids()).unwrap();
        let id = rs[0].id;
        sent(&mut rs, id, &Outbox::Confirm, Sent::Ok, &r, 1);
        assert_eq!(confirm(&mut rs, id, 5), Confirmed::Now);
        assert_eq!(confirm(&mut rs, id, 6), Confirmed::Already);
        let before = rs.clone();
        let f = fold(&mut rs, vec![signup("A@b.no", 10 * 86400)], &r, ids()).unwrap();
        assert_eq!(f, Folded::default());
        assert_eq!(rs, before);
        assert_eq!(expire(&mut rs, &r, 100 * 86400), 0);
    }

    #[test]
    fn too_many_pending_holds_new_ones() {
        let r = rules();
        let mut rs = Vec::new();
        let many = ["a@b.no", "c@b.no", "d@b.no", "e@b.no"].map(|e| signup(e, 0));
        let f = fold(&mut rs, many.to_vec(), &r, ids()).unwrap();
        assert_eq!((f.new, f.held), (3, 1));
    }

    #[test]
    fn pending_records_expire() {
        let r = rules();
        let mut rs = Vec::new();
        fold(&mut rs, vec![signup("a@b.no", 0), signup("c@b.no", 86400)], &r, ids()).unwrap();
        assert_eq!(expire(&mut rs, &r, 7 * 86400 - 1), 0);
        assert_eq!(expire(&mut rs, &r, 7 * 86400), 1);
        assert_eq!(rs[0].email.as_str(), "c@b.no");
    }

    #[test]
    fn retries_then_give_up() {
        let r = rules();
        let mut rs = Vec::new();
        fold(&mut rs, vec![signup("a@b.no", 0)], &r, ids()).unwrap();
        let id = rs[0].id;
        assert_eq!(sent(&mut rs, id, &Outbox::Confirm, Sent::Later, &r, 0), After::Retry);
        assert_eq!(due(&rs, 59), []);
        assert_eq!(due(&rs, 60).len(), 1);
        assert_eq!(sent(&mut rs, id, &Outbox::Confirm, Sent::Later, &r, 60), After::Retry);
        assert_eq!(rs[0].next_try, 360);
        assert_eq!(
            sent(&mut rs, id, &Outbox::Confirm, Sent::Later, &r, 360),
            After::GivenUp
        );
        assert_eq!(due(&rs, 10_000), []);
        assert_eq!(rs.len(), 1);
    }

    #[test]
    fn a_refused_pending_address_is_deleted() {
        let r = rules();
        let mut rs = Vec::new();
        fold(&mut rs, vec![signup("a@b.no", 0)], &r, ids()).unwrap();
        let id = rs[0].id;
        assert_eq!(sent(&mut rs, id, &Outbox::Confirm, Sent::Never, &r, 0), After::Deleted);
        assert!(rs.is_empty());
    }

    #[test]
    fn a_result_for_a_changed_record_is_stale() {
        let r = rules();
        let mut rs = Vec::new();
        fold(&mut rs, vec![signup("a@b.no", 0)], &r, ids()).unwrap();
        let id = rs[0].id;
        confirm(&mut rs, id, 1);
        assert_eq!(sent(&mut rs, id, &Outbox::Confirm, Sent::Ok, &r, 2), After::Stale);
        assert_eq!(rs[0].mails, 1);
        assert!(remove(&mut rs, id));
        assert_eq!(sent(&mut rs, id, &Outbox::Confirm, Sent::Later, &r, 3), After::Stale);
        assert!(!remove(&mut rs, id));
        assert_eq!(confirm(&mut rs, id, 4), Confirmed::Gone);
    }

    #[test]
    fn launch_goes_to_confirmed_records_only() {
        let r = rules();
        let mut rs = Vec::new();
        fold(
            &mut rs,
            vec![signup("a@b.no", 0), signup("c@b.no", 0), signup("d@b.no", 0)],
            &r,
            ids(),
        )
        .unwrap();
        let (a, c) = (rs[0].id, rs[1].id);
        sent(&mut rs, a, &Outbox::Confirm, Sent::Ok, &r, 1);
        confirm(&mut rs, a, 2);
        // c confirmed while its mail is still due for a retry: the confirm clears it
        confirm(&mut rs, c, 2);
        let only = Email::parse("c@b.no").unwrap();
        assert_eq!(queue_launch(&mut rs, "donguru", "test", Some(&only), 9), (1, 0));
        rs[1].outbox = None;
        assert_eq!(queue_launch(&mut rs, "donguru", "launch-1", None, 10), (2, 0));
        assert_eq!(queue_launch(&mut rs, "donguru", "launch-2", None, 11), (0, 2));
        let due: Vec<Id> = due(&rs, 10)
            .into_iter()
            .filter(|(_, o)| *o != Outbox::Confirm)
            .map(|(i, _)| i)
            .collect();
        assert_eq!(due, [a, c]);
        assert_eq!(delete_address(&mut rs, &Email::parse("a@b.no").unwrap()), 1);
    }
}
