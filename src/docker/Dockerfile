FROM node:24

# node:24 inherits docker-entrypoint.sh which prepends `node` to any command it can't resolve,
# mangling python/claude/opencode invocations. Clear it so commands run directly.
ENTRYPOINT []

ARG CLAUDE_CODE_VERSION=latest
ARG OPENCODE_VERSION=latest

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        gh \
        jq \
        procps \
        ca-certificates \
        curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# uv manages Python 3.12+ since Debian bookworm only ships 3.11 (agent-shell-py needs 3.12+)
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# Install under /opt so non-root `node` user can read it (default ~/.local lives in /root/)
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
RUN uv python install 3.12 && \
    uv venv /opt/venv --python 3.12 && \
    uv pip install --python /opt/venv/bin/python agent-shell-py
ENV PATH="/opt/venv/bin:${PATH}"

# npm global prefix relocated so non-root `node` user can install globals
RUN mkdir -p /usr/local/share/npm-global && \
    chown -R node:node /usr/local/share

RUN mkdir -p /workspace /home/node/.claude /home/node/.local/share/opencode && \
    chown -R node:node /workspace /home/node/.claude /home/node/.local

WORKDIR /workspace

USER node

ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global
ENV PATH=$PATH:/usr/local/share/npm-global/bin

RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} && \
    npm install -g opencode-ai@${OPENCODE_VERSION}
