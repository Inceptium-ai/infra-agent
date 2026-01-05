# Infrastructure Build Workflow

This document describes the workflow for building and managing AWS infrastructure using the Infrastructure Agent.

## Overview

The Infrastructure Agent automates the deployment and management of AWS resources through CloudFormation, following a strict order of operations to ensure dependencies are satisfied.

## Stack Deployment Order

Infrastructure is deployed in the following order to satisfy dependencies:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Phase 1: Foundation                          │
├─────────────────────────────────────────────────────────────────┤
│  1. IAM Roles (iam-roles.yaml)                                  │
│     ├── EKS Cluster Role                                        │
│     ├── EKS Node Group Role                                     │
│     ├── Bastion Role                                            │
│     ├── VPC Flow Logs Role                                      │
│     └── IRSA Policies (LB Controller, EBS CSI, VPC CNI)         │
│                                                                 │
│  2. VPC (vpc.yaml)                                              │
│     ├── VPC with dual CIDR (10.0.0.0/16 + 100.64.0.0/16)       │
│     ├── Public Subnets (3 AZs) - ALB only                       │
│     ├── Private Subnets (3 AZs) - Bastion, NAT, RDS             │
│     ├── Pod Subnets (3 AZs) - EKS pods (100.64.x.x)            │
│     ├── Internet Gateway                                        │
│     ├── NAT Gateways (3 for HA)                                 │
│     ├── Route Tables                                            │
│     └── VPC Flow Logs                                           │
│                                                                 │
│  3. Security Groups (security-groups.yaml)                      │
│     ├── ALB Security Group                                      │
│     ├── Bastion Security Group                                  │
│     ├── EKS Cluster Security Group                              │
│     ├── EKS Nodes Security Group                                │
│     ├── RDS Security Group                                      │
│     ├── VPC Endpoints Security Group                            │
│     └── Istio Ingress Security Group                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Phase 2: EKS Cluster                         │
├─────────────────────────────────────────────────────────────────┤
│  4. EKS Cluster (cluster.yaml)                                  │
│     ├── EKS Control Plane                                       │
│     ├── KMS Key for Secrets Encryption                          │
│     ├── OIDC Provider for IRSA                                  │
│     └── Control Plane Logging                                   │
│                                                                 │
│  5. EKS Node Groups (node-groups.yaml)                          │
│     ├── General Purpose Nodes                                   │
│     └── Spot Instances (optional)                               │
│                                                                 │
│  6. EKS Add-ons (addons.yaml)                                   │
│     ├── AWS Load Balancer Controller                            │
│     ├── Amazon EBS CSI Driver                                   │
│     ├── CoreDNS                                                 │
│     ├── kube-proxy                                              │
│     └── Amazon VPC CNI                                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Phase 3: K8s Services                        │
├─────────────────────────────────────────────────────────────────┤
│  7. Helm Releases                                               │
│     ├── Istio (service mesh)                                    │
│     ├── LGTM Stack (observability)                              │
│     ├── Trivy Operator (security scanning)                      │
│     ├── Velero (backups)                                        │
│     ├── Kubecost (cost management)                              │
│     └── Headlamp (admin console)                                │
└─────────────────────────────────────────────────────────────────┘
```

## Agent Interaction

### Chat Agent Commands

```bash
# Start interactive chat session
infra-agent chat --env dev

# Execute single command
infra-agent exec "deploy vpc stack" --env dev

# Check deployment status
infra-agent status --env dev
```

### Example Interactions

#### Deploy VPC Stack

```
You: Deploy the VPC stack to dev environment

Agent: I'll deploy the VPC CloudFormation stack to the dev environment.

Step 1: Validating template with cfn-lint...
✓ Template validation passed

Step 2: Running cfn-guard NIST compliance checks...
✓ All 8 NIST controls passed (AU-2, AU-3, SC-7, SC-8, AC-2, AC-6, CM-8, CM-3)

Step 3: Creating change set 'infra-agent-dev-vpc-20250104-001'...
✓ Change set created

Step 4: Changes to be applied:
  - CREATE AWS::EC2::VPC (infra-agent-dev-vpc)
  - CREATE AWS::EC2::Subnet (x9 subnets across 3 AZs)
  - CREATE AWS::EC2::InternetGateway
  - CREATE AWS::EC2::NatGateway (x3)
  - CREATE AWS::EC2::RouteTable (x4)
  - CREATE AWS::EC2::FlowLog

Do you want to execute this change set? (yes/no)
```

#### Check Stack Status

```
You: Show me the status of all stacks

Agent: Current CloudFormation stack status for dev environment:

Stack Name                     Status              Last Updated
─────────────────────────────────────────────────────────────
infra-agent-dev-iam-roles     CREATE_COMPLETE     2025-01-04 10:00:00
infra-agent-dev-vpc           CREATE_COMPLETE     2025-01-04 10:15:00
infra-agent-dev-security-groups CREATE_COMPLETE   2025-01-04 10:30:00
infra-agent-dev-eks-cluster   CREATE_IN_PROGRESS  2025-01-04 10:45:00

EKS cluster creation typically takes 15-20 minutes.
```

## Validation Workflow

Every CloudFormation template goes through this validation pipeline:

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   cfn-lint       │────▶│   cfn-guard      │────▶│   Change Set     │
│   (Syntax)       │     │   (NIST Rules)   │     │   (Preview)      │
└──────────────────┘     └──────────────────┘     └──────────────────┘
         │                        │                        │
         ▼                        ▼                        ▼
    Syntax errors           NIST violations         Resource changes
    Template issues         Missing tags            Cost estimates
```

### cfn-lint Checks

- YAML/JSON syntax validation
- AWS resource property validation
- Best practice recommendations
- Reference resolution

### cfn-guard NIST Checks

```bash
# Run NIST compliance validation
cfn-guard validate \
  --data infra/cloudformation/stacks/00-foundation/vpc.yaml \
  --rules infra/cloudformation/cfn-guard-rules/nist-800-53/phase1-controls.guard \
  --rules infra/cloudformation/cfn-guard-rules/nist-800-53/tagging-rules.guard
```

Controls validated:
- **AU-2**: VPC Flow Logs enabled
- **AU-3**: Flow logs capture all traffic
- **SC-7**: NACLs and security groups configured
- **SC-8**: TLS-only traffic enforced
- **AC-2**: IAM roles with trust policies
- **AC-6**: No wildcard permissions
- **CM-8**: Mandatory tags present
- **CM-3**: IaC version tagged

## Rollback Procedures

### Automatic Rollback

CloudFormation automatically rolls back failed deployments:

```
You: Deploy eks cluster stack

Agent: Deploying EKS cluster stack...

Step 3: Executing change set...
ERROR: Stack creation failed - IAM role not found

CloudFormation has automatically rolled back the stack.
Reason: Resource handler returned message: "Role
arn:aws:iam::123456789012:role/infra-agent-dev-eks-cluster-role
is not authorized to perform: eks:CreateCluster"

Recommendation: Ensure the IAM roles stack is deployed first.
```

### Manual Rollback

```
You: Rollback the last deployment of vpc stack

Agent: I'll initiate a rollback of the VPC stack.

Current version: v1.2.0 (deployed 2025-01-04 10:15:00)
Previous version: v1.1.0 (deployed 2025-01-03 15:30:00)

Changes to revert:
  - MODIFY AWS::EC2::Subnet (CIDR change)
  - DELETE AWS::EC2::NatGateway (additional NAT removed)

Do you want to proceed with rollback? (yes/no)
```

## Drift Detection

The Verification Agent monitors for configuration drift:

```
You: Check for drift in all stacks

Agent: Running drift detection on all stacks...

Stack: infra-agent-dev-vpc
  ✓ No drift detected

Stack: infra-agent-dev-security-groups
  ⚠ DRIFT DETECTED

  Resource: AlbSecurityGroup (AWS::EC2::SecurityGroup)
  Drift Status: MODIFIED

  Expected:
    SecurityGroupIngress:
      - FromPort: 443
        ToPort: 443

  Actual:
    SecurityGroupIngress:
      - FromPort: 443
        ToPort: 443
      - FromPort: 80    ← ADDED MANUALLY
        ToPort: 80

  Recommendation: Remove port 80 ingress rule (violates NIST SC-8)

Do you want to auto-remediate this drift? (yes/no)
```

## Environment Promotion

Infrastructure changes follow this promotion path:

```
DEV ──────▶ TST ──────▶ PRD
  │           │           │
  │           │           ├── MFA Required
  │           │           └── JIT Access Only
  │           │
  │           └── Integration Tests
  │
  └── Development & Unit Tests
```

### Promotion Command

```
You: Promote vpc stack from dev to tst

Agent: Promoting infra-agent-dev-vpc to TST environment...

Pre-promotion checks:
  ✓ DEV stack status: CREATE_COMPLETE
  ✓ All NIST controls pass
  ✓ No drift detected
  ✓ DEV tests passed (15/15)

Creating TST deployment plan:
  - Stack name: infra-agent-tst-vpc
  - Region: us-east-1
  - Parameters: Adjusted for TST environment

Do you want to proceed with promotion? (yes/no)
```

## Tagging Enforcement

All resources must have these mandatory tags:

| Tag | Description | Example |
|-----|-------------|---------|
| Environment | Deployment environment | dev, tst, prd |
| Owner | Responsible team | platform-team |
| SecurityLevel | Data classification | internal, restricted |
| IaC_Version | Template version | 1.0.0 |

The IaC Agent validates tags before deployment:

```
You: Deploy security groups stack

Agent: Validating template...

ERROR: NIST CM-8 violation - Missing mandatory tags

Resource: CustomSecurityGroup
Missing tags: Owner, SecurityLevel

Please add the required tags to proceed.
```

## Cost Estimation

Change sets include cost estimates:

```
You: What will the vpc stack cost?

Agent: Estimated monthly costs for infra-agent-dev-vpc:

Resource                    Quantity    Monthly Cost
────────────────────────────────────────────────────
NAT Gateway                 3           $96.36
  - Hourly: $0.045/hr × 3 × 730 hrs
  - Data: ~$0.045/GB (varies)

VPC Flow Logs               1           ~$5-20
  - CloudWatch Logs ingestion

Elastic IPs                 3           $0.00
  - Attached to NAT Gateways (no charge)

VPC                         1           $0.00
Subnets                     9           $0.00
Route Tables                4           $0.00

────────────────────────────────────────────────────
Estimated Total:                        ~$101-116/month

Note: Actual costs depend on data transfer volume.
```

## Cleanup

```
You: Delete all dev environment stacks

Agent: This will delete all CloudFormation stacks in dev environment.

Deletion order (reverse dependency):
  1. infra-agent-dev-eks-addons
  2. infra-agent-dev-eks-nodegroups
  3. infra-agent-dev-eks-cluster
  4. infra-agent-dev-security-groups
  5. infra-agent-dev-vpc
  6. infra-agent-dev-iam-roles

⚠ WARNING: This action is irreversible!

Type 'DELETE DEV' to confirm:
```
