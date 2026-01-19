# Infra-Agent

AI-powered Infrastructure Agent for managing AWS EKS clusters with NIST 800-53 Rev 5 compliance.

## Features

- **Multi-Agent Architecture**: Chat orchestrator routes to specialized agents
- **Investigation Agent**: Diagnose issues (pods restarting, nodes unhealthy, etc.)
- **Audit Agent**: NIST compliance, security scans, cost optimization, drift detection
- **4-Agent Pipeline**: Planning → IaC → Review → Deploy for infrastructure changes
- **IaC-First**: All changes go through CloudFormation or Helm (no direct kubectl apply)

## Quick Start

```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install
pip install -e .

# 3. Start SSM tunnel (required - EKS has private endpoint)
./scripts/tunnel.sh

# 4. Run
infra-agent chat -e dev
```

## Example Commands

```bash
# Investigation
"Why are SigNoz pods restarting?"
"Debug why nodes are NotReady"

# Audit
"Audit NIST 800-53 compliance"
"Find cost optimization opportunities"

# Changes (4-agent pipeline)
"Scale SigNoz frontend to 3 replicas"
"Create an S3 bucket for logs with encryption"

# Queries
"List all pods in signoz namespace"
"Show node status"
```

## Documentation

- [User Guide](docs/user-guide.md) - How to use the agent with examples
- [Architecture](docs/architecture.md) - System design and agent diagrams
- [Requirements](docs/requirements.md) - Functional requirements (AGT-*)

## Requirements

- Python 3.11+
- AWS credentials configured
- SSM tunnel for EKS access (private endpoint)

## License

MIT
