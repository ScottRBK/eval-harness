"""Integration tests for the repair_nginx_service terminal-task eval.

These tests exercise the eval-owned task image (not the agent) to validate that
the hidden tests correctly score the expected outcomes:

- untouched starting environment → 0
- oracle solution → 1
- non-Nginx server on 8080 → 0
- another service on 8080 while Nginx runs elsewhere → 0
- empty custom 404 response → 0
- valid minimal log format and conventional custom 404 heading → 1
- log format without the response status → 0
- correct pages without access logging → 0
- correct config with Nginx stopped → 0

They require Docker and the base image (eval-harness:latest) but do NOT require
agent credentials — the agent is never invoked.
"""

from pathlib import Path

import docker
import pytest

pytestmark = pytest.mark.integration

EVAL_DIR = Path(__file__).resolve().parents[2] / "example_evals" / "repair_nginx_service"
IMAGE = "eval-harness-fixture-repair_nginx_service:latest"
BUILD_CMD = (
    f"docker build -t {IMAGE} -f {EVAL_DIR}/fixtures/image/Dockerfile {EVAL_DIR}/fixtures/image/"
)
TESTS_PATH = EVAL_DIR / "fixtures" / "tests.py"
ORACLE_PATH = EVAL_DIR / "fixtures" / "oracle.sh"
DEBIAN_SNAPSHOT = "20260723T000000Z"
NGINX_VERSION = "1.22.1-9+deb12u9"


def _run_tests_in_container(docker_client, setup_cmds: str = "") -> str:
    """Run the hidden tests inside the task image after optional setup commands."""
    container_name = "eval_harness_nginx_test"
    try:
        docker_client.containers.get(container_name).remove(force=True)
    except docker.errors.NotFound:
        pass

    container = docker_client.containers.run(
        image=IMAGE,
        command=["sleep", "infinity"],
        detach=True,
        name=container_name,
        volumes={
            str(TESTS_PATH): {"bind": "/tmp/_eval_hidden_tests.py", "mode": "ro"},
            **(
                {str(ORACLE_PATH): {"bind": "/tmp/oracle.sh", "mode": "ro"}}
                if ORACLE_PATH.exists()
                else {}
            ),
        },
    )

    try:
        full_cmd = (
            setup_cmds + "\npython -I /tmp/_eval_hidden_tests.py"
            if setup_cmds
            else "python -I /tmp/_eval_hidden_tests.py"
        )
        exit_code, output = container.exec_run(
            ["sh", "-c", full_cmd],
        )
        buffer = output.decode(errors="replace")
        assert exit_code == 0, buffer
        return buffer
    finally:
        try:
            container.stop(timeout=5)
            container.remove()
        except docker.errors.NotFound:
            pass


def _extract_score(output: str) -> float:
    for line in output.splitlines():
        if line.startswith("EVAL_SCORE="):
            return float(line.removeprefix("EVAL_SCORE=").strip())
    pytest.fail(f"No EVAL_SCORE in output:\n{output}")


class TestRepairNginxServiceScoring:
    def test_broken_starting_state_scores_zero(self, docker_client, require_docker_image):
        require_docker_image(IMAGE, BUILD_CMD)
        output = _run_tests_in_container(docker_client)
        assert _extract_score(output) == 0.0

    def test_oracle_solution_scores_one(self, docker_client, require_docker_image):
        require_docker_image(IMAGE, BUILD_CMD)
        output = _run_tests_in_container(docker_client, "bash /tmp/oracle.sh")
        assert _extract_score(output) == 1.0

    def test_non_nginx_server_scores_zero(self, docker_client, require_docker_image):
        require_docker_image(IMAGE, BUILD_CMD)
        setup = "python -m http.server 8080 --directory /srv/site &\nsleep 2\n"
        output = _run_tests_in_container(docker_client, setup)
        assert _extract_score(output) == 0.0

    def test_port_8080_listener_must_be_nginx(
        self,
        docker_client,
        require_docker_image,
    ):
        require_docker_image(IMAGE, BUILD_CMD)
        setup = """\
set -e
bash /tmp/oracle.sh
nginx -s stop
sed -i 's/listen 8080;/listen 8081;/' /etc/nginx/nginx.conf
nginx -t
nginx
python - <<'PY' &
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def version_string(self):
        return "nginx"

    def do_GET(self):
        if self.path == "/":
            status = 200
            body = Path("/srv/site/index.html").read_bytes()
        elif self.path == "/health":
            status = 200
            body = b"healthy"
        else:
            status = 404
            body = b"<h1>Page not found</h1>"

        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        user_agent = self.headers.get("User-Agent", "")
        with Path("/var/log/nginx/access.log").open("a") as log:
            log.write(f'GET {status} "{user_agent}"\\n')

    def log_message(self, format, *args):
        pass


HTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
PY
sleep 1
"""
        output = _run_tests_in_container(docker_client, setup)
        assert _extract_score(output) == 0.0
        assert "PASS: nginx process running" in output
        assert "PASS: Server header indicates Nginx" in output
        assert "FAIL: Nginx owns port 8080 listener" in output

    def test_empty_custom_404_scores_zero(self, docker_client, require_docker_image):
        require_docker_image(IMAGE, BUILD_CMD)
        setup = "bash /tmp/oracle.sh\ntruncate -s 0 /srv/site/custom_404.html\n"
        output = _run_tests_in_container(docker_client, setup)
        assert _extract_score(output) == 0.0
        assert "FAIL: 404 page is non-empty" in output

    def test_valid_minimal_log_and_conventional_custom_404_score_one(
        self,
        docker_client,
        require_docker_image,
    ):
        require_docker_image(IMAGE, BUILD_CMD)
        setup = """\
set -e
bash /tmp/oracle.sh
nginx -s stop
python - <<'PY'
from pathlib import Path

config_path = Path("/etc/nginx/nginx.conf")
config = config_path.read_text()
start = config.index("    log_format eval_log")
end = config.index("    access_log", start)
minimal_log = "    log_format eval_log '$request_method $status \\\"$http_user_agent\\\"';"
config_path.write_text(config[:start] + minimal_log + chr(10) * 2 + config[end:])
page = "<h1>404 Not Found</h1>" + chr(10) + "<p>Custom page</p>" + chr(10)
Path("/srv/site/custom_404.html").write_text(page)
PY
rm -f /var/log/nginx/access.log
nginx -t && nginx
sleep 1
"""
        output = _run_tests_in_container(docker_client, setup)
        assert _extract_score(output) == 1.0

    def test_log_without_status_scores_zero(self, docker_client, require_docker_image):
        require_docker_image(IMAGE, BUILD_CMD)
        setup = """\
set -e
bash /tmp/oracle.sh
nginx -s stop
python - <<'PY'
from pathlib import Path

config_path = Path("/etc/nginx/nginx.conf")
config = config_path.read_text()
start = config.index("    log_format eval_log")
end = config.index("    access_log", start)
missing_status_log = "    log_format eval_log '$request_method \\\"$http_user_agent\\\"';"
config_path.write_text(config[:start] + missing_status_log + chr(10) * 2 + config[end:])
PY
rm -f /var/log/nginx/access.log
nginx -t
nginx
sleep 1
"""
        output = _run_tests_in_container(docker_client, setup)
        assert _extract_score(output) == 0.0
        assert "FAIL: log entry contains status code" in output

    def test_correct_without_logging_scores_zero(self, docker_client, require_docker_image):
        require_docker_image(IMAGE, BUILD_CMD)
        setup = (
            "bash /tmp/oracle.sh\n"
            "nginx -s stop\n"
            "sleep 1\n"
            "sed -i 's#access_log /var/log/nginx/access.log eval_log;#access_log off;#' "
            "/etc/nginx/nginx.conf\n"
            "rm -f /var/log/nginx/access.log\n"
            "nginx -t && nginx\n"
            "sleep 1\n"
        )
        output = _run_tests_in_container(docker_client, setup)
        assert _extract_score(output) == 0.0

    def test_correct_config_stopped_scores_zero(self, docker_client, require_docker_image):
        require_docker_image(IMAGE, BUILD_CMD)
        setup = "bash /tmp/oracle.sh\nnginx -s stop\nsleep 1\n"
        output = _run_tests_in_container(docker_client, setup)
        assert _extract_score(output) == 0.0

    def test_hidden_tests_outside_build_context(self):
        image_dir = EVAL_DIR / "fixtures" / "image"
        assert not (image_dir / "tests.py").exists()
        assert not (image_dir / "oracle.sh").exists()
        assert not (image_dir / "instruction.md").exists()

    def test_task_image_has_audited_nginx_version(
        self,
        docker_client,
        require_docker_image,
    ):
        require_docker_image(IMAGE, BUILD_CMD)
        output = docker_client.containers.run(
            image=IMAGE,
            command=["dpkg-query", "-W", "-f=${Version}", "nginx"],
            remove=True,
        )
        assert output.decode().strip() == NGINX_VERSION

        labels = docker_client.images.get(IMAGE).labels
        assert labels["org.eval-harness.debian-snapshot"] == DEBIAN_SNAPSHOT
        assert labels["org.eval-harness.nginx-version"] == NGINX_VERSION
