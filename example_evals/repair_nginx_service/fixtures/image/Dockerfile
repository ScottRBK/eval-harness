FROM eval-harness:latest

USER root

ARG DEBIAN_SNAPSHOT=20260723T000000Z
ARG NGINX_VERSION=1.22.1-9+deb12u9

# Fail closed if the harness base distribution or audited Nginx package changes.
# A version update must be accompanied by a fresh audit in terminal_task.md.
RUN . /etc/os-release \
    && test "$VERSION_CODENAME" = "bookworm" \
    && printf '%s\n' \
        "Types: deb" \
        "URIs: https://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}" \
        "Suites: bookworm bookworm-updates" \
        "Components: main" \
        "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg" \
        "Check-Valid-Until: no" \
        "" \
        "Types: deb" \
        "URIs: https://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}" \
        "Suites: bookworm-security" \
        "Components: main" \
        "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg" \
        "Check-Valid-Until: no" \
        > /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        "nginx=${NGINX_VERSION}" \
    && test "$(dpkg-query -W -f='${Version}' nginx)" = "${NGINX_VERSION}" \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

LABEL org.eval-harness.debian-snapshot="${DEBIAN_SNAPSHOT}" \
      org.eval-harness.nginx-version="${NGINX_VERSION}"

# Static site content
COPY site/ /srv/site/

# Deliberately broken starting configuration — the agent must repair this.
COPY broken-nginx.conf /etc/nginx/nginx.conf

# Nginx runs as the non-root `node` user, so its PID, temp, and log paths
# must be writable by that user.
RUN mkdir -p /tmp/nginx/client_temp /tmp/nginx/proxy_temp \
             /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp \
             /tmp/nginx/scgi_temp \
             /var/log/nginx \
    && chown -R node:node /tmp/nginx /var/log/nginx \
    && chown -R node:node /etc/nginx /srv/site

USER node
