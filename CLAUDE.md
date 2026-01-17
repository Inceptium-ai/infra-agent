# Infra-Agent Project Context

## PRINCIPLE #1: IaC IS THE ABSOLUTE SOURCE OF TRUTH

**NEVER modify infrastructure or Kubernetes resources directly. ALL changes MUST go through IaC first.**

This includes:
- **AWS Resources**: CloudFormation templates ONLY (not `aws` CLI commands that modify state)
- **Kubernetes Resources**: Helm values files ONLY (not `kubectl apply/patch/edit/create`)
- **Node Scaling**: CloudFormation node group config (not `aws eks update-nodegroup-config`)
- **ANY Resource**: If it exists in the cluster or AWS, it MUST be managed by IaC

**Correct workflow:**
1. Edit IaC file (`infra/cloudformation/` or `infra/helm/values/`)
2. Validate with cfn-lint and cfn-guard
3. Commit to Git
4. Deploy via `aws cloudformation deploy` or `helm upgrade`

**Read-only commands are OK:** `kubectl get`, `aws describe-*`, `aws list-*`

**Exception - Operational Scaling:** Node group scaling (`aws eks update-nodegroup-config --scaling-config`) is permitted for operational flexibility. CloudFormation defines the baseline; actual scaling may differ based on load.

---

## PRINCIPLE #2: ALWAYS USE MINIMUM 3 NODES

**When starting the cluster, ALWAYS scale to minimum 3 nodes for multi-AZ coverage.**

**Why:**
- EBS volumes are AZ-bound - PVs can ONLY attach to nodes in the same AZ
- With fewer than 3 nodes, StatefulSets may fail if their PV's AZ has no node
- This caused complete data loss in the StatefulSet PV AZ-Binding Incident (2026-01-15)

**ALWAYS use the graceful startup script:**
```bash
/Users/ymuwakki/infra-agent/scripts/graceful-startup.sh
```

**The script enforces minimum 3 nodes:**
```bash
if [ "$NODE_COUNT" -lt 3 ]; then
    log_warn "Requested $NODE_COUNT nodes, but minimum 3 required for multi-AZ. Using 3."
    NODE_COUNT=3
fi
```

**NEVER manually scale to fewer than 3 nodes:**
```bash
# DON'T DO THIS
aws eks update-nodegroup-config ... --scaling-config desiredSize=1  # WRONG
aws eks update-nodegroup-config ... --scaling-config desiredSize=2  # WRONG

# DO THIS INSTEAD
/Users/ymuwakki/infra-agent/scripts/graceful-startup.sh  # Enforces min 3
```

---

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

### Step 3: Port Forward Services (optional, for local access)
```bash
# SigNoz (observability) - http://localhost:3301
kubectl port-forward svc/signoz-frontend 3301:3301 -n signoz &

# Headlamp (K8s admin) - http://localhost:8080
kubectl port-forward svc/headlamp 8080:80 -n headlamp &

# Kubecost (costs) - http://localhost:9091
kubectl port-forward svc/kubecost-cost-analyzer 9091:9090 -n kubecost &
```

## Observability Endpoints

### Internet Access (ALB + Cognito)

| Service | URL | Auth | Notes |
|---------|-----|------|-------|
| SigNoz | https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/ | ALB Cognito | Unified observability |
| Headlamp | https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/headlamp/ | OIDC → EKS OIDC | Per-user K8s audit |
| Kubecost | https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/kubecost/ | ALB Cognito | Cost management |
| Kiali | https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/kiali/ | ALB Cognito | Istio traffic visualization |

**Note:** DEV uses self-signed cert - accept browser warning.

### Authentication Architecture (2026-01-17)

| Service | Auth Method | Per-User Audit |
|---------|-------------|----------------|
| SigNoz | ALB Cognito | No (shared) |
| Headlamp | OIDC → EKS OIDC | **Yes** (K8s audit logs) |
| Kubecost | ALB Cognito | No (shared) |
| Kiali | ALB Cognito | No (shared) |

**Headlamp EKS OIDC:** Users authenticate via Cognito, token used for K8s API access. User identity (`cognito:email`) appears in K8s audit logs.

### Local Access (port-forward, after SSM tunnel)

| Service | URL | Purpose |
|---------|-----|---------|
| SigNoz | http://localhost:3301 | Metrics, logs, traces, dashboards |
| Headlamp | http://localhost:8080 | Kubernetes admin console |
| Kubecost | http://localhost:9091 | Cost analysis |
| Kiali | http://localhost:20001/kiali | Istio traffic visualization |

```bash
# Kiali port-forward
kubectl port-forward svc/kiali 20001:20001 -n istio-system &
```

## Chrome Bookmarks (Genesis/Infra folder)

User has bookmarks organized under **Bookmarks Bar → Genesis → Infra**:

| Folder | Bookmarks |
|--------|-----------|
| **Observability** | SigNoz ALB, SigNoz Local (3301) |
| **Operations** | Headlamp ALB, Kubecost ALB |
| **AWS Console** | EKS, CloudFormation, VPC, Cognito, CloudWatch, S3 |
| **Documentation** | GitHub, SigNoz/Istio/Kubecost/Velero/Trivy docs |

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

### Start compute (ALWAYS use graceful-startup.sh)
```bash
# Use the graceful startup script - enforces minimum 3 nodes for multi-AZ
/Users/ymuwakki/infra-agent/scripts/graceful-startup.sh

# The script automatically:
# 1. Starts the bastion instance
# 2. Waits for SSM agent
# 3. Scales nodes to 3 (minimum enforced for multi-AZ)
# 4. Prints next steps for kubectl access
```

**NEVER manually scale to fewer than 3 nodes** - see PRINCIPLE #2 above.

## IaC Source of Truth

All infrastructure changes MUST be tracked in IaC:
- CloudFormation templates: `infra/cloudformation/stacks/`
- Helm values: `infra/helm/values/`
- cfn-guard rules: `infra/cloudformation/cfn-guard-rules/`

## Namespaces

| Namespace | Purpose | Istio |
|-----------|---------|-------|
| `signoz` | SigNoz unified observability (metrics, logs, traces) | Enabled |
| `istio-system` | Istio service mesh + Kiali | N/A |
| `kiali-operator` | Kiali operator | Disabled |
| `headlamp` | Kubernetes admin console | Enabled |
| `kubecost` | Cost analysis | Enabled |
| `velero` | Backup/restore | Disabled |
| `trivy-system` | Security scanning | Disabled |
| `demo` | HotROD demo app for tracing | Enabled |

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

**Re-added (2026-01-17):**
- Kiali - for Istio traffic visualization (SigNoz traces complement, not replace, Kiali's real-time mesh topology)

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

### ALB Path-Based Routing (2026-01-17)
**Pattern:** Single ALB routes to multiple services via path patterns.

| Path | Service | NodePort |
|------|---------|----------|
| `/` (default) | SigNoz | 30301 |
| `/headlamp/*` | Headlamp | 30446 |
| `/kubecost/*` | Kubecost nginx | 30091 |
| `/kiali/*` | Kiali | 30520 |

**Trailing Slash:** Apps like Headlamp and Kiali require trailing slash. ALB rules redirect `/headlamp` → `/headlamp/` and `/kiali` → `/kiali/`.

**Kubecost nginx Proxy:** Kubecost doesn't support subpath routing natively. nginx proxy rewrites `/kubecost/*` → `/*`.

### Kubecost OIDC Limitation (2026-01-15)
**Issue:** Kubecost OIDC requires specific environment variable format, not just secret reference.

**Workaround:** Use ALB Cognito auth (no per-user audit in Kubecost).

**TODO:** Configure Kubecost OIDC with correct environment variable mappings for per-user audit.

### StatefulSet PV AZ-Binding Incident (2026-01-15) - CRITICAL

**Incident:** After cluster restart, SigNoz pods stuck in Pending for 20+ hours, requiring full data loss to recover.

**Root Cause Chain:**
```
1. SigNoz deployed → PVs created in us-east-1b (only AZ with node at time)
2. Cluster shutdown (nodes scaled to 0)
3. Cluster restart → new nodes created in 3 AZs
4. Deployments scheduled first → filled us-east-1b node to 98% CPU
5. StatefulSets tried to schedule LAST → us-east-1b full
6. EBS volumes are AZ-bound → pods CANNOT move to other AZs
7. Force-deleting stuck pod → ClickHouse operator deleted entire CHI
8. Result: Complete data loss, full reinstall required
```

**Why This Is Unacceptable:**
- StatefulSets contain persistent data (ClickHouse DB)
- Resource contention should NOT cause data loss
- Operator cleanup behavior is dangerous when triggered incorrectly

**Prevention Design (MUST IMPLEMENT FOR PRODUCTION):**

1. **Multi-AZ StatefulSets** (spread PVs across AZs):
   ```yaml
   # In Helm values - configure topology spread
   topologySpreadConstraints:
     - maxSkew: 1
       topologyKey: topology.kubernetes.io/zone
       whenUnsatisfiable: DoNotSchedule
   ```

2. **PriorityClasses** (StatefulSets schedule before Deployments):
   ```yaml
   # Create high-priority class for stateful workloads
   apiVersion: scheduling.k8s.io/v1
   kind: PriorityClass
   metadata:
     name: stateful-critical
   value: 1000000
   globalDefault: false
   description: "Critical stateful workloads (databases)"
   ```

3. **Resource Reservations** (guarantee capacity):
   - Reserve 20% CPU headroom on each node
   - Use ResourceQuotas to prevent overcommit
   - Set appropriate requests/limits on all pods

4. **Graceful Shutdown Procedure**:
   ```bash
   # BEFORE scaling nodes to 0:
   # 1. Cordon nodes (prevent new scheduling)
   # 2. Scale down StatefulSets gracefully
   # 3. Wait for PVs to detach
   # 4. Then scale nodes
   ```

5. **NEVER Force-Delete StatefulSet Pods**:
   - Force-delete triggers operator cleanup
   - Always use graceful deletion with proper drain
   - If stuck, investigate root cause first

6. **Backup Strategy** (Velero):
   - Daily backups of PVCs
   - Test restore procedures monthly
   - Document RTO/RPO requirements

7. **Node Autoscaling with Buffer**:
   ```yaml
   # CloudFormation: ensure buffer capacity
   GeneralNodeMinSize: 3  # Not 1 or 2
   GeneralNodeDesiredSize: 3
   ```

**IaC Changes Required:**
- [ ] Add PriorityClass to `infra/helm/values/signoz/values.yaml`
- [ ] Add topologySpreadConstraints for multi-AZ
- [ ] Update node-groups.yaml minSize to 3
- [ ] Document graceful shutdown procedure
- [ ] Configure Velero backup schedule for signoz namespace

**Immediate Actions Taken:**
- Deleted orphaned LGTM PVCs (12 PVs wasting storage)
- Reinstalled SigNoz (data loss accepted for dev)
- PVs now in us-east-1c (available capacity)

### Trivy/Istio Init Container Conflict (2026-01-15)

**Issue:** Trivy scan jobs fail with `Duplicate value: "istio-init"`

**Root Cause:** Trivy creates pods with an init container named `istio-init` that conflicts with Istio's auto-injected container.

**Solution:** Disable Istio injection for trivy-system:
```yaml
# infra/helm/values/trivy/namespace.yaml
metadata:
  labels:
    istio-injection: disabled
```

### OTLP GRPC Fails Through Istio - Use HTTP (2026-01-15)

**Issue:** OTLP trace export via GRPC (port 4317) fails through Istio Envoy with "protocol error"

**Solution:** Use HTTP/protobuf (port 4318) instead:
```yaml
env:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://signoz-otel-collector.signoz.svc.cluster.local:4318"
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: "http/protobuf"
```

**Rule:** In Istio-enabled clusters, default to OTLP HTTP (4318) over GRPC (4317).

### Namespaces That Should Disable Istio (Updated 2026-01-17)

| Namespace | Reason |
|-----------|--------|
| `trivy-system` | Init container name conflict (`istio-init`) |
| `velero` | Backup operations need direct access |
| `kiali-operator` | Operator doesn't need mTLS |

**Note:** `demo` namespace now has Istio ENABLED for Kiali traffic visualization. OTLP HTTP/protobuf (port 4318) works through Envoy.

## NEVER do these

- NEVER enable public endpoint on EKS cluster
- NEVER commit secrets to git
- NEVER bypass cfn-guard compliance checks
- NEVER make infrastructure changes outside of IaC
- NEVER deploy workloads to namespaces without checking istio-injection label
- **NEVER use kubectl patch/apply/edit to modify deployed resources directly** - ALWAYS update the source Helm values or CloudFormation templates first, then redeploy
- **NEVER scale to fewer than 3 nodes** - EBS volumes are AZ-bound; fewer nodes causes StatefulSet failures. ALWAYS use `scripts/graceful-startup.sh` which enforces this

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

**ALL IaC MUST pass linting and policy validation before deployment.**

### CloudFormation Validation

```bash
# Activate virtual environment (Python 3.13+)
source /Users/ymuwakki/infra-agent/.venv/bin/activate

# Run cfn-lint (syntax and best practices)
cfn-lint infra/cloudformation/stacks/**/*.yaml

# Run cfn-guard (NIST compliance rules)
cfn-guard validate \
  --data infra/cloudformation/stacks/ \
  --rules infra/cloudformation/cfn-guard-rules/nist-800-53/ \
  --show-summary all

# Both must pass with no errors before deployment
```

### Helm/Kubernetes Validation

```bash
# Run kubeconform (schema validation)
kubeconform -summary infra/helm/values/demo/

# Run kube-linter (security best practices)
kube-linter lint infra/helm/values/demo/

# For Helm charts, template first then validate
helm template <release> <chart> -f values.yaml | kubeconform -summary
helm template <release> <chart> -f values.yaml | kube-linter lint -
```

### Validation Requirements

| IaC Type | Tool | Must Pass | Blocks Deploy |
|----------|------|-----------|---------------|
| CloudFormation | cfn-lint | 0 errors | Yes |
| CloudFormation | cfn-guard | 0 FAIL | Yes |
| Helm/K8s manifests | kubeconform | 0 invalid | Yes |
| Helm/K8s manifests | kube-linter | 0 errors | Yes |

**NEVER deploy without validation:**
- cfn-lint catches syntax errors, deprecated features, and AWS best practices
- cfn-guard enforces NIST 800-53 compliance rules
- kubeconform validates Kubernetes manifest schemas
- kube-linter enforces security best practices (runAsNonRoot, readOnlyRootFilesystem, etc.)

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
