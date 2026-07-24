"""Hidden tests for the repair_nginx_service eval.

These are injected into the container only during the score phase and run
with `python -I` (isolated mode) so no site-packages leak in.

All checks must pass (binary scoring: 1.0 or 0.0). A fixture/evaluator defect
raises rather than printing a score, so it surfaces as a FAILED run instead of
a misleading zero.
"""

import http.client
import os
import re
import secrets
import string
import subprocess
import time
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8080
ACCESS_LOG = "/var/log/nginx/access.log"
CHECK_USER_AGENT = "eval-harness-check/1.0"
_PROBE_TOKEN = "".join(secrets.choice(string.ascii_lowercase) for _ in range(16))
PROBE_PATH = f"/eval-harness-log-probe-{_PROBE_TOKEN}"
PROBE_USER_AGENT = f"eval-harness-log-probe-{_PROBE_TOKEN}"

# Distinctive footer from the stock Debian Nginx 404 page.
_STOCK_404_MARKER = "<hr><center>nginx"
_GET_TOKEN = re.compile(r"(?<![A-Za-z])GET(?![A-Za-z])")
_STATUS_404_TOKEN = re.compile(r"(?<!\d)404(?!\d)")

_failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        msg = f"FAIL: {name}" + (f" — {detail}" if detail else "")
        _failures.append(msg)
        print(msg)


def _get(
    path: str,
    user_agent: str = CHECK_USER_AGENT,
) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection(HOST, PORT, timeout=10)
    conn.request("GET", path, headers={"User-Agent": user_agent})
    return conn.getresponse()


def _listener_owners(port: int) -> list[tuple[int, str, str, bool]]:
    """Return processes holding a listening TCP socket for *port*."""
    socket_inodes: set[str] = set()
    for table_path in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        try:
            rows = table_path.read_text().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            fields = row.split()
            if len(fields) < 10:
                continue
            local_address = fields[1]
            state = fields[3]
            if state == "0A" and int(local_address.rsplit(":", 1)[1], 16) == port:
                socket_inodes.add(fields[9])

    owners: list[tuple[int, str, str, bool]] = []
    for process_dir in Path("/proc").iterdir():
        if not process_dir.name.isdigit():
            continue
        try:
            fd_paths = list((process_dir / "fd").iterdir())
        except OSError:
            continue
        owns_listener = False
        for fd_path in fd_paths:
            try:
                target = os.readlink(fd_path)
            except OSError:
                continue
            if target.startswith("socket:[") and target[8:-1] in socket_inodes:
                owns_listener = True
                break
        if not owns_listener:
            continue

        try:
            command = (process_dir / "comm").read_text().strip()
        except OSError:
            command = "unknown"
        try:
            executable = os.readlink(process_dir / "exe")
        except OSError:
            executable = "unknown"
        try:
            is_nginx = os.path.samefile(process_dir / "exe", "/usr/sbin/nginx")
        except OSError:
            is_nginx = False
        owners.append((int(process_dir.name), command, executable, is_nginx))
    return owners


# Issue a probe request *first* so we can verify it appears in the access log
# later. The random letters identify this run without putting digits that could
# be mistaken for a response status into the request path or user agent.
try:
    _probe_resp = _get(PROBE_PATH, PROBE_USER_AGENT)
    _probe_status = _probe_resp.status
    _probe_resp.read()
    _probe_resp.close()
except Exception:
    _probe_status = 0
time.sleep(0.5)  # let nginx flush the log entry

# 0. nginx -t succeeds
_t = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
check("nginx -t succeeds", _t.returncode == 0, _t.stderr.strip() or _t.stdout.strip())

# 1. Nginx master process running
_ps = subprocess.run(["pgrep", "-x", "nginx"], capture_output=True)
check(
    "nginx process running",
    _ps.returncode == 0 and bool(_ps.stdout.strip()),
    f"pgrep output: {_ps.stdout!r}",
)

# 2. The process accepting connections on port 8080 is the packaged Nginx
_port_owners = _listener_owners(PORT)
_nginx_owners = [owner for owner in _port_owners if owner[3]]
check(
    "Nginx owns port 8080 listener",
    bool(_nginx_owners),
    f"owners={[(pid, command, executable) for pid, command, executable, _ in _port_owners]!r}",
)

# 3. Port 8080 serves /srv/site/index.html at /
try:
    resp = _get("/")
    body = resp.read().decode(errors="replace")
    check("GET / returns 200", resp.status == 200, f"status={resp.status}")
    with open("/srv/site/index.html") as f:
        expected = f.read()
    check(
        "GET / serves /srv/site/index.html",
        body.strip() == expected.strip(),
        f"body mismatch (len={len(body)} vs {len(expected)})",
    )
    resp.close()
except Exception as e:
    check("GET / request", False, str(e))

# 4. /health returns exactly 'healthy' with HTTP 200
try:
    resp = _get("/health")
    body = resp.read().decode(errors="replace")
    check("GET /health returns 200", resp.status == 200, f"status={resp.status}")
    check(
        "GET /health body is exactly 'healthy'",
        body.strip() == "healthy",
        f"body={body!r}",
    )
    resp.close()
except Exception as e:
    check("GET /health request", False, str(e))

# 5. Missing path returns HTTP 404 and a non-empty custom page
try:
    resp = _get("/this-path-does-not-exist")
    body = resp.read().decode(errors="replace")
    check("missing path returns 404", resp.status == 404, f"status={resp.status}")
    check("404 page is non-empty", bool(body.strip()), f"body={body!r}")
    has_stock_marker = _STOCK_404_MARKER in body.lower()
    check(
        "404 page is custom (not stock Nginx)",
        not has_stock_marker,
        f"body contains stock marker; body={body!r}",
    )
    resp.close()
except Exception as e:
    check("missing path request", False, str(e))

# 6 & 7. Access log contains this run's probe with method, status, user agent
try:
    with open(ACCESS_LOG, "r") as f:
        log_contents = f.read()
    check(
        "access log file exists and is non-empty",
        bool(log_contents.strip()),
        "log file empty or missing",
    )
    probe_lines = [line for line in log_contents.splitlines() if PROBE_USER_AGENT in line]
    check(
        "access log contains probe request line",
        len(probe_lines) >= 1,
        "no log line for probe user agent",
    )
    if probe_lines:
        line = probe_lines[-1]
        check(
            "log entry contains request method (GET)",
            bool(_GET_TOKEN.search(line)),
            f"line={line!r}",
        )
        check(
            "log entry contains status code",
            _probe_status == 404 and bool(_STATUS_404_TOKEN.search(line)),
            f"probe_status={_probe_status}; line={line!r}",
        )
        check(
            "log entry contains user agent",
            PROBE_USER_AGENT in line,
            f"line={line!r}",
        )
    else:
        check("log entry fields", False, "no probe line to inspect")
except Exception as e:
    check("access log", False, str(e))

# 8. Nginx also identifies itself in the response
try:
    resp = _get("/")
    server = resp.getheader("Server", "")
    check(
        "Server header indicates Nginx",
        "nginx" in server.lower(),
        f"Server={server!r}",
    )
    resp.close()
except Exception as e:
    check("Server header", False, str(e))

# --- Verdict ---------------------------------------------------------------
if _failures:
    print(f"\n{len(_failures)} check(s) failed")
    print("EVAL_SCORE=0.0")
else:
    print("\nAll checks passed")
    print("EVAL_SCORE=1.0")
