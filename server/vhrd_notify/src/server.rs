//! `POST /api/notify`: one signup from the site's form.
//!
//! The form (`application/x-www-form-urlencoded`, at most `max_body` bytes) has the fields `email`, `list`,
//! `consent` (the version of the text shown next to it), `from` (the page it is on) and `leave_empty`, a honeypot no
//! person sees: when it is filled the answer is the same as for a signup, and nothing is stored.
//!
//! Two kinds of client get two kinds of answer, and neither ever carries the visitor's input:
//! - the page's script sends `Accept: application/json` and gets a status with a fixed plain-text body: 200
//!   accepted, 400 refused, 429 too many from this client, 503 not stored;
//! - a plain form post (no JavaScript) gets a 303 back to the page it came from, to `#notify-ok`, `#notify-bad`,
//!   `#notify-wait` or `#notify-err`, which the page shows (CSS `:target`).
//!
//! An accepted signup is one line appended to the store's intake and nothing more, the same work and the same
//! answer for every well-formed address: whether it is new, waiting for its confirmation or on the list already is
//! decided later by the worker ([`crate::outbox`], [`crate::list`]), and never shows in the answer.
//!
//! A request that is not the form at all (another content type, a body over the limit, a field twice or one not
//! listed above, an Origin of another site) gets a plain 400, and counts against no rate limit.
//!
//! Every answer carries [`RELEASE_HEADER`] with the release's git sha (the same one the site's footer shows), so the
//! Deploy workflow can tell from outside that the release it uploaded is the one answering.

use std::net::{IpAddr, SocketAddr};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use axum::Router;
use axum::body::Body;
use axum::extract::{ConnectInfo, Request, State};
use axum::http::{HeaderMap, HeaderValue, StatusCode, header};
use axum::middleware;
use axum::response::{IntoResponse, Response};
use axum::routing::post;

use crate::config::Config;
use crate::email::Email;
use crate::limit::RateLimit;
use crate::store::{Intake, Store};

/// The response header that names the release answering (`vhrd_notify --version`'s git sha).
pub const RELEASE_HEADER: &str = "x-vhrd-release";

pub struct App {
    pub(crate) cfg: Config,
    /// The value of [`RELEASE_HEADER`]; none in tests that don't set one.
    release: Option<HeaderValue>,
    pub(crate) store: Arc<Store>,
    /// Wakes the worker ([`crate::outbox`]) after a signup.
    pub(crate) wake: tokio::sync::Notify,
    /// Records pending and in all, as the worker last counted them.
    pub(crate) pending: AtomicUsize,
    pub(crate) records: AtomicUsize,
    /// The links' key ([`crate::token`]).
    pub(crate) key: crate::token::Key,
    /// How mail goes out; none without the settings' `[mail]` table.
    pub(crate) mailer: Option<crate::mail::Mailer>,
    limit: Mutex<RateLimit>,
    /// The limits of the confirm and remove buttons, and of the one-click unsubscribe, each counted on its own.
    pub(crate) link_limit: Mutex<RateLimit>,
    pub(crate) one_click_limit: Mutex<RateLimit>,
    /// The client address header was missing once already (said once in the log, not per request).
    header_missing: AtomicBool,
}

/// Why the service can't start: a setting, the key or the mail password. The binary exits 78 on it.
#[derive(Debug)]
pub enum ServeError {
    Setup(String),
    Io(std::io::Error),
}

impl std::fmt::Display for ServeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ServeError::Setup(s) => f.write_str(s),
            ServeError::Io(e) => write!(f, "{e}"),
        }
    }
}

impl From<std::io::Error> for ServeError {
    fn from(e: std::io::Error) -> Self {
        ServeError::Io(e)
    }
}

impl App {
    /// For tests: [`App::try_new`], panicking on a setup error.
    pub fn new(cfg: Config) -> Arc<App> {
        App::try_new(cfg, None).expect("app setup")
    }

    /// An app whose answers name `release` in [`RELEASE_HEADER`] (a release name that is not a valid header value
    /// is left out).
    pub fn with_release(cfg: Config, release: Option<&str>) -> Arc<App> {
        App::try_new(cfg, release).expect("app setup")
    }

    /// Loads (or makes) the token key and readies the mailer; answers name `release` as [`App::with_release`]
    /// says. A relative `token_key` is taken from the store's folder.
    pub fn try_new(mut cfg: Config, release: Option<&str>) -> Result<Arc<App>, String> {
        if cfg.token_key.is_relative()
            && let Some(dir) = cfg.store.parent()
        {
            cfg.token_key = dir.join(&cfg.token_key);
        }
        let key = crate::token::Key::load_or_create(&cfg.token_key)?;
        let mailer = cfg.mail.as_ref().map(crate::mail::Mailer::new).transpose()?;
        let limit = |client, network| {
            Mutex::new(RateLimit::new(
                client,
                network,
                Duration::from_secs(cfg.rate_window_secs),
                cfg.rate_clients,
            ))
        };
        Ok(Arc::new(App {
            store: Arc::new(Store::new(&cfg.store)),
            limit: limit(cfg.rate_limit, cfg.rate_limit_network),
            link_limit: limit(cfg.link_rate_limit, cfg.link_rate_limit_network),
            one_click_limit: limit(cfg.one_click_rate_limit, cfg.one_click_rate_limit),
            header_missing: AtomicBool::new(false),
            release: release.and_then(|r| HeaderValue::from_str(r).ok()),
            wake: tokio::sync::Notify::new(),
            pending: AtomicUsize::new(0),
            records: AtomicUsize::new(0),
            key,
            mailer,
            cfg,
        }))
    }
}

pub fn router(app: Arc<App>) -> Router {
    Router::new()
        .route("/api/notify", post(notify))
        .route("/api/notify/confirm", post(crate::links::confirm))
        .route("/api/notify/remove", post(crate::links::remove))
        .route(
            "/api/notify/unsubscribe",
            post(crate::links::one_click).get(crate::links::unsubscribe_page),
        )
        .fallback(|| async { plain(StatusCode::NOT_FOUND, "not found\n") })
        .layer(middleware::map_response_with_state(app.clone(), stamp))
        .with_state(app)
}

async fn stamp(State(app): State<Arc<App>>, mut r: Response) -> Response {
    if let Some(v) = &app.release {
        r.headers_mut().insert(RELEASE_HEADER, v.clone());
    }
    r
}

/// Serves until SIGTERM or Ctrl-C; every answer names `release` (see [`RELEASE_HEADER`]).
pub async fn serve(cfg: Config, release: &str) -> Result<(), ServeError> {
    let app = App::try_new(cfg, Some(release)).map_err(ServeError::Setup)?;
    let cfg = &app.cfg;
    if app.mailer.is_none() {
        eprintln!("vhrd_notify: no [mail] settings: mails stay in the outbox");
    }
    let listener = tokio::net::TcpListener::bind(&cfg.listen).await?;
    eprintln!(
        "vhrd_notify: listening on {}, store {}",
        listener.local_addr()?,
        cfg.store.display()
    );
    // the first round before the first request: a store that can't be read fails the start, not a signup
    crate::outbox::tick(&app, crate::utc::now_secs())?;
    tokio::spawn(crate::outbox::run(app.clone()));
    let app = router(app);
    axum::serve(listener, app.into_make_service_with_connect_info::<SocketAddr>())
        .with_graceful_shutdown(shutdown())
        .await?;
    Ok(())
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
    leave_empty: Option<String>,
}

fn parse_form(body: &[u8]) -> Option<Form> {
    let mut f = Form::default();
    for (k, v) in form_urlencoded::parse(body) {
        let slot = match &*k {
            "email" => &mut f.email,
            "list" => &mut f.list,
            "consent" => &mut f.consent,
            "from" => &mut f.from,
            "leave_empty" => &mut f.leave_empty,
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
    let script = wants_json(&headers);
    if !content_type_is(&headers, "application/x-www-form-urlencoded") {
        return plain(StatusCode::BAD_REQUEST, "bad request\n");
    }
    let ip = app.client(&headers, &req);

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
        h.insert(
            header::ACCESS_CONTROL_ALLOW_ORIGIN,
            origin.cloned().expect("same_site has an origin"),
        );
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
    if form.leave_empty.as_deref().is_some_and(|w| !w.is_empty()) {
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
    if app.pending.load(Ordering::Relaxed) >= cfg.max_pending || app.records.load(Ordering::Relaxed) >= cfg.max_signups
    {
        eprintln!(
            "vhrd_notify: store full (max_pending {} or max_signups {}), refused",
            cfg.max_pending, cfg.max_signups
        );
        return Outcome::Err;
    }
    let intake = Intake {
        time: crate::utc::now_secs(),
        list: list.clone(),
        email,
        consent: consent.clone(),
    };
    let (store, max) = (app.store.clone(), cfg.max_intake_bytes);
    match tokio::task::spawn_blocking(move || store.accept(&intake, max)).await {
        Ok(Ok(true)) => {
            app.wake.notify_one();
            Outcome::Ok
        }
        Ok(Ok(false)) => {
            eprintln!("vhrd_notify: intake full (max_intake_bytes {max}), refused");
            Outcome::Err
        }
        Ok(Err(e)) => {
            eprintln!("vhrd_notify: intake: {e}");
            Outcome::Err
        }
        Err(e) => {
            eprintln!("vhrd_notify: intake task: {e}");
            Outcome::Err
        }
    }
}

impl App {
    /// The client's address: from nginx's header, else the connection's (said once in the log when the header is
    /// missing).
    pub(crate) fn client(&self, headers: &HeaderMap, req: &Request) -> Option<IpAddr> {
        let cfg = &self.cfg;
        let peer = req.extensions().get::<ConnectInfo<SocketAddr>>().map(|c| c.0.ip());
        let ip = client_ip(headers, &cfg.client_ip_header);
        if ip.is_none() && !cfg.client_ip_header.is_empty() && !self.header_missing.swap(true, Ordering::Relaxed) {
            eprintln!(
                "vhrd_notify: no client address in {}: every such request shares one rate limit (nginx block missing?)",
                cfg.client_ip_header
            );
        }
        ip.or(peer)
    }
}

/// The page's script asks for a status instead of a redirect.
pub(crate) fn wants_json(headers: &HeaderMap) -> bool {
    headers
        .get(header::ACCEPT)
        .and_then(|a| a.to_str().ok())
        .is_some_and(|a| a.contains("application/json"))
}

pub(crate) fn content_type_is(headers: &HeaderMap, want: &str) -> bool {
    headers
        .get(header::CONTENT_TYPE)
        .and_then(|c| c.to_str().ok())
        .is_some_and(|c| c.split(';').next().unwrap_or("").trim().eq_ignore_ascii_case(want))
}

/// The Origin header is the site's or missing; `Some(origin)` when it is the site's.
pub(crate) fn origin_ok(cfg: &Config, headers: &HeaderMap) -> Result<Option<HeaderValue>, ()> {
    match headers.get(header::ORIGIN) {
        None => Ok(None),
        Some(o) if o.as_bytes() == cfg.site_origin.as_bytes() => Ok(Some(o.clone())),
        Some(_) => Err(()),
    }
}

/// CORS for the site's own script.
pub(crate) fn allow_origin(resp: &mut Response, origin: Option<HeaderValue>) {
    if let Some(o) = origin {
        let h = resp.headers_mut();
        h.insert(header::ACCESS_CONTROL_ALLOW_ORIGIN, o);
        h.insert(header::VARY, HeaderValue::from_static("Origin"));
    }
}

/// A 303 to `to`, which the caller built only from settings and checked tokens.
pub(crate) fn see_other(to: &str) -> Response {
    let mut r = plain(StatusCode::SEE_OTHER, "");
    match HeaderValue::from_str(to) {
        Ok(v) => {
            r.headers_mut().insert(header::LOCATION, v);
            r
        }
        Err(_) => plain(StatusCode::INTERNAL_SERVER_ERROR, "server error\n"),
    }
}

fn client_ip(headers: &HeaderMap, name: &str) -> Option<IpAddr> {
    if name.is_empty() {
        return None;
    }
    headers.get(name)?.to_str().ok()?.trim().parse().ok()
}

pub(crate) fn plain(status: StatusCode, text: &'static str) -> Response {
    let mut r = (status, Body::from(text)).into_response();
    let h = r.headers_mut();
    h.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("text/plain; charset=utf-8"),
    );
    h.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    h.insert(header::X_CONTENT_TYPE_OPTIONS, HeaderValue::from_static("nosniff"));
    r
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn form_fields_once_and_known_only() {
        let f = parse_form(b"email=a%40b.no&list=donguru&consent=v1&from=home&leave_empty=").unwrap();
        assert_eq!(f.email.as_deref(), Some("a@b.no"));
        assert_eq!(f.leave_empty.as_deref(), Some(""));
        assert!(parse_form(b"email=a&email=b").is_none());
        assert!(parse_form(b"email=a&admin=1").is_none());
        // a + is a space in a form body: the address check refuses it later
        assert_eq!(
            parse_form(b"email=a+b%40c.no").unwrap().email.as_deref(),
            Some("a b@c.no")
        );
    }
}
