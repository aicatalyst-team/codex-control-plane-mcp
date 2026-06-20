# Deploying an MCP Server on OpenShift: Zero Dependencies, Full Protocol

Running AI agent tooling on enterprise Kubernetes is a common request, but most MCP (Model Context Protocol) servers are designed as local developer tools. Can a zero-dependency MCP server run reliably in an unprivileged OpenShift container? We tested it.

## The Project

[Codex Control Plane MCP](https://github.com/aresyn/codex-control-plane-mcp) is a durable control plane for long-running Codex Desktop tasks. It implements the MCP protocol over stdio, providing 31+ tools for task submission, workflow orchestration, chat management, diagnostics, and repair. The project's distinguishing feature is zero external Python dependencies -- everything runs on the standard library.

## What We Tested

We containerized the server using a UBI 9 Python 3.12 base image and deployed it as a Kubernetes Job on OpenShift. The PoC validated three scenarios:

1. **MCP Initialize Handshake** -- Send a JSON-RPC initialize request and verify the server responds with the correct protocol version and capabilities.
2. **Tool Catalog** -- Request the full tool list and verify the server returns structured tool definitions with JSON schemas.
3. **Package Import** -- Confirm the Python package installs and imports correctly in the container.

All three passed.

## Containerization

The Dockerfile is straightforward because there are no external dependencies to install:

```dockerfile
FROM registry.access.redhat.com/ubi9/python-312

WORKDIR /opt/app-root/src
COPY pyproject.toml MANIFEST.in README.md LICENSE ./
COPY codex_control_plane_mcp/ codex_control_plane_mcp/
COPY openclaw_codex_mcp/ openclaw_codex_mcp/

RUN pip install --no-cache-dir .

USER 0
RUN chgrp -R 0 /opt/app-root && chmod -R g=u /opt/app-root
USER 1001

ENTRYPOINT ["codex-control-plane-mcp"]
```

One gotcha: UBI Python images default to USER 1001, so the `chgrp` command for OpenShift arbitrary UID support needs a temporary `USER 0` switch. Without it, the build fails with permission errors on the installed package files.

## Deployment Pattern

Since this is a stdio-based server (not HTTP), we deployed it as a Kubernetes Job rather than a Deployment. The Job pipes JSON-RPC messages into the server's stdin and captures responses:

```bash
INIT_MSG='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}'
RESPONSE=$(echo "$INIT_MSG" | codex-control-plane-mcp)
```

The server responded with the full MCP protocol handshake, confirming it operates correctly in a containerized environment.

## Results

| Test | Status | Detail |
|------|--------|--------|
| MCP Initialize | Pass | Protocol version 2024-11-05, tools capability confirmed |
| Tool Catalog | Pass | 31+ tools with full JSON Schema definitions returned |
| Package Import | Pass | Version 0.1.4 imported successfully |

The container starts and responds in under 2 seconds, with no warm-up time.

## Lessons Learned

- **Zero-dependency projects are ideal PoC candidates.** No pip install failures, no version conflicts, no missing system libraries. The entire containerization took minutes.
- **Stdio MCP servers need a transport adapter for network access.** To serve this as a platform service, you would wrap it with an HTTP/SSE layer.
- **Quay.io OAuth tokens require `$oauthtoken` as the Docker username.** Using the organization name fails silently during push.

## What This Means for OpenShift AI

MCP is becoming the standard protocol for AI agent tool integration. This PoC demonstrates that MCP servers can run on OpenShift with minimal effort, especially when they have clean dependency profiles. The 31-tool catalog with structured JSON schemas provides a reference implementation for teams building managed MCP services on the platform.

For organizations evaluating MCP-based agent architectures, the deployment pattern shown here -- containerized stdio server behind a transport adapter -- offers a path from local developer tooling to centrally managed agent infrastructure.

---

*Deployed on OpenShift using UBI 9 Python 3.12. Container image: `quay.io/aicatalyst/codex-control-plane-mcp:latest`*
