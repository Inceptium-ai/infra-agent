# NIST 800-53 Rev 5 Compliance Workflow

This document describes how the Infrastructure Agent implements and validates NIST 800-53 Rev 5 security controls.

## Overview

The Infrastructure Agent enforces NIST 800-53 Rev 5 controls at multiple layers:

1. **IaC Validation** - cfn-guard rules validate CloudFormation templates
2. **Runtime Scanning** - Trivy scans containers and configurations
3. **Continuous Monitoring** - Drift detection and compliance reporting
4. **Audit Logging** - All agent actions are logged for AU-2 compliance

## Control Implementation by Phase

### Phase 1: Foundation Controls

| Control | Family | Implementation |
|---------|--------|----------------|
| **AU-2** | Audit | VPC Flow Logs to CloudWatch |
| **AU-3** | Audit | Flow logs capture all traffic |
| **SC-7** | System & Comms | NACLs, Security Groups, Zero Trust |
| **SC-8** | System & Comms | TLS-only (no HTTP), mTLS via Istio |
| **AC-2** | Access Control | IAM roles with trust policies |
| **AC-6** | Access Control | Least privilege (no wildcards) |
| **CM-8** | Config Mgmt | Mandatory resource tagging |
| **CM-3** | Config Mgmt | IaC version control |

### Phase 2-9: Additional Controls

| Control | Family | Implementation |
|---------|--------|----------------|
| **SC-28** | System & Comms | KMS encryption for EKS secrets |
| **IA-5** | Identification | AWS Secrets Manager, MFA |
| **CP-9** | Contingency | Velero backups to S3 |
| **CP-10** | Contingency | Blue/Green deployments, rollback |
| **SI-2** | System Integrity | Trivy vulnerability scanning |
| **CA-7** | Assessment | Continuous monitoring, drift detection |
| **PM-3** | Program Mgmt | Kubecost resource tracking |

## cfn-guard Rules

### Rule Structure

```
infra/cloudformation/cfn-guard-rules/
└── nist-800-53/
    ├── phase1-controls.guard    # Core infrastructure controls
    └── tagging-rules.guard      # CM-8 tagging validation
```

### Phase 1 Controls (phase1-controls.guard)

```ruby
# AU-2: VPC Flow Logs must exist
rule vpc_flow_logs_exist when %Resources.*[ Type == "AWS::EC2::VPC" ] {
    %Resources.*[ Type == "AWS::EC2::FlowLog" ] EXISTS
    <<
        NIST AU-2: VPC must have Flow Logs enabled for audit trail
    >>
}

# AU-3: Flow Logs must capture ALL traffic
rule flow_logs_capture_all when %Resources.*[ Type == "AWS::EC2::FlowLog" ] {
    %Resources.*[ Type == "AWS::EC2::FlowLog" ].Properties.TrafficType == "ALL"
    <<
        NIST AU-3: VPC Flow Logs must capture ALL traffic
    >>
}

# SC-7: Security Groups must restrict access
rule no_public_http when %Resources.*[ Type == "AWS::EC2::SecurityGroup" ] {
    let sg_ingress = %Resources.*[ Type == "AWS::EC2::SecurityGroup" ].Properties.SecurityGroupIngress
    when %sg_ingress EXISTS {
        %sg_ingress[
            CidrIp == "0.0.0.0/0" OR CidrIpv6 == "::/0"
        ].FromPort != 80
        <<
            NIST SC-8: No unencrypted HTTP from internet
        >>
    }
}

# AC-6: No wildcard IAM permissions
rule no_wildcard_actions when %Resources.*[ Type == "AWS::IAM::Role" ] {
    let policies = %Resources.*[ Type == "AWS::IAM::Role" ].Properties.Policies
    when %policies EXISTS {
        %policies[*].PolicyDocument.Statement[*].Action != "*"
        <<
            NIST AC-6: No wildcard (*) actions in IAM policies
        >>
    }
}

# CM-8: Mandatory tags
rule vpc_mandatory_tags when %Resources.*[ Type == "AWS::EC2::VPC" ] {
    %Resources.*[ Type == "AWS::EC2::VPC" ].Properties.Tags[*].Key EXISTS
    <<
        NIST CM-8: VPC must have mandatory tags
    >>
}
```

### Running Validation

```bash
# Validate a single template
cfn-guard validate \
  --data infra/cloudformation/stacks/00-foundation/vpc.yaml \
  --rules infra/cloudformation/cfn-guard-rules/nist-800-53/

# Validate all templates
cfn-guard validate \
  --data infra/cloudformation/stacks/ \
  --rules infra/cloudformation/cfn-guard-rules/nist-800-53/ \
  --output-format json
```

## Agent Compliance Commands

### Check Compliance Status

```
You: Check NIST compliance for all stacks

Agent: Running NIST 800-53 Rev 5 compliance checks...

┌─────────────────────────────────────────────────────────────────┐
│                    COMPLIANCE REPORT                            │
│                    Environment: dev                             │
│                    Date: 2025-01-04                             │
├─────────────────────────────────────────────────────────────────┤

Stack: infra-agent-dev-vpc
────────────────────────────────────────────────────────────────
Control   Status    Description
────────────────────────────────────────────────────────────────
AU-2      ✓ PASS   VPC Flow Logs enabled
AU-3      ✓ PASS   Flow Logs capture ALL traffic
SC-7      ✓ PASS   NACLs configured with deny rules
SC-8      ✓ PASS   No HTTP ingress from internet
CM-8      ✓ PASS   All mandatory tags present

Stack: infra-agent-dev-security-groups
────────────────────────────────────────────────────────────────
Control   Status    Description
────────────────────────────────────────────────────────────────
SC-7      ✓ PASS   Security Groups restrict access
SC-8      ✓ PASS   TLS-only ingress enforced
AC-6      ✓ PASS   Least privilege egress rules
CM-8      ✓ PASS   All mandatory tags present

Stack: infra-agent-dev-iam-roles
────────────────────────────────────────────────────────────────
Control   Status    Description
────────────────────────────────────────────────────────────────
AC-2      ✓ PASS   Trust policies defined
AC-6      ✓ PASS   No wildcard permissions
CM-8      ✓ PASS   All mandatory tags present

────────────────────────────────────────────────────────────────
SUMMARY: 14/14 controls PASSED (100%)
────────────────────────────────────────────────────────────────
```

### Compliance Remediation

```
You: Fix compliance issues in security-groups stack

Agent: Analyzing security-groups stack for compliance issues...

Found 1 compliance violation:

Control: SC-8 (Transmission Confidentiality)
Resource: WebAppSecurityGroup
Issue: HTTP ingress (port 80) allowed from 0.0.0.0/0
Severity: HIGH

Recommended remediation:
  1. Remove port 80 ingress rule
  2. Ensure all traffic uses HTTPS (port 443)

I can auto-remediate this by updating the CloudFormation template.

Do you want me to:
  [1] Auto-remediate and deploy
  [2] Generate remediation plan only
  [3] Skip

Choice:
```

## Control-Specific Implementation

### AU-2: Audit Events

**Requirement:** The system must generate audit records for defined events.

**Implementation:**
- VPC Flow Logs capture all network traffic
- CloudWatch Logs store flow logs with 90-day retention
- Agent actions logged to audit trail
- EKS control plane logging enabled

```yaml
# VPC Flow Log Configuration
VpcFlowLog:
  Type: AWS::EC2::FlowLog
  Properties:
    ResourceId: !Ref VPC
    ResourceType: VPC
    TrafficType: ALL
    LogDestinationType: cloud-watch-logs
    LogGroupName: !Sub '/${ProjectName}/${Environment}/vpc-flow-logs'
    MaxAggregationInterval: 60
```

### SC-7: Boundary Protection

**Requirement:** Monitor and control communications at external boundaries.

**Implementation:**
- Zero Trust network architecture
- Non-routable pod subnets (100.64.x.x)
- Public subnets restricted to ALB only
- Security groups enforce least privilege

```
Network Boundary Architecture:

Internet
    │
    ▼
┌───────────────────┐
│   ALB (Public)    │  ← Only HTTPS (443)
│   10.0.x.x        │
└─────────┬─────────┘
          │
┌─────────▼─────────┐
│  Istio Gateway    │  ← mTLS termination
│  100.64.x.x       │
└─────────┬─────────┘
          │
┌─────────▼─────────┐
│   Pod Network     │  ← Non-routable
│   100.64.x.x      │     from internet
└───────────────────┘
```

### AC-6: Least Privilege

**Requirement:** Employ the principle of least privilege.

**Implementation:**
- IAM roles scoped to specific resources
- No wildcard (*) permissions
- IRSA for Kubernetes workloads
- JIT access for PRD environment

```yaml
# Example: Scoped IAM Policy
PolicyDocument:
  Statement:
    - Effect: Allow
      Action:
        - eks:DescribeCluster
        - eks:ListClusters
      Resource: !Sub 'arn:aws:eks:${AWS::Region}:${AWS::AccountId}:cluster/${ProjectName}-${Environment}-*'
```

### SC-8: Transmission Confidentiality

**Requirement:** Protect transmitted information.

**Implementation:**
- TLS 1.2+ for all external traffic
- mTLS via Istio for pod-to-pod traffic
- No HTTP (port 80) allowed from internet
- Certificate management via ACM

```yaml
# Istio PeerAuthentication for mTLS
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: istio-system
spec:
  mtls:
    mode: STRICT
```

### CM-8: System Component Inventory

**Requirement:** Maintain inventory of system components.

**Implementation:**
- Mandatory tags on all resources
- Resource tagging validated by cfn-guard
- Tags include: Environment, Owner, SecurityLevel, IaC_Version

```yaml
# Mandatory Tags Example
Tags:
  - Key: Environment
    Value: !Ref Environment      # dev, tst, prd
  - Key: Owner
    Value: !Ref Owner            # platform-team
  - Key: SecurityLevel
    Value: internal              # public, internal, confidential, restricted
  - Key: IaC_Version
    Value: !Ref IaCVersion       # 1.0.0
```

## Security Gates

All deployments must pass these gates:

```
┌──────────────────────────────────────────────────────────────┐
│                     SECURITY GATES                           │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Gate 1: Template Validation                                 │
│  ────────────────────────────                                │
│  • cfn-lint syntax checks                                    │
│  • cfn-guard NIST rules                                      │
│  • Must pass: 100%                                           │
│                                                              │
│  Gate 2: Container Scanning                                  │
│  ─────────────────────────                                   │
│  • Trivy vulnerability scan                                  │
│  • Must pass: Zero CRITICAL vulnerabilities                  │
│                                                              │
│  Gate 3: Environment Tests                                   │
│  ────────────────────────                                    │
│  • DEV: Unit tests (100% pass)                               │
│  • TST: Integration tests (100% pass)                        │
│  • PRD: E2E tests (100% pass)                                │
│                                                              │
│  Gate 4: Production Approval                                 │
│  ─────────────────────────                                   │
│  • MFA verification required                                 │
│  • JIT access only                                           │
│  • Blue/Green deployment                                     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## Compliance Reporting

### Generate Compliance Report

```
You: Generate NIST compliance report for prd environment

Agent: Generating NIST 800-53 Rev 5 compliance report...

Report saved to: reports/nist-compliance-prd-2025-01-04.pdf

Summary:
────────────────────────────────────────────────────────────────
Control Family          Implemented    Compliant    Coverage
────────────────────────────────────────────────────────────────
Access Control (AC)     5              5            100%
Audit (AU)              4              4            100%
Config Mgmt (CM)        3              3            100%
Contingency (CP)        3              3            100%
Identification (IA)     2              2            100%
System Integrity (SI)   2              2            100%
System & Comms (SC)     4              4            100%
────────────────────────────────────────────────────────────────
TOTAL                   23             23           100%
────────────────────────────────────────────────────────────────

This report can be used for compliance audits and assessments.
```

### Continuous Monitoring (CA-7)

```
You: Enable continuous compliance monitoring

Agent: Configuring continuous compliance monitoring...

Monitoring Schedule:
  • cfn-guard validation: On every deployment
  • Drift detection: Every 4 hours
  • Trivy scanning: Daily at 02:00 UTC
  • Compliance report: Weekly on Sundays

Alert Configuration:
  • Drift detected: SNS notification
  • NIST violation: PagerDuty alert
  • CRITICAL vulnerability: Immediate notification

Compliance dashboard: https://grafana.infra-agent-dev.example.com/d/nist-compliance

✓ Continuous monitoring enabled
```

## MFA Requirements (IA-5)

PRD environment operations require MFA:

```
You: Deploy vpc stack to prd

Agent: This operation requires MFA verification.

PRD environment is protected by additional security controls:
  • MFA verification required
  • JIT access only (4-hour sessions)
  • All actions are audited

Please complete MFA verification:
  [1] Enter TOTP code from authenticator app
  [2] Request hardware token verification
  [3] Cancel operation

Enter your 6-digit TOTP code: ******

✓ MFA verified. Proceeding with PRD deployment...
```

## Audit Trail

All agent actions are logged:

```
You: Show audit log for today

Agent: Displaying audit log for 2025-01-04...

Timestamp            Agent     Action                  Status  NIST Control
────────────────────────────────────────────────────────────────────────────
2025-01-04 10:00:00  IaC       validate_template       SUCCESS CM-3
2025-01-04 10:01:00  IaC       nist_compliance_check   SUCCESS Multiple
2025-01-04 10:02:00  IaC       create_change_set       SUCCESS CM-3
2025-01-04 10:05:00  IaC       execute_change_set      SUCCESS CM-3
2025-01-04 10:15:00  Verify    drift_detection         SUCCESS CA-7
2025-01-04 10:20:00  Security  trivy_scan              SUCCESS SI-2
2025-01-04 10:25:00  Chat      user_query              SUCCESS AU-2

Filter options:
  • By agent: iac, security, verify, chat, k8s, deploy, cost
  • By status: success, failure, pending
  • By date range: --from 2025-01-01 --to 2025-01-04
```
