# [Terminal Task](../../example_evals/repair_nginx_service)

This eval pattern grades whether an agent leaves a realistic terminal environment in the required
final state. It evaluates **outcomes** — not commands, reasoning, console output, or a prescribed
implementation.

## Overview

Inspired by [Terminal-Bench](https://arxiv.org/abs/2601.11868), a terminal task gives the agent a
natural-language instruction, a deterministic starting environment inside a Docker container, and a
set of hidden checks against the final container state. The agent is free to use any approach —
editing config files, running commands, installing packages — as long as the environment it leaves
behind satisfies the requirements.

The example eval, `repair_nginx_service`, presents a container with Nginx installed but stopped and
deliberately misconfigured. The agent must repair the configuration and leave a working Nginx
service that listens on port 8080, serves static content, exposes a `/health` endpoint, returns a
custom 404 page, logs each request to `/var/log/nginx/access.log` with
method/status/user-agent, and stays running.

Three characteristics make this pattern distinct from the others in this collection:

1. **No repository to clone.** The starting environment is a Docker image built from the eval's own
   `fixtures/image/Dockerfile`. The agent works directly inside that container.
1. **Outcome-only scoring.** There is no test suite to run, no JSON to compare, no CSV to parse.
   The hidden checks inspect the live container state — processes, HTTP responses, log files.
1. **Binary scoring.** All checks pass or the task scores zero. There is no partial credit for
   getting four of seven requirements right.

> [!TIP]
> This pattern uses the eval-owned Dockerfile capability. The task image derives from
> `eval-harness:latest`, so the Python runtime, agent CLIs and harness tools remain available.
> The Dockerfile's parent directory (`fixtures/image/`) is the complete build context, so only
> agent-visible starting files belong there. The hidden tests, instruction, and oracle live in
> `fixtures/` outside `image/` and are never baked into the image.

## Task structure

```text
repair_nginx_service/
├── eval.py
└── fixtures/
    ├── instruction.md       # natural-language task (agent-visible, embedded via act)
    ├── tests.py             # hidden state checks (embedded via score)
    ├── oracle.sh            # human-written reference solution (authoring artifact only)
    └── image/
        ├── Dockerfile
        ├── broken-nginx.conf
        └── site/
            └── index.html
```

The oracle is never embedded into any runtime phase. The hidden `tests.py` and `oracle.sh` files sit
outside `fixtures/image/`, which is the complete Docker build context. Only agent-visible starting
files belong under `fixtures/image/`.

## Task acceptance criteria

A good terminal task must satisfy three Terminal-Bench criteria and four harness integrity checks:

- **Specificity:** the instruction and hidden tests describe the same acceptable outcomes. If the
  instruction says "a custom error page", the tests must verify a custom page exists — they must not
  check for a specific string the agent could not have known about.
- **Solvability:** the oracle solution passes all hidden tests. Validate this during authoring.
- **Integrity:** a no-op (doing nothing) and obvious shortcuts (e.g. a non-Nginx server) fail.
- **Isolation:** the hidden tests, instruction, and oracle remain outside the Docker build context
  (`fixtures/image/`), and the hidden tests and oracle remain absent during `act`.
- **Determinism:** repeated no-op and oracle checks produce the same result.
- **Scoring:** all checks passing produces `EVAL_SCORE=1.0`; any candidate failure produces
  `EVAL_SCORE=0.0`. Evaluator and fixture defects raise so the run is marked FAILED.
- **Supply chain:** every package installed in the task image has an audit covering its source,
  signing, and known vulnerabilities. Record that audit in this pattern documentation.

The task is ready only when all seven checks have evidence from the actual eval image.

## Evaluation Details

### Eval-owned image

The eval declares its own Dockerfile, built once per session:

```python
dockerfile = "fixtures/image/Dockerfile"
```

The Dockerfile installs Nginx into the base image, copies the static site and a deliberately broken
starting configuration, and sets up writable paths for the `node` user (since the agent runs as
non-root). The broken config has several real defects: wrong listen port, no root directive, PID
path owned by root, no custom log format, no `/health` endpoint, and no custom 404 page.

### arrange

`arrange()` is deliberately small — the custom image owns the starting environment. It confirms the
expected starting files exist and ensures Nginx is stopped, so each run starts from a clean state.

### act

`act()` loads `instruction.md` through `act_embedded_values` and passes it to `AgentShell` with a
writable working directory. The instruction describes the required final state without mentioning
evaluation, hidden tests, or scoring. Web tools are not disabled — the agent may consult
documentation if it needs to.

### score

`score()` loads `tests.py` through `score_embedded_values` and sends it to `python -I -` over
standard input. It does not create a predictable agent-writable file that a background process
could replace. The tests verify:

1. `nginx -t` succeeds (valid configuration).
2. An Nginx process is running.
3. The packaged Nginx executable owns the listening socket on port 8080.
4. Port 8080 serves `/srv/site/index.html` at `/`.
5. `/health` returns exactly `healthy` with HTTP 200.
6. A missing path returns HTTP 404 and a non-empty custom page (not the stock Nginx 404).
7. `/var/log/nginx/access.log` exists and is non-empty.
8. The log entry for a per-run probe contains the method, exact status code, and user agent.
9. The `Server` response header identifies Nginx.

All checks passing emits `EVAL_SCORE=1.0`; any failure emits `EVAL_SCORE=0.0`. Evaluator or fixture
defects raise so the run is marked FAILED rather than producing a misleading zero.

## Nginx supply-chain audit

Audit date: **2026-07-24**.

The task image uses Debian's repository snapshots from **2026-07-23 00:00 UTC** and pins
`nginx=1.22.1-9+deb12u9` from Debian Bookworm. It therefore does not accept whichever package
version happens to be current when the image is rebuilt. The Dockerfile also verifies that its
session-local `eval-harness:latest` base is Bookworm, checks the installed package version, and
records the snapshot and version as image labels. A base-distribution or Nginx-version change
therefore fails the build instead of silently invalidating this audit. CI builds the harness base
from the checked-out source immediately before building this fixture image.

The package comes from Debian's signed `bookworm`/`bookworm-security` archives, using the Debian
archive keyring already present in the base image. The version pin is a reproducibility control, not
a claim that the package has no open security issues. Before changing the pin, review both the
[Debian security tracker](https://security-tracker.debian.org/tracker/source-package/nginx) and the
[upstream Nginx advisories](https://nginx.org/en/security_advisories.html), update the audit date,
and rerun the image integration tests. This eval exposes Nginx only inside an ephemeral Docker
network namespace and sends its checks over loopback, which limits the task's exposure.

## Context7 documentation review

Before implementing the service configuration, current Nginx documentation was consulted via
Context7 (`/websites/nginx_en`). Key findings that affected the eval design:

- **`log_format`** is defined at the `http` context level. Variables `$request`, `$status`, and
  `$http_user_agent` provide the method, status, and user agent that the tests verify.
- **`error_page`** with an `internal` location prevents direct access to the custom 404 page.
- **`pid`** and **temp path** directives must point to locations writable by the `node` user, since
  Nginx runs as non-root. The `user` directive in the main context is ignored when the master
  process is already started by a non-root user.
- **`return 200 "healthy"`** in a `location = /health` block provides the health endpoint.
- **`access_log on;`** is NOT valid syntax — Nginx interprets `on` as a file path. Logging is
  enabled by default once `access_log <path> <format>;` is set at the `http` or `server` level.
