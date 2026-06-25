"""Shared test doubles for DockerRunner unit tests.

Everything here is hermetic: the docker daemon is never contacted. ``FakeStream``
and ``make_fake_client`` stand in for docker-py's exec API so the suite runs on a
bare CI runner with no Docker installed.
"""

from unittest import mock

import docker
import pytest


class FakeStream:
    """Stand-in for ``client.api.exec_start(stream=True)``.

    Iterable of byte chunks, plus the private ``_response`` attribute the runner
    closes in its ``finally`` block (the leak-fix regression). Set ``_raise`` to
    simulate the stream blowing up mid-iteration.
    """

    def __init__(self, chunks, raise_on_iter=False):
        self._chunks = chunks
        self._raise = raise_on_iter
        self._response = mock.Mock()

    def __iter__(self):
        for chunk in self._chunks:
            yield chunk
        if self._raise:
            raise RuntimeError("stream boom")


def make_fake_client(phases):
    """Build a mock docker client for the arrange/act/score exec chain.

    ``phases`` is a list of ``(output, exit_code)`` tuples, one per phase, fed to
    the runner in order. The returned client exposes ``_streams`` (the per-phase
    FakeStreams) and ``_container`` so tests can assert on cleanup/close.
    """
    client = mock.Mock()

    # No stale "eval_harness" container by default; the runner swallows NotFound.
    client.containers.get.side_effect = docker.errors.NotFound("absent")

    container = mock.Mock()
    container.id = "container-id"
    client.containers.run.return_value = container

    streams = [FakeStream([out.encode()]) for out, _ in phases]
    client.api.exec_create.return_value = {"Id": "exec-id"}
    client.api.exec_start.side_effect = streams
    client.api.exec_inspect.side_effect = [{"ExitCode": code} for _, code in phases]

    client._streams = streams
    client._container = container
    return client


@pytest.fixture
def make_docker_client():
    """Factory fixture; call with a list of ``(output, exit_code)`` phase tuples."""
    return make_fake_client
