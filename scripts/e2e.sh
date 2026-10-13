#!/usr/bin/env bash
# End-to-end checks of the Docker image against a local HTTP server on a private
# Docker network. No internet access is needed.
# Usage: scripts/e2e.sh [IMAGE]   (default: rss-reader-try)
set -euo pipefail

IMAGE=${1:-rss-reader-try}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
NETWORK=rss-reader-try-e2e-$$
SERVER=feeds-$$
URL=http://$SERVER:8000
FAILURES=0

cleanup() {
    docker rm -f "$SERVER" >/dev/null 2>&1 || true
    docker network rm "$NETWORK" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

mkdir -p "$WORK/feeds" "$WORK/out"
cp "$ROOT"/examples/sample-feed.xml "$ROOT"/tests/fixtures/* "$WORK/feeds/"
cat >"$WORK/feeds/blog.html" <<'HTML'
<!doctype html><html><head><title>Blog</title>
<link rel="alternate" type="application/rss+xml" href="sample-feed.xml">
</head><body>blog</body></html>
HTML

docker network create "$NETWORK" >/dev/null
docker run -d --rm --name "$SERVER" --network "$NETWORK" -v "$WORK/feeds:/srv:ro" -w /srv \
    --entrypoint python "$IMAGE" -m http.server 8000 >/dev/null
for _ in $(seq 50); do
    if docker exec "$SERVER" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/')" 2>/dev/null; then
        break
    fi
    sleep 0.2
done

# check NAME EXPECTED_EXIT EXPECTED_OUTPUT_REGEX [ARGS...]
# Runs the image (read-only, no capabilities) with ARGS; $NET picks the network.
check() {
    local name=$1 want_exit=$2 pattern=$3 output status=0
    shift 3
    output=$(docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
        --user "$(id -u):$(id -g)" --network "${NET:-$NETWORK}" -v "$WORK/out:/data" \
        "$IMAGE" "$@" 2>&1) || status=$?
    if [[ $status == "$want_exit" ]] && grep -Eq -- "$pattern" <<<"$output"; then
        echo "ok   $name"
    else
        echo "FAIL $name (exit $status, expected $want_exit)"
        echo "     ${output//$'\n'/$'\n'     }"
        FAILURES=$((FAILURES + 1))
    fi
}

# check_file NAME FILE MUST_MATCH MUST_NOT_MATCH
check_file() {
    if grep -Eq -- "$3" "$WORK/out/$2" && ! grep -Eq -- "$4" "$WORK/out/$2"; then
        echo "ok   $1"
    else
        echo "FAIL $1"
        FAILURES=$((FAILURES + 1))
    fi
}

check "fetch over HTTP" 0 '^fetched: 3 articles from "Sample Feed" -> html/Sample-Feed.html$' \
    "$URL/sample-feed.xml"
check "second run uses the cache" 0 '^cache: 3 articles from "Sample Feed" \(fetched ' \
    "$URL/sample-feed.xml"
check "unchanged feed is not downloaded again (304)" 0 '^fetched: 3 articles .*\(not modified\)' \
    --max-age 0 "$URL/sample-feed.xml"
check "feed found from an HTML page" 0 '^fetched: 3 articles from "Sample Feed"' \
    --db discovery.sqlite3 "$URL/blog.html"
check "several feeds and an index" 1 '^index: 2 pages -> html/index.html$' \
    "$URL/sample-feed.xml" "$URL/missing.xml" "$URL/atom.xml"
check_file "index links to the pages" html/index.html 'href="Atom-Feed.html"' '<script'
check "HTTP error" 1 '^error: cannot read .*/missing.xml: HTTP Error 404' "$URL/missing.xml"
check "not a feed" 1 '^error: not a feed: ' "$URL/not-a-feed.html"
check "hostile feed" 0 '^fetched: 2 articles from "\.\./\.\./etc/passwd <script>' "$URL/malicious.xml"
check_file "hostile feed is escaped" html/etc-passwd-script-alert-1-script.html \
    '&lt;img src=x onerror=alert\(1\)&gt;' '<script|<img|javascript:'
NET=none check "offline without cache" 1 'cannot resolve host' --db offline.sqlite3 "$URL/atom.xml"
NET=none check "offline with a stale cache" 0 '^cache: 1 article from "Atom Feed"' \
    --max-age 0 "$URL/atom.xml"
check "file:// is refused" 1 '^error: unsupported feed source' file:///etc/passwd
check "bad --max-age" 2 'must be a number of hours' --max-age -1 "$URL/atom.xml"

if ((FAILURES)); then
    echo "$FAILURES check(s) failed"
    exit 1
fi
echo "all checks passed"
