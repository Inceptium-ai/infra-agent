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
