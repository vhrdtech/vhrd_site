//! The endpoint as nginx would reach it: the router driven in-process, and once over a real socket.

use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};

use axum::body::Body;
use axum::extract::ConnectInfo;
use axum::http::{Request, StatusCode, header};
use tower::ServiceExt;
use vhrd_notify::server::{App, router};
use vhrd_notify::{Config, Store};

/// A config with its own store in a fresh temp folder.
fn config() -> (Config, PathBuf) {
    static N: AtomicU32 = AtomicU32::new(0);
    let dir = std::env::temp_dir().join(format!(
        "vhrd_notify-endpoint-{}-{}",
        std::process::id(),
        N.fetch_add(1, Ordering::Relaxed)
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let cfg = Config {
        store: dir.join("signups.tsv"),
        ..Config::default()
    };
    (cfg, dir)
}

/// The records once the worker has folded the accepted signups in (the in-process router runs no worker).
fn records(store: &Store) -> Vec<vhrd_notify::store::Record> {
    let rules = Config::default().rules();
    store
        .transact(|intake, st| {
            vhrd_notify::list::fold(&mut st.records, intake, &rules, vhrd_notify::store::Id::random)?;
            Ok((false, st.records.clone()))
        })
        .unwrap()
}

const FORM: &str = "application/x-www-form-urlencoded";

struct Post<'a> {
    body: &'a str,
    script: bool,
    origin: Option<&'a str>,
    ip: &'a str,
    content_type: &'a str,
}

impl Default for Post<'_> {
    fn default() -> Self {
        Post {
            body: "",
            script: true,
            origin: Some("https://vhrd.tech"),
            ip: "192.0.2.10",
            content_type: FORM,
        }
    }
}

async fn send(app: &axum::Router, p: Post<'_>) -> (StatusCode, Option<String>, String) {
    let mut req = Request::post("/api/notify")
        .header(header::CONTENT_TYPE, p.content_type)
        .header("x-real-ip", p.ip);
    if p.script {
        req = req.header(header::ACCEPT, "application/json");
    }
    if let Some(o) = p.origin {
        req = req.header(header::ORIGIN, o);
    }
    let mut req = req.body(Body::from(p.body.to_owned())).unwrap();
    req.extensions_mut()
        .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 1], 40000))));
    let resp = app.clone().oneshot(req).await.unwrap();
    let status = resp.status();
    assert_eq!(resp.headers()[header::CACHE_CONTROL], "no-store");
    let location = resp
        .headers()
        .get(header::LOCATION)
        .map(|l| l.to_str().unwrap().to_owned());
    let body = axum::body::to_bytes(resp.into_body(), 4096).await.unwrap();
    (status, location, String::from_utf8(body.to_vec()).unwrap())
}

fn good(email: &str) -> String {
    format!(
        "email={}&list=donguru&consent=2026-11-05&from=donguru&leave_empty=",
        email.replace('@', "%40")
    )
}

#[tokio::test]
async fn signup_is_stored_once() {
    let (cfg, dir) = config();
    let store = Store::new(&cfg.store);
    let app = router(App::new(cfg));
    let body = good("Someone@Example.com");
    let (s, _, text) = send(
        &app,
        Post {
            body: &body,
            ..Default::default()
        },
    )
    .await;
    assert_eq!((s, text.as_str()), (StatusCode::OK, "ok\n"));
    // the same address again: the same answer, nothing new stored
    let (s, _, _) = send(
        &app,
        Post {
            body: &body,
            ..Default::default()
        },
    )
    .await;
    assert_eq!(s, StatusCode::OK);
    let all = records(&store);
    assert_eq!(all.len(), 1);
    assert_eq!(
        (all[0].email.as_str(), all[0].list.as_str(), all[0].consent.as_str()),
        ("someone@example.com", "donguru", "2026-11-05")
    );
    assert_eq!(all[0].status, vhrd_notify::store::Status::Pending);
    std::fs::remove_dir_all(dir).unwrap();
}

#[tokio::test]
async fn without_script_redirects_back_to_the_page() {
    let (cfg, dir) = config();
    let app = router(App::new(cfg));
    let body = good("a@b.no").replace("from=donguru", "from=home");
    let (s, loc, _) = send(
        &app,
        Post {
            body: &body,
            script: false,
            ..Default::default()
        },
    )
    .await;
    assert_eq!(s, StatusCode::SEE_OTHER);
    assert_eq!(loc.as_deref(), Some("https://vhrd.tech/#notify-ok"));
    let body = "email=nope&list=donguru&consent=2026-11-05&from=donguru";
    let (s, loc, _) = send(
        &app,
        Post {
            body,
            script: false,
            ..Default::default()
        },
    )
    .await;
    assert_eq!(s, StatusCode::SEE_OTHER);
    assert_eq!(loc.as_deref(), Some("https://vhrd.tech/donguru/#notify-bad"));
    // a page not listed goes to the first one, never to a place the form names
    let body = "email=nope&list=donguru&consent=2026-11-05&from=https%3A%2F%2Fevil.example";
    let (_, loc, _) = send(
        &app,
        Post {
            body,
            script: false,
            ..Default::default()
        },
    )
    .await;
    assert_eq!(loc.as_deref(), Some("https://vhrd.tech/donguru/#notify-bad"));
    std::fs::remove_dir_all(dir).unwrap();
}

#[tokio::test]
async fn bad_input_is_a_plain_400_that_echoes_nothing() {
    let (cfg, dir) = config();
    let store = Store::new(&cfg.store);
    let app = router(App::new(Config { rate_limit: 100, ..cfg }));
    let evil = "<script>alert(1)</script>";
    let bodies = [
        format!("email={evil}&list=donguru&consent=2026-11-05"),
        "email=a%40b.no%0D%0ABcc%3A+x%40y.no&list=donguru&consent=2026-11-05".into(),
        "email=r%C3%B8m%C3%A5n%40example.no&list=donguru&consent=2026-11-05".into(),
        "email=a%40b.no&list=other&consent=2026-11-05".into(),
        "email=a%40b.no&list=donguru&consent=1999-01-01".into(),
        "email=a%40b.no&list=donguru".into(),
        format!("email=a%40b.no&list=donguru&consent=2026-11-05&{evil}=1"),
        "email=a%40b.no&email=c%40d.no&list=donguru&consent=2026-11-05".into(),
        format!("email={}%40b.no&list=donguru&consent=2026-11-05", "a".repeat(300)),
        "email=%FF%FE%40b.no&list=donguru&consent=2026-11-05".into(),
    ];
    for body in &bodies {
        let (s, _, text) = send(
            &app,
            Post {
                body,
                ..Default::default()
            },
        )
        .await;
        assert_eq!(s, StatusCode::BAD_REQUEST, "{body}");
        assert_eq!(text, "bad request\n");
    }
    // another site's page, another content type
    let body = good("a@b.no");
    let (s, _, _) = send(
        &app,
        Post {
            body: &body,
            origin: Some("https://evil.example"),
            ..Default::default()
        },
    )
    .await;
    assert_eq!(s, StatusCode::BAD_REQUEST);
    let (s, _, _) = send(
        &app,
        Post {
            body: &body,
            content_type: "application/json",
            ..Default::default()
        },
    )
    .await;
    assert_eq!(s, StatusCode::BAD_REQUEST);
    // over the size limit
    let big = format!("{body}&from={}", "x".repeat(1100));
    let (s, _, text) = send(
        &app,
        Post {
            body: &big,
            ..Default::default()
        },
    )
    .await;
    assert_eq!((s, text.as_str()), (StatusCode::BAD_REQUEST, "bad request\n"));
    assert!(records(&store).is_empty());
    std::fs::remove_dir_all(dir).unwrap();
}

#[tokio::test]
async fn honeypot_looks_fine_and_stores_nothing() {
    let (cfg, dir) = config();
    let store = Store::new(&cfg.store);
    let app = router(App::new(cfg));
    let body = good("bot@example.com").replace("leave_empty=", "leave_empty=http%3A%2F%2Fspam.example");
    let (s, _, _) = send(
        &app,
        Post {
            body: &body,
            ..Default::default()
        },
    )
    .await;
    assert_eq!(s, StatusCode::OK);
    assert!(records(&store).is_empty());
    std::fs::remove_dir_all(dir).unwrap();
}

#[tokio::test]
async fn rate_limit_per_client() {
    let (cfg, dir) = config();
    let app = router(App::new(Config { rate_limit: 2, ..cfg }));
    for i in 0..2 {
        let body = good(&format!("p{i}@example.com"));
        assert_eq!(
            send(
                &app,
                Post {
                    body: &body,
                    ..Default::default()
                }
            )
            .await
            .0,
            StatusCode::OK
        );
    }
    let body = good("p9@example.com");
    let (s, _, _) = send(
        &app,
        Post {
            body: &body,
            ..Default::default()
        },
    )
    .await;
    assert_eq!(s, StatusCode::TOO_MANY_REQUESTS);
    let (s, loc, _) = send(
        &app,
        Post {
            body: &body,
            script: false,
            ..Default::default()
        },
    )
    .await;
    assert_eq!(
        (s, loc.as_deref()),
        (StatusCode::SEE_OTHER, Some("https://vhrd.tech/donguru/#notify-wait"))
    );
    // another client is not held back
    let (s, _, _) = send(
        &app,
        Post {
            body: &body,
            ip: "198.51.100.4",
            ..Default::default()
        },
    )
    .await;
    assert_eq!(s, StatusCode::OK);
    std::fs::remove_dir_all(dir).unwrap();
}

#[tokio::test]
async fn full_store_is_a_503() {
    let (cfg, dir) = config();
    let a = App::new(Config { max_signups: 1, ..cfg });
    let app = router(a.clone());
    assert_eq!(
        send(
            &app,
            Post {
                body: &good("a@b.no"),
                ..Default::default()
            }
        )
        .await
        .0,
        StatusCode::OK
    );
    // the worker's round counts the records
    vhrd_notify::outbox::tick(&a, vhrd_notify::utc::now_secs()).unwrap();
    let (s, _, _) = send(
        &app,
        Post {
            body: &good("c@d.no"),
            ..Default::default()
        },
    )
    .await;
    assert_eq!(s, StatusCode::SERVICE_UNAVAILABLE);
    std::fs::remove_dir_all(dir).unwrap();
}

#[tokio::test]
async fn same_site_gets_cors_and_other_paths_404() {
    let (cfg, dir) = config();
    let app = router(App::new(cfg));
    let mut req = Request::post("/api/notify")
        .header(header::CONTENT_TYPE, FORM)
        .header(header::ORIGIN, "https://vhrd.tech")
        .body(Body::from(good("a@b.no")))
        .unwrap();
    req.extensions_mut()
        .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 1], 40000))));
    let resp = app.clone().oneshot(req).await.unwrap();
    assert_eq!(resp.headers()[header::ACCESS_CONTROL_ALLOW_ORIGIN], "https://vhrd.tech");
    assert_eq!(resp.headers().get(header::SET_COOKIE), None);
    let req = Request::get("/api/other").body(Body::empty()).unwrap();
    assert_eq!(app.clone().oneshot(req).await.unwrap().status(), StatusCode::NOT_FOUND);
    let req = Request::get("/api/notify").body(Body::empty()).unwrap();
    assert_eq!(app.oneshot(req).await.unwrap().status(), StatusCode::METHOD_NOT_ALLOWED);
    std::fs::remove_dir_all(dir).unwrap();
}

/// The whole stack over a socket: a raw HTTP/1.1 request, a body over the limit with a Content-Length that says so.
#[tokio::test]
async fn over_a_real_socket() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let (cfg, dir) = config();
    let store = Store::new(&cfg.store);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let app = router(App::new(Config {
        client_ip_header: String::new(),
        ..cfg
    }));
    tokio::spawn(async move {
        axum::serve(listener, app.into_make_service_with_connect_info::<SocketAddr>())
            .await
            .unwrap();
    });
    async fn raw(addr: SocketAddr, body: &str) -> String {
        let mut s = tokio::net::TcpStream::connect(addr).await.unwrap();
        let req = format!(
            "POST /api/notify HTTP/1.1\r\nHost: x\r\nContent-Type: {FORM}\r\nAccept: application/json\r\n\
             Content-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        );
        s.write_all(req.as_bytes()).await.unwrap();
        let mut out = String::new();
        s.read_to_string(&mut out).await.unwrap();
        out
    }
    let ok = raw(addr, &good("sock@example.com")).await;
    assert!(ok.starts_with("HTTP/1.1 200"), "{ok}");
    let big = raw(addr, &"x".repeat(5000)).await;
    assert!(big.starts_with("HTTP/1.1 400"), "{big}");
    assert_eq!(records(&store).len(), 1);
    std::fs::remove_dir_all(dir).unwrap();
}

/// Every answer names the release (the Deploy workflow's check from outside), and a probe that is not the form
/// costs the prober none of its rate limit.
#[tokio::test]
async fn answers_name_the_release() {
    use vhrd_notify::server::RELEASE_HEADER;
    let (cfg, dir) = config();
    let app = router(App::with_release(Config { rate_limit: 1, ..cfg }, Some("abc1234")));
    for _ in 0..3 {
        let req = Request::post("/api/notify")
            .header(header::CONTENT_TYPE, FORM)
            .header(header::ACCEPT, "application/json")
            .header("x-real-ip", "192.0.2.10")
            .body(Body::from("probe=1"))
            .unwrap();
        let resp = app.clone().oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
        assert_eq!(resp.headers()[RELEASE_HEADER], "abc1234");
    }
    let req = Request::get("/elsewhere").body(Body::empty()).unwrap();
    assert_eq!(
        app.clone().oneshot(req).await.unwrap().headers()[RELEASE_HEADER],
        "abc1234"
    );
    // the probes above used none of the one signup this client may send
    let body = good("probe@example.com");
    let (s, _, _) = send(
        &app,
        Post {
            body: &body,
            ..Default::default()
        },
    )
    .await;
    assert_eq!(s, StatusCode::OK);
    // without a release, no header
    let (cfg, dir2) = config();
    let req = Request::get("/elsewhere").body(Body::empty()).unwrap();
    let resp = router(App::new(cfg)).oneshot(req).await.unwrap();
    assert_eq!(resp.headers().get(RELEASE_HEADER), None);
    std::fs::remove_dir_all(dir).unwrap();
    std::fs::remove_dir_all(dir2).unwrap();
}
