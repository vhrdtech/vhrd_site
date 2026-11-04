# vhrd.tech, a Zola site: test builds and checks it, lint checks the sources, install puts the pinned Zola on this
# PC, brand pulls the stylesheets from vhrd_brand, live builds the site for vhrd.tech, preview a noindex copy
# for a share link.

zola_version := "0.23.6"
brand := env("VHRD_BRAND", home_directory() / "git/vhrd_brand")
preview_host := "https://shadow.vhrd.tech"

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

# The site builds, internal links resolve, the old WordPress paths redirect to its pages (deploy/redirects.map), every
# page passes the browser checks, the brand files match vhrd_brand (when it is checked out here)
test *args:
    zola --version | grep -qF "{{ zola_version }}" || { echo "zola {{ zola_version }} expected: just install"; exit 1; }
    zola check --skip-external-links
    zola build --output-dir target/test --force
    python3 tools/check_live.py redirects target/test
    uv run tools/check_pages.py
    if [ -d "{{ brand }}/web" ]; then diff -q "{{ brand }}/web/tokens.css" static/css/brand/tokens.css && diff -q "{{ brand }}/web/vhrd.css" static/css/brand/vhrd.css; else echo "note: {{ brand }} missing, brand files not compared"; fi

# Every page in headless Chromium at phone, tablet and desktop widths, dark and light: no console errors, no sideways
# scroll, theme toggle, keyboard tabs (needs chromium)
check-browser:
    uv run tools/check_pages.py

# The same checks against a deployed preview (its full URL), with full-page screenshots at 390 and 1440 px into DIR
check-preview url dir="target/shots":
    uv run tools/check_pages.py "{{ url }}" --shots "{{ dir }}"

# No whitespace errors, the tools parse, the deploy workflow passes actionlint and zizmor. Check only: the bytecode
# goes to a temp dir, never into the tree
lint:
    git diff --check HEAD
    PYTHONPYCACHEPREFIX="$(mktemp -d)" uv run --no-project python -m py_compile tools/wordmark.py tools/check_pages.py tools/samples.py tools/perf.py tools/fonts.py tools/check_live.py scripts/render_boards.py
    uvx --from actionlint-py actionlint .github/workflows/deploy.yml
    uvx zizmor --offline .github/workflows/deploy.yml

# Install the pinned Zola release binary into ~/.local/bin (no root)
install:
    mkdir -p ~/.local/bin
    curl -fsSL "https://github.com/getzola/zola/releases/download/v{{ zola_version }}/zola-v{{ zola_version }}-$(uname -m)-unknown-linux-gnu.tar.gz" | tar xz -C ~/.local/bin zola
    zola --version

# The front page's first screen on a slow phone (slow 4G, CPU / 4): requests, bytes, FCP, LCP, layout shift
perf *args:
    uv run tools/perf.py {{ args }}

# Cut the Core subset out of each IBM Plex Latin1 face and update fonts.css (after a change to the Latin1 files)
fonts:
    uv run tools/fonts.py

# Pull tokens.css and vhrd.css from the vhrd_brand checkout (never edit them here) and note its version
brand:
    cp "{{ brand }}/web/tokens.css" "{{ brand }}/web/vhrd.css" static/css/brand/
    git -C "{{ brand }}" describe --tags --always --dirty > static/css/brand/VERSION
    cat static/css/brand/VERSION

# Redraw the wordmark outlines from vhrd_brand's Audiowide (the font itself is never published)
wordmark:
    uv run tools/wordmark.py "{{ brand }}/typst/vhrd/fonts/Audiowide-Regular.ttf"

# Build the live site for https://vhrd.tech/ into target/live: indexable (robots.txt allows it and names the sitemap,
# every page has its canonical URL). WordPress is gone from vhrd.tech: its old paths (posts, /feed/, /product/,
# /cart/, ...) redirect on the server (deploy/redirects.map), and nothing of WordPress may ship.
live:
    rm -rf target/live
    zola check --skip-external-links
    zola build --base-url "https://vhrd.tech/" --output-dir target/live
    python3 tools/check_live.py built target/live --stamp "$VHRD_GIT"
    @echo "built https://vhrd.tech/ ($VHRD_GIT) in target/live"

# Deploy main to https://vhrd.tech/: starts the Deploy workflow on GitHub and follows it. It waits for approval in
# the production environment (README "Deploy")
deploy:
    gh workflow run deploy.yml --repo vhrdtech/vhrd_site --ref main
    @echo "approve it in GitHub (Actions > Deploy vhrd.tech), then: gh run watch --repo vhrdtech/vhrd_site"

# Check the deployed site against target/live (from `just live` at the same commit): every page 200, the footer
# stamp, every old WordPress path's 301, the site's own 404 page
check-live url="https://vhrd.tech":
    python3 tools/check_live.py site "{{ url }}" --built target/live --stamp "$VHRD_GIT" --full

# Build a noindex preview for https://shadow.vhrd.tech/TOKEN/ into target/preview/TOKEN. TOKEN is the share link's
# token, a fresh one per preview; the site is built for that base path, so it only works under that link. The
# folder is then uploaded as it is by the share tool, which the last line prints.
preview token:
    echo "{{ token }}" | grep -qE '^[A-Za-z0-9_-]+$' || { echo "token: letters, digits, - and _ only"; exit 1; }
    rm -rf "target/preview/{{ token }}"
    zola check --skip-external-links
    VHRD_NOINDEX=1 zola build --base-url "{{ preview_host }}/{{ token }}/" --output-dir "target/preview/{{ token }}"
    @echo "built {{ preview_host }}/{{ token }}/ ($VHRD_GIT) in target/preview/{{ token }}"
    @echo "upload: tpm share target/preview/{{ token }} --token {{ token }} -e 3m -t 'vhrd.tech preview $VHRD_GIT'"

# Rebuild board product renders in static/img/boards/ from ~/git/hw (KiCad). With --variants: only the missing web
# widths, from the PNG sources already here (no KiCad needed). Board numbers (b129 b133) limit it to those boards
renders *args:
    uv run scripts/render_boards.py {{ args }}
