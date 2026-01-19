# Infra-Agent Documentation

This folder contains documentation for the AI-powered Infrastructure Agent that manages the AWS EKS platform.

## Documents

### Core Documentation

| Document | Description |
|----------|-------------|
| [architecture.md](architecture.md) | Agent architecture, 4-agent pipeline, component diagrams |
| [requirements.md](requirements.md) | Agent functional requirements (AGT-*) |
| [user-guide.md](user-guide.md) | How to use the CLI, chat commands, examples |
| [knowledge-base.md](knowledge-base.md) | Known AWS/K8s limitations, patterns, troubleshooting |
| [lessons-learned.md](lessons-learned.md) | Agent development lessons (intent classification, etc.) |

### Implementation Reference

| Document | Description |
|----------|-------------|
| [system-prompts.md](system-prompts.md) | All agent system prompts with variable substitution |
| [mcp-integration.md](mcp-integration.md) | MCP server implementation, AWS/Git tools, routing |
| [langgraph-workflow.md](langgraph-workflow.md) | LangGraph StateGraph, pipeline state, routing |
| [tools-reference.md](tools-reference.md) | All tool signatures (Investigation, Audit, Review) |

## Quick Start

```bash
# Install
source .venv/bin/activate
pip install -e .

# Start SSM tunnel (required for EKS access)
./scripts/tunnel.sh

# Run interactive chat
infra-agent chat -e dev
```

## Key Features

- **Multi-Agent Architecture**: Chat orchestrator routes to specialized agents
- **4-Agent Pipeline**: Planning → IaC → Review → Deploy
- **MCP Integration**: Full AWS API and Git repository access
- **Real-time Progress**: Live feedback during agent operations

## Related

- [Security & Observability Platform](../security-observability/README.md) - The platform this agent manages
- [Main README](../../README.md) - Project overview
