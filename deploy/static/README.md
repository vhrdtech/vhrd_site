# Re-deploys to static.vhrd.tech (draft, not installed)

**Draft.** This root helper is not installed on vhrd.tech. It is security-sensitive (a new sudo script on the web server) and waits for its own security review; Roman installs it after that. Until then a re-deploy needs the old dir moved away by hand (top-level README, "Preview").

The preview lives in one top-level dir of static.vhrd.tech, `/vhrd-site-preview/`. Uploads go to the deploy user's inbox, `/home/deploy/to_static/`, and a root script moves them into the web root, `/usr/share/nginx/static.vhrd.tech/`.

The server's `/root/move_to_www_fix_perms.sh` only creates dirs. When the dir already exists it prints `mv: cannot overwrite ...: Directory not empty`, still exits 0, and leaves the upload in the inbox, owned by www-data. So it serves the first deploy only.

`static_replace.sh NAME` does the re-deploy:

1. It takes only a plain name (lowercase letters, digits and `-`) and refuses symlinks.
2. It moves the live dir to `/root/static_replaced/NAME-<time>`, so a bad deploy can be undone.
3. It moves the upload in, drops any symlinks in it, and sets www-data ownership with 755 dirs and 644 files.

`sudoers-static` lets the deploy user run it.

## Install (as root on vhrd.tech)

From this directory (scp and sftp are not set up, so through an ssh pipe):

```sh
tar c static_replace.sh sudoers-static | ssh -p 7722 roman@vhrd.tech 'mkdir -p /tmp/static && tar x -C /tmp/static'
ssh -p 7722 roman@vhrd.tech
```

Then on the server:

```sh
cd /tmp/static
sudo install -m 700 static_replace.sh /root/
sudo visudo -cf sudoers-static && sudo install -m 440 sudoers-static /etc/sudoers.d/static
rm -r /tmp/static
```

Check from a PC whose key the deploy user accepts: `ssh -p 7722 deploy@vhrd.tech "sudo -ln"` lists `/root/static_replace.sh`.

The first deploy of the preview (4 Nov 2026) went through the mover. A second upload then stuck in the inbox, owned by www-data, so the deploy user can't overwrite it. Right after installing the script, run it once to put that upload live and clear the inbox: `ssh -p 7722 deploy@vhrd.tech "sudo /root/static_replace.sh vhrd-site-preview"`. From then on `just deploy-preview` works for every deploy.

What the deploy user gains: it can replace any top-level dir of static.vhrd.tech, not only create new ones. The replaced dir is kept under `/root/static_replaced/`, never deleted.

## Known problem, to fix before install

After the `mv` the tree is still owned by deploy. Between `find -type f` and `chmod`, deploy can swap a file for a symlink, and `chmod` follows it (for example `chmod 644 /etc/shadow`). The fix: copy the upload as root into a fresh root-owned dir without following links, or chown it to root first, and only then fix the permissions and move it live.
