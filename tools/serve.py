# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Serve the site with live reload on this PC's Tailscale address, so another PC or a phone on the tailnet can
open the working tree while it rebuilds, without landing or deploying.

Usage: uv run tools/serve.py [PORT]   (just serve [PORT])

Without PORT, the first free port from 1111 up is used, so more than one session can serve on the same PC at
once. Prints the URL to open: this PC's Tailscale MagicDNS name (`tailscale status --json` Self.DNSName) when it
has one, else its Tailscale IPv4 address (`tailscale ip -4`), with the chosen port. Binds only that Tailscale
address, never 0.0.0.0: these PCs sit on public wifi too. zola's live reload runs its websocket on the same port
as the page (checked against zola 0.23.6), so nothing else needs to be reachable.

When Tailscale is down, falls back to 127.0.0.1 with a clear message: reachable only on this PC.

The signup forms post to a local notify service (README "Notify service"): it is built with cargo and started on the
next free port of the same address, with its own settings and store in target/notify-dev/, and the site is told
where it is through VHRD_NOTIFY_API. It stops with the site. Without cargo the forms have nowhere to post.
"""

import json
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

START_PORT = 1111
MAX_ATTEMPTS = 200


def tailscale_host():
    """(bind_ip, display_host) from Tailscale, or (None, None) when it is down."""
    try:
        ip = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
        status = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    if ip.returncode != 0 or not ip.stdout.strip():
        return None, None
    bind_ip = ip.stdout.strip().splitlines()[0]
    display = bind_ip
    if status.returncode == 0:
        try:
            dns_name = json.loads(status.stdout)["Self"]["DNSName"].rstrip(".")
            if dns_name:
                display = dns_name
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    return bind_ip, display


def free_port(interface, requested=None, skip=()):
    candidates = [requested] if requested else range(START_PORT, START_PORT + MAX_ATTEMPTS)
    for port in candidates:
        if port in skip:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((interface, port))
                return port
            except OSError:
                continue
    where = f"port {requested}" if requested else f"a free port from {START_PORT} up"
    sys.exit(f"serve: no {where} available on {interface}")


def main():
    requested = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else None

    bind_ip, display = tailscale_host()
    if bind_ip is None:
        print("serve: Tailscale is down, serving on 127.0.0.1 only (not reachable from other PCs)", file=sys.stderr)
        bind_ip = display = "127.0.0.1"

    port = free_port(bind_ip, requested)
    service = notify_service(bind_ip, display, port)
    print(f"serve: open http://{display}:{port}/")
    sys.stdout.flush()

    zola = ["zola", "serve", "--interface", bind_ip, "--port", str(port), "--base-url", display]
    if service is None:
        os.execvp("zola", zola)
    # zola and the service end together: Ctrl-C reaches both, a SIGTERM to this script is passed on
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        sys.exit(subprocess.call(zola))
    except KeyboardInterrupt:
        pass
    finally:
        service.terminate()
        service.wait()


def notify_service(bind_ip, display, site_port):
    """Build and start the notify service on the next free port beside the site; None without cargo."""
    root = Path(__file__).resolve().parent.parent
    try:
        build = subprocess.run(["cargo", "build", "--quiet", "-p", "vhrd_notify_cli"], cwd=root)
    except OSError:
        print("serve: no cargo, the signup forms have nowhere to post", file=sys.stderr)
        return None
    if build.returncode != 0:
        sys.exit("serve: the notify service did not build")
    port = free_port(bind_ip, skip={site_port})
    dev = root / "target" / "notify-dev"
    dev.mkdir(parents=True, exist_ok=True)
    # a local instance: the site's own origin, no proxy in front, a store of its own
    (dev / "notify.toml").write_text(
        f'listen = "{bind_ip}:{port}"\nstore = "signups.tsv"\nsite_origin = "http://{display}:{site_port}"\n'
        'client_ip_header = ""\n'
    )
    os.environ["VHRD_NOTIFY_API"] = f"http://{display}:{port}/api/notify"
    exe = root / "target" / "debug" / "vhrd_notify"
    service = subprocess.Popen([exe, "serve", "--config", dev / "notify.toml"])
    print(f"serve: notify service on port {port}, signups in {dev / 'signups.tsv'} (vhrd_notify list --config {dev / 'notify.toml'})")
    return service


if __name__ == "__main__":
    main()
