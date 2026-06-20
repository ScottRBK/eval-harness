This evaluation harness is designed to test not just Large Language Models but also the Agentic Coding
harnesses that are wrapped around these models. 

I feel it is important to frame all evaluations from the perpsective of not just the Large Language Model
but also the coding harness that was used during the evaluation.

The following agent harnesses are currently supported: 

- [x] Claude Code
- [x] Opencode
- [ ] Copilot
- [ ] Codex

A lot of this is possible thanks to the agentic harness abstraction repository 
[agent-shell](https://github.com/ScottRBK/agent-shell), check it out if you have use cases where you 
want to seemlessly switch between agentic harness for a particular worklow.

## Example Evals
This harness ships with some [example evals]("docs/evals.md"), as I come up with different types of 
evaluations for my own workflows, then this example collection will increase.

These examples will hopefully give you ideas on how you can structure your own workflows, however 
the evals themselves are not all that difficult for most modern harnesses, typically because they are
using public data that are likely to be used in the process of creating the model in the first place.


# Getting Started

install uv if you do not have it already:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

1. Fork the repo 
1. Replace the example eval folder with your own evals 
1. Update evals.json 
1. execute the harness 
```bash 


uv run main.py
```

# Harness Architecture
The harness is structured in a way that there is an evaluation protocol, any evaluation must implement
the same methods within the protocol.

The harness ingests an evaluation file (the default is [evals.json](evals.json)), which determines
which evaluations are in scope of the evaluiation run, and also which agent harness/model combinations
should be in scope of the run as well.

When I build my own automated tests for testing my actual code, I have used the popular _Arrange_, 
_Act_ and _Assert_ pattern, to this end I have adopted these as methods that any evaluation class must
provide, with one exception, given that `assert` is a keyword in python, I changed that to `score`


# Technical Notes

### Building behind a TLS-intercepting proxy

If your machine routes traffic through a TLS-intercepting proxy (Netskope, Zscaler, etc.), container builds 
and agent API calls will fail certificate verification. Drop your proxy's CA certificate chain 
(PEM format, `.crt` extension) into `src/docker/certs/` and rebuild — certs in that directory are gitignored and get baked into the image's trust store. To extract the chain your proxy presents:

```bash
docker run --rm node:24 sh -c 'echo | openssl s_client -showcerts -connect astral.sh:443 2>/dev/null' \
  | awk '/BEGIN CERTIFICATE/{n++} n>=2' > src/docker/certs/proxy-ca.crt
```

### Docker rebuild command 

```bash
docker build -t eval-harness:latest -f src/docker/Dockerfile src/docker/
```

