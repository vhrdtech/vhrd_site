//! `POST /api/notify`: one signup from the site's form.
//!
//! The form (`application/x-www-form-urlencoded`, at most `max_body` bytes) has the fields `email`, `list`,
//! `consent` (the version of the text shown next to it), `from` (the page it is on) and `website`, a honeypot no
//! person sees: when it is filled the answer is the same as for a signup, and nothing is stored.
//!
//! Two kinds of client get two kinds of answer, and neither ever carries the visitor's input:
//! - the page's script sends `Accept: application/json` and gets a status with a fixed plain-text body: 200 signed
//!   up (or already on the list: the answer never tells whether an address is there), 400 refused, 429 too many
//!   from this client, 503 not stored;
//! - a plain form post (no JavaScript) gets a 303 back to the page it came from, to `#notify-ok`, `#notify-bad`,
//!   `#notify-wait` or `#notify-err`, which the page shows (CSS `:target`).
//!
//! A request that is not the form at all (another content type, a body over the limit, a field twice or one not
//! listed above, an Origin of another site) gets a plain 400.

use std::net::{IpAddr, SocketAddr};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use axum::Router;
use axum::body::Body;
use axum::extract::{ConnectInfo, Request, State};
use axum::http::{HeaderMap, HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::post;

use crate::config::Config;
use crate::email::Email;
use crate::limit::RateLimit;
use crate::store::{Added, Store};

pub struct App {
    cfg: Config,
    store: Arc<Store>,
    limit: Mutex<RateLimit>,
}

impl App {
    pub fn new(cfg: Config) -> Arc<App> {
        let limit = RateLimit::new(cfg.rate_limit, Duration::from_secs(cfg.rate_window_secs), cfg.rate_clients);
        Arc::new(App { store: Arc::new(Store::new(&cfg.store)), limit: Mutex::new(limit), cfg })
    }
}

pub fn router(app: Arc<App>) -> Router {
    Router::new()
        .route("/api/notify", post(notify))
        .fallback(|| async { plain(StatusCode::NOT_FOUND, "not found\n") })
        .with_state(app)
}

/// Serves until SIGTERM or Ctrl-C.
pub async fn serve(cfg: Config) -> std::io::Result<()> {
    let listener = tokio::net::TcpListener::bind(&cfg.listen).await?;
    eprintln!("vhrd_notify: listening on {}, store {}", listener.local_addr()?, cfg.store.display());
    let app = router(App::new(cfg));
    axum::serve(listener, app.into_make_service_with_connect_info::<SocketAddr>())
        .with_graceful_shutdown(shutdown())
        .await
}

async fn shutdown() {
    use tokio::signal::unix::{SignalKind, signal};
    let mut term = signal(SignalKind::terminate()).expect("SIGTERM handler");
    tokio::select! {
        _ = term.recv() => {}
        _ = tokio::signal::ctrl_c() => {}
    }
}

/// What came of a signup, as the page names it (`#notify-<name>`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Outcome {
    Ok,
    Bad,
    Wait,
    Err,
}

impl Outcome {
    fn name(self) -> &'static str {
        match self {
            Outcome::Ok => "ok",
            Outcome::Bad => "bad",
            Outcome::Wait => "wait",
            Outcome::Err => "err",
        }
    }

    fn status(self) -> (StatusCode, &'static str) {
        match self {
            Outcome::Ok => (StatusCode::OK, "ok\n"),
            Outcome::Bad => (StatusCode::BAD_REQUEST, "bad request\n"),
            Outcome::Wait => (StatusCode::TOO_MANY_REQUESTS, "too many requests, try again later\n"),
            Outcome::Err => (StatusCode::SERVICE_UNAVAILABLE, "not stored, try again later\n"),
        }
    }
}

/// The form's fields, each at most once.
#[derive(Default)]
struct Form {
    email: Option<String>,
    list: Option<String>,
    consent: Option<String>,
    from: Option<String>,
    website: Option<String>,
}

fn parse_form(body: &[u8]) -> Option<Form> {
    let mut f = Form::default();
    for (k, v) in form_urlencoded::parse(body) {
        let slot = match &*k {
            "email" => &mut f.email,
            "list" => &mut f.list,
            "consent" => &mut f.consent,
            "from" => &mut f.from,
            "website" => &mut f.website,
            _ => return None,
        };
        if slot.replace(v.into_owned()).is_some() {
            return None;
        }
    }
    Some(f)
}

async fn notify(State(app): State<Arc<App>>, req: Request) -> Response {
    let cfg = &app.cfg;
    let headers = req.headers().clone();
    let origin = headers.get(header::ORIGIN);
    let same_site = origin.is_some_and(|o| o.as_bytes() == cfg.site_origin.as_bytes());
    if origin.is_some() && !same_site {
        return plain(StatusCode::BAD_REQUEST, "bad request\n");
    }
    let script = headers
        .get(header::ACCEPT)
        .and_then(|a| a.to_str().ok())
        .is_some_and(|a| a.contains("application/json"));
    let is_form = headers
        .get(header::CONTENT_TYPE)
        .and_then(|c| c.to_str().ok())
        .is_some_and(|c| {
            c.split(';').next().unwrap_or("").trim().eq_ignore_ascii_case("application/x-www-form-urlencoded")
        });
    if !is_form {
        return plain(StatusCode::BAD_REQUEST, "bad request\n");
    }
    let peer = req.extensions().get::<ConnectInfo<SocketAddr>>().map(|c| c.0.ip());
    let ip = client_ip(&headers, &cfg.client_ip_header).or(peer);

    let Ok(body) = axum::body::to_bytes(req.into_body(), cfg.max_body).await else {
        return plain(StatusCode::BAD_REQUEST, "bad request\n");
    };
    let Some(form) = parse_form(&body) else {
        return plain(StatusCode::BAD_REQUEST, "bad request\n");
    };
    let page = form
        .from
        .as_deref()
        .and_then(|f| cfg.pages.iter().find(|p| p.name == f))
        .unwrap_or(&cfg.pages[0]);

    let outcome = signup(&app, &form, ip).await;
    let mut resp = if script {
        let (status, text) = outcome.status();
        plain(status, text)
    } else {
        let to = format!("{}{}#notify-{}", cfg.site_origin, page.path, outcome.name());
        let mut r = plain(StatusCode::SEE_OTHER, "");
        match HeaderValue::from_str(&to) {
            Ok(v) => r.headers_mut().insert(header::LOCATION, v),
            Err(_) => return plain(StatusCode::INTERNAL_SERVER_ERROR, "server error\n"),
        };
        r
    };
    if same_site {
        let h = resp.headers_mut();
        h.insert(header::ACCESS_CONTROL_ALLOW_ORIGIN, origin.cloned().expect("same_site has an origin"));
        h.insert(header::VARY, HeaderValue::from_static("Origin"));
    }
    resp
}

async fn signup(app: &Arc<App>, form: &Form, ip: Option<IpAddr>) -> Outcome {
    let cfg = &app.cfg;
    // every attempt counts, a refused one too; a request with no client address shares one bucket
    let ip = ip.unwrap_or(IpAddr::from([0, 0, 0, 0]));
    if !app.limit.lock().expect("rate limit lock").allow(ip, Instant::now()) {
        eprintln!("vhrd_notify: refused, too many from one client");
        return Outcome::Wait;
    }
    if form.website.as_deref().is_some_and(|w| !w.is_empty()) {
        eprintln!("vhrd_notify: honeypot filled, nothing stored");
        return Outcome::Ok;
    }
    let (Some(email), Some(list), Some(consent)) = (&form.email, &form.list, &form.consent) else {
        return Outcome::Bad;
    };
    let email = match Email::parse(email) {
        Ok(e) => e,
        Err(why) => {
            eprintln!("vhrd_notify: refused: {why}");
            return Outcome::Bad;
        }
    };
    if !cfg.lists.contains(list) || !cfg.consent_versions.contains(consent) {
        eprintln!("vhrd_notify: refused: unknown list or consent version");
        return Outcome::Bad;
    }
    let (store, list, consent, max) = (app.store.clone(), list.clone(), consent.clone(), cfg.max_signups);
    let time = crate::utc::format(crate::utc::now_secs());
    let added = tokio::task::spawn_blocking(move || store.add(&email, &list, &consent, &time, max)).await;
    match added {
        Ok(Ok(Added::New)) => {
            eprintln!("vhrd_notify: signed up");
            Outcome::Ok
        }
        Ok(Ok(Added::Duplicate)) => Outcome::Ok,
        Ok(Ok(Added::Full)) => {
            eprintln!("vhrd_notify: store full (max_signups {max}), refused");
            Outcome::Err
        }
        Ok(Err(e)) => {
            eprintln!("vhrd_notify: store: {e}");
            Outcome::Err
        }
        Err(e) => {
            eprintln!("vhrd_notify: store task: {e}");
            Outcome::Err
        }
    }
}

fn client_ip(headers: &HeaderMap, name: &str) -> Option<IpAddr> {
    if name.is_empty() {
        return None;
    }
    headers.get(name)?.to_str().ok()?.trim().parse().ok()
}

fn plain(status: StatusCode, text: &'static str) -> Response {
    let mut r = (status, Body::from(text)).into_response();
    let h = r.headers_mut();
    h.insert(header::CONTENT_TYPE, HeaderValue::from_static("text/plain; charset=utf-8"));
    h.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    h.insert(header::X_CONTENT_TYPE_OPTIONS, HeaderValue::from_static("nosniff"));
    r
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn form_fields_once_and_known_only() {
        let f = parse_form(b"email=a%40b.no&list=donguru&consent=v1&from=home&website=").unwrap();
        assert_eq!(f.email.as_deref(), Some("a@b.no"));
        assert_eq!(f.website.as_deref(), Some(""));
        assert!(parse_form(b"email=a&email=b").is_none());
        assert!(parse_form(b"email=a&admin=1").is_none());
        // a + is a space in a form body: the address check refuses it later
        assert_eq!(parse_form(b"email=a+b%40c.no").unwrap().email.as_deref(), Some("a b@c.no"));
    }
}
