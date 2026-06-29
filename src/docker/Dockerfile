FROM node:24

# node:24 inherits docker-entrypoint.sh which prepends `node` to any command it can't resolve,
# mangling python/claude/opencode invocations. Clear it so commands run directly.
ENTRYPOINT []

ARG CLAUDE_CODE_VERSION=latest
ARG OPENCODE_VERSION=latest
ARG CODEX_VERSION=latest 
ARG COPILOT_VERSION=latest 

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        gh \
        jq \
        procps \
        ca-certificates \
        curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Optional: proxy CA certs (Netskope, Zscaler, ...). Drop *.crt files into
# src/docker/certs/ (gitignored) and they get baked into the trust store; no-op when empty.
# curl/git/uv read the system store; the env vars cover node and python http clients.
COPY certs/ /usr/local/share/ca-certificates/
RUN update-ca-certificates
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# uv manages Python 3.12+ since Debian bookworm only ships 3.11 (agent-shell-py needs 3.12+)
# Download-then-run (not curl|sh) so a failed download fails the build instead of passing silently
RUN curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-install.sh && \
    env UV_INSTALL_DIR=/usr/local/bin sh /tmp/uv-install.sh && \
    rm /tmp/uv-install.sh

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
    npm install -g opencode-ai@${OPENCODE_VERSION} && \
    npm install -g @github/copilot@${COPILOT_VERSION} && \
    npm install -g @openai/codex@${CODEX_VERSION} 
