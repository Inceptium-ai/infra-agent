# Lessons Learned - Infrastructure Deployment

This document captures errors encountered during infrastructure deployment and their resolutions.

## Date: January 2025

---

## 1. CloudFormation Tag Value Validation Error

**Error:**
```
Value at 'tags.2.member.value' failed to satisfy constraint: Member must satisfy regular expression pattern
```

**Cause:**
NIST_Control tag values contained commas (e.g., `AC-2,AC-6`) which aren't allowed in CloudFormation tag values.

**Fix:**
Replace commas with underscores in all NIST_Control tag values.
```yaml
# Before
- Key: NIST_Control
  Value: AC-2,AC-6

# After
- Key: NIST_Control
  Value: AC-2_AC-6
```

**Files Affected:**
- `infra/cloudformation/stacks/00-foundation/iam-roles.yaml`
- `infra/cloudformation/stacks/00-foundation/security-groups.yaml`
- `infra/cloudformation/stacks/03-eks/cluster.yaml`

---

## 2. SSM Parameter Reference Not Found

**Error:**
```
Parameters: [ssm:/infra-agent/git-sha:1] cannot be found
```

**Cause:**
Template referenced a non-existent SSM parameter for IaC_Version tags using dynamic reference syntax.

**Fix:**
Replace SSM dynamic references with static values until SSM parameters are created.
```yaml
# Before
- Key: IaC_Version
  Value: !Sub '{{resolve:ssm:/infra-agent/git-sha:1}}'

# After
- Key: IaC_Version
  Value: '1.0.0'
```

**Lesson:**
Don't use SSM parameter references in CloudFormation until the parameters are created. Consider using a bootstrap stack to create SSM parameters first.

---

## 3. Duplicate CloudFormation Export Names

**Error:**
```
Export with name infra-agent-dev-eks-cluster-sg-id is already exported by stack infra-agent-dev-security-groups
```

**Cause:**
Both `security-groups.yaml` and `cluster.yaml` exported a value with the same name. The security-groups stack exports the input security group, while the cluster stack tried to export the EKS-created security group with the same name.

**Fix:**
Rename the export in cluster.yaml to differentiate the two:
```yaml
# cluster.yaml - renamed export
Export:
  Name: !Sub '${ProjectName}-${Environment}-eks-cluster-created-sg-id'
```

**Lesson:**
Use clear, distinct naming for CloudFormation exports. Document what each export represents.

---

## 4. CloudFormation Export Length Limit Exceeded

**Error:**
```
Cannot export output CertificateAuthorityData with length 1476. Max length of 1024 exceeded
```

**Cause:**
EKS cluster's CertificateAuthorityData is base64-encoded and exceeds CloudFormation's 1024 character export limit.

**Fix:**
Remove the Export from this output - keep the output for stack reference but don't export it:
```yaml
CertificateAuthorityData:
  Description: Certificate authority data for the cluster (not exported due to length limit)
  Value: !GetAtt EksCluster.CertificateAuthorityData
  # Note: Cannot export - exceeds CloudFormation 1024 char limit
```

**Lesson:**
CloudFormation exports have a 1024 character limit. For large values like certificates, either:
- Don't export them (use SSM Parameter Store instead)
- Store in Secrets Manager
- Reference the cluster directly via AWS API

---

## 5. CloudWatch Log Group Already Exists

**Error:**
```
Resource of type 'AWS::Logs::LogGroup' with identifier '/aws/eks/infra-agent-dev-cluster/cluster' already exists
```

**Cause:**
EKS automatically creates a CloudWatch log group when logging is enabled. If the CloudFormation stack also defines a log group with the same name, and a previous deployment partially succeeded, the log group may already exist.

**Fix:**
Add `DependsOn` to ensure the log group is created BEFORE the EKS cluster:
```yaml
EksCluster:
  Type: AWS::EKS::Cluster
  DependsOn: EksLogGroup  # Log group must exist before EKS creates it
```

**Lesson:**
When EKS logging is enabled, EKS will use an existing log group if one exists, or create one if it doesn't. Create the log group first with your desired retention settings.

---

## 6. Wrong AMI for Bastion Host

**Error:**
```
/var/lib/cloud/instance/scripts/part-001: line 5: dnf: command not found
```

**Cause:**
Used an Ubuntu AMI (ami-0c7217cdde317cfec) instead of Amazon Linux 2023. The user data script used `dnf` (AL2023 package manager) but Ubuntu uses `apt`.

**Fix:**
Use the correct Amazon Linux 2023 AMI:
```yaml
Mappings:
  RegionAMI:
    us-east-1:
      AMI: ami-068c0051b15cdb816  # Amazon Linux 2023 x86_64
```

**Lesson:**
Always verify AMI IDs match the expected operating system. Use AWS SSM public parameters for dynamic AMI lookup:
```yaml
# Better approach - use SSM parameter for latest AL2023 AMI
ImageId: '{{resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64}}'
```

---

## 7. Python Version Mismatch

**Issue:**
System defaulted to `/usr/bin/python3` (Python 3.9.6) instead of Homebrew's Python 3.14.2.

**Cause:**
Homebrew bin path `/opt/homebrew/bin` was not in the system PATH.

**Fix:**
Added Homebrew to PATH in `.zshrc`:
```bash
eval "$(/opt/homebrew/bin/brew shellenv)"
export PATH="/opt/homebrew/bin:$PATH"
```

**Lesson:**
On macOS, always verify which Python is being used. Homebrew Python requires PATH configuration.

---

## 8. Package Conflicts on Amazon Linux 2023

**Error:**
```
package curl-minimal conflicts with curl provided by curl-8.11.1
```

**Cause:**
Amazon Linux 2023 has `curl-minimal` pre-installed. Attempting to install `curl` causes a conflict.

**Fix:**
Either skip curl installation (curl-minimal is sufficient) or use `--allowerasing`:
```bash
dnf install -y curl --allowerasing
```

**Better approach:** Don't install curl manually on AL2023 - `curl-minimal` is already available.

---

## 9. EKS Version Selection

**Issue:**
Initially used EKS 1.32 when 1.34 was available.

**Cause:**
Plan document specified 1.32 based on older information.

**Fix:**
Updated to use EKS 1.34 (latest available version).

**Files Updated:**
- `infra/cloudformation/stacks/03-eks/cluster.yaml` - Default parameter
- `src/infra_agent/config.py` - Config default
- `.env.example` - Environment variable
- `docs/architecture.md` - Documentation
- `docs/planning/phase-details.md` - Plan details
- `docs/access-urls.md` - Access documentation
- `infra/cloudformation/stacks/00-foundation/bastion.yaml` - kubectl version

**Lesson:**
Always verify the latest supported EKS version before deployment AND update ALL IaC references:
```python
eks = boto3.client('eks')
response = eks.describe_addon_versions()
# Extract cluster versions from addon compatibility
```

---

## 10. IRSA OIDC Condition Syntax in CloudFormation

**Error:**
```
Template format error: [/Resources/VpcCniRole/Properties/AssumeRolePolicyDocument/Statement/0/Condition/StringEquals] map keys must be strings; received a map instead
```

**Cause:**
IRSA roles require dynamic OIDC URL in the Condition keys. Using `!Sub` inside a YAML map key doesn't work.

**Wrong approach:**
```yaml
Condition:
  StringEquals:
    !Sub '${OidcProviderUrl}:sub': 'system:serviceaccount:kube-system:aws-node'
```

**Fix:**
Use `Fn::Sub` with a JSON string for the entire AssumeRolePolicyDocument:
```yaml
AssumeRolePolicyDocument:
  Fn::Sub:
    - |
      {
        "Version": "2012-10-17",
        "Statement": [
          {
            "Effect": "Allow",
            "Principal": {
              "Federated": "${OidcArn}"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
              "StringEquals": {
                "${OidcUrl}:sub": "system:serviceaccount:kube-system:aws-node",
                "${OidcUrl}:aud": "sts.amazonaws.com"
              }
            }
          }
        ]
      }
    - OidcArn: !Ref OidcProviderArn
      OidcUrl: !Ref OidcProviderUrl
```

**Lesson:**
When CloudFormation YAML conditions need dynamic keys, use JSON string with Fn::Sub to substitute variables in keys.

---

## 11. CloudFormation UserData Changes Don't Replace EC2 Instances

**Issue:**
Updated UserData in CloudFormation but the EC2 instance wasn't replaced - old user data still running.

**Cause:**
CloudFormation treats UserData changes as non-replacement updates. The instance metadata is updated, but cloud-init doesn't re-run on an existing instance.

**Fix:**
To force instance replacement, either:
1. Delete and recreate the stack
2. Terminate the instance manually (CloudFormation won't auto-recreate)
3. Change a property that forces replacement (e.g., `SubnetId`, `ImageId`)

**Better approach:** Add a metadata version tag that changes with UserData:
```yaml
BastionHost:
  Type: AWS::EC2::Instance
  Metadata:
    UserDataVersion: "1.0.1"  # Increment to force replacement
  Properties:
    UserData: ...
```

Or use AutoScaling Group with Launch Template for automatic replacement.

**Lesson:**
UserData changes alone don't trigger EC2 instance replacement. Plan for explicit replacement strategy.

---

## 12. Bastion IAM Role Needs EKS Cluster Access

**Error:**
```
error: You must be logged in to the server (the server has asked for the client to provide credentials)
```

**Cause:**
The bastion's IAM role was not authorized to access the EKS cluster. EKS requires explicit mapping of IAM roles to Kubernetes RBAC.

**Fix:**
Add the bastion role to EKS access using one of:

**Option 1: EKS Access Entries (newer, recommended)**
```bash
aws eks create-access-entry \
    --cluster-name infra-agent-dev-cluster \
    --principal-arn arn:aws:iam::ACCOUNT:role/infra-agent-dev-bastion-role \
    --type STANDARD

aws eks associate-access-policy \
    --cluster-name infra-agent-dev-cluster \
    --principal-arn arn:aws:iam::ACCOUNT:role/infra-agent-dev-bastion-role \
    --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \
    --access-scope type=cluster
```

**Option 2: aws-auth ConfigMap (legacy)**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: aws-auth
  namespace: kube-system
data:
  mapRoles: |
    - rolearn: arn:aws:iam::ACCOUNT:role/infra-agent-dev-bastion-role
      username: bastion
      groups:
        - system:masters
```

**Lesson:**
Always configure EKS access for bastion/admin roles during cluster setup. Include this in IaC for reproducibility.

---

## 13. Always Use IaC for Infrastructure Changes

**Issue:**
Used AWS CLI to add EKS access entry instead of CloudFormation, creating configuration drift.

**Bad Practice:**
```bash
# Don't do this - creates drift from IaC
aws eks create-access-entry --cluster-name ... --principal-arn ...
```

**Correct Approach:**
Add access entries to CloudFormation:
```yaml
# In cluster.yaml or separate access-config.yaml
BastionAccessEntry:
  Type: AWS::EKS::AccessEntry
  Properties:
    ClusterName: !Ref EksCluster
    PrincipalArn: !Ref BastionRoleArn
    Type: STANDARD
    AccessPolicies:
      - PolicyArn: arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy
        AccessScope:
          Type: cluster
```

**Lesson:**
ALL infrastructure changes must go through IaC (CloudFormation). Never use CLI for permanent changes - it creates drift and makes infrastructure non-reproducible.

---

## 14. VPC CNI Add-on Verification Checklist

**Before deploying VPC CNI add-on, verify:**

1. **IAM Role**: Ensure `AmazonEKS_CNI_Policy` is attached
   ```bash
   aws iam list-attached-role-policies --role-name <vpc-cni-role>
   ```

2. **Subnet IP Space**: Pod subnets should have ample IPs (/18 or larger recommended)
   ```bash
   aws ec2 describe-subnets --subnet-ids <pod-subnet-ids> \
     --query 'Subnets[*].{CIDR:CidrBlock,AvailableIPs:AvailableIpAddressCount}'
   ```

3. **Version Compatibility**: Check CNI version matches EKS version
   ```bash
   aws eks describe-addon-versions --addon-name vpc-cni --kubernetes-version <version>
   ```

4. **Custom Networking**: If using secondary CIDR (100.64.x.x), set:
   ```json
   {
     "env": {
       "AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG": "true",
       "ENI_CONFIG_LABEL_DEF": "topology.kubernetes.io/zone"
     }
   }
   ```

5. **Monitor Logs**: Check ipamd logs for errors
   ```bash
   kubectl logs -n kube-system -l k8s-app=aws-node
   ```

**Lesson:**
VPC CNI add-on creation takes 10-15 minutes. Verify IAM, subnet space, and version compatibility beforehand.

---

## 15. SSM Shell Doesn't Inherit Root KUBECONFIG

**Error:**
```
The connection to the server localhost:8080 was refused
```

**Cause:**
SSM Session Manager runs commands with a different environment. The KUBECONFIG at `/root/.kube/config` isn't automatically used.

**Fix:**
Always export KUBECONFIG explicitly in SSM commands:
```bash
export KUBECONFIG=/root/.kube/config && kubectl get nodes
```

Or add to the user's bashrc during bastion setup:
```bash
echo 'export KUBECONFIG=/root/.kube/config' >> /root/.bashrc
echo 'export KUBECONFIG=/home/ec2-user/.kube/config' >> /home/ec2-user/.bashrc
```

**Lesson:**
SSM shell environment differs from normal SSH. Always set KUBECONFIG explicitly or configure it in bashrc during instance setup.

---

## 16. ENIConfig CRDs Required for VPC CNI Custom Networking

**Error:**
```
ENIConfig.crd.k8s.amazonaws.com "us-east-1c" not found
Initialization failure: Failed to attach any ENIs for custom networking
```

**Cause:**
When `AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG=true` is set, VPC CNI requires ENIConfig CRDs to map each AZ to its pod subnet. Without these, pods cannot get IPs from the secondary CIDR (100.64.x.x).

**Fix:**
Create ENIConfig resources for each AZ via Helm chart:

```yaml
# infra/helm/charts/eniconfigs/templates/eniconfigs.yaml
apiVersion: crd.k8s.amazonaws.com/v1alpha1
kind: ENIConfig
metadata:
  name: us-east-1a
spec:
  securityGroups:
    - <nodes-security-group-id>
  subnet: <pod-subnet-id-for-az>
```

**Deploy:**
```bash
helm upgrade --install eniconfigs infra/helm/charts/eniconfigs \
  -f infra/helm/values/eniconfigs/dev.yaml
```

**Lesson:**
When using VPC CNI custom networking:
1. ENIConfig CRDs must exist BEFORE nodes join the cluster
2. Each AZ needs its own ENIConfig pointing to the pod subnet
3. Use Helm chart for IaC compliance - don't apply manually via kubectl

---

## 17. curl-minimal Conflict on Amazon Linux 2023

**Error:**
```
package curl-minimal conflicts with curl provided by curl-8.x
```

**Cause:**
Amazon Linux 2023 ships with `curl-minimal` which conflicts with full `curl` package.

**Fix:**
Don't install `curl` on AL2023 - `curl-minimal` provides the `curl` command. Remove `curl` from `dnf install` commands.

```bash
# Wrong - causes conflict
dnf install -y curl wget

# Correct - curl-minimal already provides curl
dnf install -y wget
```

**Lesson:**
AL2023 uses minimal packages by default. Check pre-installed packages before adding to install list.

---

## Best Practices Derived

1. **Validate CloudFormation templates** before deployment with `cfn-lint`
2. **Use consistent naming conventions** for all exports
3. **Test with smaller resources first** (e.g., bastion) before deploying expensive resources (EKS)
4. **Document AMI mappings** with clear comments about the OS version
5. **Use SSM public parameters** for AMI lookups instead of hardcoding
6. **Check service limits** like CloudFormation export length limits
7. **Create dependencies explicitly** with `DependsOn` when order matters
8. **Verify Python/tool versions** before running deployment scripts
9. **ALWAYS verify versions are current and stable** before specifying in templates:
   - Check AWS documentation for latest supported versions
   - Use AWS APIs to query available versions programmatically
   - Prefer latest stable versions over older ones
   - Document version choices with dates

---

## Version Verification Checklist

Before deploying, verify these component versions:

| Component | How to Check | Current (Jan 2025) |
|-----------|-------------|-------------------|
| EKS | `aws eks describe-addon-versions` | 1.34 |
| Amazon Linux 2023 AMI | SSM: `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64` | Dynamic |
| Istio | https://istio.io/latest/docs/releases/supported-releases/ | 1.24.x |
| Helm Charts | Check chart repositories | Varies |

### EKS Version Query
```python
import boto3
eks = boto3.client('eks')
response = eks.describe_addon_versions()
versions = set()
for addon in response.get('addons', []):
    for compat in addon.get('addonVersions', []):
        for cluster_compat in compat.get('compatibilities', []):
            versions.add(cluster_compat.get('clusterVersion'))
print(sorted(versions, reverse=True))
```

### AMI Lookup (Dynamic)
```yaml
# Use SSM parameter for always-current AMI
ImageId: '{{resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64}}'
```

---

## 18. Place Nodes in Pod Subnets - Avoid Custom Networking Complexity

**Problem:**
Initially attempted to use VPC CNI custom networking with ENIConfigs to route pods to 100.64.x.x subnets while nodes were in 10.0.x.x subnets. This caused:
- Chicken-and-egg deployment problems (ENIConfig CRD doesn't exist until VPC CNI installs)
- Complex two-phase deployments
- Unnecessary ENIConfig Helm charts

**Root Cause:**
Misunderstanding of the simplest architecture. Custom networking is only needed when nodes and pods must be in DIFFERENT subnets.

**Correct Approach:**
Place worker nodes directly in the 100.64.x.x (non-routable) subnets. Pods automatically get IPs from the same subnet as the node.

```
WRONG (complex):
  Nodes in 10.0.x.x → Custom networking → ENIConfigs → Pods in 100.64.x.x

CORRECT (simple):
  Nodes in 100.64.x.x → Default VPC CNI → Pods in 100.64.x.x (automatic)
```

**Architecture:**
| Subnet Type | CIDR | Resources |
|-------------|------|-----------|
| Public | 10.0.0.0/20 - 10.0.32.0/20 | ALB only |
| Private | 10.0.48.0/20 - 10.0.80.0/20 | Bastion, NAT, RDS |
| Pod/Node | 100.64.0.0/18 - 100.64.128.0/18 | **EKS nodes AND pods** |

**VPC CNI Config (simplified):**
```yaml
ConfigurationValues: |
  {
    "env": {
      "ENABLE_PREFIX_DELEGATION": "true",
      "WARM_PREFIX_TARGET": "1"
    }
  }
```

No `AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG`, no ENIConfigs, no complexity.

**Lesson:**
When pods need to be in specific subnets (like non-routable 100.64.x.x), place the NODES in those subnets. Default VPC CNI assigns pod IPs from the node's subnet automatically. Custom networking is only needed when nodes and pods MUST be in different subnets (rare).

---

## 19. When Custom Networking IS Actually Needed

**Custom networking with ENIConfigs is only required when:**

1. Nodes MUST be in different subnets than pods (regulatory/network topology requirement)
2. You need different security groups for pod ENIs vs node ENIs
3. You're retrofitting an existing cluster where moving nodes isn't possible

**For most use cases (including non-routable pod subnets):**
Simply deploy nodes into the desired pod subnets. This is simpler, faster to deploy, and has no chicken-and-egg problems.

**Lesson:**
Don't reach for complex solutions (custom networking, ENIConfigs) when a simpler architecture (nodes in pod subnets) achieves the same goal.

---

## 20. Grafana Loki Helm Chart - Correct bucketNames Structure

**Error:**
```
Error: execution error at (loki/templates/write/statefulset-write.yaml:50:28):
Please define loki.storage.bucketNames.chunks
```

**Cause:**
Placed `bucketNames` under `loki.storage.s3.bucketNames` instead of `loki.storage.bucketNames`.

**Wrong Structure:**
```yaml
loki:
  storage:
    type: s3
    s3:
      region: us-east-1
      bucketNames:        # WRONG - nested under s3
        chunks: my-bucket
        ruler: my-bucket
```

**Correct Structure:**
```yaml
loki:
  storage:
    type: s3
    bucketNames:          # CORRECT - sibling to s3, not nested
      chunks: my-bucket
      ruler: my-bucket
      admin: my-bucket
    s3:
      region: us-east-1
      endpoint: null
      secretAccessKey: null
      accessKeyId: null
```

**Lesson:**
Always check the official Helm chart values.yaml structure before configuring. Grafana Loki chart expects `bucketNames` at `loki.storage.bucketNames`, not nested under the storage backend configuration (`s3`, `gcs`, etc.).

**Reference:**
https://github.com/grafana/loki/blob/main/production/helm/loki/values.yaml

---

## 21. Loki Self-Monitoring Requires Grafana Agent Operator CRDs

**Error:**
```
resource mapping not found for name: "loki" namespace: "observability" from "":
no matches for kind "GrafanaAgent" in version "monitoring.grafana.com/v1alpha1"
ensure CRDs are installed first
```

**Cause:**
Loki's `monitoring.selfMonitoring.enabled: true` creates GrafanaAgent, LogsInstance, and PodLogs resources that require Grafana Agent Operator CRDs to be pre-installed.

**Fix:**
Either install Grafana Agent Operator CRDs first, or disable self-monitoring:
```yaml
monitoring:
  selfMonitoring:
    enabled: false  # Disable if not using Grafana Agent Operator
    grafanaAgent:
      installOperator: false
  lokiCanary:
    enabled: false  # Also uses GrafanaAgent CRDs
```

**Lesson:**
When using Grafana Loki Helm chart, `selfMonitoring.enabled: true` requires Grafana Agent Operator. For simpler setups, disable self-monitoring and use Prometheus ServiceMonitors instead if metrics are needed.

---

## 22. Use Git as Source of Truth - Not S3 for Config Files

**Bad Practice:**
Using S3 to transfer Helm values or config files to bastion for deployment.

```bash
# DON'T do this - creates drift from source control
aws s3 cp loki-values.yaml s3://bucket/config/
# Then on bastion: aws s3 cp s3://bucket/config/loki-values.yaml .
```

**Problems:**
- S3 is not version controlled
- Creates configuration drift
- Not auditable (who changed what, when)
- Violates NIST CM-3 (Configuration Change Control)
- Files can diverge from Git repo

**Correct Approach:**
Git repo is the single source of truth. Deploy from local workstation via SSM tunnel (see Lesson #23).

**Lesson:**
ALL IaC and configuration must live in Git. Never use S3, Secrets Manager, or other storage as a substitute for version-controlled configuration.

---

## 23. SSM Port Forwarding for Private EKS Access

**Problem:**
EKS cluster has private-only API endpoint (NIST SC-7 compliant). Need to run kubectl/helm from local workstation.

**Solution:**
Use SSM port forwarding to tunnel through bastion to EKS API.

**Setup:**
```bash
# Terminal 1: Start tunnel (keep running)
aws ssm start-session \
  --target <bastion-instance-id> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<EKS-API-ENDPOINT>"],"portNumber":["443"],"localPortNumber":["6443"]}'

# Terminal 2: Configure kubectl
aws eks update-kubeconfig --name <cluster-name> --region us-east-1

# Modify kubeconfig to use tunnel
sed -i.bak 's|https://<EKS-API-ENDPOINT>|https://localhost:6443|' ~/.kube/config

# Skip TLS verification (cert is for EKS hostname, not localhost)
kubectl config set-cluster <cluster-arn> --insecure-skip-tls-verify=true

# Test
kubectl get nodes
```

**Benefits:**
- No public EKS endpoint needed
- All traffic encrypted through SSM
- Audited via CloudTrail
- Deploy directly from local Git repo
- No config file transfers needed

**For This Project:**
```bash
# Bastion ID: i-06b868c656de96829
# EKS Endpoint: C13DEB3971BF51477027AF0BEF0B1D0D.yl4.us-east-1.eks.amazonaws.com
# Cluster ARN: arn:aws:eks:us-east-1:340752837296:cluster/infra-agent-dev-cluster
```

**Lesson:**
SSM port forwarding allows secure kubectl access to private EKS clusters without exposing the API endpoint to the internet.

---

## 24. Create GP3 StorageClass Before Deploying StatefulSets

**Error:**
```
Warning  FailedScheduling  default-scheduler  0/3 nodes are available:
pod has unbound immediate PersistentVolumeClaims. not found
```

**Cause:**
PVCs specify `storageClass: gp3` but only `gp2` StorageClass exists in EKS by default. EKS default `gp2` uses the deprecated `kubernetes.io/aws-ebs` provisioner.

**Fix:**
Create a `gp3` StorageClass using EBS CSI driver before deploying workloads:

```yaml
# infra/k8s/storage/gp3-storageclass.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
parameters:
  type: gp3
  fsType: ext4
  encrypted: "true"  # NIST SC-28
```

**Deploy order:**
1. EBS CSI Driver add-on (CloudFormation)
2. GP3 StorageClass (`kubectl apply -f`)
3. Helm charts that use PVCs

**Lesson:**
Always create required StorageClasses before deploying StatefulSets. Add this to the deployment checklist.

---

## 25. PVCs Cannot Be Modified After Creation

**Problem:**
Created PVCs without specifying `storageClass` picked up no storage class (blank). Cannot modify PVCs to add storage class.

**Fix:**
Must delete PVCs and let StatefulSets recreate them:

```bash
# Delete PVCs
kubectl delete pvc -n observability data-loki-backend-0 data-loki-backend-1

# Delete StatefulSets (they'll be recreated by Helm)
kubectl delete statefulset -n observability loki-backend loki-write

# Helm upgrade recreates everything
helm upgrade --install loki grafana/loki -n observability -f values.yaml
```

**Lesson:**
PVCs are immutable once created. If wrong storage class is applied, must delete and recreate.

---

## 26. Helm "Another Operation in Progress" Error

**Error:**
```
Error: UPGRADE FAILED: another operation (install/upgrade/rollback) is in progress
```

**Cause:**
Previous Helm install was interrupted (timeout, Ctrl+C, terminal closed), leaving the release in `pending-install` state.

**Fix:**
```bash
# Check release status
helm history <release-name> -n <namespace>

# Uninstall the stuck release
helm uninstall <release-name> -n <namespace>

# Fresh install
helm install <release-name> <chart> -n <namespace> -f values.yaml
```

**Lesson:**
Use `--wait --timeout` carefully. If interrupted, check `helm history` and uninstall stuck releases before retrying.

---

## 27. Headlamp Requires Writable Filesystem

**Error:**
```
{"level":"error","error":"mkdir /home/headlamp/.config: read-only file system","message":"creating plugins directory"}
{"level":"error","error":"mkdir /tmp/.headlamp334353572: read-only file system","message":"Failed to create static dir"}
```

**Cause:**
Setting `securityContext.readOnlyRootFilesystem: true` prevents Headlamp from creating its required temp and config directories.

**Fix:**
Disable read-only root filesystem for Headlamp:
```yaml
securityContext:
  readOnlyRootFilesystem: false  # Headlamp needs /tmp and ~/.config writable
  runAsNonRoot: true
  runAsUser: 100
  allowPrivilegeEscalation: false
```

**Lesson:**
Not all applications support read-only root filesystem. Check application requirements before applying strict security contexts. Headlamp specifically needs `/tmp` and `/home/headlamp/.config` to be writable.

---

## 28. Kubecost 2.9.x Requires Migration Setup

**Error:**
```
Error: execution error: Kubecost 2.9.x is only used for preparing agents to upgrade to 3.0.
```

**Cause:**
Kubecost 2.9.x versions are transitional releases designed specifically for migrating to version 3.0. They're not meant for fresh installations.

**Fix:**
Use a stable 2.8.x version for fresh installations:
```bash
helm install kubecost kubecost/cost-analyzer -n kubecost \
  --version 2.8.5 \
  -f values.yaml
```

**Lesson:**
Check Helm chart release notes before using latest version. Some versions are designed for specific upgrade paths only. For fresh installations, use the stable version (2.8.x in this case).

---

## 29. Velero CRD Job Timeout During Install

**Error:**
```
Error: INSTALLATION FAILED: failed pre-install: resource not ready, name: velero-upgrade-crds, kind: Job, status: InProgress
context deadline exceeded
```

**Cause:**
Velero Helm chart runs a pre-install job to create/upgrade CRDs. If this job times out (image pull issues, slow cluster), the install fails but CRDs may already be installed.

**Fix:**
```bash
# Check if CRDs are already installed
kubectl get crds | grep velero.io

# If CRDs exist, uninstall the stuck release
helm uninstall velero -n velero

# Delete any stuck jobs
kubectl delete jobs -n velero --all

# Reinstall with CRD upgrade disabled
helm install velero vmware-tanzu/velero -n velero \
  -f values.yaml \
  --set upgradeCRDs=false \
  --timeout 10m
```

**Lesson:**
Velero CRD jobs can be slow. If CRDs are already present, use `--set upgradeCRDs=false` to skip the pre-install job.

---

## 30. Always Run cfn-lint Before Deploying CloudFormation

**Issue:**
CloudFormation templates were deployed without validation, leading to potential issues with unused parameters, missing tags, and security misconfigurations.

**Fix:**
Always run cfn-lint on all CloudFormation templates before deployment:
```bash
# Install cfn-lint
pip3 install cfn-lint

# Run on all templates
cfn-lint infra/cloudformation/stacks/**/*.yaml
```

**Add to CI/CD:**
```yaml
# .github/workflows/validate-iac.yaml
- name: Validate CloudFormation
  run: cfn-lint infra/cloudformation/stacks/**/*.yaml
```

**Lesson:**
Make cfn-lint a mandatory step in the deployment process. Add to pre-commit hooks or CI pipeline.

---

## 31. Mimir Was Missing from Observability Stack

**Issue:**
Deployed Grafana and Loki but forgot Mimir (metrics). This caused:
- Grafana dashboards not working (no metrics)
- "No data" in all metric panels

**Root Cause:**
Mimir was not included in the initial deployment.

**Fix:**
1. Create S3 bucket + IRSA role via CloudFormation (mimir-storage.yaml)
2. Deploy Mimir via Helm with S3 backend
3. Grafana datasources already configured for `mimir-nginx.observability.svc`

**Observability Stack Components (Current):**
| Component | Purpose | Storage |
|-----------|---------|---------|
| **Loki** | Logs | S3 |
| **Grafana** | Dashboards | EBS (PVC) |
| **Tempo** | Distributed tracing | S3 |
| **Mimir** | Metrics storage | S3 |
| **Prometheus** | Metrics scraping | - |
| **Kiali** | Traffic visualization | - |

**Lesson:**
When deploying the observability stack, verify all components are included:
- [ ] Loki (logs)
- [ ] Grafana (dashboards)
- [ ] Tempo (distributed tracing)
- [ ] Mimir (metrics storage) ← Easy to forget!
- [ ] Prometheus (metrics scraping)
- [ ] Kiali (Istio traffic visualization)

---

## 32. Tempo vs Kiali - Know What You Actually Need

**Issue:**
Deployed Tempo for "traffic visualization" but Tempo provides distributed tracing (following individual requests), NOT traffic flow visualization.

**What Each Tool Does:**
| Tool | Purpose | Visual Output |
|------|---------|---------------|
| **Tempo/Jaeger** | Distributed tracing | Waterfall diagram of ONE request through services |
| **Kiali** | Service mesh visualization | Real-time traffic graph with animated flows |

**The Real Question:**
- "I want to see how requests flow through my microservices" → **Kiali**
- "I want to debug latency in a specific request" → **Tempo/Jaeger**

**Fix:**
Removed Tempo, deployed Kiali for traffic visualization needs.

**Lesson:**
Before deploying observability tools, clearly define what you want to SEE:
- Traffic flow topology → Kiali
- Request tracing → Tempo/Jaeger
- Log aggregation → Loki
- Metrics → Prometheus/Mimir

---

## 33. Mimir is Storage, Not a Scraper

**Issue:**
Deployed Mimir expecting metrics to appear in Grafana, but Mimir had no data.

**Root Cause:**
Mimir is a **metrics storage backend** (like a database). It does NOT scrape metrics from pods/nodes. It only receives and stores what's pushed to it.

**The Flow:**
```
[Pods/Nodes] → [Prometheus SCRAPES] → [remote_write] → [Mimir STORES] → [Grafana QUERIES]
```

**Fix:**
Deploy Prometheus with `remoteWrite` configured to push to Mimir:
```yaml
server:
  remoteWrite:
    - url: "http://mimir-gateway.observability.svc.cluster.local:80/api/v1/push"
```

**Lesson:**
Mimir (like Cortex, Thanos) is long-term storage only. You always need a scraper (Prometheus, Grafana Agent, Alloy) to collect metrics and push them.

---

## 34. Prometheus Chart Has Built-in Scrape Configs

**Error:**
```
Error loading config: parsing YAML file: found multiple scrape configs with job name "kubernetes-pods"
```

**Cause:**
Added a `kubernetes-pods` job in `extraScrapeConfigs` but the Prometheus Helm chart already includes this job by default.

**Fix:**
Remove duplicate job from extraScrapeConfigs. Only add truly EXTRA configs:
```yaml
extraScrapeConfigs: |
  # Only add configs NOT already in the chart
  - job_name: 'istiod'
    kubernetes_sd_configs: ...
  - job_name: 'envoy-stats'
    kubernetes_sd_configs: ...
  # DON'T add kubernetes-pods - chart already has it
```

**Lesson:**
Check the Prometheus Helm chart's default values.yaml before adding extraScrapeConfigs. The chart includes many standard Kubernetes scrape configs by default.

---

## 35. Stack Simplification - Question Every Component

**Issue:**
Initial deployment had too many components without clear justification:
- Tempo (not needed for traffic visualization)
- Mimir without scraper (useless alone)
- Multiple overlapping tools

**Resolution Process:**
1. Listed ALL deployed components
2. Asked "what happens without it?" for each
3. Identified actual need vs assumed need
4. Removed unnecessary components

**Final Simplified Stack:**
| Component | Need | Justification |
|-----------|------|---------------|
| Loki | Yes | Centralized logs - no alternative |
| Grafana | Yes | Single pane of glass for dashboards |
| Prometheus | Yes | Metrics scraping → pushes to Mimir |
| Mimir | Yes | Long-term metrics (S3-backed, NIST AU-11) |
| Kiali | Yes | Traffic flow visualization (replaces Tempo for this use case) |
| Istio | Yes | mTLS, NIST SC-8 requirement |
| Trivy | Yes | Vulnerability scanning, NIST SI-2 |
| Velero | Yes | Backup/restore, NIST CP-9 |
| Kubecost | Optional | Pod-level cost visibility |
| Headlamp | Optional | K8s web UI convenience |

**Lesson:**
Before deploying any component, ask:
1. What problem does it solve?
2. What happens without it?
3. Is there overlap with existing tools?
4. Is it truly needed for compliance?
