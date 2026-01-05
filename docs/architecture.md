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

### CloudFormation Constraints (Lessons Learned)
| Constraint | Impact | Mitigation |
|------------|--------|------------|
| Export value max 1024 chars | Cannot export EKS CertificateAuthorityData | Store in SSM Parameter Store or retrieve via API |
| No commas in tag values | NIST_Control tags like `AC-2,AC-6` fail validation | Use underscores: `AC-2_AC-6` |
| SSM parameters must exist | `{{resolve:ssm:...}}` fails if parameter missing | Use static values until bootstrap stack creates params |
| Export names must be unique | Duplicate exports across stacks cause failures | Use descriptive prefixes (e.g., `eks-cluster-created-sg-id`) |
| EKS creates log groups | Defining same log group causes conflict | Add `DependsOn` to create log group BEFORE EKS cluster |
| EKS upgrade path | Can only upgrade one minor version at a time | Plan sequential upgrades (1.32 → 1.33 → 1.34) |

### AMI and Instance Constraints
| Constraint | Impact | Mitigation |
|------------|--------|------------|
| AMI IDs are region-specific | Hardcoded AMIs break cross-region | Use SSM public parameters for dynamic lookup |
| AL2023 has curl-minimal | Installing curl causes package conflict | Skip curl install or use `--allowerasing` |
| User data must match OS | AL2023 uses dnf, Ubuntu uses apt | Verify AMI matches expected OS before deployment |

---

## Dependencies

### AWS Services
| Service | Purpose | Version/Config |
|---------|---------|----------------|
| Amazon EKS | Kubernetes control plane | 1.34 |
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

## Compute Requirements

### EKS Add-on Resource Requirements

| Component | CPU Request | Memory Request | Replicas | Total CPU | Total Memory |
|-----------|-------------|----------------|----------|-----------|--------------|
| **Istio Control Plane** |
| istiod | 500m | 2Gi | 2 | 1000m | 4Gi |
| istio-ingressgateway | 100m | 128Mi | 2 | 200m | 256Mi |
| istio sidecars (per pod) | 100m | 128Mi | ~20 | 2000m | 2.5Gi |
| **Observability (LGTM)** |
| Loki | 500m | 1Gi | 3 | 1500m | 3Gi |
| Grafana | 250m | 512Mi | 2 | 500m | 1Gi |
| Tempo | 500m | 1Gi | 2 | 1000m | 2Gi |
| Mimir | 500m | 1Gi | 2 | 1000m | 2Gi |
| **Security & Operations** |
| Trivy Operator | 100m | 256Mi | 1 | 100m | 256Mi |
| Velero | 100m | 256Mi | 1 | 100m | 256Mi |
| Kubecost | 200m | 512Mi | 1 | 200m | 512Mi |
| Headlamp | 100m | 128Mi | 1 | 100m | 128Mi |
| **AWS Controllers** |
| AWS LB Controller | 100m | 128Mi | 2 | 200m | 256Mi |
| EBS CSI Driver | 100m | 128Mi | 2 | 200m | 256Mi |
| **Kubernetes Core** |
| CoreDNS | 100m | 70Mi | 2 | 200m | 140Mi |
| kube-proxy | 100m | 128Mi | per node | 300m | 384Mi |
| VPC CNI (aws-node) | 25m | 64Mi | per node | 75m | 192Mi |

### Total Resource Summary

| Resource | Base Estimate | With 30% Buffer |
|----------|---------------|-----------------|
| **Total CPU** | ~8.3 vCPU | ~11 vCPU |
| **Total Memory** | ~16.5 Gi | ~22 Gi |

### Worker Node Sizing

Based on compute requirements, the recommended instance type is **t3a.xlarge**:

| Instance Type | vCPU | Memory | Network | Hourly Cost | Monthly (3 nodes) |
|---------------|------|--------|---------|-------------|-------------------|
| t3a.large | 2 | 8 Gi | Up to 5 Gbps | $0.0752 | ~$165 |
| **t3a.xlarge** ✓ | 4 | 16 Gi | Up to 5 Gbps | $0.1504 | ~$330 |
| m5a.xlarge | 4 | 16 Gi | Up to 10 Gbps | $0.172 | ~$375 |

**Selected Configuration:**
- Instance Type: `t3a.xlarge` (4 vCPU, 16 Gi RAM)
- Min Nodes: 2
- Desired Nodes: 3
- Max Nodes: 10
- Disk: 100 GB gp3 (3,000 IOPS, 125 MB/s)
- AMI: AL2023_x86_64_STANDARD (EKS Optimized)

**Cost Estimate (DEV environment):**
| Resource | Monthly Cost |
|----------|--------------|
| EKS Control Plane | $73 |
| Worker Nodes (3x t3a.xlarge) | ~$330 |
| NAT Gateways (3x) | ~$100 |
| EBS Storage (3x 100GB gp3) | ~$24 |
| Data Transfer | ~$20-50 |
| **Total DEV** | **~$550-580/month** |

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

### Bastion Access Architecture (SSM Session Manager)

The bastion host uses **AWS Systems Manager Session Manager** instead of traditional SSH. This is a Zero Trust approach that eliminates SSH key management and exposed ports.

```
┌─────────────────┐                    ┌─────────────────┐                    ┌─────────────────┐
│   Operator      │                    │   AWS SSM       │                    │    Bastion      │
│   Workstation   │                    │   Service       │                    │    (Private)    │
│                 │                    │                 │                    │                 │
│  ┌───────────┐  │   HTTPS (443)      │  ┌───────────┐  │   SSM Agent        │  ┌───────────┐  │
│  │ AWS CLI + │  │ ─────────────────► │  │ Session   │  │ ◄───────────────── │  │ SSM Agent │  │
│  │ SSM Plugin│  │   WebSocket        │  │ Manager   │  │   Outbound HTTPS   │  │           │  │
│  └───────────┘  │                    │  └───────────┘  │                    │  └───────────┘  │
└─────────────────┘                    └─────────────────┘                    └─────────────────┘
        │                                      │                                      │
        │                                      │                                      │
   IAM Auth +                            TLS 1.2/1.3                           No inbound
   MFA (optional)                        Encryption                            ports open
```

**Security Features:**

| Feature | Traditional SSH | SSM Session Manager |
|---------|-----------------|---------------------|
| **Inbound Ports** | Port 22 open | No inbound ports |
| **Key Management** | SSH key pairs | IAM credentials |
| **Authentication** | Key-based | IAM + optional MFA |
| **Audit Trail** | Manual logging | CloudTrail automatic |
| **Session Logging** | Optional | S3/CloudWatch Logs |
| **Network Path** | Direct to instance | Via AWS control plane |

**Protocol Flow:**
1. Operator runs `aws ssm start-session --target <instance-id>`
2. AWS CLI authenticates via IAM credentials (supports MFA)
3. SSM service validates IAM permissions (`ssm:StartSession`)
4. WebSocket connection established over HTTPS (port 443)
5. SSM Agent on bastion (outbound only) connects to SSM service
6. Bidirectional encrypted tunnel created
7. All commands logged to CloudTrail

**NIST 800-53 R5 Controls Satisfied:**

| Control | Implementation |
|---------|---------------|
| AC-2 (Account Management) | IAM-based access, no shared SSH keys |
| AC-6 (Least Privilege) | Fine-grained IAM policies per user/role |
| AU-2 (Audit Events) | All sessions logged to CloudTrail |
| AU-3 (Audit Content) | Session recordings to S3 (optional) |
| SC-7 (Boundary Protection) | No inbound ports, outbound-only agent |
| SC-8 (Transmission Confidentiality) | TLS 1.2+ encryption end-to-end |
| IA-2 (Identification) | IAM identity, optional MFA |

**Connection Script:** `scripts/bastion-connect.sh`
```bash
./scripts/bastion-connect.sh  # Interactive shell on bastion
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
| EKS | 1.34 | Latest standard support |
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
| 1.1 | 2025-01-04 | AI Agent | Added CloudFormation and AMI constraints from lessons learned |
| 1.2 | 2025-01-04 | AI Agent | Added Bastion Access Architecture (SSM Session Manager) section |
| 1.3 | 2025-01-04 | AI Agent | Added Compute Requirements section with EKS add-on resource estimates |
