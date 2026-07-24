#!/bin/bash
# Oracle solution for repair_nginx_service.
#
# This is an authoring artifact. It must NOT be embedded in any runtime phase
# or placed inside fixtures/image/ (the Docker build context).
#
# Run it inside the eval task container to verify the hidden tests pass.
set -euo pipefail

cat > /etc/nginx/nginx.conf <<'CONF'
worker_processes auto;

pid /tmp/nginx.pid;

events {
    worker_connections 1024;
}

http {
    client_body_temp_path /tmp/nginx/client_temp;
    proxy_temp_path       /tmp/nginx/proxy_temp;
    fastcgi_temp_path     /tmp/nginx/fastcgi_temp;
    uwsgi_temp_path       /tmp/nginx/uwsgi_temp;
    scgi_temp_path        /tmp/nginx/scgi_temp;

    log_format eval_log '$remote_addr - $remote_user [$time_local] '
                        '"$request" $status $body_bytes_sent '
                        '"$http_referer" "$http_user_agent"';

    access_log /var/log/nginx/access.log eval_log;

    server {
        listen 8080;
        root /srv/site;
        index index.html;

        location / {
            try_files $uri $uri/ =404;
        }

        location = /health {
            return 200 "healthy";
        }

        error_page 404 /custom_404.html;
        location = /custom_404.html {
            internal;
            root /srv/site;
        }
    }
}
CONF

cat > /srv/site/custom_404.html <<'PAGE'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Page Not Found</title>
</head>
<body>
    <h1>Oops!</h1>
    <p>The page you requested could not be found.</p>
</body>
</html>
PAGE

# Stop any running instance, validate, and start.
nginx -s stop 2>/dev/null || true
nginx -t
nginx
