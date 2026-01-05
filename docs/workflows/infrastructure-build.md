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

---

## Agent Orchestration Script

The following Python module enables autonomous infrastructure deployment:

### orchestrator.py

```python
#!/usr/bin/env python3
"""
Infrastructure Build Orchestrator
Enables AI agent to build infrastructure autonomously
"""

import boto3
import time
import json
from typing import Dict, Any, Optional

class InfrastructureOrchestrator:
    """Orchestrates CloudFormation stack deployments"""

    def __init__(self, region: str = 'us-east-1'):
        self.region = region
        self.cf = boto3.client('cloudformation', region_name=region)
        self.eks = boto3.client('eks', region_name=region)
        self.ssm = boto3.client('ssm', region_name=region)
        self.logs = boto3.client('logs', region_name=region)

    # =========================================
    # Step 0: Version Verification
    # =========================================

    def get_latest_eks_version(self) -> str:
        """Get latest available EKS version"""
        response = self.eks.describe_addon_versions()
        versions = set()
        for addon in response.get('addons', []):
            for compat in addon.get('addonVersions', []):
                for cluster_compat in compat.get('compatibilities', []):
                    v = cluster_compat.get('clusterVersion')
                    if v:
                        versions.add(v)
        return sorted(versions, reverse=True)[0]

    # =========================================
    # Stack Deployment Methods
    # =========================================

    def deploy_stack(
        self,
        stack_name: str,
        template_path: str,
        parameters: list,
        capabilities: list = None,
        wait: bool = True,
        wait_timeout_minutes: int = 30
    ) -> Dict[str, Any]:
        """Deploy a CloudFormation stack"""

        with open(template_path, 'r') as f:
            template_body = f.read()

        # Check if stack exists
        try:
            existing = self.cf.describe_stacks(StackName=stack_name)['Stacks'][0]
            status = existing['StackStatus']

            if status == 'ROLLBACK_COMPLETE':
                self._delete_stack(stack_name)
            elif status in ['CREATE_COMPLETE', 'UPDATE_COMPLETE']:
                return self._get_stack_outputs(stack_name)
            elif 'IN_PROGRESS' in status:
                if wait:
                    return self._wait_for_stack(stack_name, wait_timeout_minutes)
                return {'Status': status}
        except self.cf.exceptions.ClientError as e:
            if 'does not exist' not in str(e):
                raise

        # Create stack
        create_params = {
            'StackName': stack_name,
            'TemplateBody': template_body,
            'Parameters': parameters,
            'Tags': [
                {'Key': 'Project', 'Value': 'infra-agent'},
                {'Key': 'ManagedBy', 'Value': 'InfrastructureOrchestrator'},
            ]
        }

        if capabilities:
            create_params['Capabilities'] = capabilities

        self.cf.create_stack(**create_params)

        if wait:
            return self._wait_for_stack(stack_name, wait_timeout_minutes)

        return {'Status': 'CREATE_IN_PROGRESS'}

    def _wait_for_stack(self, stack_name: str, timeout_minutes: int) -> Dict[str, Any]:
        """Wait for stack to complete"""
        waiter = self.cf.get_waiter('stack_create_complete')
        waiter.wait(
            StackName=stack_name,
            WaiterConfig={'Delay': 30, 'MaxAttempts': timeout_minutes * 2}
        )
        return self._get_stack_outputs(stack_name)

    def _get_stack_outputs(self, stack_name: str) -> Dict[str, Any]:
        """Get stack outputs as dictionary"""
        stack = self.cf.describe_stacks(StackName=stack_name)['Stacks'][0]
        return {o['OutputKey']: o['OutputValue'] for o in stack.get('Outputs', [])}

    def _delete_stack(self, stack_name: str):
        """Delete a stack"""
        self.cf.delete_stack(StackName=stack_name)
        waiter = self.cf.get_waiter('stack_delete_complete')
        waiter.wait(StackName=stack_name)

    # =========================================
    # Phase 1: Foundation
    # =========================================

    def deploy_iam_roles(self, env: str = 'dev') -> Dict[str, Any]:
        """Deploy IAM Roles stack"""
        return self.deploy_stack(
            stack_name=f'infra-agent-{env}-iam-roles',
            template_path='infra/cloudformation/stacks/00-foundation/iam-roles.yaml',
            parameters=[
                {'ParameterKey': 'ProjectName', 'ParameterValue': 'infra-agent'},
                {'ParameterKey': 'Environment', 'ParameterValue': env},
                {'ParameterKey': 'Owner', 'ParameterValue': 'platform-team'},
            ],
            capabilities=['CAPABILITY_NAMED_IAM'],
            wait_timeout_minutes=5
        )

    def deploy_vpc(self, env: str = 'dev') -> Dict[str, Any]:
        """Deploy VPC stack"""
        return self.deploy_stack(
            stack_name=f'infra-agent-{env}-vpc',
            template_path='infra/cloudformation/stacks/00-foundation/vpc.yaml',
            parameters=[
                {'ParameterKey': 'ProjectName', 'ParameterValue': 'infra-agent'},
                {'ParameterKey': 'Environment', 'ParameterValue': env},
                {'ParameterKey': 'Owner', 'ParameterValue': 'platform-team'},
                {'ParameterKey': 'SecurityLevel', 'ParameterValue': 'Internal'},
            ],
            capabilities=['CAPABILITY_NAMED_IAM'],
            wait_timeout_minutes=10
        )

    def deploy_security_groups(self, env: str, vpc_outputs: Dict) -> Dict[str, Any]:
        """Deploy Security Groups stack"""
        return self.deploy_stack(
            stack_name=f'infra-agent-{env}-security-groups',
            template_path='infra/cloudformation/stacks/00-foundation/security-groups.yaml',
            parameters=[
                {'ParameterKey': 'ProjectName', 'ParameterValue': 'infra-agent'},
                {'ParameterKey': 'Environment', 'ParameterValue': env},
                {'ParameterKey': 'VpcId', 'ParameterValue': vpc_outputs['VpcId']},
                {'ParameterKey': 'AllowedCidrBlocks', 'ParameterValue': '10.0.0.0/8'},
                {'ParameterKey': 'Owner', 'ParameterValue': 'platform-team'},
            ],
            wait_timeout_minutes=5
        )

    def deploy_bastion(
        self,
        env: str,
        vpc_outputs: Dict,
        sg_outputs: Dict,
        iam_outputs: Dict
    ) -> Dict[str, Any]:
        """Deploy Bastion Host stack"""
        private_subnets = vpc_outputs['PrivateSubnetIds'].split(',')

        return self.deploy_stack(
            stack_name=f'infra-agent-{env}-bastion',
            template_path='infra/cloudformation/stacks/00-foundation/bastion.yaml',
            parameters=[
                {'ParameterKey': 'ProjectName', 'ParameterValue': 'infra-agent'},
                {'ParameterKey': 'Environment', 'ParameterValue': env},
                {'ParameterKey': 'PrivateSubnetId', 'ParameterValue': private_subnets[0]},
                {'ParameterKey': 'BastionSecurityGroupId', 'ParameterValue': sg_outputs['BastionSecurityGroupId']},
                {'ParameterKey': 'BastionInstanceProfileArn', 'ParameterValue': iam_outputs['BastionInstanceProfileArn']},
                {'ParameterKey': 'InstanceType', 'ParameterValue': 't3a.medium'},
                {'ParameterKey': 'Owner', 'ParameterValue': 'platform-team'},
            ],
            wait_timeout_minutes=5
        )

    # =========================================
    # Network Testing
    # =========================================

    def test_network_connectivity(self, instance_id: str) -> Dict[str, bool]:
        """Run network connectivity tests on bastion"""
        commands = [
            'nslookup google.com > /dev/null 2>&1 && echo "DNS:PASS" || echo "DNS:FAIL"',
            'curl -s --connect-timeout 5 https://google.com > /dev/null && echo "INTERNET:PASS" || echo "INTERNET:FAIL"',
            'aws sts get-caller-identity > /dev/null 2>&1 && echo "AWS_API:PASS" || echo "AWS_API:FAIL"',
            'curl -s --connect-timeout 5 https://public.ecr.aws/v2/ > /dev/null && echo "ECR:PASS" || echo "ECR:FAIL"',
            'curl -s --connect-timeout 5 https://registry-1.docker.io/v2/ > /dev/null && echo "DOCKER:PASS" || echo "DOCKER:FAIL"',
        ]

        response = self.ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName='AWS-RunShellScript',
            Parameters={'commands': commands},
            TimeoutSeconds=60
        )

        command_id = response['Command']['CommandId']
        time.sleep(15)

        output = self.ssm.get_command_invocation(
            CommandId=command_id,
            InstanceId=instance_id
        )

        results = {}
        for line in output['StandardOutputContent'].split('\n'):
            if ':' in line:
                key, value = line.strip().split(':')
                results[key] = value == 'PASS'

        return results

    # =========================================
    # Phase 2: EKS Cluster
    # =========================================

    def deploy_eks_cluster(
        self,
        env: str,
        vpc_outputs: Dict,
        sg_outputs: Dict,
        iam_outputs: Dict,
        eks_version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Deploy EKS Cluster stack"""

        if eks_version is None:
            eks_version = self.get_latest_eks_version()

        private_subnets = vpc_outputs['PrivateSubnetIds'].split(',')

        # Clean up any orphaned log group from previous failed deployment
        log_group_name = f'/aws/eks/infra-agent-{env}-cluster/cluster'
        try:
            self.logs.delete_log_group(logGroupName=log_group_name)
        except self.logs.exceptions.ResourceNotFoundException:
            pass

        return self.deploy_stack(
            stack_name=f'infra-agent-{env}-eks-cluster',
            template_path='infra/cloudformation/stacks/03-eks/cluster.yaml',
            parameters=[
                {'ParameterKey': 'ProjectName', 'ParameterValue': 'infra-agent'},
                {'ParameterKey': 'Environment', 'ParameterValue': env},
                {'ParameterKey': 'KubernetesVersion', 'ParameterValue': eks_version},
                {'ParameterKey': 'VpcId', 'ParameterValue': vpc_outputs['VpcId']},
                {'ParameterKey': 'PrivateSubnet1Id', 'ParameterValue': private_subnets[0]},
                {'ParameterKey': 'PrivateSubnet2Id', 'ParameterValue': private_subnets[1]},
                {'ParameterKey': 'PrivateSubnet3Id', 'ParameterValue': private_subnets[2]},
                {'ParameterKey': 'EksClusterSecurityGroupId', 'ParameterValue': sg_outputs['EksClusterSecurityGroupId']},
                {'ParameterKey': 'EksClusterRoleArn', 'ParameterValue': iam_outputs['EksClusterRoleArn']},
                {'ParameterKey': 'Owner', 'ParameterValue': 'platform-team'},
                {'ParameterKey': 'EnablePublicEndpoint', 'ParameterValue': 'false'},
            ],
            capabilities=['CAPABILITY_NAMED_IAM'],
            wait_timeout_minutes=30  # EKS takes 15-20 minutes
        )

    # =========================================
    # Full Orchestration
    # =========================================

    def build_infrastructure(self, env: str = 'dev') -> Dict[str, Dict]:
        """
        Build complete infrastructure stack

        This is the main entry point for autonomous infrastructure deployment.
        """
        results = {}

        # Step 0: Get latest versions
        eks_version = self.get_latest_eks_version()
        print(f"[INFO] Using EKS version: {eks_version}")

        # Phase 1: Foundation
        print("\n[PHASE 1] Deploying Foundation Infrastructure...")

        print("[1/4] Deploying IAM Roles...")
        results['iam'] = self.deploy_iam_roles(env)
        print(f"      ✓ IAM Roles: {results['iam'].get('EksClusterRoleArn', 'N/A')}")

        print("[2/4] Deploying VPC...")
        results['vpc'] = self.deploy_vpc(env)
        print(f"      ✓ VPC: {results['vpc'].get('VpcId', 'N/A')}")

        print("[3/4] Deploying Security Groups...")
        results['security_groups'] = self.deploy_security_groups(env, results['vpc'])
        print(f"      ✓ Security Groups: {results['security_groups'].get('EksClusterSecurityGroupId', 'N/A')}")

        print("[4/4] Deploying Bastion Host...")
        results['bastion'] = self.deploy_bastion(
            env, results['vpc'], results['security_groups'], results['iam']
        )
        print(f"      ✓ Bastion: {results['bastion'].get('BastionInstanceId', 'N/A')}")

        # Network testing
        print("\n[VALIDATION] Testing network connectivity...")
        time.sleep(60)  # Wait for bastion to initialize

        network_tests = self.test_network_connectivity(results['bastion']['BastionInstanceId'])
        all_passed = all(network_tests.values())
        for test, passed in network_tests.items():
            status = '✓' if passed else '✗'
            print(f"      {status} {test}")

        if not all_passed:
            raise Exception("Network tests failed - check VPC configuration")

        # Phase 2: EKS
        print("\n[PHASE 2] Deploying EKS Cluster...")
        results['eks'] = self.deploy_eks_cluster(
            env, results['vpc'], results['security_groups'], results['iam'], eks_version
        )
        print(f"      ✓ EKS Cluster: {results['eks'].get('ClusterName', 'N/A')}")
        print(f"      ✓ Endpoint: {results['eks'].get('ClusterEndpoint', 'N/A')}")

        # Phase 3: Node Groups (TODO)
        # Phase 4: Add-ons (TODO)
        # Phase 5: Helm Charts (TODO)

        return results


# Main execution
if __name__ == '__main__':
    orchestrator = InfrastructureOrchestrator(region='us-east-1')
    outputs = orchestrator.build_infrastructure('dev')

    print("\n" + "=" * 60)
    print("DEPLOYMENT COMPLETE")
    print("=" * 60)
    print(json.dumps(outputs, indent=2, default=str))
```

---

## Agent Training Instructions

When training the AI agent to use this workflow:

### Key Principles

1. **Always verify versions first** - Never hardcode versions without checking latest stable
2. **Follow dependency order** - IAM → VPC → Security Groups → Bastion → EKS
3. **Test before proceeding** - Run network tests before EKS deployment
4. **Handle errors gracefully** - Clean up failed stacks before retry
5. **Use IaC exclusively** - All resources via CloudFormation templates

### Error Recovery Patterns

| Error Type | Detection | Resolution |
|------------|-----------|------------|
| ROLLBACK_COMPLETE | Stack status check | Delete stack, fix issue, retry |
| Resource exists | "already exists" in error | Delete orphaned resource |
| IAM permission | "not authorized" | Check IAM role permissions |
| Export conflict | "already exported" | Rename export in template |
| Version mismatch | API version check | Update template to latest |

### Decision Points

The agent should ask for confirmation at these points:

1. Before first deployment to a new environment
2. Before deploying EKS (expensive, long-running)
3. Before any PRD environment changes
4. When network tests fail

### Monitoring Progress

The agent should report status using this format:

```
[PHASE N] Phase description
[step/total] Action description...
      ✓ Resource: identifier
      ✗ Error: description
```

### Idempotency

All operations should be idempotent:
- Check if stack exists before creating
- Skip completed steps on retry
- Clean up partial failures before retry

---

## Verification Scripts

Each phase has automated verification scripts that test the deployed infrastructure and save evidence.

### Phase 1: Foundation Verification

**Script:** `scripts/verify-phase1-foundation.sh`

**Tests:**
| Test | What it Verifies |
|------|------------------|
| IAM Roles stack exists | CloudFormation stack CREATE_COMPLETE |
| EKS Cluster Role exists | IAM role created with correct policies |
| EKS Node Group Role exists | IAM role for worker nodes |
| Bastion Role exists | IAM role for bastion with SSM permissions |
| VPC stack exists | CloudFormation stack CREATE_COMPLETE |
| VPC is available | VPC state is 'available' |
| VPC has dual CIDR | 10.0.0.0/16 + 100.64.0.0/16 |
| Internet Gateway attached | IGW exists and attached to VPC |
| NAT Gateway available | NAT Gateway in 'available' state |
| Public subnets (3 AZs) | 3 public subnets created |
| Private subnets (3 AZs) | 3 private subnets created |
| Pod subnets (3 AZs) | 3 pod subnets (100.64.x.x) created |
| Security Groups stack exists | CloudFormation stack CREATE_COMPLETE |
| EKS Cluster SG exists | Security group for EKS control plane |
| EKS Nodes SG exists | Security group for worker nodes |
| Bastion stack exists | CloudFormation stack CREATE_COMPLETE |
| Bastion instance running | EC2 instance in 'running' state |
| Bastion in private subnet | No public IP assigned |
| Bastion SSM connectivity | SSM agent online |
| Bastion internet connectivity | Outbound via NAT Gateway works |

**Run:**
```bash
./scripts/verify-phase1-foundation.sh
```

**Evidence saved to:** `evidence/phase1-foundation/`

### Phase 2: EKS Verification

**Script:** `scripts/verify-phase2-eks.sh`

**Tests:**
| Test | What it Verifies |
|------|------------------|
| EKS Cluster stack exists | CloudFormation stack CREATE_COMPLETE |
| EKS Cluster is ACTIVE | Cluster status is ACTIVE |
| EKS Cluster version is 1.34 | Correct Kubernetes version |
| EKS Cluster endpoint exists | API server endpoint available |
| EKS private endpoint enabled | Private access to cluster |
| EKS logging enabled | Control plane logs to CloudWatch |
| EKS secrets encryption | KMS encryption for secrets |
| Node Groups stack exists | CloudFormation stack CREATE_COMPLETE |
| General node group ACTIVE | Node group status ACTIVE |
| Instance type t3a.xlarge | Correct instance type |
| AMI is AL2023 | EKS optimized AMI |
| Node group in pod subnets | Nodes in 100.64.x.x subnets |
| Node group scaling config | Min 2, Desired 3 nodes |
| kubectl can connect | kubectl cluster-info works |
| Nodes are Ready | All nodes in Ready state |
| Expected node count | >= 2 nodes running |
| CoreDNS pods running | DNS pods healthy |
| kube-proxy pods running | Network proxy pods healthy |
| VPC CNI pods running | CNI plugin pods healthy |
| OIDC issuer configured | IRSA OIDC issuer exists |
| OIDC provider in IAM | IAM OIDC provider created |

**Run:**
```bash
./scripts/verify-phase2-eks.sh
```

**Evidence saved to:** `evidence/phase2-eks/`

### Evidence Collection

Each verification script saves evidence to the `evidence/` directory:

```
evidence/
├── phase1-foundation/
│   ├── iam-roles-stack.txt
│   ├── eks-cluster-role.json
│   ├── vpc-state.txt
│   ├── vpc-cidrs.txt
│   ├── nat-gateway.txt
│   ├── bastion-ssm-status.txt
│   └── bastion-network-test.txt
├── phase2-eks/
│   ├── eks-cluster-status.txt
│   ├── eks-cluster-version.txt
│   ├── nodegroup-instance-type.txt
│   ├── kubectl-nodes.txt
│   ├── coredns-pods.txt
│   └── cluster-full-description.json
└── phase3-addons/
    └── (created after Phase 3)
```

### Agent Verification Workflow

The agent must run verification after each phase:

```python
def deploy_phase(phase_num: int, stacks: list):
    """Deploy phase with verification"""

    # Deploy all stacks in phase
    for stack in stacks:
        deploy_stack(stack)
        wait_for_stack_complete(stack)

    # Run verification
    result = run_verification(f"scripts/verify-phase{phase_num}-*.sh")

    if result.failed_count > 0:
        raise PhaseVerificationError(
            f"Phase {phase_num} verification failed: "
            f"{result.failed_count} tests failed"
        )

    # Log evidence
    log_evidence(f"evidence/phase{phase_num}-*/")

    return result
```

### Verification Summary Format

After each phase, report verification status:

```
============================================
PHASE 1: FOUNDATION VERIFICATION
============================================
Timestamp: 2025-01-04T21:45:00Z
Environment: dev

Tests Passed: 18/20
Tests Failed: 2/20

Failed Tests:
  - Bastion internet connectivity: TIMEOUT
  - NAT Gateway available: PENDING

Evidence Location: evidence/phase1-foundation/
============================================
```
