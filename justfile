# vhrd.tech, a Zola site: test builds and checks it, lint checks the sources, install puts the pinned Zola on this
# PC, brand pulls the stylesheets from vhrd_brand, deploy-preview publishes a noindex build to static.vhrd.tech.

zola_version := "0.23.6"
brand := env("VHRD_BRAND", home_directory() / "git/vhrd_brand")
preview_url := "https://static.vhrd.tech/vhrd-site-preview/"

export PATH := home_directory() / ".local/bin:" + env("PATH")
# The footer's build stamp: short hash (with -dirty) and commit date, read by the templates through get_env
export VHRD_GIT := `git describe --always --dirty --abbrev=7 2>/dev/null || echo unknown`
export VHRD_BUILT := `git log -1 --format=%cd --date=format:'%-d %b %Y' 2>/dev/null || true`

# Bare `just` only lists the recipes
default:
    @just --list

# Serve with live reload on http://127.0.0.1:1111
serve:
    zola serve

# Build into public/ (links and the site's own files checked first)
build:
    zola check --skip-external-links
    zola build

# The site builds, internal links resolve, every page passes the browser checks, the brand files match vhrd_brand
# (when it is checked out here)
test *args:
    zola --version | grep -qF "{{ zola_version }}" || { echo "zola {{ zola_version }} expected: just install"; exit 1; }
    zola check --skip-external-links
    zola build --output-dir target/test --force
    uv run tools/check_pages.py
    if [ -d "{{ brand }}/web" ]; then diff -q "{{ brand }}/web/tokens.css" static/css/brand/tokens.css && diff -q "{{ brand }}/web/vhrd.css" static/css/brand/vhrd.css; else echo "note: {{ brand }} missing, brand files not compared"; fi

# Every page in headless Chromium at phone, tablet and desktop widths, dark and light: no console errors, no sideways
# scroll, theme toggle, keyboard tabs (needs chromium)
check-browser:
    uv run tools/check_pages.py

# The same checks against the deployed preview, with full-page screenshots at 390 and 1440 px into DIR
check-preview dir="target/shots":
    uv run tools/check_pages.py "{{ preview_url }}" --shots "{{ dir }}"

# No whitespace errors, the tools parse
lint:
    git diff --check HEAD
    uv run --no-project python -m py_compile tools/wordmark.py tools/check_pages.py

# Install the pinned Zola release binary into ~/.local/bin (no root)
install:
    mkdir -p ~/.local/bin
    curl -fsSL "https://github.com/getzola/zola/releases/download/v{{ zola_version }}/zola-v{{ zola_version }}-$(uname -m)-unknown-linux-gnu.tar.gz" | tar xz -C ~/.local/bin zola
    zola --version

# Pull tokens.css and vhrd.css from the vhrd_brand checkout (never edit them here) and note its version
brand:
    cp "{{ brand }}/web/tokens.css" "{{ brand }}/web/vhrd.css" static/css/brand/
    git -C "{{ brand }}" describe --tags --always --dirty > static/css/brand/VERSION
    cat static/css/brand/VERSION

# Redraw the wordmark outlines from vhrd_brand's Audiowide (the font itself is never published)
wordmark:
    uv run tools/wordmark.py "{{ brand }}/typst/vhrd/fonts/Audiowide-Regular.ttf"

# Publish a noindex build to https://static.vhrd.tech/vhrd-site-preview/ (public: nothing private goes there).
# Needs a PC whose ssh key the deploy user accepts. The server's mover only creates dirs: before a re-deploy the old
# vhrd-site-preview dir must be moved away on the server by hand (README "Preview"). The mover exits 0 even when it
# could not move, so the last line checks that the live footer carries this build's hash.
deploy-preview:
    rm -rf target/preview
    zola check --skip-external-links
    VHRD_NOINDEX=1 zola build --base-url "{{ preview_url }}" --output-dir target/preview/vhrd-site-preview
    rsync -rlz --delete --chmod=D755,F644 --info=progress2 -e "ssh -p 7722" target/preview/vhrd-site-preview deploy@vhrd.tech:/home/deploy/to_static/
    ssh -p 7722 deploy@vhrd.tech "sudo /root/move_to_www_fix_perms.sh"
    curl -fsS "{{ preview_url }}" | grep -qF "built from <code>$VHRD_GIT</code>" && echo "live: {{ preview_url }} ($VHRD_GIT)"
