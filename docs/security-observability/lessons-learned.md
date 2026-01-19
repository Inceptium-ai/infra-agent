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
Initially deployed Tempo expecting "traffic visualization" but Tempo provides distributed tracing (following individual requests), NOT traffic flow visualization. Removed it, then realized we still need distributed tracing for debugging latency issues.

**What Each Tool Does:**
| Tool | Purpose | Visual Output | When to Use |
|------|---------|---------------|-------------|
| **Tempo** | Distributed tracing | Waterfall diagram of ONE request through services | "Why was this request slow?" |
| **Kiali** | Service mesh visualization | Real-time traffic graph with animated flows | "How does traffic flow between services?" |

**Key Insight:**
These tools serve DIFFERENT purposes - you need BOTH for complete observability:
- Kiali shows the forest (all traffic patterns)
- Tempo shows one tree (single request path)

**Resolution:**
Deploy BOTH tools:
- Kiali for traffic visualization and mesh topology
- Tempo for distributed tracing and latency debugging

**Lesson:**
Before deploying observability tools, clearly define what you want to SEE:
- Traffic flow topology → Kiali
- Request tracing → Tempo
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
- Mimir without scraper (useless alone)
- Confusion about Tempo vs Kiali use cases
- Multiple overlapping tools

**Resolution Process:**
1. Listed ALL deployed components
2. Asked "what problem does it solve?" for each
3. Identified actual need vs assumed need
4. Clarified tool purposes (Tempo for tracing, Kiali for traffic viz)

**Final Stack:**
| Component | Need | Justification |
|-----------|------|---------------|
| Loki | Yes | Centralized logs - no alternative |
| Grafana | Yes | Single pane of glass for dashboards |
| Prometheus | Yes | Metrics scraping → pushes to Mimir |
| Mimir | Yes | Long-term metrics (S3-backed, NIST AU-11) |
| Tempo | Yes | Distributed tracing for latency debugging |
| Kiali | Yes | Traffic flow visualization |
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

---

## 36. Istio Sidecar Injection Must Be Enabled BEFORE Deploying Workloads

**Issue:**
Deployed entire observability stack (Grafana, Loki, Prometheus, Mimir, etc.) without Istio sidecar injection. Discovered 53 pods running WITHOUT mTLS encryption - a NIST SC-8 compliance gap.

**Root Cause:**
Namespaces were not labeled with `istio-injection=enabled` before deploying Helm charts. Pods deployed without the label don't get Envoy sidecar proxies.

**Impact:**
| Namespace | Pods | Istio Sidecar | mTLS Status |
|-----------|------|---------------|-------------|
| observability | 37 | None | Plaintext traffic |
| velero | 9 | None | Plaintext traffic |
| kubecost | 5 | None | Plaintext traffic |
| trivy-system | 1 | None | Plaintext traffic |
| headlamp | 1 | None | Plaintext traffic |

**Resource Constraint:**
Adding Istio sidecars to all 53 pods would require:
- ~5.3 vCPU additional (100m per sidecar)
- ~6.8 Gi additional memory (128Mi per sidecar)
- Cluster only had ~1.8 vCPU free

**Correct Approach:**
```bash
# BEFORE deploying any Helm chart:
kubectl create namespace observability
kubectl label namespace observability istio-injection=enabled

# THEN deploy workloads
helm install grafana grafana/grafana -n observability -f values.yaml
```

**Remediation for Existing Deployments:**
```bash
# Label namespace
kubectl label namespace observability istio-injection=enabled

# Restart all deployments to inject sidecars
kubectl rollout restart deployment -n observability
```

**Decision Made (2026-01-11):**
- DEV: Enable Istio only on user-facing services (Grafana, Headlamp) due to resource constraints
- TST/PRD: Full Istio injection on all namespaces (additional nodes budgeted)

**Compensating Controls for DEV:**
- All traffic within private VPC (100.64.x.x non-routable)
- Network policies restrict pod-to-pod communication
- No external exposure without ALB + TLS termination

**Prevention Checklist:**
- [ ] Label namespace with `istio-injection=enabled` BEFORE any helm install
- [ ] Add sidecar annotations to all Helm values files
- [ ] Audit deployments with: `kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{.spec.containers[*].name}{"\n"}{end}' | grep -v istio-proxy`
- [ ] Verify with: `istioctl analyze` after deployment

**Lesson:**
Istio sidecar injection is namespace-level. If you forget to label the namespace BEFORE deploying workloads, all pods will run without mTLS. This is easy to miss and creates a silent compliance gap.

---

## 37. SSM Tunnel Session Timeouts

**Issue:**
SSM tunnel to EKS API kept disconnecting, requiring frequent restarts.

**Defaults:**
| Setting | Default Value | Impact |
|---------|---------------|--------|
| Idle timeout | 20 minutes | Disconnects if no traffic |
| Max session duration | 60 minutes | Hard limit regardless of activity |

**Configuration (AWS Console):**
Systems Manager → Session Manager → Preferences:
- Idle session timeout: Up to 60 minutes
- Max session duration: Up to 24 hours

**Workaround for Long Sessions:**
Keep traffic flowing to prevent idle timeout:
```bash
# Add to tunnel script
while true; do sleep 300; kubectl get nodes > /dev/null 2>&1; done &
```

**Lesson:**
For extended kubectl sessions, either increase SSM timeout in preferences or implement keep-alive traffic.

---

## 38. NEVER Use kubectl/AWS CLI to Modify Resources - IaC Only

**Issue:**
Attempted to enable Istio sidecars using `kubectl label namespace` and `kubectl patch deployment` - creating configuration drift from IaC.

**Wrong approach (creates drift):**
```bash
# DON'T DO THIS
kubectl label namespace headlamp istio-injection=enabled
kubectl patch deployment grafana -n observability -p '{"spec":...}'
aws eks update-cluster-config --name cluster --resources-vpc-config ...
```

**Correct approach (IaC):**
```yaml
# Update infra/helm/values/headlamp/values.yaml
podAnnotations:
  sidecar.istio.io/inject: "true"
  proxy.istio.io/config: '{"holdApplicationUntilProxyStarts": true}'
```

Then deploy via Helm:
```bash
helm upgrade headlamp headlamp/headlamp -n headlamp -f infra/helm/values/headlamp/values.yaml
```

**Why this matters:**
- kubectl/AWS CLI changes are not tracked in Git
- Next `helm upgrade` or CloudFormation deploy will overwrite manual changes
- Cannot reproduce environment from IaC alone
- Violates NIST CM-3 (Configuration Change Control)
- Audit trail is incomplete

**All IaC sources in this project:**
| Resource Type | IaC Location | Deploy Method |
|---------------|--------------|---------------|
| AWS Resources | `infra/cloudformation/stacks/` | `aws cloudformation deploy` |
| Kubernetes | `infra/helm/values/` | `helm upgrade` |
| Istio Config | `infra/helm/values/istio/` | `helm upgrade` |

**Lesson:**
Treat ALL infrastructure as immutable. Never touch it directly. Always go through the IaC source files, commit to Git, then deploy.

---

## 39. Implement Drift Detection Early

**Issue:**
Multiple configuration drifts accumulated without detection:
- EKS node group scaling changed via CLI
- Namespace labels added via kubectl
- Bastion EC2 MetadataOptions drifted
- Failed Helm releases (prometheus, velero) went unnoticed

**Root Cause:**
No automated drift detection was in place. Changes made outside IaC went undetected until manual audit.

**Detection Methods Available:**

| Method | Command | What It Checks |
|--------|---------|----------------|
| **CloudFormation Drift** | `aws cloudformation detect-stack-drift --stack-name <name>` | AWS resources |
| **Helm Diff Plugin** | `helm diff upgrade <release> <chart> -f values.yaml` | K8s workloads |
| **Custom Script** | `./scripts/drift-check.sh` | Both |

**Drift Check Script Created:**
```bash
./scripts/drift-check.sh
```

Output example:
```
=== CloudFormation Stacks ===
Checking infra-agent-dev-bastion... ⚠️  DRIFTED
Checking infra-agent-dev-eks-node-groups... ✅ IN_SYNC

=== Helm Release Drift ===
prometheus    failed
velero        failed
```

**When to Run Drift Detection:**
- Before any deployment
- After any manual troubleshooting session
- Weekly scheduled check
- After infrastructure incidents

**Future Improvement:**
- Add drift check to CI/CD pipeline
- Consider GitOps (Argo CD/Flux) for continuous drift detection and auto-remediation

**Lesson:**
Implement drift detection from day one. Run `./scripts/drift-check.sh` regularly and before deployments to catch drift early.

---

## 40. Failed Helm Releases Need Investigation

**Issue:**
Drift check revealed Helm releases in "failed" state:
- prometheus: failed
- velero: failed

**Cause:**
Failed releases indicate the last `helm upgrade/install` did not complete successfully. The release is stuck and may have partial resources deployed.

**How to Investigate:**
```bash
# Check release history
helm history prometheus -n observability
helm history velero -n velero

# Check what's deployed
kubectl get all -n observability -l app.kubernetes.io/name=prometheus
kubectl get all -n velero

# Check pod logs for errors
kubectl logs -n observability -l app.kubernetes.io/name=prometheus --tail=50
```

**How to Fix:**
```bash
# Option 1: Rollback to last successful
helm rollback prometheus 1 -n observability

# Option 2: Uninstall and reinstall
helm uninstall prometheus -n observability
helm install prometheus prometheus-community/prometheus -n observability -f values.yaml

# Option 3: Force upgrade
helm upgrade --install prometheus prometheus-community/prometheus -n observability -f values.yaml --force
```

**Lesson:**
Monitor Helm release status. A "failed" release needs immediate attention - it indicates broken IaC deployment.

---

## 41. CloudFormation Drift Detection False Positive for EC2 MetadataOptions

**Issue:**
CloudFormation drift detection reported bastion EC2 instance as "DRIFTED" for MetadataOptions, but the instance was correctly configured.

**Drift Detection Output:**
```json
{
  "PropertyPath": "/MetadataOptions",
  "ExpectedValue": {"HttpEndpoint":"enabled","HttpPutResponseHopLimit":1,"HttpTokens":"required"},
  "ActualValue": "null",
  "DifferenceType": "REMOVE"
}
```

**Root Cause:**
This is a **known AWS limitation**. CloudFormation drift detection cannot properly read MetadataOptions from running EC2 instances. It reports `null` for the actual value even when the instance is correctly configured with IMDSv2.

**Consequence:**
Running `aws cloudformation deploy` to "fix" this drift caused CloudFormation to **replace the instance** (since MetadataOptions changes require instance replacement), creating unnecessary downtime and a new instance.

**How to Verify Actual Instance Configuration:**
```bash
# Check actual MetadataOptions on the running instance
aws ec2 describe-instances --instance-ids i-xxxxx \
  --query 'Reservations[0].Instances[0].MetadataOptions' \
  --output json
```

**Lesson:**
Before "fixing" CloudFormation drift:
1. **Verify the actual resource state** - don't blindly trust drift detection
2. **Research known drift detection limitations** for the resource type
3. For EC2 MetadataOptions drift, always verify via `aws ec2 describe-instances` first
4. **Document false positives** to avoid repeated unnecessary updates

**Known CloudFormation Drift Detection Limitations:**
- EC2 MetadataOptions (reports null)
- Some IAM policy details
- Lambda function code changes

---

## 42. Istio Sidecar Injection Requires Pod Label (Not Just Annotation)

**Issue:**
After adding `sidecar.istio.io/inject: "true"` as a pod annotation, Istio was not injecting sidecars into Grafana and Headlamp pods.

**Root Cause:**
The Istio mutating webhook's `objectSelector` uses **label matchers**, not annotation matchers:

```yaml
objectSelector:
  matchExpressions:
  - key: sidecar.istio.io/inject
    operator: In
    values:
    - "true"
```

This selector checks for `sidecar.istio.io/inject` as a **pod label**, not annotation.

**For annotation-based injection to work**, the namespace must have either:
- `istio-injection=enabled` label, OR
- `istio.io/rev=default` label

**Solution:**
Add both pod label AND annotation in Helm values:
```yaml
# Label required for webhook objectSelector matching
podLabels:
  sidecar.istio.io/inject: "true"

# Annotations for injection configuration
podAnnotations:
  sidecar.istio.io/inject: "true"
  proxy.istio.io/config: '{"holdApplicationUntilProxyStarts": true}'
```

**Lesson:**
When using Istio sidecar injection without namespace labels:
- Set `sidecar.istio.io/inject: "true"` as both **label** and **annotation**
- The label triggers the webhook selector
- The annotation configures injection behavior
- Always test injection after deployment

---

## 43. Kubernetes 1.28+ Native Sidecars

**Observation:**
After successful Istio sidecar injection, the `istio-proxy` container doesn't appear in `.spec.containers[]`. Instead, it appears in `.spec.initContainers[]`.

**Explanation:**
Istio uses **Kubernetes 1.28+ native sidecars**, a new feature where sidecar containers are specified as init containers with `restartPolicy: Always`.

```yaml
initContainers:
- name: istio-init
  restartPolicy: null        # Runs once (normal init container)
- name: istio-proxy
  restartPolicy: Always      # Native sidecar - runs continuously
```

**How to Verify Sidecar Injection:**
```bash
# Check init container restart policy
kubectl get pod <pod-name> -o json | jq '.spec.initContainers[] | "\(.name): \(.restartPolicy)"'

# Expected output:
# istio-init: null
# istio-proxy: Always

# Check READY column - includes native sidecars
kubectl get pods -n <namespace>
# headlamp   2/2   Running   (main container + istio-proxy)
```

**Benefits of Native Sidecars:**
- Startup ordering: sidecars start before main container
- Shutdown ordering: sidecars stop after main container
- Better lifecycle management

**Lesson:**
On EKS 1.28+, Istio sidecars won't appear in `.spec.containers[]`. Check:
1. READY column (e.g., 2/2 instead of 1/1)
2. `.spec.initContainers[]` with `restartPolicy: Always`

---

## 44. Always Use cfn-lint and cfn-guard for IaC Validation

**Issue:**
CloudFormation templates were deployed without proper validation, leading to:
- Unused parameters that clutter templates
- Missing NIST 800-53 compliance requirements
- Potential security misconfigurations

**Tools:**

| Tool | Purpose | Install |
|------|---------|---------|
| **cfn-lint** | Syntax/best practice validation | `pip3 install cfn-lint` |
| **cfn-guard** | Policy-as-code compliance (NIST) | `brew install cloudformation-guard` |

**cfn-lint Usage:**
```bash
# Validate all CloudFormation templates
cfn-lint infra/cloudformation/stacks/**/*.yaml

# Common issues detected:
# W2001 - Unused parameter
# W8001 - Unused condition
# E0000 - Template syntax error
```

**cfn-guard Usage:**
```bash
# Validate against NIST 800-53 rules
cfn-guard validate -d template.yaml -r cfn-guard-rules/nist-800-53/phase1-controls.guard

# Output:
# PASS - Rule passed for this resource type
# SKIP - Rule not applicable (no matching resources in template)
# FAIL - Compliance violation
```

**cfn-guard Rule Structure (v3.x):**
```guard
rule rds_encryption {
    AWS::RDS::DBInstance {
        Properties.StorageEncrypted == true
        <<
            NIST SC-28: RDS instances must have storage encryption enabled
        >>
    }
}
```

**CI/CD Integration:**
```yaml
# .github/workflows/validate-iac.yaml
- name: Validate CloudFormation
  run: |
    cfn-lint infra/cloudformation/stacks/**/*.yaml
    cfn-guard validate -d infra/cloudformation/stacks/**/*.yaml \
      -r infra/cloudformation/cfn-guard-rules/nist-800-53/*.guard
```

**Lesson:**
Run both cfn-lint (syntax) and cfn-guard (compliance) on ALL CloudFormation changes before deployment. Add to CI/CD pipeline as mandatory gates.

---

## 45. ~~Keycloak for Centralized SSO Authentication~~ (SUPERSEDED)

> **SUPERSEDED:** This lesson was replaced by Lesson #46 (AWS Cognito). Keycloak IaC has been removed from the codebase. Use AWS Cognito for authentication.

**Original Issue (Historical):**
Multiple observability tools (Grafana, Headlamp, Kiali, Kubecost) each had separate authentication:
- Grafana: admin password
- Headlamp: service account token
- Kiali: various auth methods
- Kubecost: basic auth

This creates multiple credentials to manage and inconsistent user experience.

**Solution:**
Deploy Keycloak as centralized identity provider (IdP) with OIDC/OAuth2.

**Architecture:**
```
                    +-----------+
                    | Keycloak  |
                    |   (IdP)   |
                    +-----+-----+
                          |
        +-----------------+------------------+
        |                 |                  |
   +----v----+      +-----v-----+     +------v------+
   | Grafana |      | Headlamp  |     |   Kiali     |
   | (OIDC)  |      |  (OIDC)   |     |   (OIDC)    |
   +---------+      +-----------+     +-------------+
```

**OIDC Configuration:**

| Service | OIDC Support | Configuration Location |
|---------|--------------|------------------------|
| Grafana | ✅ Native | `auth.generic_oauth` in grafana-values.yaml |
| Headlamp | ✅ Native | `--oidc-*` flags in headlamp-values.yaml |
| Kiali | ✅ Native | `auth.strategy: openid` in kiali-values.yaml |
| Kubecost | ⚠️ Limited | Basic auth or SSO via ingress |

**IaC for Keycloak:**
```
infra/cloudformation/stacks/02-data/keycloak-rds.yaml   # RDS PostgreSQL
infra/helm/values/keycloak/keycloak-deployment.yaml    # K8s deployment
```

**NIST Controls:**
- IA-2 (Identification and Authentication): Centralized identity management
- IA-5 (Authenticator Management): Unified credential policies
- AC-2 (Account Management): Single point for user provisioning

**Lesson:**
For production environments, deploy Keycloak (or similar IdP) for centralized SSO. This simplifies authentication management and improves security posture.

---

## 46. AWS Cognito + ALB Authentication (Replacing Keycloak)

**Decision:**
Switched from self-managed Keycloak to AWS Cognito for observability authentication. Simpler, managed service, no RDS required.

**Architecture:**
```
User → ALB (HTTPS) → Cognito Auth → Backend Service
                          ↓
                    JWT in X-Amzn-Oidc-Data header
```

**Key Components:**
| Component | Purpose |
|-----------|---------|
| Cognito User Pool | User directory, password policy |
| Cognito App Client | OAuth2 client for ALB |
| ALB authenticate-cognito action | Redirects unauthenticated users to Cognito |

**CloudFormation Resources:**
- `infra/cloudformation/stacks/01-networking/cognito-auth.yaml`
- `infra/cloudformation/stacks/01-networking/alb-observability.yaml`

**Lesson:**
AWS Cognito provides simpler authentication than self-managed Keycloak for most use cases. Consider Cognito first for AWS-native workloads.

---

## 47. Cognito App Client ExplicitAuthFlows Required for Login

**Error:**
```
401 Unauthorized
Incorrect username or password
```

**Cause:**
Cognito app client was created without `ExplicitAuthFlows`. The hosted UI requires specific auth flows to be enabled.

**Fix:**
Add ExplicitAuthFlows to CloudFormation:
```yaml
UserPoolClient:
  Type: AWS::Cognito::UserPoolClient
  Properties:
    ExplicitAuthFlows:
      - ALLOW_USER_SRP_AUTH        # Required for hosted UI
      - ALLOW_USER_PASSWORD_AUTH   # Required for username/password login
      - ALLOW_REFRESH_TOKEN_AUTH   # Required for token refresh
```

**Lesson:**
When using Cognito hosted UI for authentication:
1. `ALLOW_USER_SRP_AUTH` - Secure Remote Password protocol
2. `ALLOW_USER_PASSWORD_AUTH` - Username/password auth
3. `ALLOW_REFRESH_TOKEN_AUTH` - Token refresh capability

Without these, users will get "incorrect username or password" even with correct credentials.

---

## 48. Grafana JWT Auth for ALB + Cognito

**Issue:**
After ALB authenticates user via Cognito, Grafana still shows its own login page.

**Cause:**
Grafana doesn't know about the ALB authentication. Need to configure Grafana to trust the JWT in ALB headers.

**Solution:**
Configure Grafana's JWT authentication in `grafana-values.yaml`:
```yaml
grafana.ini:
  auth.jwt:
    enabled: true
    header_name: X-Amzn-Oidc-Data
    email_claim: email
    username_claim: email
    auto_sign_up: true
    jwk_set_url: https://public-keys.auth.elb.us-east-1.amazonaws.com
```

**How it works:**
1. ALB authenticates user via Cognito
2. ALB adds JWT to `X-Amzn-Oidc-Data` header
3. Grafana reads JWT from header
4. Grafana validates JWT against ALB's public keys
5. Grafana auto-creates user from JWT claims

**Lesson:**
When putting Grafana behind ALB + Cognito, configure `auth.jwt` to use ALB's JWT header. The JWK URL is region-specific: `https://public-keys.auth.elb.{region}.amazonaws.com`

---

## 49. Kiali Anonymous Mode Behind ALB

**Issue:**
Kiali requires a Kubernetes token even after ALB/Cognito authentication.

**Solution:**
Set Kiali to anonymous mode since ALB already handles authentication:
```yaml
# kiali-cr.yaml
spec:
  auth:
    strategy: anonymous
```

**Security Note:**
This is acceptable because:
1. ALB + Cognito authenticates all users before reaching Kiali
2. Only authenticated users can access the ALB URL
3. Kiali is not directly exposed to internet

**Lesson:**
For services behind ALB + Cognito that don't support JWT header auth, use anonymous mode. The perimeter authentication (ALB) provides the security layer.

---

## 50. Headlamp Token Requirement - Architectural Limitation

**Issue:**
Headlamp STILL requires a Kubernetes token even after Cognito authentication.

**Root Cause:**
This is a fundamental architectural constraint, not a bug:
1. Headlamp is a Kubernetes dashboard
2. It needs to call the Kubernetes API
3. Kubernetes API requires authentication (token, certificate, etc.)
4. ALB/Cognito auth is for the web UI only, not K8s API

**Comparison:**
| Service | Web UI Auth | Backend Auth |
|---------|-------------|--------------|
| Grafana | JWT (ALB header) | Datasource auth (internal) |
| Kiali | Anonymous | Service account (internal) |
| Headlamp | Cognito (ALB) | **K8s token (user provides)** |

**Why Headlamp is different:**
- Grafana/Kiali have internal service accounts for their backends
- Headlamp proxies K8s API calls on behalf of the user
- User's K8s permissions determine what they can see/do
- This is intentional - RBAC at the K8s level

**Future Options to Eliminate Token:**
1. **Headlamp OIDC**: Configure Headlamp to use Cognito OIDC directly (complex)
2. **Pre-injected Token**: Mount a service account token (reduces RBAC granularity)
3. **EKS Pod Identity + IRSA**: Map Cognito users to K8s RBAC (most complex)

**Lesson:**
Headlamp's token requirement is by design for K8s RBAC. Accept this as a UX limitation or invest in OIDC integration for true SSO.

---

## 51. NEVER Update AWS Resources via CLI - Always Use IaC

**Violation:**
```bash
# WRONG - This creates drift!
aws cognito-idp update-user-pool-client \
  --user-pool-id us-east-1_xxx \
  --client-id xxx \
  --explicit-auth-flows ALLOW_USER_SRP_AUTH ALLOW_REFRESH_TOKEN_AUTH
```

**Why it's wrong:**
1. Change is not tracked in Git
2. CloudFormation/Terraform doesn't know about it
3. Next IaC deployment may overwrite it
4. Cannot reproduce environment from IaC alone
5. Violates NIST CM-3 (Configuration Change Control)

**Correct approach:**
1. Update CloudFormation template
2. Run cfn-lint and cfn-guard validation
3. Deploy via `aws cloudformation update-stack`

```yaml
# In cognito-auth.yaml
UserPoolClient:
  Properties:
    ExplicitAuthFlows:
      - ALLOW_USER_SRP_AUTH
      - ALLOW_USER_PASSWORD_AUTH
      - ALLOW_REFRESH_TOKEN_AUTH
```

**Lesson:**
EVERY infrastructure change must go through IaC:
- AWS resources → CloudFormation
- K8s resources → Helm charts
- Never use CLI for permanent changes

---

## 52. Istio Sidecar Injection Version Mismatch

**Error:**
```
admission webhook "object.sidecar-injector.istio.io" denied the request:
failed to run injection template: template: inject:29:111: executing "inject"
at <.NativeSidecars>: can't evaluate field NativeSidecars in type *inject.SidecarTemplateData
```

**Cause:**
Istio sidecar injector template references `.NativeSidecars` field which doesn't exist in the current Istio version's SidecarTemplateData struct.

**Workaround:**
Temporarily disable Istio injection for affected workloads:
```yaml
podLabels:
  sidecar.istio.io/inject: "false"
podAnnotations:
  sidecar.istio.io/inject: "false"
```

**Proper Fix:**
- Upgrade Istio to version compatible with K8s native sidecars
- Or downgrade injection template

**Lesson:**
Istio version must be compatible with Kubernetes version. When using K8s 1.28+ native sidecars feature, ensure Istio supports it.

---

## 53. StatefulSet PV AZ-Binding Causes Scheduling Failures After Node Restart - CRITICAL

**Incident Date:** 2026-01-15

**Incident:**
After cluster restart (nodes scaled to 0, then back up), SigNoz pods stuck in Pending for 20+ hours, ultimately requiring full data loss to recover.

**Root Cause Chain:**
```
1. SigNoz deployed → PVs (EBS volumes) created in us-east-1b
2. Cluster shutdown (nodes scaled to 0)
3. Cluster restart → new nodes created in 3 AZs (us-east-1a, 1b, 1c)
4. Deployments scheduled first → filled us-east-1b node to 98% CPU
5. StatefulSets tried to schedule LAST → us-east-1b node was FULL
6. EBS volumes are AZ-bound → pods CANNOT move to other AZs
7. Force-deleting stuck pod → ClickHouse operator deleted entire CHI
8. Result: Complete data loss, full reinstall required
```

**Why EBS Volumes Are AZ-Bound:**
EBS volumes are physical storage in a specific Availability Zone. They can ONLY be attached to EC2 instances in the same AZ. This is an AWS limitation, not a Kubernetes issue.

**Why This Is Unacceptable:**
- StatefulSets contain persistent data (ClickHouse database)
- Resource contention should NOT cause data loss
- Operator cleanup behavior is dangerous when triggered incorrectly
- No visibility into the issue until manual investigation

**Impact:**
- SigNoz (observability) DOWN for 20+ hours
- All metrics, logs, traces data LOST
- Required complete reinstall
- 12 orphaned LGTM PVCs discovered and cleaned up

**Prevention Design (MUST IMPLEMENT FOR PRODUCTION):**

### 1. Multi-AZ StatefulSets
Spread PVs across AZs so not all data is in one AZ:
```yaml
# In Helm values
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: DoNotSchedule
    labelSelector:
      matchLabels:
        app: signoz
```

### 2. PriorityClasses for StatefulSets
Ensure StatefulSets schedule BEFORE Deployments:
```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: stateful-critical
value: 1000000
globalDefault: false
description: "Critical stateful workloads (databases)"
---
# In StatefulSet spec:
spec:
  template:
    spec:
      priorityClassName: stateful-critical
```

### 3. Resource Reservations
Reserve headroom on each node:
```yaml
# In node-groups.yaml - ensure buffer capacity
GeneralNodeMinSize: 3  # Minimum 3 nodes, not 1 or 2
GeneralNodeDesiredSize: 3
```

### 4. Graceful Shutdown Procedure
```bash
# BEFORE scaling nodes to 0:

# 1. Cordon nodes (prevent new scheduling)
kubectl cordon --all

# 2. Scale down StatefulSets gracefully
kubectl scale statefulset --all -n signoz --replicas=0

# 3. Wait for PVs to detach (check EBS console)
aws ec2 describe-volumes --filters "Name=tag:kubernetes.io/created-for/pvc/namespace,Values=signoz"

# 4. Then scale nodes to 0
aws eks update-nodegroup-config --scaling-config desiredSize=0 ...
```

### 5. NEVER Force-Delete StatefulSet Pods
```bash
# WRONG - triggers operator cleanup cascade!
kubectl delete pod clickhouse-0 --force --grace-period=0

# RIGHT - investigate root cause first
kubectl describe pod clickhouse-0
kubectl logs clickhouse-0
kubectl get events --sort-by='.lastTimestamp'
```

### 6. Velero Backup Schedule
```yaml
# Schedule daily backups for stateful namespaces
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: signoz-daily
spec:
  schedule: "0 2 * * *"
  template:
    includedNamespaces:
      - signoz
    includedResources:
      - persistentvolumeclaims
      - persistentvolumes
    snapshotVolumes: true
```

### 7. Node Autoscaling with Buffer
```yaml
# Ensure cluster can scale to meet demand
GeneralNodeMinSize: 3
GeneralNodeMaxSize: 10
GeneralNodeDesiredSize: 3
```

**IaC Changes Required:**
- [ ] Add PriorityClass to `infra/helm/values/signoz/values.yaml`
- [ ] Add topologySpreadConstraints for multi-AZ
- [ ] Update node-groups.yaml minSize to 3
- [ ] Create `scripts/graceful-shutdown.sh`
- [ ] Configure Velero backup schedule for signoz namespace
- [ ] Document RTO/RPO requirements

**Detection:**
```bash
# Check if StatefulSet pods are stuck
kubectl get pods -A | grep -E "Pending|Init"

# Check PV AZ bindings
kubectl get pv -o custom-columns='NAME:.metadata.name,AZ:.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0]'

# Check node capacity
kubectl describe nodes | grep -A 6 "Allocated resources"
```

**Lesson:**
StatefulSets with EBS-backed PVCs are vulnerable to AZ-specific resource constraints. After node restarts, if the AZ with PVs has insufficient resources, pods cannot schedule and data is at risk. Implement multi-AZ StatefulSets, PriorityClasses, and proper shutdown procedures to prevent this.

---

## 54. Orphaned PVCs After Stack Migration

**Issue:**
After migrating from LGTM stack (Grafana, Loki, Tempo, Mimir, Prometheus) to SigNoz, 12 PVCs were left orphaned in the `observability` namespace.

**Root Cause:**
Helm uninstall does not delete PVCs by default (to protect data). When Helm releases were deleted, the PVCs remained.

**Impact:**
- 12 EBS volumes (~200GB) wasting storage costs
- Orphaned PVs tied up AZ capacity
- Confusion during troubleshooting

**Detection:**
```bash
# Find PVCs not associated with running workloads
kubectl get pvc -A --no-headers | while read ns name rest; do
  pod_count=$(kubectl get pods -n $ns -o json 2>/dev/null | jq --arg pvc "$name" '[.items[] | select(.spec.volumes[]?.persistentVolumeClaim.claimName == $pvc)] | length')
  if [ "$pod_count" == "0" ]; then
    echo "ORPHANED: $ns/$name"
  fi
done
```

**Cleanup:**
```bash
# Delete all PVCs in orphaned namespace
kubectl delete pvc --all -n observability

# Delete empty namespace
kubectl delete namespace observability
```

**Prevention:**
When decommissioning a stack:
1. Document all PVCs that will be orphaned
2. Backup data if needed (Velero snapshot)
3. Explicitly delete PVCs after Helm uninstall
4. Delete empty namespaces

**Lesson:**
Always clean up PVCs after removing Helm releases. Add PVC cleanup to decommissioning checklists.


---

## 55. Trivy Scan Jobs Fail with Istio Injection (2026-01-15)

**Issue:** Trivy vulnerability scan jobs fail with error: `spec.initContainers[0].name: Duplicate value: "istio-init"`

**Root Cause:** 
- Trivy operator creates scan Job pods with their own init containers
- One of Trivy's init containers is named `istio-init`
- When Istio injection is enabled, Istio also adds an `istio-init` container
- Kubernetes rejects pods with duplicate container names

**Impact:**
- All vulnerability scans fail
- Jobs hit BackoffLimitExceeded and DeadlineExceeded
- No vulnerability reports generated

**Solution:**
Disable Istio injection for the trivy-system namespace:
```bash
kubectl label namespace trivy-system istio-injection=disabled --overwrite
```

**IaC Fix:**
Updated `infra/helm/values/trivy/namespace.yaml`:
```yaml
metadata:
  labels:
    istio-injection: disabled  # Conflicts with Trivy scan job init containers
```

**Prevention:**
- Before enabling Istio injection for a namespace, check if any workloads use init containers named `istio-init`
- Some operators/tools may use this name internally
- Document Istio-incompatible namespaces in architecture docs

---

## 56. OTLP GRPC Fails Through Istio - Use HTTP Instead (2026-01-15)

**Issue:** HotROD demo app traces failed to export to SigNoz OTel Collector with error:
```
traces export: context deadline exceeded: retry-able request failure: 
upstream connect error or disconnect/reset before headers. 
reset reason: protocol error
```

**Root Cause:**
- OTLP GRPC (port 4317) doesn't work reliably through Istio Envoy proxy
- Even with `traffic.sidecar.istio.io/excludeOutboundPorts: "4317"` annotation, the issue persisted
- The Envoy proxy has issues with H2 (HTTP/2) protocol handling for some GRPC services

**Solution:**
Switch from GRPC to HTTP/protobuf for OTLP trace export:
```yaml
env:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://signoz-otel-collector.signoz.svc.cluster.local:4318"  # HTTP, not 4317
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: "http/protobuf"  # Not "grpc"
```

**Verification:**
```bash
# Test HTTP endpoint works through Istio
kubectl run -n <namespace> --rm -i --restart=Never --image=curlimages/curl test -- \
  curl -X POST "http://signoz-otel-collector.signoz.svc.cluster.local:4318/v1/traces" \
  -H "Content-Type: application/json" -d '{}'
# Should return: {"partialSuccess":{}}
```

**Prevention:**
- Default to HTTP/protobuf (port 4318) for OTLP in Istio-enabled clusters
- Only use GRPC (port 4317) if source and destination are both outside Istio mesh
- Document this in onboarding guides for new services

**Lesson:**
When running in an Istio service mesh, prefer OTLP HTTP (4318) over GRPC (4317) for trace export. The HTTP protocol works reliably through Envoy sidecars while GRPC has protocol-level issues.

---

## 57. Demo Namespaces CAN Use Istio with HTTP OTLP (2026-01-17 - UPDATED)

**Original Issue (2026-01-15):** Initially disabled Istio for demo namespace due to OTLP/Envoy conflicts.

**Resolution (2026-01-17):** Re-enabled Istio for demo namespace because:
1. OTLP HTTP/protobuf (port 4318) works reliably through Istio Envoy
2. Istio enables Kiali traffic visualization for demos
3. mTLS provides realistic production-like environment

**Current Configuration:**
```yaml
# infra/helm/values/demo/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: demo
  labels:
    istio-injection: enabled  # ENABLED for Kiali visualization
    purpose: tracing-demo
```

```yaml
# infra/helm/values/demo/hotrod-deployment.yaml
metadata:
  annotations:
    sidecar.istio.io/inject: "true"
env:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://signoz-otel-collector.signoz.svc.cluster.local:4318"  # HTTP works!
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: "http/protobuf"
```

**Key Insight:**
- OTLP GRPC (port 4317) fails through Istio Envoy
- OTLP HTTP/protobuf (port 4318) works through Istio Envoy
- If using HTTP, Istio injection is fine for demo apps

**Namespaces That Should Disable Istio:**
| Namespace | Reason |
|-----------|--------|
| `trivy-system` | Init container name conflict (`istio-init`) |
| `velero` | Backup operations need direct access |

**Note:** `demo` namespace now has Istio ENABLED for Kiali traffic visualization.

**Lesson:**
Don't assume Istio breaks OTLP. Only GRPC has issues; HTTP/protobuf works fine. Enable Istio for demo namespaces when you want Kiali traffic visualization.

---

## 58. Cleanup Checklist After Stack Migration (2026-01-15)

**Issue:** After migrating from LGTM stack to SigNoz, multiple orphaned resources remained:
- Kiali operator namespace and Helm release
- Empty `identity` namespace
- Deprecated scripts with old references
- IaC files with stale configurations

**Cleanup Checklist:**
```markdown
## Post-Migration Cleanup

### Kubernetes Resources
- [ ] Uninstall deprecated Helm releases: `helm uninstall <release> -n <namespace>`
- [ ] Delete orphaned PVCs: `kubectl delete pvc --all -n <namespace>`
- [ ] Delete empty namespaces: `kubectl delete namespace <name>`
- [ ] Remove completed Jobs: `kubectl delete jobs --field-selector status.successful=1 -A`

### IaC Updates
- [ ] Update values files to remove old references
- [ ] Move deprecated IaC to `deprecated/` folder
- [ ] Update CLAUDE.md/README with new components
- [ ] Update access-urls.md with new endpoints

### Scripts
- [ ] Archive scripts that reference old stack to `scripts/deprecated/`
- [ ] Update any automation scripts
- [ ] Test remaining scripts work with new stack

### Documentation
- [ ] Update architecture diagrams
- [ ] Update lessons-learned.md
- [ ] Update runbooks for new components
```

**Prevention:**
- Create migration checklist BEFORE starting migration
- Use IaC drift detection to find orphaned resources
- Schedule cleanup tasks immediately after migration

**Lesson:**
Stack migrations leave debris. Create and follow a cleanup checklist to ensure all orphaned resources, IaC, scripts, and documentation are properly cleaned up.

---

## 59. TargetGroupBindings for Automatic ALB Target Registration (2026-01-17)

**Issue:** After graceful cluster restart, ALB target groups showed 0 healthy targets for Kiali. Users could not access Kiali via ALB.

**Root Cause:**
When EKS nodes terminate and new ones launch, the ALB target groups lose their targets. Without `TargetGroupBinding` CRDs, targets must be manually re-registered.

**Why Other Services Worked:**
SigNoz, Headlamp, and Kubecost had `TargetGroupBinding` resources created earlier. Kiali was missing this configuration.

**Solution:**
Create `TargetGroupBinding` resources for all services behind the ALB:

```yaml
# infra/helm/values/kiali/targetgroupbinding.yaml
apiVersion: elbv2.k8s.aws/v1beta1
kind: TargetGroupBinding
metadata:
  name: kiali-tgb
  namespace: istio-system
  labels:
    app: kiali
spec:
  serviceRef:
    name: kiali
    port: 20001
  targetGroupARN: arn:aws:elasticloadbalancing:us-east-1:340752837296:targetgroup/infra-agent-dev-kiali-tg/7b0614394ce78a79
  targetType: instance
```

**How TargetGroupBinding Works:**
1. AWS Load Balancer Controller watches for TargetGroupBinding resources
2. Controller automatically registers/deregisters node IPs with the ALB target group
3. When nodes terminate, controller removes them from target group
4. When nodes launch, controller adds them to target group
5. No manual intervention required

**Files Created:**
- `infra/helm/values/kiali/targetgroupbinding.yaml`
- `infra/helm/values/signoz/targetgroupbinding.yaml`
- `infra/helm/values/headlamp/targetgroupbinding.yaml`
- `infra/helm/values/kubecost/targetgroupbinding.yaml`

**Lesson:**
Every service exposed via ALB must have a TargetGroupBinding resource to ensure automatic target registration when nodes cycle. Add this to the deployment checklist for any new service.

---

## 60. EKS Nodes Terminate, Not Stop (By Design) (2026-01-17)

**User Question:** "Why are nodes terminating? They should just shutdown and not terminate."

**Answer:** This is by design. EKS Managed Node Groups use AWS Auto Scaling Groups (ASG), which terminate instances on scale-down and launch new instances on scale-up.

**Why This Is Correct:**
| Component | Scale Down | Scale Up | Design Pattern |
|-----------|------------|----------|----------------|
| **EKS Nodes** | Terminate | Launch new | Cattle (ephemeral) |
| **Bastion** | Stop | Start | Pet (persistent) |

**Key Points:**
1. Kubernetes nodes are "cattle, not pets" - designed to be disposable
2. ASG manages instance lifecycle - terminate/launch is the only supported operation
3. Fresh nodes ensure clean state without configuration drift
4. AWS best practice for managed Kubernetes

**What IS Preserved:**
- EBS PersistentVolumes (AZ-bound, reattach to new nodes in same AZ)
- Kubernetes state (stored in etcd on AWS-managed control plane)
- Pod definitions (Deployments/StatefulSets recreate pods on new nodes)
- ConfigMaps and Secrets (stored in etcd)

**What is NOT Preserved:**
- Local ephemeral storage (emptyDir volumes)
- Node-specific cache (container image cache rebuilt)
- In-memory state (pods restart fresh)

**Documented As:** Requirements NFR-050 to NFR-053 in `docs/requirements.md`

**Lesson:**
Don't try to make EKS nodes "stop" - embrace the terminate/launch model. Design your applications to handle node replacement gracefully.

---

## 61. Graceful Shutdown - Don't Scale Pods, Just Nodes (2026-01-17)

**User Question:** "Do we have to scale the pods to 0? Why can't we simply set the nodes to 0? And when the nodes come back up - the pods come up automatically."

**Answer:** The user is correct. The original `graceful-shutdown.sh` was over-engineered.

**Old Approach (Over-engineered):**
```bash
# DON'T DO THIS - unnecessary steps
kubectl scale deployments --all -n signoz --replicas=0
kubectl scale statefulsets --all -n signoz --replicas=0
# Wait for pods to terminate
# Then scale nodes
```

**New Approach (Correct):**
```bash
# Just scale nodes to 0
aws eks update-nodegroup-config \
  --cluster-name infra-agent-dev-cluster \
  --nodegroup-name infra-agent-dev-general-nodes \
  --scaling-config minSize=0,maxSize=10,desiredSize=0

# Stop bastion
aws ec2 stop-instances --instance-ids i-02c424847cd5f557e
```

**Why This Works:**
1. When nodes terminate, pods are evicted automatically
2. Kubernetes handles graceful shutdown via preStop hooks and terminationGracePeriodSeconds
3. When nodes come back, controllers (Deployment, StatefulSet, DaemonSet) recreate pods
4. StatefulSets reattach to existing PVs

**Startup (Also Simple):**
```bash
# Start bastion
aws ec2 start-instances --instance-ids i-02c424847cd5f557e

# Scale nodes back up
aws eks update-nodegroup-config \
  --cluster-name infra-agent-dev-cluster \
  --nodegroup-name infra-agent-dev-general-nodes \
  --scaling-config minSize=3,maxSize=10,desiredSize=3
```

**Lesson:**
Let Kubernetes do its job. Don't manually scale pods to 0 before shutdown. Just scale nodes to 0 and let Kubernetes handle pod eviction. On startup, scale nodes up and let controllers recreate pods.

---

## 62. DaemonSets Don't Need Istio Sidecars (2026-01-17)

**Issue:** DaemonSet pods (otel-agent, velero node-agent) failed to schedule with "Insufficient CPU" errors.

**Root Cause:**
- Istio sidecar injection adds ~100m CPU per pod
- DaemonSets run on EVERY node
- 3 nodes × DaemonSet pods × 100m = significant overhead
- Cluster was at 95% CPU request allocation

**Solution:**
Disable Istio sidecar injection for DaemonSets:
```yaml
# In DaemonSet values
podAnnotations:
  sidecar.istio.io/inject: "false"
```

**Why This Is Acceptable:**
1. DaemonSets are infrastructure components (logging, backup agents)
2. They communicate with control plane services, not application pods
3. They already have secure channels (otel-agent → SigNoz, node-agent → Velero)
4. mTLS overhead isn't justified for infrastructure traffic

**Files Updated:**
- `infra/helm/values/signoz/k8s-infra-values.yaml` (otel-agent)
- `infra/helm/values/velero/values.yaml` (node-agent)

**Lesson:**
Not every workload needs Istio sidecars. DaemonSets for infrastructure purposes (logging, monitoring, backup) can safely skip sidecar injection to save resources.

---

## 63. Kiali Requires Prometheus (SigNoz Isn't Compatible) (2026-01-17)

**Issue:** After migrating to SigNoz, Kiali traffic graph showed error: "no such host signoz-query-service.signoz.svc.cluster.local:8080"

**Root Cause:**
Kiali needs Prometheus to query Istio metrics. SigNoz does NOT provide a Prometheus-compatible query API. The SigNoz query service is ClickHouse-based, not Prometheus.

**Solution:**
Deploy a minimal Prometheus instance specifically for Kiali:

```yaml
# infra/helm/values/prometheus-kiali/values.yaml
server:
  name: prometheus-kiali
  persistentVolume:
    enabled: false  # No persistence needed - metrics are ephemeral
  retention: "2h"    # Kiali only needs recent data
  resources:
    requests:
      cpu: 50m
      memory: 256Mi
serverFiles:
  prometheus.yml:
    scrape_configs:
      - job_name: 'istiod'
        kubernetes_sd_configs:
          - role: endpoints
            namespaces:
              names:
                - istio-system
      - job_name: 'envoy-stats'
        metrics_path: /stats/prometheus
        kubernetes_sd_configs:
          - role: pod
```

**Configuration:**
Update Kiali values to point to the new Prometheus:
```yaml
external_services:
  prometheus:
    url: "http://prometheus-kiali-server.prometheus-kiali.svc.cluster.local"
```

**Important Clarification:**
Kiali and Prometheus are NOT part of Istio. They are separate CNCF projects that integrate with Istio:
- **Kiali**: Service mesh visualization tool FOR Istio
- **Prometheus**: General-purpose metrics collection that scrapes Istio metrics

**Lesson:**
SigNoz and Prometheus serve different purposes. If you need Prometheus-compatible APIs (like Kiali does), you must deploy Prometheus alongside SigNoz.

---

## 64. Always Validate IaC Before Deployment (2026-01-17)

**User Feedback:** "did you use IaC for everything and did you do a lint and guard check on all new iac and helm code?"

**Issue:** New Helm values and Kubernetes manifests were created without running validation, risking security issues.

**Required Validation Steps:**

### For CloudFormation:
```bash
source /Users/ymuwakki/infra-agent/.venv/bin/activate
cfn-lint infra/cloudformation/stacks/**/*.yaml
cfn-guard validate \
  -d infra/cloudformation/stacks/ \
  -r infra/cloudformation/cfn-guard-rules/nist-800-53/
```

### For Kubernetes/Helm:
```bash
# Schema validation (kubeconform)
kubeconform -strict infra/helm/values/**/*.yaml

# Security validation (kube-linter)
kube-linter lint infra/helm/values/
```

**Common kube-linter Findings:**
- Missing resource limits
- Missing security context (readOnlyRootFilesystem, runAsNonRoot)
- Containers running as root
- Missing liveness/readiness probes

**What We Fixed:**
1. Added `securityContext` to prometheus-kiali values
2. Added resource limits to all init containers
3. Added `readOnlyRootFilesystem: true` where applicable

**NEVER Deploy Without Validation:**
```markdown
## Pre-Deployment Checklist
- [ ] cfn-lint passes (0 errors)
- [ ] cfn-guard passes (0 FAIL)
- [ ] kubeconform passes (0 invalid)
- [ ] kube-linter passes (0 errors)
```

**Lesson:**
Always validate ALL IaC changes before deployment. cfn-lint + cfn-guard for CloudFormation, kubeconform + kube-linter for Kubernetes. This is non-negotiable.

---

## 65. Schema Migrator Job Deletion Causes Startup Issues (2026-01-17)

**Issue:** After cluster restart, SigNoz otel-collector pods stuck in Init:0/1 state indefinitely.

**Root Cause:**
1. SigNoz uses a Kubernetes Job for schema migrations
2. During shutdown, the Job was deleted (Job completed + TTL or manual cleanup)
3. On startup, otel-collector init container waits for schema migration to complete
4. With no Job to wait for, init container hangs forever

**Symptoms:**
```
kubectl get pods -n signoz
NAME                                   READY   STATUS     RESTARTS
signoz-otel-collector-xxx              0/1     Init:0/1   0
```

**Solution:**
Run `helm upgrade` to recreate the schema migration Job:
```bash
helm upgrade signoz signoz/signoz -n signoz -f infra/helm/values/signoz/values.yaml
```

**Why This Works:**
Helm upgrade recreates the Job, which runs the schema migration. Once complete, the init container succeeds and otel-collector starts.

**Prevention:**
- Document this in startup runbook
- Consider using `ttlSecondsAfterFinished: 86400` (1 day) instead of immediate cleanup
- After startup, verify Jobs exist: `kubectl get jobs -n signoz`

**Lesson:**
Helm Jobs may not survive cluster restart. When troubleshooting pods stuck in Init state, check if dependent Jobs exist. Use `helm upgrade` to recreate missing Jobs.

---

## 66. Infrastructure Telemetry Collectors Don't Need Istio (2026-01-17)

**Issue:** k8s-infra-otel-deployment (cluster metrics collector) failed to export metrics with "protocol error" and "no healthy upstream".

**Root Cause:**
The k8s-infra deployment collector had Istio sidecar enabled, but OTLP gRPC doesn't work through Istio Envoy proxy due to protocol incompatibility.

**Error Messages:**
```
"error":"rpc error: code = Unavailable desc = no healthy upstream"
"error":"rpc error: code = Unavailable desc = upstream connect error or disconnect/reset before headers. reset reason: protocol error"
```

**Solution:**
Disable Istio sidecar for ALL infrastructure telemetry collectors:

```yaml
# infra/helm/values/signoz/k8s-infra-values.yaml
otelAgent:  # DaemonSet
  podAnnotations:
    sidecar.istio.io/inject: "false"

otelDeployment:  # Deployment (cluster metrics)
  podAnnotations:
    sidecar.istio.io/inject: "false"
```

**Why This Is Acceptable:**
1. Infrastructure telemetry is internal cluster traffic
2. otel-collector → SigNoz communication is internal
3. No user-facing data traverses this path
4. The alternative (HTTP/protobuf through Istio) adds unnecessary complexity

**Rule:**
**ALL otel-collector components should disable Istio sidecar:**
- otel-agent (DaemonSet) - already disabled
- otel-deployment (Deployment) - now disabled
- signoz-otel-collector - also doesn't need sidecar for internal ingestion

**Lesson:**
Infrastructure telemetry collectors (OpenTelemetry agents, Prometheus, etc.) should skip Istio sidecar injection. They communicate internally and gRPC doesn't work through Envoy.

---

## 67. SigNoz API Key Authentication (2026-01-18)

**Issue:** Initial attempts to use SigNoz API failed, returning HTML login page.

**Root Cause:**
Was using wrong API version endpoint (`/api/v2/`) and wrong header formats.

**Correct Format:**
```bash
# This WORKS - use SIGNOZ-API-KEY header with v1 API
curl -H "SIGNOZ-API-KEY: <key>" http://localhost:3301/api/v1/dashboards

# These DON'T work:
curl -H "Authorization: Bearer <key>" ...  # Wrong header
curl ... http://localhost:3301/api/v2/...  # Wrong API version
```

**Create API Key:**
SigNoz UI → Settings → API Keys → Create

**Example - Create Dashboard via API:**
```bash
curl -X POST \
  -H "SIGNOZ-API-KEY: <key>" \
  -H "Content-Type: application/json" \
  -d @dashboard.json \
  "http://localhost:3301/api/v1/dashboards"
```

**Example - Delete Dashboard:**
```bash
curl -X DELETE \
  -H "SIGNOZ-API-KEY: <key>" \
  "http://localhost:3301/api/v1/dashboards/<dashboard-id>"
```

**Lesson:**
SigNoz API keys DO work in OSS. Use `SIGNOZ-API-KEY` header (not Authorization Bearer) with `/api/v1/` endpoints.

---

## 68. Accessing ClickHouse Credentials in SigNoz (2026-01-18)

**Issue:** Need to query ClickHouse directly but don't know credentials.

**Solution:**
Get credentials from the SigNoz pod environment variables:

```bash
# Get ClickHouse credentials
kubectl exec -n signoz signoz-0 -c signoz -- env | grep -i click

# Output includes:
# CLICKHOUSE_USER=default
# CLICKHOUSE_PASSWORD=<uuid>
# CLICKHOUSE_HOST=signoz-clickhouse
```

**Query ClickHouse Directly:**
```bash
kubectl exec -n signoz chi-signoz-clickhouse-cluster-0-0-0 -- \
  clickhouse-client --user default --password '<password>' \
  --query "SELECT DISTINCT metric_name FROM signoz_metrics.time_series_v4 WHERE metric_name LIKE 'k8s%'"
```

**Use Cases:**
- Verify what metrics are being collected
- Debug metric pipeline issues
- Check data retention

**Lesson:**
When debugging SigNoz metrics, query ClickHouse directly using credentials from the signoz-0 pod environment. Don't try to use the API.

---

## 69. SigNoz Dashboard Variable Queries with Backticks Fail (2026-01-18)

**Issue:** Dashboard variable query returned error: "Unknown expression identifier `k8s.cluster.name`"

**Problem Query:**
```sql
SELECT JSONExtractString(labels, 'k8s.cluster.name')
FROM signoz_metrics.distributed_time_series_v4_1day
WHERE metric_name = 'k8s.container.ready'
GROUP BY `k8s.cluster.name`   -- THIS FAILS
```

**Root Cause:**
ClickHouse interprets backtick-quoted identifiers as column names, not as strings. The `GROUP BY \`k8s.cluster.name\`` tries to group by a non-existent column.

**Solution:**
Use SigNoz builder query format instead of raw SQL for dashboards:

```json
{
  "query": {
    "builder": {
      "queryData": [{
        "dataSource": "metrics",
        "aggregateOperator": "count",
        "aggregateAttribute": {
          "key": "k8s.pod.phase",
          "type": "Gauge"
        },
        "groupBy": [{
          "key": "k8s.cluster.name",
          "type": "tag"
        }]
      }]
    },
    "queryType": "builder"
  }
}
```

**Better Approach:**
Avoid using variable queries with raw SQL. Use the builder format which SigNoz translates correctly.

**Lesson:**
SigNoz dashboard queries should use the builder format, not raw ClickHouse SQL. The builder handles label extraction and grouping correctly.

---

## 70. K8s Metrics from k8sclusterreceiver (2026-01-18)

**Context:** SigNoz k8s-infra Helm chart deploys an OTel collector with k8sclusterreceiver and kubeletstatsreceiver.

**Available Metric Categories:**

| Category | Metrics |
|----------|---------|
| Pod | `k8s.pod.phase`, `k8s.pod.cpu.usage`, `k8s.pod.memory.working_set` |
| Container | `k8s.container.restarts`, `k8s.container.ready`, `k8s.container.cpu_limit` |
| Node | `k8s.node.condition_ready`, `k8s.node.cpu.usage`, `k8s.node.memory.working_set` |
| Deployment | `k8s.deployment.available`, `k8s.deployment.desired` |
| StatefulSet | `k8s.statefulset.ready_pods`, `k8s.statefulset.current_pods` |
| DaemonSet | `k8s.daemonset.ready_nodes`, `k8s.daemonset.desired_scheduled_nodes` |
| Volume | `k8s.volume.available`, `k8s.volume.capacity` |

**Labels Available:**
- `k8s.cluster.name` - Cluster identifier
- `k8s.namespace.name` - Namespace
- `k8s.pod.name` - Pod name
- `k8s.node.name` - Node name
- `k8s.deployment.name` - Deployment name

**Verify Metrics Collection:**
```bash
# Check collector logs
kubectl logs -n signoz deploy/k8s-infra-otel-deployment --tail=20
# Should show: "Completed syncing shared informer caches"

# Query ClickHouse for available metrics
kubectl exec -n signoz chi-signoz-clickhouse-cluster-0-0-0 -- \
  clickhouse-client --user default --password '<password>' \
  --query "SELECT DISTINCT metric_name FROM signoz_metrics.time_series_v4 WHERE metric_name LIKE 'k8s%'"
```

**Dashboard Location:**
```
infra/helm/values/signoz/dashboards/kubernetes-cluster-metrics.json
```

**Lesson:**
K8s metrics in SigNoz come from k8sclusterreceiver (workload metrics) and kubeletstatsreceiver (node/pod resource metrics). Always verify collection is working by checking collector logs before creating dashboards.

---

## 71. SigNoz Dashboard Panel Types (2026-01-18)

**Context:** Creating custom dashboards in SigNoz via API.

**Valid Panel Types:**
| Panel Type | Use Case |
|------------|----------|
| `graph` | Time series visualization (line charts) |
| `table` | Tabular data display |
| `list` | Simple list of values |

**Invalid Panel Types:**
| Panel Type | Error |
|------------|-------|
| `pie` | "panel type is invalid: invalid panel type: pie" |
| `value` | "error in builder queries" |

**Query Format:**
SigNoz normalizes dashboard queries on save. The API accepts:
```json
{
  "aggregateOperator": "count",
  "aggregateAttribute": {"key": "k8s.pod.phase", ...}
}
```

But stores internally as:
```json
{
  "aggregations": [{
    "metricName": "k8s.pod.phase",
    "spaceAggregation": "sum",
    "timeAggregation": "count"
  }]
}
```

**Best Practice:**
When creating IaC dashboards, export the normalized version from SigNoz after first deployment:
```bash
curl -s -H "SIGNOZ-API-KEY: $API_KEY" \
  http://localhost:3301/api/v1/dashboards/$DASHBOARD_ID | \
  jq '.data.data' > dashboards/my-dashboard.json
```

**Lesson:**
Always use `graph`, `table`, or `list` panel types. Export normalized dashboard JSON after creation for IaC to ensure consistency.

---

## 72. Use Official SigNoz Dashboards Instead of Custom (2026-01-18)

**Context:** Attempted to create custom K8s dashboards for SigNoz, but queries kept failing due to incorrect aggregation settings.

**Problem:**
- Custom dashboards had incorrect query structures (missing `timeAggregation`, wrong `spaceAggregation`)
- SigNoz normalizes queries on save, but doesn't validate all combinations
- Panels with empty aggregation settings fail silently in the UI

**Solution:** Use official pre-built dashboards from https://github.com/SigNoz/dashboards

```bash
# Download official K8s dashboards
curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/k8s-infra-metrics/kubernetes-cluster-metrics.json" \
  -o infra/helm/values/signoz/dashboards/kubernetes-cluster-metrics.json

curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/k8s-infra-metrics/kubernetes-pod-metrics-overall.json" \
  -o infra/helm/values/signoz/dashboards/kubernetes-pod-metrics.json

curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/k8s-infra-metrics/kubernetes-node-metrics-overall.json" \
  -o infra/helm/values/signoz/dashboards/kubernetes-node-metrics.json
```

**Available Official K8s Dashboards:**
| Dashboard | Content |
|-----------|---------|
| `kubernetes-cluster-metrics.json` | Deployments, DaemonSets, StatefulSets, Jobs, HPAs, Pods by phase |
| `kubernetes-pod-metrics-overall.json` | CPU, Memory, Network, Restarts by pod |
| `kubernetes-node-metrics-overall.json` | CPU, Memory, Disk, Network by node |
| `kubernetes-pvc-metrics.json` | PVC capacity and usage |

**Lesson:**
Always use official SigNoz dashboards when available. Custom dashboard creation is error-prone due to undocumented query format requirements.

---

## 73. Velero Kopia Maintenance Jobs Fail with Istio and readOnlyRootFilesystem (2026-01-18)

**Context:** After cluster restart, Velero Kopia maintenance jobs showed Error status. All 16 maintenance job pods (one per backed-up namespace) were failing.

**Problem 1 - Istio Sidecar on Jobs:**
```
Events:
  Normal  Killing  3m32s  kubelet  Stopping container istio-proxy
```
Jobs with Istio sidecars don't terminate properly because the istio-proxy container keeps running after the main container completes, leaving the pod in Error state.

**Problem 2 - readOnlyRootFilesystem:**
```
Repo maintenance error: error to connect backup repo: unable to create config directory: mkdir /nonexistent: read-only file system
```
Kopia tries to write to HOME directory (`/nonexistent` for user 65534), but `readOnlyRootFilesystem: true` prevents this.

**Root Cause:**
1. `velero` namespace had `istio-injection: enabled` despite being documented as needing Istio disabled
2. Velero pods run as user 65534 whose HOME is `/nonexistent`, which isn't writable

**Solution:**

1. Disable Istio injection for velero namespace:
```yaml
# infra/helm/values/velero/namespace.yaml
metadata:
  labels:
    istio-injection: disabled  # Jobs don't work with sidecars
```

2. Set HOME to writable directory in Velero values:
```yaml
# infra/helm/values/velero/values.yaml
extraEnvVars:
  - name: HOME
    value: "/tmp"
```

3. Apply changes:
```bash
kubectl apply -f infra/helm/values/velero/namespace.yaml
helm upgrade velero vmware-tanzu/velero -n velero -f infra/helm/values/velero/values.yaml
```

**Files Changed:**
- `infra/helm/values/velero/namespace.yaml` - `istio-injection: disabled`
- `infra/helm/values/velero/values.yaml` - Added `extraEnvVars` with `HOME=/tmp`

**Lesson:**
1. Jobs (CronJobs, batch Jobs) should NEVER have Istio sidecars - the sidecar doesn't terminate when the job completes
2. When using `readOnlyRootFilesystem: true` with non-root users, ensure HOME points to a writable location (usually /tmp via emptyDir)
3. Always verify namespace labels match documentation after cluster operations

---

## 74. Helm Values Must Match Chart Structure Exactly (2026-01-18)

**Context:** Added `extraEnvVars` to Velero values.yaml to set `HOME=/tmp`, but the fix didn't take effect after `helm upgrade`.

**Problem:**
```yaml
# WRONG - extraEnvVars at top level
containerSecurityContext:
  readOnlyRootFilesystem: true

extraEnvVars:           # <-- Wrong location!
  - name: HOME
    value: "/tmp"

configuration:
  backupStorageLocation:
    ...
```

The Helm chart ignored the value because it was at the wrong YAML level.

**Root Cause:** Didn't check `helm show values <chart>` to verify the correct structure. The Velero chart expects `extraEnvVars` under `configuration:`, not at the top level.

**Solution:**
```yaml
# CORRECT - extraEnvVars under configuration
configuration:
  extraEnvVars:         # <-- Correct location
    - name: HOME
      value: "/tmp"
  backupStorageLocation:
    ...
```

**How to Verify:**
```bash
# Always check chart structure before adding new values
helm show values <chart> | grep -B 5 -A 10 "<key-name>"

# After upgrade, verify the value took effect
kubectl get deployment <name> -o jsonpath='{.spec.template.spec.containers[0].env}' | jq .
```

**Lesson:**
1. ALWAYS run `helm show values <chart>` to verify correct YAML structure before adding new keys
2. After `helm upgrade`, verify changes took effect by inspecting the deployed resources
3. Helm silently ignores values at wrong YAML levels - no error is thrown

---

## 75. DaemonSet Pods Orphaned on Terminated Nodes (2026-01-18)

**Context:** After cluster restart, DaemonSet pods showed Pending status forever. DaemonSets reported DESIRED=4 but only 3 nodes existed.

**Problem:**
```
NAMESPACE     NAME       DESIRED   CURRENT   READY
kube-system   aws-node   4         4         3      # 4 desired but only 3 nodes!

kubectl get pods -A | grep Pending
kube-system   aws-node-lb2wg     0/2   Pending   # Stuck forever
```

**Root Cause:** When EKS nodes terminate during scale-down, pods already scheduled to those nodes can get orphaned. The pod remains in Pending state, assigned to a node that no longer exists or is NotReady. Kubernetes doesn't automatically clean these up.

**Timeline:**
1. Shutdown scales nodes to 0
2. New startup scales nodes to 3
3. Old node objects briefly exist alongside new nodes (SchedulingDisabled)
4. DaemonSet controllers schedule pods to old nodes (still in node list)
5. Old nodes transition: Ready,SchedulingDisabled → NotReady,SchedulingDisabled → removed
6. During overlap period, DaemonSet controllers keep recreating pods on old nodes
7. Pods remain Pending, assigned to non-existent/NotReady nodes

**Solution:** Post-startup cleanup script that deletes pods scheduled to non-Ready nodes.

```bash
# scripts/cleanup-orphaned-pods.sh
# Only consider nodes that are Ready (exclude NotReady, SchedulingDisabled)
READY_NODES=$(kubectl get nodes --no-headers | grep " Ready " | grep -v "NotReady" | grep -v "SchedulingDisabled" | awk '{print $1}')

kubectl get pods -A --field-selector=status.phase=Pending --no-headers | while read line; do
    NAMESPACE=$(echo "$line" | awk '{print $1}')
    POD=$(echo "$line" | awk '{print $2}')
    NODE=$(kubectl get pod -n "$NAMESPACE" "$POD" -o jsonpath='{.spec.nodeName}')

    if [ -n "$NODE" ] && ! echo "$READY_NODES" | grep -q "^${NODE}$"; then
        kubectl delete pod -n "$NAMESPACE" "$POD" --force --grace-period=0
    fi
done

# Also clean up failed Velero Kopia jobs
kubectl get pods -n velero --no-headers | grep -E "kopia.*Error" | awk '{print $1}' | xargs -r kubectl delete pod -n velero
```

**Usage:**
```bash
./scripts/startup.sh                # Start cluster (waits for bastion + SSM)
./scripts/tunnel.sh                 # Connect to cluster
./scripts/cleanup-orphaned-pods.sh  # Clean up orphaned pods (may need to run multiple times)
```

**Important:** During the ~2-3 minute overlap period while old nodes terminate, DaemonSet controllers keep recreating pods on the terminating nodes. You may need to run cleanup-orphaned-pods.sh multiple times until old nodes are fully removed.

**Alternative Solutions (not implemented):**
- **AWS Node Termination Handler (NTH)** - production best practice, handles graceful draining
- **Wait for 0 nodes before startup** - modify startup.sh to wait until old nodes fully terminate before scaling up new ones (eliminates overlap period)
- **Karpenter** - better node lifecycle management

**Files:**
- `scripts/startup.sh` - Starts bastion, waits for SSM, scales nodes
- `scripts/shutdown.sh` - Scales nodes to 0, stops bastion
- `scripts/cleanup-orphaned-pods.sh` - Deletes orphaned pods on NotReady/terminated nodes

**Lesson:**
1. EKS node termination can orphan scheduled pods
2. DaemonSet controllers recreate pods on terminating nodes during overlap period
3. Cleanup script must check for NotReady nodes, not just non-existent ones
4. Always run cleanup script after cluster restart
5. For production, implement AWS Node Termination Handler or wait for 0 nodes

---

## 76. Bastion Start Command Silently Fails with || true (2026-01-18)

**Context:** After running startup.sh, the bastion was still stopped. The script reported success but the bastion never started.

**Problem:**
```bash
# Original startup.sh - WRONG
aws ec2 start-instances --instance-ids $BASTION_ID --region $REGION > /dev/null 2>&1 || true
```

The `> /dev/null 2>&1 || true` suppresses all output AND errors. If the start-instances command fails for any reason, the script continues silently.

**Root Cause:** Defensive coding that went too far. The `|| true` was added to handle the case where bastion is already running (which returns an error), but it also hides real failures.

**Solution:** Properly check bastion state and wait for it:
```bash
# Fixed startup.sh - CORRECT
BASTION_STATE=$(aws ec2 describe-instances --instance-ids $BASTION_ID --region $REGION --query 'Reservations[0].Instances[0].State.Name' --output text)
if [ "$BASTION_STATE" = "stopped" ]; then
    aws ec2 start-instances --instance-ids $BASTION_ID --region $REGION > /dev/null
    aws ec2 wait instance-running --instance-ids $BASTION_ID --region $REGION
elif [ "$BASTION_STATE" = "running" ]; then
    echo "Bastion already running."
fi

# Also wait for SSM agent
for i in {1..30}; do
    SSM_STATUS=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$BASTION_ID" --query 'InstanceInformationList[0].PingStatus' --output text)
    if [ "$SSM_STATUS" = "Online" ]; then break; fi
    sleep 5
done
```

**Lesson:**
1. Never use `|| true` to hide errors from critical operations
2. Check preconditions explicitly instead of suppressing errors
3. Use `aws ec2 wait` commands to ensure state transitions complete
4. SSM agent takes additional time after instance is "running" - must wait for it separately
