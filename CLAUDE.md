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

**ALWAYS use the startup script:**
```bash
/Users/ymuwakki/infra-agent/scripts/startup.sh
```

**The script enforces minimum 3 nodes:**
```bash
if [ "$REQUESTED_NODES" -lt "$MIN_NODES" ]; then
    echo "WARNING: Requested $REQUESTED_NODES nodes, but minimum $MIN_NODES required for multi-AZ."
    REQUESTED_NODES=$MIN_NODES
fi
```

**NEVER manually scale to fewer than 3 nodes:**
```bash
# DON'T DO THIS
aws eks update-nodegroup-config ... --scaling-config desiredSize=1  # WRONG
aws eks update-nodegroup-config ... --scaling-config desiredSize=2  # WRONG

# DO THIS INSTEAD
/Users/ymuwakki/infra-agent/scripts/startup.sh  # Enforces min 3
```

---

This is an AI-powered Infrastructure Agent for managing AWS EKS clusters with NIST 800-53 Rev 5 compliance.

## Quick Reference

### Platform Documentation (`docs/security-observability/`)

| Document | Purpose |
|----------|---------|
| `docs/security-observability/architecture.md` | EKS cluster, VPC, Istio, SigNoz observability |
| `docs/security-observability/security.md` | NIST 800-53 compliance, security controls |
| `docs/security-observability/access-guide.md` | **All access URLs and instructions** |
| `docs/security-observability/decisions.md` | Platform choices (SigNoz vs LGTM, etc.) |
| `docs/security-observability/lessons-learned.md` | Infrastructure lessons (Istio, StatefulSets, etc.) |

### Agent Documentation (`docs/infra-agent/`)

| Document | Purpose |
|----------|---------|
| `docs/infra-agent/architecture.md` | Agent architecture, 4-agent pipeline, MCP |
| `docs/infra-agent/user-guide.md` | How to use the CLI, chat commands, examples |
| `docs/infra-agent/requirements.md` | Agent functional requirements (AGT-*) |
| `docs/infra-agent/knowledge-base.md` | **Known AWS/K8s limitations, patterns, troubleshooting** |
| `docs/infra-agent/lessons-learned.md` | Agent development lessons |

## Infra-Agent Architecture Summary

The AI agent consists of 8 specialized agents, all with access to AWS and Git MCP tools:

| Agent | Purpose | MCP Tools |
|-------|---------|-----------|
| ChatAgent | Orchestrator - routes queries to appropriate handlers | AWS + Git (dynamic) |
| PlanningAgent | Generates requirements and acceptance criteria | AWS + Git |
| IaCAgent | Modifies CloudFormation/Helm, commits, pushes, creates PRs | AWS + Git |
| ReviewAgent | Runs cfn-guard, cfn-lint, kube-linter, security scans | AWS + Git |
| DeployValidateAgent | Deploys and runs acceptance tests | AWS + Git |
| InvestigationAgent | Diagnoses pod/service/node issues | AWS + Git |
| AuditAgent | Compliance checks, drift detection | AWS + Git |
| K8sAgent | Kubernetes queries | AWS + Git |

**MCP Tools Available:**
- `aws_api_call(service, operation, parameters)` - Any boto3 operation
- `list_aws_services()`, `list_service_operations(service)` - Discovery
- `git_read_file()`, `git_list_files()`, `git_get_iac_files()` - Repository access
- `git_compare_with_deployed()` - Drift detection

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

### Shutdown (save costs)
```bash
./scripts/shutdown.sh
```

### Startup (full procedure)
```bash
# 1. Start compute (waits for bastion + SSM agent)
./scripts/startup.sh

# 2. Connect to cluster
./scripts/tunnel.sh

# 3. Clean up orphaned pods (required after restart)
./scripts/cleanup-orphaned-pods.sh
```

**What startup.sh does:**
- Starts bastion and waits for it to be running
- Waits for SSM agent to come online
- Scales nodes to 3 (minimum enforced for multi-AZ)

**What cleanup-orphaned-pods.sh does:**
- Deletes pods stuck on terminated/NotReady nodes
- Cleans up failed Velero Kopia maintenance jobs
- Must run after every restart to clear orphaned DaemonSet pods

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

### Namespaces That Should Disable Istio (Updated 2026-01-18)

| Namespace | Reason |
|-----------|--------|
| `trivy-system` | Init container name conflict (`istio-init`) |
| `velero` | Jobs (Kopia maintenance) don't terminate with sidecars |
| `kiali-operator` | Operator doesn't need mTLS |

**Note:** `demo` namespace now has Istio ENABLED for Kiali traffic visualization. OTLP HTTP/protobuf (port 4318) works through Envoy.

### Jobs and CronJobs Should Never Have Istio Sidecars (2026-01-18)

**Issue:** Velero Kopia maintenance jobs stuck in Error status after cluster restart.

**Root Cause:** Jobs with Istio sidecars don't terminate properly. The istio-proxy container keeps running after the main container completes, leaving pods in Error state forever.

**Solution:** Disable Istio at namespace level for any namespace running Jobs/CronJobs:
```yaml
# namespace.yaml
metadata:
  labels:
    istio-injection: disabled
```

Or disable per-pod if namespace needs Istio for other workloads:
```yaml
# In pod spec
annotations:
  sidecar.istio.io/inject: "false"
```

**Rule:** If a namespace runs batch Jobs or CronJobs, disable Istio injection for that namespace.

### readOnlyRootFilesystem with Non-Root Users (2026-01-18)

**Issue:** Velero Kopia jobs failed with `mkdir /nonexistent: read-only file system`

**Root Cause:** User 65534 (nobody) has HOME=/nonexistent. With `readOnlyRootFilesystem: true`, applications can't write to HOME.

**Solution:** Set HOME to a writable directory (usually /tmp which is an emptyDir):
```yaml
extraEnvVars:
  - name: HOME
    value: "/tmp"
```

**Rule:** When using `readOnlyRootFilesystem: true` with non-root users (65534, nobody), always set `HOME=/tmp`.

### TargetGroupBindings for ALB Auto-Registration (2026-01-17)

**Issue:** After cluster restart, ALB target groups had 0 healthy targets for Kiali.

**Root Cause:** EKS nodes terminate and new ones launch. Without TargetGroupBinding CRDs, ALB targets must be manually re-registered.

**Solution:** Every service behind ALB needs a TargetGroupBinding:
```yaml
# Example: infra/helm/values/kiali/targetgroupbinding.yaml
apiVersion: elbv2.k8s.aws/v1beta1
kind: TargetGroupBinding
metadata:
  name: kiali-tgb
  namespace: istio-system
spec:
  serviceRef:
    name: kiali
    port: 20001
  targetGroupARN: arn:aws:elasticloadbalancing:...
  targetType: instance
```

**Files:**
- `infra/helm/values/kiali/targetgroupbinding.yaml`
- `infra/helm/values/signoz/targetgroupbinding.yaml`
- `infra/helm/values/headlamp/targetgroupbinding.yaml`
- `infra/helm/values/kubecost/targetgroupbinding.yaml`

### EKS Nodes Terminate, Not Stop (By Design) (2026-01-17)

EKS Managed Node Groups use AWS Auto Scaling Groups (ASG):
- Scale down = **Terminate** (not stop)
- Scale up = **Launch new** (not start)

**This is correct behavior:**
- Kubernetes nodes are "cattle, not pets"
- Fresh nodes ensure clean state without drift
- Bastion is the exception (stop/start to preserve state)

**What IS preserved:** PersistentVolumes (EBS), K8s state (etcd), ConfigMaps, Secrets
**What is NOT preserved:** Local storage (emptyDir), container image cache, in-memory state

**See:** `docs/requirements.md` NFR-050 to NFR-053

### Graceful Shutdown - Don't Scale Pods (2026-01-17)

**Old (over-engineered):** Scale deployments to 0, then scale statefulsets to 0, then scale nodes to 0.

**New (correct):** Just scale nodes to 0. Kubernetes handles pod eviction automatically.

```bash
# Shutdown - just scale nodes
/Users/ymuwakki/infra-agent/scripts/shutdown.sh

# Startup - scale nodes back up (minimum 3 for multi-AZ)
/Users/ymuwakki/infra-agent/scripts/startup.sh
```

Pods auto-recover when nodes come back up because controllers (Deployment, StatefulSet, DaemonSet) recreate them.

### DaemonSets Don't Need Istio Sidecars (2026-01-17)

**Issue:** DaemonSet pods (otel-agent, velero node-agent) failed to schedule with "Insufficient CPU".

**Root Cause:** Istio sidecar adds ~100m CPU per pod. DaemonSets run on every node.

**Solution:** Disable sidecar injection for infrastructure DaemonSets:
```yaml
podAnnotations:
  sidecar.istio.io/inject: "false"
```

**Files updated:**
- `infra/helm/values/signoz/k8s-infra-values.yaml` (otel-agent)
- `infra/helm/values/velero/values.yaml` (node-agent)

### Kiali Requires Prometheus (Not Part of Istio) (2026-01-17)

**Clarification:** Kiali and Prometheus are NOT part of Istio. They are separate CNCF projects that integrate with Istio.

**Issue:** After SigNoz migration, Kiali traffic graph failed because SigNoz doesn't provide Prometheus-compatible API.

**Solution:** Deploy minimal Prometheus specifically for Kiali:
```yaml
# infra/helm/values/prometheus-kiali/values.yaml
server:
  retention: "2h"
  persistentVolume:
    enabled: false  # Ephemeral - Kiali only needs recent data
```

Configure Kiali to use it:
```yaml
external_services:
  prometheus:
    url: "http://prometheus-kiali-server.prometheus-kiali.svc.cluster.local"
```

### SigNoz Dashboards (2026-01-18)

**Use official SigNoz dashboards** from https://github.com/SigNoz/dashboards - custom dashboards are error-prone.

```
infra/helm/values/signoz/dashboards/
├── kubernetes-cluster-metrics.json  # Deployments, StatefulSets, DaemonSets, Jobs, HPAs
├── kubernetes-pod-metrics.json      # Pod CPU, Memory, Network, Restarts
├── kubernetes-node-metrics.json     # Node CPU, Memory, Disk, Network
└── README.md
```

**Deploy dashboards:**
```bash
./scripts/deploy-signoz-dashboards.sh              # Deploy all
./scripts/deploy-signoz-dashboards.sh --delete-existing  # Clean deploy
```

**Update to latest official dashboards:**
```bash
curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/k8s-infra-metrics/kubernetes-cluster-metrics.json" \
  -o infra/helm/values/signoz/dashboards/kubernetes-cluster-metrics.json
curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/k8s-infra-metrics/kubernetes-pod-metrics-overall.json" \
  -o infra/helm/values/signoz/dashboards/kubernetes-pod-metrics.json
curl -s "https://raw.githubusercontent.com/SigNoz/dashboards/main/k8s-infra-metrics/kubernetes-node-metrics-overall.json" \
  -o infra/helm/values/signoz/dashboards/kubernetes-node-metrics.json
```

**NEVER create custom dashboards** - SigNoz query format is undocumented and error-prone. Use official dashboards or export from UI.

### SigNoz API Key Authentication (2026-01-18)

SigNoz API keys work with the correct header and endpoint:
```bash
# CORRECT - use SIGNOZ-API-KEY header with /api/v1/
curl -H "SIGNOZ-API-KEY: <key>" http://localhost:3301/api/v1/dashboards

# WRONG - these don't work
curl -H "Authorization: Bearer <key>" ...  # Wrong header format
curl ... http://localhost:3301/api/v2/...  # Wrong API version
```

**Create/Delete dashboards via API:**
```bash
# Create
curl -X POST -H "SIGNOZ-API-KEY: <key>" -H "Content-Type: application/json" \
  -d @dashboard.json http://localhost:3301/api/v1/dashboards

# Delete
curl -X DELETE -H "SIGNOZ-API-KEY: <key>" \
  http://localhost:3301/api/v1/dashboards/<id>
```

### Querying ClickHouse Directly (2026-01-18)

Get credentials from signoz-0 pod:
```bash
kubectl exec -n signoz signoz-0 -c signoz -- env | grep CLICKHOUSE_PASSWORD
```

Query metrics:
```bash
kubectl exec -n signoz chi-signoz-clickhouse-cluster-0-0-0 -- \
  clickhouse-client --user default --password '<password>' \
  --query "SELECT DISTINCT metric_name FROM signoz_metrics.time_series_v4 WHERE metric_name LIKE 'k8s%'"
```

### K8s Metrics Available in SigNoz (2026-01-18)

k8sclusterreceiver provides:
- Pod: `k8s.pod.phase`, `k8s.pod.cpu.usage`, `k8s.pod.memory.working_set`
- Node: `k8s.node.condition_ready`, `k8s.node.cpu.usage`, `k8s.node.memory.working_set`
- Workloads: `k8s.deployment.available`, `k8s.statefulset.ready_pods`, `k8s.daemonset.ready_nodes`
- Container: `k8s.container.restarts`, `k8s.container.ready`

Labels: `k8s.cluster.name`, `k8s.namespace.name`, `k8s.pod.name`, `k8s.node.name`

### MCP (Model Context Protocol) for AWS and Git Access (2026-01-19)

**Addition:** Full AWS and Git access via MCP tools for comprehensive drift detection and infrastructure queries.

**Components:**
- `src/infra_agent/mcp/aws_server.py` - FastMCP server with generic boto3 wrapper
- `src/infra_agent/mcp/git_server.py` - GitHub/GitLab access for IaC source of truth
- `src/infra_agent/mcp/client.py` - LangChain tool adapters

**Key Tools:**
| Tool | Purpose |
|------|---------|
| `aws_api_call(service, operation, parameters)` | Execute ANY boto3 operation |
| `git_read_file(repo, path, ref)` | Read IaC files from Git |
| `git_get_iac_files(repo)` | Discover all CloudFormation/Helm files |
| `git_compare_with_deployed(repo, path, content)` | Compare Git vs AWS state |

**Usage:**
```bash
# Via CLI
infra-agent exec "list all running EC2 instances" -e dev
infra-agent exec "show CloudFormation stacks" -e dev
infra-agent exec "check for drift between Git and AWS" -e dev

# MCP server standalone
infra-agent mcp-server -t stdio
```

**Environment Variables Required:**
- `GITHUB_TOKEN` or `GH_TOKEN` - for GitHub access
- AWS credentials via standard credential chain

### Chat UI Progress Feedback (2026-01-19)

**Issue:** Long-running operations (30-60s LLM calls) showed no progress, causing users to think the system hung.

**Solution:** Added real-time progress feedback using Rich's Live display:
- Progress updates during LLM reasoning iterations
- Tool call announcements with parameters
- Tool result summaries
- Elapsed time tracking

**New Chat Commands:**
| Command | Description |
|---------|-------------|
| `/status` | Show all agent tasks (running/completed/failed) |
| `/help` | Show available commands |
| `/clear` | Clear screen |

**Files Changed:**
- `src/infra_agent/agents/base.py` - Added `ProgressCallback` type and callback support in `invoke_with_tools`
- `src/infra_agent/agents/chat/agent.py` - Added task tracking, progress display, `/status` command

### Intent Classification - Exact Word Matching (2026-01-19)

**Issue:** Queries like "check what is deployed" incorrectly triggered the DEPLOY pipeline because "deployed" contains "deploy" as substring.

**Root Cause:** Using `"deploy" in user_input.lower()` matches substrings.

**Solution:** Use regex word boundaries for exact matching:
```python
import re
words = set(re.findall(r'\b\w+\b', user_input.lower()))

# Correct: exact word match
if words & {"deploy", "release", "rollout"}:
    return OperationType.DEPLOY

# Wrong: substring match
if "deploy" in user_input.lower():  # Matches "deployed", "deployment", etc.
```

**Rule:** Always use word boundary matching (`\b`) for intent classification to avoid false positives.

## NEVER do these

- NEVER enable public endpoint on EKS cluster
- NEVER commit secrets to git
- NEVER bypass cfn-guard compliance checks
- NEVER make infrastructure changes outside of IaC
- NEVER deploy workloads to namespaces without checking istio-injection label
- **NEVER use kubectl patch/apply/edit to modify deployed resources directly** - ALWAYS update the source Helm values or CloudFormation templates first, then redeploy
- **NEVER scale to fewer than 3 nodes** - EBS volumes are AZ-bound; fewer nodes causes StatefulSet failures. ALWAYS use `scripts/startup.sh` which enforces this
- **NEVER create custom SigNoz dashboards** - Use official dashboards from https://github.com/SigNoz/dashboards. Custom queries have undocumented format requirements and fail silently.
- **NEVER enable Istio on namespaces with Jobs/CronJobs** - Sidecars don't terminate when jobs complete, leaving pods in Error state forever. Velero namespace must have `istio-injection: disabled`.
- **NEVER let infra-agent generate fake deployment outputs** - The LLM MUST NOT fabricate resource IDs, command outputs, or deployment success claims. All deployments MUST be verified by querying AWS/K8s APIs. See `docs/infra-agent/lessons-learned.md` for the 2026-01-19 hallucination incident.

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
