# Infra-Agent Project Context

This is an AI-powered Infrastructure Agent for managing AWS EKS clusters with NIST 800-53 Rev 5 compliance.

## Quick Reference

| Document | Purpose |
|----------|---------|
| `docs/architecture.md` | System architecture, components, NIST controls |
| `docs/access-urls.md` | **All access URLs and instructions** |
| `docs/dev-vs-prod-decisions.md` | Infrastructure comparison (Dev vs Prod vs AWS) |
| `docs/gitlab.md` | GitLab deployment documentation |

## EKS Cluster Access (CRITICAL)

The EKS cluster has a **private endpoint only**. You MUST use the SSM tunnel to access kubectl.

### Step 1: Start SSM Tunnel (keep running)
```bash
/Users/ymuwakki/infra-agent/scripts/tunnel.sh
```

### Step 2: Configure kubectl (one-time after tunnel starts)
```bash
aws eks update-kubeconfig --name infra-agent-dev-cluster --region us-east-1
sed -i.bak 's|https://C13DEB3971BF51477027AF0BEF0B1D0D.yl4.us-east-1.eks.amazonaws.com|https://localhost:6443|' ~/.kube/config
kubectl config set-cluster arn:aws:eks:us-east-1:340752837296:cluster/infra-agent-dev-cluster --insecure-skip-tls-verify=true
```

### Step 3: Port Forward Observability Services
```bash
# Grafana (dashboards) - http://localhost:3000
kubectl port-forward svc/grafana 3000:3000 -n observability &

# Loki (logs) - http://localhost:3100
kubectl port-forward svc/loki-gateway 3100:3100 -n observability &

# Tempo (traces) - http://localhost:3200
kubectl port-forward svc/tempo 3200:3200 -n observability &

# Prometheus (metrics) - http://localhost:9090
kubectl port-forward svc/prometheus-server 9090:80 -n observability &

# Kiali (traffic) - http://localhost:20001
kubectl port-forward svc/kiali 20001:20001 -n istio-system &

# Headlamp (K8s admin) - http://localhost:8080
kubectl port-forward svc/headlamp 8080:80 -n headlamp &

# Kubecost (costs) - http://localhost:9091
kubectl port-forward svc/kubecost-cost-analyzer 9091:9090 -n kubecost &
```

Or use the services script:
```bash
/Users/ymuwakki/infra-agent/scripts/services.sh
```

## Observability Endpoints

### Internet Access (ALB + Cognito)

| Service | URL | Auth | Notes |
|---------|-----|------|-------|
| SigNoz | https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/ | ALB Cognito | Unified observability |
| Headlamp | https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/headlamp/ | OIDC → EKS OIDC | Per-user K8s audit |
| Kubecost | https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/kubecost/ | ALB Cognito | Cost management |

**Note:** DEV uses self-signed cert - accept browser warning.

### Authentication Architecture (2026-01-15)

| Service | Auth Method | Per-User Audit |
|---------|-------------|----------------|
| SigNoz | ALB Cognito | No (shared) |
| Headlamp | OIDC → EKS OIDC | **Yes** (K8s audit logs) |
| Kubecost | ALB Cognito | No (shared) |

**Headlamp EKS OIDC:** Users authenticate via Cognito, token used for K8s API access. User identity (`cognito:email`) appears in K8s audit logs.

### Local Access (port-forward, after SSM tunnel)

| Service | URL | Purpose |
|---------|-----|---------|
| SigNoz | http://localhost:3301 | Metrics, logs, traces, dashboards |
| Headlamp | http://localhost:8080 | Kubernetes admin console |
| Kubecost | http://localhost:9091 | Cost analysis |

## Chrome Bookmarks (Genesis/Infra folder)

User has bookmarks organized under **Bookmarks Bar → Genesis → Infra**:

| Folder | Bookmarks |
|--------|-----------|
| **Observability** | Grafana (3000), Kiali (20001), Prometheus (9090) |
| **Operations** | Headlamp (8080), Kubecost (9091) |
| **AWS Console** | EKS, CloudFormation, VPC, RDS, CloudWatch, S3 |
| **Documentation** | GitHub, Loki/Mimir/Kiali/Istio/Kubecost/Velero/Trivy docs |

**Missing bookmarks to add:**
- Loki (Logs): `http://localhost:3100`
- Tempo (Traces): `http://localhost:3200`

## Key AWS Resources

| Resource | ID/Name |
|----------|---------|
| EKS Cluster | `infra-agent-dev-cluster` |
| Bastion Instance | `i-02c424847cd5f557e` |
| Node Group | `infra-agent-dev-general-nodes` |
| Region | `us-east-1` |

## Compute Management

### Shutdown all compute (save costs)
```bash
# Scale nodes to 0
aws eks update-nodegroup-config \
  --cluster-name infra-agent-dev-cluster \
  --nodegroup-name infra-agent-dev-general-nodes \
  --scaling-config minSize=0,maxSize=3,desiredSize=0 \
  --region us-east-1

# Stop bastion
aws ec2 stop-instances --instance-ids i-02c424847cd5f557e --region us-east-1
```

### Start compute
```bash
# Scale nodes back up
aws eks update-nodegroup-config \
  --cluster-name infra-agent-dev-cluster \
  --nodegroup-name infra-agent-dev-general-nodes \
  --scaling-config minSize=1,maxSize=3,desiredSize=2 \
  --region us-east-1

# Start bastion
aws ec2 start-instances --instance-ids i-02c424847cd5f557e --region us-east-1
```

## IaC Source of Truth

All infrastructure changes MUST be tracked in IaC:
- CloudFormation templates: `infra/cloudformation/stacks/`
- Helm values: `infra/helm/values/`
- cfn-guard rules: `infra/cloudformation/cfn-guard-rules/`

## Namespaces

| Namespace | Purpose |
|-----------|---------|
| `signoz` | SigNoz unified observability (metrics, logs, traces) |
| `istio-system` | Istio service mesh |
| `headlamp` | Kubernetes admin console |
| `kubecost` | Cost analysis |
| `velero` | Backup/restore |
| `trivy-system` | Security scanning |

## Lessons Learned

### Istio Sidecar Injection (2026-01-11)
**Issue:** Observability add-ons (Grafana, Loki, Prometheus, etc.) were deployed WITHOUT Istio sidecar injection, creating a NIST SC-8 compliance gap (no mTLS between services).

**Root Cause:** Namespaces were not labeled with `istio-injection=enabled` before deploying Helm charts.

**Impact:**
- 53 pods running without mTLS encryption
- Traffic between observability services is plaintext
- NIST SC-8 (Transmission Confidentiality) not fully satisfied

**Resource Constraint:** Enabling sidecars on all 53 pods would require ~5.3 vCPU additional - cluster only has ~1.8 vCPU free.

**Decision:** Enable Istio only on critical user-facing services (Grafana, Headlamp) for partial compliance without adding nodes.

**Prevention:**
- Always label namespaces with `istio-injection=enabled` BEFORE deploying workloads
- Include sidecar annotations in all Helm values files
- Audit existing deployments for sidecar presence after mesh installation

### SSM Tunnel Timeout
- Default idle timeout: 20 minutes
- Max session duration: 60 minutes (configurable to 24 hours in SSM preferences)

### SigNoz Migration (2026-01-14/15)
**Change:** Replaced LGTM stack (Grafana, Loki, Tempo, Mimir, Prometheus) with SigNoz for unified observability.

**Benefits:**
- Single UI for metrics, logs, and traces
- Reduced complexity (1 tool vs 5)
- Lower resource footprint
- Native OpenTelemetry support

**Removed:**
- Grafana, Loki, Tempo, Mimir, Prometheus
- Kiali (SigNoz can show service maps via traces)

### EKS OIDC with Cognito (2026-01-15)
**Purpose:** Enable per-user Kubernetes API authentication for Headlamp.

**Architecture:**
1. User accesses Headlamp → redirected to Cognito
2. After login, Headlamp gets OIDC token
3. Token used for K8s API via EKS OIDC identity provider
4. K8s audit logs show `cognito:user@email.com`

**IaC Files:**
- `infra/cloudformation/stacks/02-eks/eks-oidc-cognito.yaml` - EKS OIDC provider
- `infra/cloudformation/stacks/01-networking/cognito-auth.yaml` - Cognito groups
- `infra/helm/values/rbac-cognito.yaml` - K8s RBAC for Cognito users

**Cognito Groups → K8s Roles:**
| Cognito Group | K8s ClusterRole |
|---------------|-----------------|
| platform-admins | cluster-admin |
| developers | view |

### ALB Path-Based Routing (2026-01-15)
**Pattern:** Single ALB routes to multiple services via path patterns.

| Path | Service | NodePort |
|------|---------|----------|
| `/` (default) | SigNoz | 30301 |
| `/headlamp/*` | Headlamp | 30446 |
| `/kubecost/*` | Kubecost nginx | 30091 |

**Trailing Slash:** Apps like Headlamp require trailing slash. ALB rules redirect `/headlamp` → `/headlamp/`.

**Kubecost nginx Proxy:** Kubecost doesn't support subpath routing natively. nginx proxy rewrites `/kubecost/*` → `/*`.

### Kubecost OIDC Limitation (2026-01-15)
**Issue:** Kubecost OIDC requires specific environment variable format, not just secret reference.

**Workaround:** Use ALB Cognito auth (no per-user audit in Kubecost).

**TODO:** Configure Kubecost OIDC with correct environment variable mappings for per-user audit.

## NEVER do these

- NEVER enable public endpoint on EKS cluster
- NEVER commit secrets to git
- NEVER bypass cfn-guard compliance checks
- NEVER make infrastructure changes outside of IaC
- NEVER deploy workloads to namespaces without checking istio-injection label
- **NEVER use kubectl patch/apply/edit to modify deployed resources directly** - ALWAYS update the source Helm values or CloudFormation templates first, then redeploy

## CRITICAL: IaC is the Source of Truth

**ALL infrastructure and Kubernetes changes MUST go through IaC:**

| Change Type | Source of Truth | Deploy Command |
|-------------|-----------------|----------------|
| AWS Resources | CloudFormation templates | `aws cloudformation deploy` |
| Kubernetes Workloads | Helm values files | `helm upgrade` |
| EKS Config | CloudFormation (cluster.yaml) | `aws cloudformation deploy` |
| IAM Roles/Policies | CloudFormation | `aws cloudformation deploy` |
| S3/RDS/VPC | CloudFormation | `aws cloudformation deploy` |

**NEVER make changes using:**
- `kubectl patch`, `kubectl edit`, `kubectl apply -f`, `kubectl label`
- `aws cli` commands that modify resources (e.g., `aws eks update-*`, `aws ec2 modify-*`)
- `boto3` scripts that create/modify/delete resources
- AWS Console clicks

**Why:**
- Direct changes create configuration drift
- Drift is undetectable and non-reproducible
- Violates NIST CM-3 (Configuration Change Control)
- Next IaC deployment will overwrite/conflict with manual changes
- Cannot rollback or audit changes

**Correct workflow:**
1. Edit the source file in `infra/cloudformation/` or `infra/helm/values/`
2. **Validate CloudFormation with cfn-lint and cfn-guard BEFORE deployment**
3. Commit to Git
4. Deploy via CloudFormation or Helm
5. Verify the change

## IaC Validation (REQUIRED)

**ALL CloudFormation templates MUST pass validation before deployment:**

```bash
# Activate virtual environment
source /Users/ymuwakki/infra-agent/.venv/bin/activate

# Run cfn-lint (syntax and best practices)
cfn-lint infra/cloudformation/stacks/**/*.yaml

# Run cfn-guard (NIST compliance rules)
cfn-guard validate \
  -d infra/cloudformation/stacks/ \
  -r infra/cloudformation/cfn-guard-rules/nist-800-53/

# Both must pass with no errors before deployment
```

**NEVER deploy CloudFormation without validation:**
- cfn-lint catches syntax errors, deprecated features, and AWS best practices
- cfn-guard enforces NIST 800-53 compliance rules
- Skipping validation can introduce security vulnerabilities and compliance gaps

**Wrong workflow:**
```bash
# DON'T DO THIS - creates drift

# Kubernetes drift:
kubectl patch deployment grafana -n observability -p '{"spec":...}'
kubectl label namespace headlamp istio-injection=enabled
kubectl apply -f my-quick-fix.yaml

# AWS drift:
aws eks update-cluster-config --name cluster --resources-vpc-config ...
aws ec2 modify-instance-attribute --instance-id i-xxx ...
aws iam attach-role-policy --role-name xxx --policy-arn ...

# boto3 drift:
ec2.modify_instance_attribute(...)
eks.update_nodegroup_config(...)
```

**Exception:** Read-only commands are OK (e.g., `kubectl get`, `aws describe-*`, `aws list-*`)
