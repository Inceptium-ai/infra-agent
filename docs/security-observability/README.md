# Security & Observability Platform Documentation

This folder contains documentation for the AWS EKS infrastructure platform, including observability stack, security controls, and NIST 800-53 compliance.

## Documents

| Document | Description |
|----------|-------------|
| [architecture.md](architecture.md) | EKS cluster architecture, VPC design, Istio service mesh, SigNoz observability |
| [requirements.md](requirements.md) | Infrastructure and observability requirements (FR-*, NFR-*) |
| [security.md](security.md) | NIST 800-53 R5 compliance, security controls, IAM policies |
| [decisions.md](decisions.md) | Architecture decisions (SigNoz vs LGTM, Cognito vs Keycloak, etc.) |
| [lessons-learned.md](lessons-learned.md) | Infrastructure lessons (Istio, StatefulSets, EKS, etc.) |
| [access-guide.md](access-guide.md) | How to access observability tools, URLs, port-forwarding |

## Quick Links

- **Observability**: SigNoz (metrics, logs, traces), Kiali (Istio mesh)
- **Security**: Trivy (vulnerability scanning), Velero (backups)
- **Authentication**: Cognito with OIDC integration

## Related

- [Infra-Agent Documentation](../infra-agent/README.md) - AI agent that manages this platform
- [Main README](../../README.md) - Project overview
