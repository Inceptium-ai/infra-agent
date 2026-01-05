# AI Infrastructure Agent for AWS EKS - Architecture Document

## Executive Summary

This document defines the architecture for an AI-powered Infrastructure Agent system that manages AWS EKS clusters following NIST 800-53 Rev 5 security controls. The system employs a multi-agent architecture using LangGraph for orchestration and Claude (via AWS Bedrock) as the LLM backbone.

**Key Capabilities:**
- Automated infrastructure provisioning via CloudFormation
- NIST 800-53 R5 compliance validation and enforcement
- Zero Trust network architecture with non-routable pod subnets
- mTLS encryption via Istio service mesh
- Comprehensive observability with LGTM stack
- AI-driven drift detection and remediation
- Blue/Green deployment with automated rollback

**Target Environment:** AWS EKS in us-east-1, with three environments (DEV, TST, PRD)

---

## Assumptions

### Technical Assumptions
1. **AWS Account Access**: Operator has AWS account(s) with permissions to create VPCs, EKS clusters, IAM roles, and related resources
2. **Region Availability**: us-east-1 has capacity for requested resources (EKS, NAT Gateways, ALBs)
3. **Bedrock Access**: Claude model is available in the target AWS region via Bedrock
4. **Kubernetes Expertise**: Operators have basic Kubernetes and Helm knowledge
5. **Git Workflow**: Team uses GitHub for version control and GitHub Actions for CI/CD

### Operational Assumptions
1. **Single Operator Model**: Initially, one AI agent manages infrastructure (multi-operator support in future phases)
2. **DEV-First Deployment**: All changes deploy to DEV before promotion to TST/PRD
3. **OSS Preference**: Open-source solutions preferred over commercial alternatives where feasible
4. **RDS over Pods**: Databases run on RDS (not containerized) for managed reliability
5. **ALB over NLB**: Application Load Balancers used for HTTP/HTTPS traffic

### Security Assumptions
1. **MFA Required**: All operator access requires multi-factor authentication
2. **No Direct PRD Access**: AI agent uses JIT (Just-In-Time) access for production
3. **Zero Trust**: All network communication assumes hostile environment
4. **Encryption Everywhere**: Data encrypted at rest (KMS) and in transit (mTLS/TLS)

---

## Constraints

### Technical Constraints
| Constraint | Impact | Mitigation |
|------------|--------|------------|
| EKS managed node groups only | Cannot use custom AMIs with specialized configurations | Use EKS-optimized AMIs, configure via user data |
| CloudFormation (not Terraform) | Limited state management compared to Terraform | Use nested stacks, export/import values |
| 100.64.0.0/16 for pods | Secondary CIDR required on VPC | Configure VPC CNI custom networking |
| Istio sidecar overhead | ~100MB RAM per pod | Right-size node groups accordingly |

### Compliance Constraints
| Constraint | NIST Control | Implementation |
|------------|--------------|----------------|
| All changes via IaC | CM-3 | CloudFormation only, no console changes |
| Mandatory resource tagging | CM-8 | cfn-guard enforces tags before deployment |
| Audit all actions | AU-2 | VPC Flow Logs, CloudWatch, Loki |
| No wildcard IAM permissions | AC-6 | cfn-guard validates IAM policies |
| Encryption at rest | SC-28 | KMS for EKS secrets, RDS, S3 |
| Encryption in transit | SC-8 | Istio mTLS, ALB TLS termination |

### Operational Constraints
| Constraint | Reason | Mitigation |
|------------|--------|------------|
| 72hr idle resource reaping (DEV only) | Cost control | Kubecost monitoring, alerts before deletion |
| Blue/Green deployments to PRD | Zero downtime requirement | ALB target group switching |
| 4-hour RTO for DR | Business continuity | Velero backups, CloudFormation re-provisioning |

---

## Dependencies

### AWS Services
| Service | Purpose | Version/Config |
|---------|---------|----------------|
| Amazon EKS | Kubernetes control plane | 1.32+ |
| EC2 | Worker nodes, bastion | t3a.medium (bastion), m5.large (nodes) |
| VPC | Networking | Primary + Secondary CIDR |
| ALB | Load balancing | Via AWS Load Balancer Controller |
| RDS | PostgreSQL databases | Aurora PostgreSQL 15+ |
| S3 | Backups, artifacts | Cross-region replication enabled |
| KMS | Encryption keys | Customer-managed keys |
| IAM | Identity management | IRSA for service accounts |
| CloudWatch | Logging, metrics | VPC Flow Logs destination |
| SQS/SNS | Event messaging | Async agent communication |
| Bedrock | LLM access | Claude model |

### Open Source Components
| Component | Version | Purpose |
|-----------|---------|---------|
| Istio | 1.24+ | Service mesh, mTLS |
| Loki | 3.x | Log aggregation |
| Grafana | 11.x | Visualization |
| Tempo | 2.x | Distributed tracing |
| Mimir | 2.x | Metrics storage |
| Trivy | 0.58+ | Vulnerability scanning |
| Trivy Operator | 0.24+ | In-cluster scanning |
| Velero | 1.15+ | Backup/restore |
| Kubecost | 2.x | Cost management |
| Headlamp | 0.26+ | Admin console |
| LangGraph | Latest | Agent orchestration |

### Python Dependencies
| Package | Purpose |
|---------|---------|
| langgraph | Agent state machine |
| langchain-aws | Bedrock integration |
| boto3 | AWS SDK |
| cfn-lint | CloudFormation linting |
| kubernetes | K8s Python client |
| click | CLI framework |
| pydantic | Data validation |
| pytest | Testing |

---

## Workflow Diagrams

### Deployment Workflow
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Commit    │────►│   CI Build  │────►│  DEV Deploy │────►│  DEV Test   │
│  to Git     │     │  & Scan     │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └──────┬──────┘
                                                                    │
                                                              Pass? │
                                                                    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  PRD Live   │◄────│  PRD Deploy │◄────│  TST Test   │◄────│  TST Deploy │
│             │     │ Blue/Green  │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

### Agent Communication Workflow
```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Chat Agent (Supervisor)                        │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐            │
│  │  Parse    │─►│  Route    │─►│  MFA      │─►│ Aggregate │            │
│  │  Command  │  │  Intent   │  │  Gate     │  │ Response  │            │
│  └───────────┘  └─────┬─────┘  └─────┬─────┘  └───────────┘            │
└───────────────────────┼──────────────┼──────────────────────────────────┘
                        │              │
        ┌───────────────┼──────────────┼───────────────┐
        │               │              │               │
   ┌────▼────┐    ┌────▼────┐   ┌─────▼────┐   ┌─────▼────┐
   │   IaC   │    │   K8s   │   │ Security │   │  Cost    │
   │  Agent  │    │  Agent  │   │  Agent   │   │  Agent   │
   └────┬────┘    └────┬────┘   └────┬─────┘   └────┬─────┘
        │              │             │              │
   ┌────▼────┐    ┌────▼────┐   ┌────▼─────┐   ┌────▼─────┐
   │ cfn-lint│    │ kubectl │   │  Trivy   │   │ Kubecost │
   │cfn-guard│    │  helm   │   │ Scanning │   │ Metrics  │
   └─────────┘    └─────────┘   └──────────┘   └──────────┘
```

### Infrastructure Build Workflow
```
Phase 1: Foundation              Phase 2: EKS                Phase 3: Services
┌─────────────────┐             ┌─────────────────┐         ┌─────────────────┐
│ VPC + Subnets   │────────────►│ EKS Cluster     │────────►│ Istio Mesh      │
│ NACLs + SGs     │             │ Node Groups     │         │ LGTM Stack      │
│ NAT + IGW       │             │ OIDC Provider   │         │ Trivy Operator  │
│ IAM Roles       │             │ EKS Add-ons     │         │ Headlamp        │
└─────────────────┘             └─────────────────┘         └─────────────────┘
```

---

## Component Diagrams

### Network Architecture
```
                              ┌─────────────────────────────────────────────────┐
                              │                    Internet                      │
                              └─────────────────────────┬───────────────────────┘
                                                        │
                              ┌─────────────────────────▼───────────────────────┐
                              │              Internet Gateway                    │
                              └─────────────────────────┬───────────────────────┘
                                                        │
┌───────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┐
│                                                  VPC (10.0.0.0/16 + 100.64.0.0/16)                            │
│                                                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                    PUBLIC SUBNETS (10.0.0.0/20 - 10.0.32.0/20)                           │  │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐                                      │  │
│  │  │  us-east-1a     │    │  us-east-1b     │    │  us-east-1c     │                                      │  │
│  │  │  ┌───────────┐  │    │  ┌───────────┐  │    │  ┌───────────┐  │                                      │  │
│  │  │  │    ALB    │  │    │  │    ALB    │  │    │  │    ALB    │  │    Route: 0.0.0.0/0 → IGW            │  │
│  │  │  └───────────┘  │    │  └───────────┘  │    │  └───────────┘  │                                      │  │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘                                      │  │
│  └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                        │                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                   PRIVATE SUBNETS (10.0.48.0/20 - 10.0.80.0/20)                          │  │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐                                      │  │
│  │  │  us-east-1a     │    │  us-east-1b     │    │  us-east-1c     │                                      │  │
│  │  │  ┌───────────┐  │    │  ┌───────────┐  │    │  ┌───────────┐  │                                      │  │
│  │  │  │  Bastion  │  │    │  │    NAT    │  │    │  │    RDS    │  │    Route: 0.0.0.0/0 → NAT            │  │
│  │  │  │ t3a.medium│  │    │  │  Gateway  │  │    │  │  Primary  │  │                                      │  │
│  │  │  └───────────┘  │    │  └───────────┘  │    │  └───────────┘  │                                      │  │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘                                      │  │
│  └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                        │                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                                 POD SUBNETS (100.64.0.0/16) - NON-ROUTABLE                               │  │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐                                      │  │
│  │  │  us-east-1a     │    │  us-east-1b     │    │  us-east-1c     │                                      │  │
│  │  │  ┌───────────┐  │    │  ┌───────────┐  │    │  ┌───────────┐  │                                      │  │
│  │  │  │ EKS Nodes │  │    │  │ EKS Nodes │  │    │  │ EKS Nodes │  │    Route: 0.0.0.0/0 → NAT (outbound) │  │
│  │  │  │   Pods    │  │    │  │   Pods    │  │    │  │   Pods    │  │    NOT directly addressable from     │  │
│  │  │  └───────────┘  │    │  └───────────┘  │    │  └───────────┘  │    internet                          │  │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘                                      │  │
│  └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Agent Architecture
```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    LANGGRAPH STATE MACHINE                                   │
│                                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐   │
│  │                              InfraAgentState                                         │   │
│  │  • messages: List[BaseMessage]     • current_agent: str                             │   │
│  │  • environment: DEV|TST|PRD        • cloudformation_templates: dict                 │   │
│  │  • validation_results: dict        • eks_cluster_status: dict                       │   │
│  │  • nist_compliance_status: dict    • audit_log: List[dict]                          │   │
│  │  • mfa_verified: bool              • session_expiry: datetime                       │   │
│  └─────────────────────────────────────────────────────────────────────────────────────┘   │
│                                           │                                                  │
│                                           ▼                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────────────┐    │
│  │                                  Chat Agent                                         │    │
│  │                               (Supervisor Node)                                     │    │
│  │  • Operator authentication        • Command parsing                                 │    │
│  │  • Intent routing                 • Response aggregation                            │    │
│  └────────────────────────────────────────┬───────────────────────────────────────────┘    │
│                                           │                                                  │
│           ┌───────────┬───────────┬───────┴───────┬───────────┬───────────┐                │
│           ▼           ▼           ▼               ▼           ▼           ▼                │
│  ┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │  IaC Agent   │ │K8s Agent │ │ Deploy   │ │ Verify   │ │ Security │ │  Cost    │        │
│  │              │ │          │ │  Agent   │ │  Agent   │ │  Agent   │ │  Agent   │        │
│  │ • cfn-lint   │ │• kubectl │ │• GitHub  │ │• Drift   │ │• Trivy   │ │• Kubecost│        │
│  │ • cfn-guard  │ │• helm    │ │  Actions │ │  detect  │ │• NIST    │ │• Reaper  │        │
│  │ • ChangeSets │ │• Istio   │ │• B/G     │ │• Tests   │ │  checks  │ │          │        │
│  └──────────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow Diagram
```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       DATA FLOWS                                             │
│                                                                                              │
│  ┌────────────┐                                                                              │
│  │  Operator  │──── CLI Command ────►┌───────────────┐                                      │
│  │            │                      │  Chat Agent   │                                      │
│  │            │◄─── Response ────────│               │                                      │
│  └────────────┘                      └───────┬───────┘                                      │
│                                              │                                               │
│                          ┌───────────────────┼───────────────────┐                          │
│                          │                   │                   │                          │
│                          ▼                   ▼                   ▼                          │
│                   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐                  │
│                   │ CloudForm.  │     │    EKS      │     │  Bedrock    │                  │
│                   │   Stacks    │     │   Cluster   │     │   Claude    │                  │
│                   └──────┬──────┘     └──────┬──────┘     └─────────────┘                  │
│                          │                   │                                               │
│                          ▼                   ▼                                               │
│                   ┌─────────────┐     ┌─────────────┐                                       │
│                   │    AWS      │     │ Kubernetes  │                                       │
│                   │  Resources  │     │   Pods      │                                       │
│                   └─────────────┘     └──────┬──────┘                                       │
│                                              │                                               │
│                          ┌───────────────────┼───────────────────┐                          │
│                          ▼                   ▼                   ▼                          │
│                   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐                  │
│                   │    Loki     │     │   Tempo     │     │   Mimir     │                  │
│                   │   (Logs)    │     │  (Traces)   │     │  (Metrics)  │                  │
│                   └──────┬──────┘     └──────┬──────┘     └──────┬──────┘                  │
│                          │                   │                   │                          │
│                          └───────────────────┼───────────────────┘                          │
│                                              ▼                                               │
│                                       ┌─────────────┐                                       │
│                                       │   Grafana   │                                       │
│                                       │ (Dashboard) │                                       │
│                                       └─────────────┘                                       │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Security Architecture

### Zero Trust Implementation
```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    ZERO TRUST LAYERS                                         │
│                                                                                              │
│  Layer 1: Network Isolation                                                                  │
│  ├── NACLs deny by default                                                                   │
│  ├── Security Groups allow specific traffic only                                             │
│  └── Pod subnets (100.64.x.x) not internet-routable                                         │
│                                                                                              │
│  Layer 2: Service Mesh (Istio)                                                               │
│  ├── mTLS between all pods (automatic)                                                       │
│  ├── SPIFFE identity certificates                                                            │
│  └── Authorization policies for service-to-service                                           │
│                                                                                              │
│  Layer 3: Identity & Access                                                                  │
│  ├── IRSA for pod-level AWS permissions                                                      │
│  ├── JIT access for production (STS AssumeRole)                                             │
│  └── MFA required for operator actions                                                       │
│                                                                                              │
│  Layer 4: Data Protection                                                                    │
│  ├── KMS encryption at rest (EKS secrets, RDS, S3)                                          │
│  ├── TLS 1.3 for ALB termination                                                            │
│  └── Secrets in AWS Secrets Manager                                                          │
│                                                                                              │
│  Layer 5: Continuous Validation                                                              │
│  ├── Trivy scans in CI/CD pipeline                                                          │
│  ├── cfn-guard NIST compliance checks                                                        │
│  └── Drift detection and auto-remediation                                                    │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Version Information

| Component | Version | Notes |
|-----------|---------|-------|
| EKS | 1.32+ | Latest standard support |
| Istio | 1.24+ | mTLS enabled |
| Loki | 3.x | Scalable mode |
| Grafana | 11.x | Unified observability |
| Trivy | 0.58+ | Latest scanning rules |
| Python | 3.11+ | LangGraph compatible |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-01-04 | AI Agent | Initial architecture document |
