//! The e-mail signup behind vhrd.tech's "Get notified" forms (AGENTS.md "Notify service"): the address check
//! ([`email`]), the append-only store ([`store`]), the per-client rate limit ([`limit`]) and the HTTP endpoint
//! ([`server`]), with its settings ([`config`]). The `vhrd_notify` binary (crate `vhrd_notify_cli`) serves it and
//! lists, counts, exports and deletes signups.

pub mod config;
pub mod email;
pub mod limit;
pub mod server;
pub mod store;
pub mod utc;

pub use config::Config;
pub use email::Email;
pub use store::Store;
