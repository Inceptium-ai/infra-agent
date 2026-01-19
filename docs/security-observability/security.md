# Security Architecture and NIST 800-53 Compliance

## Executive Summary

This document outlines the security architecture for the AI Infrastructure Agent system, including NIST 800-53 Rev 5 compliance controls, authentication mechanisms, and security tooling.

**Key Security Features:**
- Zero Trust network architecture with non-routable pod subnets (100.64.x.x)
- Centralized SSO via AWS Cognito (OIDC) with ALB authentication
- mTLS encryption via Istio service mesh
- IaC validation via cfn-lint and cfn-guard (CloudFormation policy-as-code)
- Helm chart validation via kube-linter and kubeconform (Kubernetes policy-as-code)
- Continuous vulnerability scanning via Trivy Operator
- KMS encryption at rest for secrets, databases, and storage

---

## NIST 800-53 Rev 5 Control Matrix

### Access Control (AC)

| Control | Description | Implementation | Status |
|---------|-------------|----------------|--------|
| **AC-2** | Account Management | AWS Cognito centralized user management, IRSA for pods | Implemented |
| **AC-3** | Access Enforcement | Kubernetes RBAC, Cognito groups mapped to K8s roles | Implemented |
| **AC-6** | Least Privilege | IRSA scoped IAM policies, no wildcard permissions | Implemented |
| **AC-7** | Unsuccessful Login Attempts | Cognito advanced security features | Implemented |
| **AC-14** | Permitted Actions Without Identification | Disabled - all access requires authentication | Implemented |

### Audit and Accountability (AU)

| Control | Description | Implementation | Status |
|---------|-------------|----------------|--------|
| **AU-2** | Audit Events | VPC Flow Logs, CloudWatch, SigNoz, EKS control plane logs | Implemented |
| **AU-3** | Content of Audit Records | Flow logs capture source/dest IP, ports, protocol, action | Implemented |
| **AU-6** | Audit Review | SigNoz dashboards for log/metric/trace visualization, Kiali for traffic | Implemented |
| **AU-9** | Protection of Audit Information | ClickHouse persistence, S3 versioning | Implemented |
| **AU-11** | Audit Record Retention | 90-day SigNoz retention, S3 lifecycle policies | Implemented |
| **AU-12** | Audit Generation | OTel Collector log collection, Istio access logs | Implemented |

### Configuration Management (CM)

| Control | Description | Implementation | Status |
|---------|-------------|----------------|--------|
| **CM-3** | Configuration Change Control | Git version control, CloudFormation IaC | Implemented |
| **CM-6** | Configuration Settings | cfn-guard policy-as-code enforcement | Implemented |
| **CM-8** | System Component Inventory | Mandatory tagging, Trivy inventory | Implemented |

### Contingency Planning (CP)

| Control | Description | Implementation | Status |
|---------|-------------|----------------|--------|
| **CP-6** | Alternate Storage Site | S3 cross-region replication | Planned |
| **CP-9** | System Backup | Velero daily/weekly backups | Implemented |
| **CP-10** | System Recovery | Blue/Green deployment, CloudFormation rollback | Implemented |

### Identification and Authentication (IA)

| Control | Description | Implementation | Status |
|---------|-------------|----------------|--------|
| **IA-2** | User Identification | AWS Cognito OIDC via ALB for all UI components | Implemented |
| **IA-5** | Authenticator Management | Cognito password policies, MFA support | Implemented |
| **IA-8** | Identification of Non-Organizational Users | Cognito identity federation (social/SAML) | Planned |

### Risk Assessment (RA)

| Control | Description | Implementation | Status |
|---------|-------------|----------------|--------|
| **RA-5** | Vulnerability Scanning | Trivy Operator continuous scanning | Implemented |

### System and Communications Protection (SC)

| Control | Description | Implementation | Status |
|---------|-------------|----------------|--------|
| **SC-7** | Boundary Protection | NACLs, Security Groups, non-routable pod subnets | Implemented |
| **SC-8** | Transmission Confidentiality | Istio mTLS (partial - see Known Gaps) | Partial |
| **SC-28** | Protection of Information at Rest | KMS encryption for EKS secrets, RDS, S3 | Implemented |

### System and Information Integrity (SI)

| Control | Description | Implementation | Status |
|---------|-------------|----------------|--------|
| **SI-2** | Flaw Remediation | Trivy scanning, patching via Helm upgrades | Implemented |
| **SI-4** | System Monitoring | SigNoz metrics/logs/traces, Kiali traffic visualization | Implemented |

---

## Authentication Architecture (AWS Cognito)

### Overview

AWS Cognito provides centralized Single Sign-On (SSO) for all UI components via ALB authentication and OIDC.

```
                    ┌─────────────────────────────────────────┐
                    │            AWS COGNITO                   │
                    │         (Identity Provider)              │
                    │                                          │
                    │  User Pool: infra-agent-dev              │
                    │  App Client: observability-alb           │
                    │                                          │
                    │  Groups:                                 │
                    │    - platform-admins → cluster-admin     │
                    │    - developers → view                   │
                    │                                          │
                    └─────────────────┬───────────────────────┘
                                      │
                              ┌───────▼───────┐
                              │  ALB + HTTPS  │
                              │  (Cognito     │
                              │   Auth)       │
                              └───────┬───────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
              ▼                       ▼                       ▼
        ┌───────────┐          ┌───────────┐          ┌───────────┐
        │  SigNoz   │          │ Headlamp  │          │   Kiali   │
        │ (ALB Auth)│          │(EKS OIDC) │          │ (ALB Auth)│
        └───────────┘          └───────────┘          └───────────┘
```

### Authentication Methods

| Service | Auth Method | Per-User Audit |
|---------|-------------|----------------|
| SigNoz | ALB Cognito | No (shared) |
| Headlamp | OIDC → EKS OIDC | **Yes** (K8s audit logs) |
| Kubecost | ALB Cognito | No (shared) |
| Kiali | ALB Cognito | No (shared) |

### Cognito Groups → Kubernetes RBAC

| Cognito Group | K8s ClusterRole | Description |
|---------------|-----------------|-------------|
| `platform-admins` | cluster-admin | Full cluster access |
| `developers` | view | Read-only access |

### ALB Path-Based Routing

| Path | Service | NodePort | Auth |
|------|---------|----------|------|
| `/` (default) | SigNoz | 30301 | ALB Cognito |
| `/headlamp/*` | Headlamp | 30446 | EKS OIDC |
| `/kubecost/*` | Kubecost | 30091 | ALB Cognito |
| `/kiali/*` | Kiali | 30520 | ALB Cognito |

---

## IaC Security Validation

**PRINCIPLE: All IaC must pass linting and policy validation before deployment.**

### Validation Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        CLOUDFORMATION (AWS Resources)                            │
├─────────────────┬─────────────────┬─────────────────┬─────────────────┐         │
│   Developer     │   cfn-lint      │   cfn-guard     │   Deploy        │         │
│   Commit        │   (Syntax)      │   (NIST Rules)  │   Change Set    │         │
└─────────────────┴─────────────────┴─────────────────┴─────────────────┘         │
                                                                                   │
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        HELM CHARTS (Kubernetes Resources)                        │
├─────────────────┬─────────────────┬─────────────────┬─────────────────┐         │
│   Developer     │   kubeconform   │   kube-linter   │   helm upgrade  │         │
│   Commit        │   (Schema)      │   (Security)    │   --install     │         │
└─────────────────┴─────────────────┴─────────────────┴─────────────────┘         │
```

### CloudFormation Validation

#### cfn-lint (Syntax & Best Practices)

Validates CloudFormation templates for:
- Syntax errors
- Resource property validation
- Best practices
- Deprecated features

```bash
# Activate virtual environment (Python 3.13+)
source .venv/bin/activate

# Lint all CloudFormation templates
cfn-lint infra/cloudformation/stacks/**/*.yaml
```

#### cfn-guard (NIST Policy-as-Code)

Enforces NIST 800-53 compliance rules before deployment.

**Key Rules:**

```guard
# SC-28: RDS encryption at rest
rule rds_encryption {
    AWS::RDS::DBInstance {
        Properties.StorageEncrypted == true
    }
}

# SC-7: RDS not publicly accessible
rule rds_not_public {
    AWS::RDS::DBInstance {
        Properties.PubliclyAccessible == false
    }
}

# CM-8: Mandatory tagging
rule vpc_mandatory_tags {
    AWS::EC2::VPC {
        Properties.Tags EXISTS
    }
}
```

```bash
# Validate against NIST rules
cfn-guard validate \
  --data infra/cloudformation/stacks/ \
  --rules infra/cloudformation/cfn-guard-rules/nist-800-53/ \
  --show-summary all
```

### Helm Chart Validation

#### kubeconform (Schema Validation)

Validates Kubernetes manifests against OpenAPI schemas:
- Correct resource kinds and API versions
- Valid property names and types
- Required fields present

```bash
# Validate Helm values that contain K8s manifests
kubeconform -summary infra/helm/values/demo/

# Validate templated Helm chart
helm template <release> <chart> -f values.yaml | kubeconform -summary
```

#### kube-linter (Security Best Practices)

Checks Kubernetes manifests for security misconfigurations:
- **AC-6 (Least Privilege):** runAsNonRoot, drop ALL capabilities
- **SC-4 (Information Remnants):** readOnlyRootFilesystem
- Resource limits set (prevent DoS)
- No privileged containers
- No host namespace sharing

```bash
# Lint Helm values containing K8s manifests
kube-linter lint infra/helm/values/demo/

# Lint templated Helm chart
helm template <release> <chart> -f values.yaml | kube-linter lint -
```

**Required Security Context (NIST AC-6, SC-4):**

```yaml
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 1000
  containers:
    - name: app
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
```

### Validation Requirements

| IaC Type | Tool | Must Pass | Blocks Deploy |
|----------|------|-----------|---------------|
| CloudFormation | cfn-lint | 0 errors | Yes |
| CloudFormation | cfn-guard | 0 FAIL | Yes |
| Helm/K8s manifests | kubeconform | 0 invalid | Yes |
| Helm/K8s manifests | kube-linter | 0 errors | Yes |

---

## Network Security

### Zero Trust Architecture

```
                    ┌─────────────────────────────────────────────────────┐
                    │                    INTERNET                          │
                    └────────────────────────┬────────────────────────────┘
                                             │
                                    ┌────────▼────────┐
                                    │  Internet GW    │
                                    └────────┬────────┘
                                             │
    ┌────────────────────────────────────────┼────────────────────────────────────────┐
    │                                  VPC                                             │
    │                                                                                  │
    │  ┌──────────────────────────────────────────────────────────────────────────┐   │
    │  │                    PUBLIC SUBNETS (10.0.x.x)                               │   │
    │  │                         ALB ONLY                                           │   │
    │  └──────────────────────────────────────────────────────────────────────────┘   │
    │                                    │                                             │
    │  ┌──────────────────────────────────────────────────────────────────────────┐   │
    │  │                   PRIVATE SUBNETS (10.0.48.x)                              │   │
    │  │              Bastion (SSM), NAT Gateway, RDS                               │   │
    │  └──────────────────────────────────────────────────────────────────────────┘   │
    │                                    │                                             │
    │  ┌──────────────────────────────────────────────────────────────────────────┐   │
    │  │               POD SUBNETS (100.64.x.x) - NON-ROUTABLE                      │   │
    │  │                     EKS Nodes + Pods                                        │   │
    │  │                                                                             │   │
    │  │  NOT directly addressable from internet                                    │   │
    │  │  Traffic flows: Internet → ALB → Pods (via VPC routing)                    │   │
    │  │  Outbound: Pods → NAT Gateway → Internet (for image pulls, patches)        │   │
    │  └──────────────────────────────────────────────────────────────────────────┘   │
    │                                                                                  │
    └──────────────────────────────────────────────────────────────────────────────────┘
```

### Security Groups

| Security Group | Ingress Rules | Egress Rules | Purpose |
|----------------|---------------|--------------|---------|
| ALB SG | 443 from 0.0.0.0/0 | All to VPC | Internet-facing load balancer |
| EKS Nodes SG | All from ALB SG | All to VPC | Worker node traffic |
| RDS SG | 5432 from EKS Nodes SG | None | Database access |
| Bastion SG | None (SSM only) | 443 to VPC endpoints | Admin access |

### Istio mTLS

Istio provides automatic mTLS encryption between all pods with sidecar injection:

```yaml
# PeerAuthentication - enforce mTLS
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: istio-system
spec:
  mtls:
    mode: STRICT
```

**Known Gap (SC-8):** See "Known Compliance Gaps" section.

---

## Vulnerability Scanning

### Trivy Operator

Continuous in-cluster vulnerability scanning for:
- Container images (CVEs)
- Kubernetes configurations
- RBAC assessments
- Exposed secrets

**Security Gate:**
- CI/CD pipeline blocks on CRITICAL vulnerabilities
- HIGH vulnerabilities generate alerts
- Reports stored as Kubernetes CRDs

### Scan Results

| Report Type | CRD | Frequency |
|-------------|-----|-----------|
| VulnerabilityReport | `vulns.aquasecurity.github.io` | On image change |
| ConfigAuditReport | `configaudits.aquasecurity.github.io` | On resource change |
| RbacAssessmentReport | `rbacassessments.aquasecurity.github.io` | Periodic |
| ExposedSecretReport | `exposedsecrets.aquasecurity.github.io` | On image change |

---

## Secrets Management

### AWS Secrets Manager

| Secret | Purpose | Rotation |
|--------|---------|----------|
| Cognito client secrets | ALB authentication | Manual |
| SigNoz ClickHouse password | Database access | Manual |

### Kubernetes Secrets

All Kubernetes secrets are encrypted at rest using AWS KMS:

```yaml
# EKS Cluster encryption config
EncryptionConfig:
  - Provider:
      KeyArn: !GetAtt EksSecretsKey.Arn
    Resources:
      - secrets
```

---

## Known Compliance Gaps

### SC-8: Transmission Confidentiality (Partial)

**Status:** PARTIAL COMPLIANCE

**Issue:** Observability stack pods in `observability`, `velero`, `kubecost`, `trivy-system` namespaces are running WITHOUT Istio sidecar injection.

**Affected Namespaces:**
| Namespace | Pods | Istio Injection | Status |
|-----------|------|-----------------|--------|
| observability | 37 | Disabled | Not compliant |
| velero | 9 | Disabled | Not compliant |
| kubecost | 5 | Disabled | Not compliant |
| trivy-system | 1 | Disabled | Not compliant |
| headlamp | 1 | Enabled | Compliant |

**Root Cause:** Namespaces not labeled with `istio-injection=enabled` before deployment.

**Resource Constraint:** Enabling sidecars on all 53 pods requires ~5.3 vCPU. Current cluster has ~1.8 vCPU free.

**Compensating Controls:**
- All traffic within private VPC (100.64.x.x non-routable)
- Network policies restrict pod-to-pod communication
- No external exposure without ALB + TLS termination

**Remediation Plan:**
1. Add 1 additional node when budget allows (+$110/mo)
2. Label namespaces: `kubectl label ns observability istio-injection=enabled`
3. Restart deployments to inject sidecars
4. Verify with `istioctl analyze`

---

## Access Patterns

### Bastion Access (SSM Session Manager)

No SSH keys or exposed ports. Access via AWS SSM:

```bash
# Start interactive session
aws ssm start-session --target <instance-id>

# Port forward to cluster
aws ssm start-session \
  --target <instance-id> \
  --document-name AWS-StartPortForwardingSession \
  --parameters "portNumber=443,localPortNumber=8443"
```

### kubectl Access

Via AWS CLI and EKS token:

```bash
# Update kubeconfig
aws eks update-kubeconfig --name infra-agent-dev-cluster --region us-east-1

# Verify access
kubectl get nodes
```

---

## Incident Response

### Logging Locations

| Log Type | Location | Retention |
|----------|----------|-----------|
| VPC Flow Logs | CloudWatch Logs | 90 days |
| EKS Control Plane | CloudWatch Logs | 365 days (PROD) |
| Application Logs | Loki (S3) | 90 days |
| Audit Logs | Loki (S3) | 1 year |

### Alert Channels

| Alert Type | Destination | Priority |
|------------|-------------|----------|
| Security vulnerabilities | Grafana Alerting | High |
| Failed authentications | CloudWatch Alarms | Medium |
| Network anomalies | Grafana Alerting | Medium |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-01-11 | AI Agent | Initial security documentation |
| 1.1 | 2025-01-11 | AI Agent | Added Keycloak authentication architecture |
| 1.2 | 2025-01-11 | AI Agent | Added IaC validation (cfn-lint, cfn-guard) section |
| 2.0 | 2026-01-17 | AI Agent | Replaced Keycloak with AWS Cognito, added Helm validation (kube-linter, kubeconform), updated to SigNoz observability |
