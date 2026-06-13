This repo is a framework i have put together to allow me to structure evaluations
for the following Agentic CLI Tools:

- [x] Claude Code
- [x] Opencode
- [ ] Copilot
- [ ] Codex
- [ ] Gemini CLI 

# Getting Started
_TODO_

# Harness Architecture
_TODO_

# Roadmap
_TODO_ 

# Technical Notes

### Building behind a TLS-intercepting proxy

If your machine routes traffic through a TLS-intercepting proxy (Netskope, Zscaler, etc.), container builds and agent API calls will fail certificate verification. Drop your proxy's CA certificate chain (PEM format, `.crt` extension) into `src/docker/certs/` and rebuild — certs in that directory are gitignored and get baked into the image's trust store. To extract the chain your proxy presents:

```bash
docker run --rm node:24 sh -c 'echo | openssl s_client -showcerts -connect astral.sh:443 2>/dev/null' \
  | awk '/BEGIN CERTIFICATE/{n++} n>=2' > src/docker/certs/proxy-ca.crt
```

### Docker rebuild command 

```bash
docker build -t eval-harness:latest -f src/docker/Dockerfile src/docker/
```

