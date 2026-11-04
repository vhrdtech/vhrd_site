#!/bin/sh
# DRAFT, not installed: has a known symlink race (README.md "Known problem"); waits for a security review.
# Replaces one top-level dir of static.vhrd.tech with the upload of the same name in the deploy user's inbox, for
# re-deploys that /root/move_to_www_fix_perms.sh can't do (it never overwrites an existing dir). The deploy user runs
# it with sudo. The live dir is moved to /root/static_replaced/ instead of deleted, so a wrong deploy can be undone.
set -eu
name="${1:-}"
case "$name" in
    '' | -* | *[!a-z0-9-]*) echo "usage: static_replace.sh NAME (lowercase letters, digits and -)" >&2; exit 2 ;;
esac
inbox="/home/deploy/to_static/$name"
live="/usr/share/nginx/static.vhrd.tech/$name"
if [ -L "$inbox" ] || [ ! -d "$inbox" ]; then
    echo "$inbox is not an uploaded directory" >&2
    exit 1
fi
if [ -L "$live" ]; then
    echo "$live is a symlink: left alone" >&2
    exit 1
fi
if [ -e "$live" ]; then
    mkdir -p /root/static_replaced
    mv "$live" "/root/static_replaced/$name-$(date +%Y%m%d-%H%M%S)"
fi
mv "$inbox" "$live"
# no links out of the web root, everything readable by nginx and nothing more
find "$live" -type l -delete
chown -R www-data:www-data "$live"
find "$live" -type d -exec chmod 755 {} +
find "$live" -type f -exec chmod 644 {} +
echo "replaced $live"
