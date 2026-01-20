# Infra-Agent Knowledge Base

This document contains known limitations, best practices, and common patterns that agents should be aware of when analyzing, planning, or implementing infrastructure changes.

---

## 1. CloudFormation Known Limitations

### 1.1 EC2 MetadataOptions Drift False Positive

**Problem**: CloudFormation drift detection incorrectly reports `MetadataOptions` as drifted even when the deployed instance matches the template.

**Root Cause**: AWS EC2 API returns MetadataOptions in a different format than CloudFormation expects during drift comparison.

**Solution**: Use `AWS::EC2::LaunchTemplate` instead of inline MetadataOptions:

```yaml
# BEFORE - causes false positive drift
BastionHost:
  Type: AWS::EC2::Instance
  Properties:
    MetadataOptions:
      HttpTokens: required  # Will show as "drifted"

# AFTER - no drift false positive
BastionLaunchTemplate:
  Type: AWS::EC2::LaunchTemplate
  Properties:
    LaunchTemplateData:
      MetadataOptions:
        HttpTokens: required

BastionHost:
  Type: AWS::EC2::Instance
  Properties:
    LaunchTemplate:
      LaunchTemplateId: !Ref BastionLaunchTemplate
      Version: !GetAtt BastionLaunchTemplate.LatestVersionNumber
```

**Agents Affected**: Review Agent, Audit Agent (drift detection)

---

### 1.2 EKS Managed Node Group Drift

**Problem**: EKS managed node groups show drift for `ScalingConfig` when actual node count differs from CloudFormation desired count.

**This is NOT a bug** - it's expected behavior when:
- Cluster Autoscaler scales nodes up/down
- Manual scaling for cost savings (shutdown/startup)

**Solution**:
- CloudFormation defines the **baseline** (min/max/desired)
- Actual scaling may differ based on operational needs
- Only flag as issue if min/max boundaries are violated

**Agents Affected**: Audit Agent (drift detection)

---

### 1.3 Security Group Self-Reference

**Problem**: Security groups that reference themselves (for intra-group communication) can't be created in a single CloudFormation operation.

**Solution**: Use `AWS::EC2::SecurityGroupIngress` as a separate resource:

```yaml
NodeSecurityGroup:
  Type: AWS::EC2::SecurityGroup
  Properties:
    GroupDescription: EKS node security group

# Separate resource for self-reference
NodeSecurityGroupIngress:
  Type: AWS::EC2::SecurityGroupIngress
  Properties:
    GroupId: !Ref NodeSecurityGroup
    SourceSecurityGroupId: !Ref NodeSecurityGroup
    IpProtocol: -1
```

**Agents Affected**: IaC Agent, Planning Agent

---

### 1.4 SSM Parameter Dynamic References

**Problem**: CloudFormation `{{resolve:ssm:...}}` dynamic references are resolved at deploy time, not stack creation. Drift detection can't track them.

**Example**: AMI IDs via SSM parameters always show as "different" in drift:
```yaml
ImageId: '{{resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64}}'
```

**This is expected** - the AMI ID changes as AWS releases updates.

**Agents Affected**: Audit Agent (ignore AMI drift for SSM-referenced AMIs)

---

### 1.5 CloudFormation Nested Stack Drift

**Problem**: Drift detection on parent stacks doesn't automatically check nested stacks.

**Solution**: Must run drift detection on each nested stack individually.

**Agents Affected**: Audit Agent

---

## 2. EKS Known Limitations

### 2.1 Private Endpoint Only - No Direct kubectl

**Problem**: EKS clusters with private-only endpoint require bastion/VPN for kubectl access.

**Solution**: Use SSM Session Manager with port forwarding:
```bash
# Tunnel through bastion
aws ssm start-session --target <bastion-id> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<eks-endpoint>"],"portNumber":["443"],"localPortNumber":["6443"]}'
```

**Agents Affected**: All agents needing K8s access, Investigation Agent

---

### 2.2 EKS OIDC Provider URL Format

**Problem**: EKS OIDC provider URL includes `https://` but IAM OIDC provider ARN doesn't.

**Correct pattern**:
```yaml
# EKS returns: https://oidc.eks.us-east-1.amazonaws.com/id/XXXXX
# IAM expects: oidc.eks.us-east-1.amazonaws.com/id/XXXXX (no https://)

OIDCProviderArn: !Sub 'arn:aws:iam::${AWS::AccountId}:oidc-provider/${OIDCProviderURL}'
# Where OIDCProviderURL has https:// stripped
```

**Agents Affected**: IaC Agent (IRSA configurations)

---

### 2.3 EKS Add-on Version Compatibility

**Problem**: EKS add-ons (VPC CNI, CoreDNS, kube-proxy) must match Kubernetes version.

**Solution**: Always check compatibility before upgrading:
```bash
aws eks describe-addon-versions --kubernetes-version 1.31 --addon-name vpc-cni
```

**Agents Affected**: Planning Agent, IaC Agent

---

### 2.4 aws-auth ConfigMap vs EKS Access Entries

**Problem**: EKS has two auth methods - legacy `aws-auth` ConfigMap and newer Access Entries API. Mixing them causes confusion.

**Best Practice**: Use Access Entries API (EKS 1.23+) for new clusters:
```yaml
# CloudFormation
AWS::EKS::AccessEntry
AWS::EKS::AccessPolicy
```

**Agents Affected**: IaC Agent, Audit Agent

---

## 3. Kubernetes/Helm Known Issues

### 3.1 StatefulSet PV AZ Binding

**CRITICAL**: EBS volumes are AZ-bound. StatefulSet PVs can only attach to nodes in the same AZ.

**Problem**: If a StatefulSet's PV is in us-east-1a but no nodes exist in us-east-1a, pods stay Pending forever.

**Solution**:
- Always run minimum 3 nodes for multi-AZ coverage
- Use `topologySpreadConstraints` to distribute StatefulSets across AZs
- Never force-delete StatefulSet pods (triggers operator cleanup)

**Agents Affected**: Planning Agent, Investigation Agent, Deploy Agent

---

### 3.2 Istio Sidecar + Jobs/CronJobs

**Problem**: Jobs with Istio sidecars never complete because istio-proxy keeps running after main container exits.

**Solution**: Disable Istio injection for namespaces with Jobs:
```yaml
metadata:
  labels:
    istio-injection: disabled
```

Or per-pod:
```yaml
annotations:
  sidecar.istio.io/inject: "false"
```

**Namespaces that need this**: velero, trivy-system, any batch job namespace

**Agents Affected**: IaC Agent, Review Agent

---

### 3.3 Istio Init Container Name Conflict

**Problem**: Some applications (Trivy) create init containers named `istio-init`, conflicting with Istio's auto-injected container.

**Error**: `Duplicate value: "istio-init"`

**Solution**: Disable Istio for that namespace.

**Agents Affected**: Investigation Agent, Review Agent

---

### 3.4 OTLP GRPC Through Istio Envoy

**Problem**: OTLP trace export via GRPC (port 4317) fails through Istio Envoy with "protocol error".

**Solution**: Use HTTP/protobuf (port 4318) instead:
```yaml
env:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://collector.namespace.svc:4318"
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: "http/protobuf"
```

**Agents Affected**: IaC Agent (OpenTelemetry configurations)

---

### 3.5 Helm Upgrade vs Install

**Problem**: `helm upgrade --install` can fail if CRDs changed or resources were manually modified.

**Common errors**:
- `cannot patch "X" with kind Y: field is immutable`
- `resource X already exists`

**Solutions**:
- For CRD changes: Delete and recreate CRDs manually
- For immutable fields: Delete resource, let Helm recreate
- For existing resources: Use `--force` carefully

**Agents Affected**: Deploy Agent, IaC Agent

---

### 3.6 readOnlyRootFilesystem + Non-Root Users

**Problem**: Containers with `readOnlyRootFilesystem: true` and non-root users (65534/nobody) fail because HOME=/nonexistent is read-only.

**Error**: `mkdir /nonexistent: read-only file system`

**Solution**: Set HOME to writable directory:
```yaml
env:
  - name: HOME
    value: "/tmp"
```

**Agents Affected**: Review Agent (security validation), IaC Agent

---

## 4. AWS Service Limits & Quotas

### 4.1 Common Limits to Check

| Service | Limit | Default | Check Command |
|---------|-------|---------|---------------|
| VPC | VPCs per region | 5 | `aws service-quotas get-service-quota --service-code vpc --quota-code L-F678F1CE` |
| EKS | Clusters per region | 100 | `aws service-quotas get-service-quota --service-code eks --quota-code L-1194D53C` |
| EC2 | On-demand instances | Varies | `aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A` |
| EBS | Snapshots per region | 100,000 | `aws service-quotas get-service-quota --service-code ebs --quota-code L-309BACF6` |
| IAM | Roles per account | 1,000 | `aws service-quotas get-service-quota --service-code iam --quota-code L-FE177D64` |

**Agents Affected**: Planning Agent (capacity planning), Audit Agent

---

### 4.2 EKS-Specific Limits

| Resource | Limit |
|----------|-------|
| Nodes per cluster | 450 (managed), 500 (self-managed) |
| Pods per node | 110 (default), varies by instance type |
| Services per cluster | 10,000 |
| ConfigMaps per namespace | 1,000 |

**Agents Affected**: Planning Agent, Investigation Agent

---

## 5. Cost Optimization Patterns

### 5.1 Spot Instances for Non-Critical Workloads

**Pattern**: Use Spot instances for dev/test, batch jobs, stateless workloads.

**CloudFormation**:
```yaml
CapacityType: SPOT
InstanceTypes:
  - t3a.medium
  - t3.medium  # Fallback
```

**Risk**: Spot interruption (2-minute warning)

**Agents Affected**: Planning Agent (cost estimates)

---

### 5.2 GP3 vs GP2 EBS Volumes

**Always use GP3** - same price, better performance:
```yaml
VolumeType: gp3
Iops: 3000      # Free baseline
Throughput: 125  # Free baseline
```

**Agents Affected**: IaC Agent, Review Agent

---

### 5.3 NAT Gateway Costs

**Problem**: NAT Gateway costs $0.045/hour + $0.045/GB processed.

**Solutions**:
- Use VPC endpoints for AWS services (S3, ECR, etc.)
- Consider NAT instances for dev environments
- Use private subnets only for resources that need them

**Agents Affected**: Planning Agent, Audit Agent (cost analysis)

---

## 6. Security Best Practices

### 6.1 IMDSv2 Enforcement

**ALWAYS enforce IMDSv2** on EC2 instances:
```yaml
MetadataOptions:
  HttpTokens: required
  HttpPutResponseHopLimit: 1
  HttpEndpoint: enabled
```

**Agents Affected**: Review Agent (security validation)

---

### 6.2 Encryption at Rest

**All storage must be encrypted**:
- EBS: `Encrypted: true`
- S3: `BucketEncryption` with SSE-S3 or SSE-KMS
- RDS: `StorageEncrypted: true`
- EFS: `Encrypted: true`

**Agents Affected**: Review Agent, Audit Agent

---

### 6.3 Security Group Rules

**Never allow 0.0.0.0/0 inbound** except:
- ALB/NLB for public endpoints (ports 80, 443 only)
- Bastion (should use SSM, no SSH)

**Pattern for internal services**:
```yaml
SecurityGroupIngress:
  - IpProtocol: tcp
    FromPort: 443
    ToPort: 443
    SourceSecurityGroupId: !Ref AllowedSecurityGroup  # Not 0.0.0.0/0
```

**Agents Affected**: Review Agent, Audit Agent

---

## 7. Troubleshooting Patterns

### 7.1 Pod Stuck in Pending

**Check order**:
1. `kubectl describe pod` - look at Events
2. Check node resources: `kubectl describe nodes | grep -A 5 "Allocated resources"`
3. Check PVC binding: `kubectl get pvc`
4. Check node selectors/affinity
5. Check taints/tolerations

**Common causes**:
- Insufficient CPU/memory
- PV in different AZ than nodes
- Missing node selector label
- Taint without toleration

**Agents Affected**: Investigation Agent

---

### 7.2 Pod Stuck in CrashLoopBackOff

**Check order**:
1. `kubectl logs <pod> --previous` - see crash logs
2. `kubectl describe pod` - check Events, exit codes
3. Check readiness/liveness probes
4. Check resource limits (OOMKilled = exit code 137)

**Common causes**:
- Application error (check logs)
- OOMKilled (increase memory limit)
- Failed health check (fix probe or app)
- Missing ConfigMap/Secret

**Agents Affected**: Investigation Agent

---

### 7.3 Service Not Reachable

**Check order**:
1. `kubectl get endpoints <service>` - should list pod IPs
2. `kubectl get pods -l <selector>` - pods must be Running
3. Check NetworkPolicies: `kubectl get networkpolicy`
4. Check Istio: `istioctl analyze -n <namespace>`

**Agents Affected**: Investigation Agent

---

## 8. LLM Behavior Known Issues

### 8.1 Hallucinated Deployment Outputs (CRITICAL)

**Problem**: LLMs can generate convincing but completely fake deployment outputs, including fabricated resource IDs, command outputs, and success messages.

**Example hallucinated output**:
```
✅ CloudFormation Stack: my-stack
   └─ Status: UPDATE_COMPLETE
   └─ New Instance: i-0abc123def456789  ← FAKE ID
```

**Why this happens**:
- LLMs are trained to be helpful and generate plausible outputs
- Beautiful formatting makes fake outputs look legitimate
- Resource ID patterns (i-0xxx, lt-0xxx) are easy to fabricate

**Solution** (implemented in infra-agent):
1. **Layer 1**: System prompts with anti-hallucination rules
2. **Layer 2**: Runtime detection of fake patterns
3. **Layer 3**: Mandatory verification via AWS/K8s APIs after deployment
4. **Layer 4**: Artifact persistence for audit trail

**Agents MUST**:
- NEVER claim deployment success without verification
- ALWAYS call `_verify_cloudformation_deployment()` or `_verify_helm_deployment()`
- Use `PROPOSED:` prefix for planned actions, `VERIFIED:` only after API confirmation

**See**: `lessons-learned.md` for the 2026-01-19 incident details

**Agents Affected**: ALL agents, especially Deploy/Validate Agent

---

## 9. NIST 800-53 Quick Reference

### Control Mappings for Common Resources

| Resource | NIST Controls |
|----------|---------------|
| VPC/Subnets | SC-7 (Boundary Protection) |
| Security Groups | AC-4 (Information Flow), SC-7 |
| IAM Roles | AC-2 (Account Management), AC-6 (Least Privilege) |
| Encryption | SC-13 (Cryptographic Protection), SC-28 (Data at Rest) |
| Logging | AU-2 (Audit Events), AU-3 (Audit Content) |
| Bastion | AC-17 (Remote Access), SC-7 |
| EKS OIDC | IA-2 (Identification), IA-8 (Non-Org Users) |

**Agents Affected**: Planning Agent (NIST mapping), Review Agent, Audit Agent

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-19 | AI Agent | Initial knowledge base |
| 1.1 | 2026-01-19 | AI Agent | Added LLM Hallucinated Deployment Outputs section |
