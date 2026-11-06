//! Not run here: `ww api check` only reads this file's text to see it calls `wire_weaver_evolution::Check`
//! (tools/term/ww_evolution, never built). A real crate runs it with `cargo test`.

#[test]
fn api_evolution() {
    wire_weaver_evolution::Check::new(env!("CARGO_MANIFEST_DIR"))
        .require_current(true)
        .assert();
}
