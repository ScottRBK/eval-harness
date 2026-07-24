You are working in a Linux environment where Nginx is installed but stopped and
incorrectly configured.

Static content is present at `/srv/site/index.html`.

Your task: leave the system with a working Nginx service that satisfies **all**
of the following requirements:

1. Nginx listens on port **8080**.
2. A `GET /` request serves the file `/srv/site/index.html`.
3. A `GET /health` request returns exactly the text `healthy` with HTTP status 200.
4. A request for any path that does not resolve to an existing file returns
   HTTP **404** and a custom error page (not the stock Nginx 404 page).
5. Every request is logged to `/var/log/nginx/access.log`. Each log entry must contain the
   request **method**, the response **status code**, and the **user agent**.
6. Nginx must **remain running** after you finish — do not leave it stopped.
7. The responding service must be **Nginx**, not a replacement server.

Note: you are running as the `node` user, not root. The Nginx PID, temp, and log
paths must be writable by that user. The Nginx configuration file is at
`/etc/nginx/nginx.conf`.

Make whatever configuration changes are necessary, validate your work, and start
Nginx before you finish.