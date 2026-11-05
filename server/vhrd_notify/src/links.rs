//! The links in our mails, as the endpoint sees them. A link never acts on GET, because mail scanners open links:
//!
//! - `POST /api/notify/confirm` and `POST /api/notify/remove`: the buttons on the site's `/notify/confirm/` and
//!   `/notify/remove/` pages, which read the token from the link's `#` (a browser never sends it, so it is in no
//!   log). The form has `token` and `from`, each at most once. The answer is a status for the page's script (200
//!   done, 404 the link is old or used, 429, 503) or a 303 back to the page's `#notify-done`, `-gone`, `-wait` or
//!   `-err`.
//! - `POST /api/notify/unsubscribe?t=TOKEN`: the one-click unsubscribe of RFC 8058, the remove token in the URL
//!   (nginx logs no query of this location). The body is `List-Unsubscribe=One-Click` as a form or multipart; mail
//!   providers send no Origin. 200 when the record is removed or gone already, 404 for a token that does not check.
//! - `GET /api/notify/unsubscribe?t=TOKEN`: a mail program that opens that URL in a browser. It removes nothing:
//!   303 to `/notify/remove/#TOKEN`, the page with the button.
//!
//! A remove for a record that is gone answers like a done one (a second click says done); a confirm for one that is
//! gone, a MAC that does not check or a token that does not parse answers 404. Nothing in an answer says whose a
//! token is.

use std::sync::Arc;
use std::time::Instant;

use axum::extract::{Request, State};
use axum::http::StatusCode;
use axum::response::Response;

use crate::list::{self, Confirmed};
use crate::outbox::change;
use crate::server::{App, allow_origin, content_type_is, origin_ok, plain, see_other, wants_json};
use crate::store::Id;
use crate::token::{Key, LEN, Purpose};
use crate::utc;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Answer {
    Done,
    Gone,
    Wait,
    Err,
}

impl Answer {
    fn status(self) -> (StatusCode, &'static str) {
        match self {
            Answer::Done => (StatusCode::OK, "ok\n"),
            Answer::Gone => (StatusCode::NOT_FOUND, "this link is old or was used\n"),
            Answer::Wait => (StatusCode::TOO_MANY_REQUESTS, "too many requests, try again later\n"),
            Answer::Err => (StatusCode::SERVICE_UNAVAILABLE, "not done, try again later\n"),
        }
    }

    fn name(self) -> &'static str {
        match self {
            Answer::Done => "done",
            Answer::Gone => "gone",
            Answer::Wait => "wait",
            Answer::Err => "err",
        }
    }
}

pub async fn confirm(State(app): State<Arc<App>>, req: Request) -> Response {
    button(app, req, Purpose::Confirm).await
}

pub async fn remove(State(app): State<Arc<App>>, req: Request) -> Response {
    button(app, req, Purpose::Remove).await
}

/// The token field of a button's form; `None` when the form has another field, a field twice, or no token.
fn parse_button(body: &[u8]) -> Option<String> {
    let (mut token, mut from) = (None, None);
    for (k, v) in form_urlencoded::parse(body) {
        let slot = match &*k {
            "token" => &mut token,
            "from" => &mut from,
            _ => return None,
        };
        if slot.replace(v.into_owned()).is_some() {
            return None;
        }
    }
    token
}

async fn button(app: Arc<App>, req: Request, purpose: Purpose) -> Response {
    let headers = req.headers().clone();
    let Ok(origin) = origin_ok(&app.cfg, &headers) else {
        return plain(StatusCode::BAD_REQUEST, "bad request\n");
    };
    if !content_type_is(&headers, "application/x-www-form-urlencoded") {
        return plain(StatusCode::BAD_REQUEST, "bad request\n");
    }
    let ip = app.client(&headers, &req);
    let Ok(body) = axum::body::to_bytes(req.into_body(), app.cfg.max_body).await else {
        return plain(StatusCode::BAD_REQUEST, "bad request\n");
    };
    let Some(token) = parse_button(&body) else {
        return plain(StatusCode::BAD_REQUEST, "bad request\n");
    };
    let answer = if allowed(&app.link_limit, ip) {
        act(&app, &token, purpose).await
    } else {
        Answer::Wait
    };
    let mut resp = if wants_json(&headers) {
        let (status, text) = answer.status();
        plain(status, text)
    } else {
        let page = match purpose {
            Purpose::Confirm => "confirm",
            Purpose::Remove => "remove",
        };
        see_other(&format!(
            "{}/notify/{page}/#notify-{}",
            app.cfg.site_origin,
            answer.name()
        ))
    };
    allow_origin(&mut resp, origin);
    resp
}

pub async fn one_click(State(app): State<Arc<App>>, req: Request) -> Response {
    let token = query_token(req.uri().query());
    let headers = req.headers().clone();
    if !(content_type_is(&headers, "application/x-www-form-urlencoded")
        || content_type_is(&headers, "multipart/form-data"))
    {
        return plain(StatusCode::BAD_REQUEST, "bad request\n");
    }
    let ip = app.client(&headers, &req);
    // the body says only List-Unsubscribe=One-Click; it is read to its limit and not looked at further
    if axum::body::to_bytes(req.into_body(), app.cfg.max_body).await.is_err() {
        return plain(StatusCode::BAD_REQUEST, "bad request\n");
    }
    let Some(token) = token else {
        return plain(Answer::Gone.status().0, Answer::Gone.status().1);
    };
    let answer = if allowed(&app.one_click_limit, ip) {
        act(&app, &token, Purpose::Remove).await
    } else {
        Answer::Wait
    };
    let (status, text) = answer.status();
    plain(status, text)
}

pub async fn unsubscribe_page(State(app): State<Arc<App>>, req: Request) -> Response {
    // only a token of the right shape goes into the Location: base64url, 44 characters
    match query_token(req.uri().query()).filter(|t| Key::id_of(t, Purpose::Remove).is_some()) {
        Some(t) => see_other(&format!("{}/notify/remove/#{t}", app.cfg.site_origin)),
        None => see_other(&format!("{}/notify/remove/#notify-gone", app.cfg.site_origin)),
    }
}

/// `t` of the query, once, of a token's length.
fn query_token(query: Option<&str>) -> Option<String> {
    let mut t = None;
    for (k, v) in form_urlencoded::parse(query?.as_bytes()) {
        if k == "t" && t.replace(v.into_owned()).is_some() {
            return None;
        }
    }
    t.filter(|t| t.len() == LEN)
}

fn allowed(limit: &std::sync::Mutex<crate::limit::RateLimit>, ip: Option<std::net::IpAddr>) -> bool {
    let ip = ip.unwrap_or(std::net::IpAddr::from([0, 0, 0, 0]));
    let ok = limit.lock().expect("rate limit lock").allow(ip, Instant::now());
    if !ok {
        eprintln!("vhrd_notify: link refused, too many from one client");
    }
    ok
}

async fn act(app: &Arc<App>, token: &str, purpose: Purpose) -> Answer {
    let Some((id, mac)) = Key::id_of(token, purpose) else {
        return Answer::Gone;
    };
    let a = app.clone();
    let r = tokio::task::spawn_blocking(move || apply(&a, id, &mac, purpose)).await;
    match r {
        Ok(Ok(answer)) => answer,
        Ok(Err(e)) => {
            eprintln!("vhrd_notify: store: {e}");
            Answer::Err
        }
        Err(e) => {
            eprintln!("vhrd_notify: link task: {e}");
            Answer::Err
        }
    }
}

fn apply(app: &App, id: Id, mac: &[u8; 16], purpose: Purpose) -> std::io::Result<Answer> {
    let now = utc::now_secs();
    let (answer, what) = change(app, |rs| {
        let Some(r) = rs.iter().find(|r| r.id == id) else {
            // removed already, or expired: a remove is done, a confirm is too late
            let a = if purpose == Purpose::Remove {
                Answer::Done
            } else {
                Answer::Gone
            };
            return (false, (a, None));
        };
        if !app.key.check(purpose, &r.id, &r.nonce, mac) {
            return (false, (Answer::Gone, Some("a link that does not check")));
        }
        match purpose {
            Purpose::Confirm => match list::confirm(rs, id, now) {
                Confirmed::Now => (true, (Answer::Done, Some("confirmed"))),
                Confirmed::Already => (false, (Answer::Done, None)),
                Confirmed::Gone => (false, (Answer::Gone, None)),
            },
            Purpose::Remove => {
                list::remove(rs, id);
                (true, (Answer::Done, Some("removed")))
            }
        }
    })?;
    if let Some(w) = what {
        eprintln!("vhrd_notify: {w}");
    }
    Ok(answer)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn button_forms() {
        assert_eq!(parse_button(b"token=abc&from=confirm").as_deref(), Some("abc"));
        assert_eq!(parse_button(b"from=confirm"), None);
        assert_eq!(parse_button(b"token=a&token=b"), None);
        assert_eq!(parse_button(b"token=a&email=x"), None);
    }

    #[test]
    fn query_tokens() {
        let t = "A".repeat(LEN);
        assert_eq!(query_token(Some(&format!("t={t}"))), Some(t.clone()));
        assert_eq!(query_token(Some(&format!("t={t}&t={t}"))), None);
        assert_eq!(query_token(Some("t=short")), None);
        assert_eq!(query_token(None), None);
    }
}
