# Component Access URLs & Instructions

This document provides URLs and access instructions for all infrastructure components.

---

## Environment Quick Reference

| Component | DEV Access | Auth Method |
|-----------|------------|-------------|
| SigNoz | ALB + Cognito (HTTPS) | Cognito OIDC |
| Headlamp | ALB + EKS OIDC (HTTPS) | Cognito → EKS OIDC |
| Kubecost | ALB + Cognito (HTTPS) | Cognito OIDC |
| Kiali | ALB + Cognito (HTTPS) | Cognito OIDC |

---

## Internet Access via ALB (DEV)

All observability tools are accessible via Application Load Balancer with AWS Cognito authentication.

### ALB URLs

| Service | URL | Authentication |
|---------|-----|----------------|
| **SigNoz** | `https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/` | Cognito OIDC |
| **Headlamp** | `https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/headlamp/` | EKS OIDC (Cognito) |
| **Kubecost** | `https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/kubecost/` | Cognito OIDC |
| **Kiali** | `https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/kiali/` | Cognito OIDC |

### Authentication Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    ALB (HTTPS:443)                                      │
│                           infra-agent-dev-obs-alb-1650635651                            │
└───────────────────────────────────────┬─────────────────────────────────────────────────┘
                                        │
        ┌───────────────┬───────────────┼───────────────┬───────────────┐
        │               │               │               │               │
        ▼               ▼               ▼               ▼               ▼
   Path: /      Path: /headlamp/*  Path: /kubecost/*  Path: /kiali/*
        │               │               │               │
        ▼               │               ▼               ▼
┌───────────────┐       │       ┌───────────────┐ ┌───────────────┐
│ ALB Cognito   │       │       │ ALB Cognito   │ │ ALB Cognito   │
│ Auth Action   │       │       │ Auth Action   │ │ Auth Action   │
└───────┬───────┘       │       └───────┬───────┘ └───────┬───────┘
        │               │               │                 │
        ▼               ▼               ▼                 ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│    SigNoz     │ │   Headlamp    │ │   Kubecost    │ │     Kiali     │
│  (port 30301) │ │  (port 30446) │ │ nginx proxy   │ │  (port 30520) │
│               │ │               │ │  (port 30091) │ │               │
│  No additional│ │ Handles OIDC  │ │               │ │  No additional│
│  auth needed  │ │ internally    │ │  No additional│ │  auth needed  │
│               │ │ (EKS OIDC)    │ │  auth needed  │ │               │
└───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘
```

### Service-Specific Authentication

| Service | ALB Auth | Additional Auth | K8s API Access |
|---------|----------|-----------------|----------------|
| **SigNoz** | Cognito OIDC | None | N/A |
| **Headlamp** | None (passthrough) | EKS OIDC via Cognito | Per-user identity |
| **Kubecost** | Cognito OIDC | None | N/A |
| **Kiali** | Cognito OIDC | None (anonymous internally) | N/A |

**Headlamp EKS OIDC Integration:**
- Headlamp handles its own OIDC authentication with Cognito
- Tokens are used directly against EKS API via OIDC identity provider
- Per-user K8s audit trail (NIST AU-3 compliant)
- Users must be in `platform-admins` Cognito group for cluster-admin access

### Cognito User Management

**User Pool:** `infra-agent-dev-users` (us-east-1_49eiiC4Ew)

**Create a new user:**
```bash
aws cognito-idp admin-create-user \
  --user-pool-id us-east-1_49eiiC4Ew \
  --username user@example.com \
  --user-attributes Name=email,Value=user@example.com \
  --temporary-password TempPass123! \
  --region us-east-1
```

**Add user to platform-admins group (for K8s access):**
```bash
aws cognito-idp admin-add-user-to-group \
  --user-pool-id us-east-1_49eiiC4Ew \
  --username user@example.com \
  --group-name platform-admins \
  --region us-east-1
```

**Available Groups:**
| Group | K8s Role | Purpose |
|-------|----------|---------|
| `platform-admins` | cluster-admin | Full cluster access |
| `developers` | view | Read-only cluster access |

### SSL Certificate Note

DEV uses a self-signed certificate. Your browser will show a security warning - click "Advanced" → "Proceed" to continue.

---

## Local Access via SSM Tunnel (DEV)

For direct kubectl access and port-forwarding, use SSM tunnel.

### Prerequisites
1. AWS CLI v2 configured
2. [SSM Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) installed
3. kubectl installed

### Step 1: Start SSM Tunnel

```bash
/Users/ymuwakki/infra-agent/scripts/tunnel.sh
```

Or manually:
```bash
aws ssm start-session \
  --target i-02c424847cd5f557e \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["C13DEB3971BF51477027AF0BEF0B1D0D.yl4.us-east-1.eks.amazonaws.com"],"portNumber":["443"],"localPortNumber":["6443"]}'
```

### Step 2: Configure kubectl (one-time)

```bash
aws eks update-kubeconfig --name infra-agent-dev-cluster --region us-east-1
sed -i.bak 's|https://C13DEB3971BF51477027AF0BEF0B1D0D.yl4.us-east-1.eks.amazonaws.com|https://localhost:6443|' ~/.kube/config
kubectl config set-cluster arn:aws:eks:us-east-1:340752837296:cluster/infra-agent-dev-cluster --insecure-skip-tls-verify=true
```

### Step 3: Port Forward Services

```bash
# SigNoz (unified observability)
kubectl port-forward svc/signoz-frontend 3301:3301 -n signoz
# Access: http://localhost:3301

# Headlamp (K8s admin)
kubectl port-forward svc/headlamp 8080:80 -n headlamp
# Access: http://localhost:8080

# Kubecost (cost analysis)
kubectl port-forward svc/kubecost-cost-analyzer 9091:9090 -n kubecost
# Access: http://localhost:9091

# Kiali (Istio traffic visualization)
kubectl port-forward svc/kiali 20001:20001 -n istio-system
# Access: http://localhost:20001/kiali
```

### Services Script

```bash
/Users/ymuwakki/infra-agent/scripts/services.sh
```

---

## Service Details

### SigNoz (Unified Observability)

**Purpose:** Metrics, logs, and traces in a single platform

| Feature | Description |
|---------|-------------|
| Metrics | PromQL-compatible queries |
| Logs | Full-text search, structured logging |
| Traces | Distributed tracing with TraceQL |
| Alerts | Built-in alerting engine |

**Architecture:**
```
┌─────────────────────────────────────────────────────────┐
│                      SigNoz                             │
├─────────────────────────────────────────────────────────┤
│  Frontend (UI)  │  Query Service  │  Alert Manager      │
├─────────────────────────────────────────────────────────┤
│              OpenTelemetry Collector                    │
├─────────────────────────────────────────────────────────┤
│                   ClickHouse                            │
│            (columnar OLAP database)                     │
└─────────────────────────────────────────────────────────┘
```

**Data Retention:**
- Metrics: 15 days (configurable)
- Logs: 15 days (configurable)
- Traces: 15 days (configurable)

**Access:**
- ALB: `https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/`
- Local: `kubectl port-forward svc/signoz-frontend 3301:3301 -n signoz` → http://localhost:3301

---

### Headlamp (K8s Admin Console)

**Purpose:** Web-based Kubernetes management with per-user audit trail

| Feature | Description |
|---------|-------------|
| Cluster Overview | Node/pod health |
| Resource Management | Create, edit, delete K8s resources |
| Log Viewing | Container logs |
| YAML Editor | Direct resource editing |

**Authentication Flow:**
1. User navigates to `/headlamp/`
2. Headlamp redirects to Cognito for OIDC login
3. User authenticates with Cognito credentials
4. Headlamp receives OIDC token
5. Token used against EKS API (via EKS OIDC identity provider)
6. All K8s actions logged with user identity

**Access:**
- ALB: `https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/headlamp/`
- Local: `kubectl port-forward svc/headlamp 8080:80 -n headlamp` → http://localhost:8080
  - Note: Local access requires manual token: `kubectl create token headlamp -n headlamp`

---

### Kubecost (Cost Analysis)

**Purpose:** Kubernetes cost visibility and optimization

| Feature | Description |
|---------|-------------|
| Cost Allocation | Cost by namespace, deployment, pod |
| Efficiency | Idle resource identification |
| Recommendations | Right-sizing suggestions |
| Reports | Cost trends and forecasting |

**Why Kubecost vs AWS Cost Explorer:**
- AWS Cost Explorer: EC2/EBS costs (node-level)
- Kubecost: Cost per pod/namespace/deployment (K8s workload level)

**Access:**
- ALB: `https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/kubecost/`
- Local: `kubectl port-forward svc/kubecost-cost-analyzer 9091:9090 -n kubecost` → http://localhost:9091

**Note:** Initial data collection takes ~25 minutes after deployment.

---

### Kiali (Istio Traffic Visualization)

**Purpose:** Real-time service mesh topology and traffic visualization for Istio

| Feature | Description |
|---------|-------------|
| Traffic Graph | Real-time service-to-service communication |
| Health Monitoring | Workload and service health status |
| Configuration Validation | Istio config validation and recommendations |
| Distributed Tracing | Integration with SigNoz for trace details |

**Why Kiali + SigNoz:**
- SigNoz: Deep trace analysis, metrics, logs (observability data)
- Kiali: Real-time mesh topology, traffic flow, Istio config (mesh visualization)

**Architecture:**
```
┌─────────────────────────────────────────────────────────┐
│                        Kiali                            │
├─────────────────────────────────────────────────────────┤
│  Traffic Graph  │  Workload Health  │  Config Validation│
├─────────────────────────────────────────────────────────┤
│              Prometheus Metrics (from SigNoz)           │
├─────────────────────────────────────────────────────────┤
│                   Istio Control Plane                   │
└─────────────────────────────────────────────────────────┘
```

**Access:**
- ALB: `https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/kiali/`
- Local: `kubectl port-forward svc/kiali 20001:20001 -n istio-system` → http://localhost:20001/kiali

**Demo Application (HotROD):**
- Namespace: `demo` (Istio-enabled)
- Access: `kubectl port-forward svc/hotrod 8080:8080 -n demo` → http://localhost:8080
- Click buttons in HotROD UI to generate traffic visible in Kiali

---

## NIST Compliance

| Control | Implementation |
|---------|---------------|
| NIST IA-2 | Cognito authentication for all services |
| NIST AU-3 | Per-user K8s audit trail via EKS OIDC (Headlamp) |
| NIST SC-8 | HTTPS/TLS 1.3 encryption via ALB |
| NIST AC-2 | Cognito user/group management |
| NIST AC-6 | RBAC with least privilege (developers=view, admins=cluster-admin) |

---

## AWS Console Links

| Service | URL |
|---------|-----|
| EKS Clusters | https://us-east-1.console.aws.amazon.com/eks/home?region=us-east-1#/clusters |
| CloudFormation | https://us-east-1.console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks |
| Cognito User Pools | https://us-east-1.console.aws.amazon.com/cognito/v2/idp/user-pools?region=us-east-1 |
| ALB | https://us-east-1.console.aws.amazon.com/ec2/home?region=us-east-1#LoadBalancers |
| CloudWatch Logs | https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups |

---

## Troubleshooting

### Cannot Access via ALB
1. Check ALB target group health:
   ```bash
   aws elbv2 describe-target-health --target-group-arn <arn> --region us-east-1
   ```
2. Verify nodes are registered as targets
3. Check security group allows ALB → NodePort traffic

### Headlamp OIDC Login Fails
1. Verify user exists in Cognito user pool
2. Check user is in `platform-admins` group for admin access
3. Clear browser cookies and retry
4. Check Headlamp pod logs:
   ```bash
   kubectl logs -l app.kubernetes.io/name=headlamp -n headlamp
   ```

### Kubecost Shows No Data
1. Wait 25+ minutes after initial deployment
2. Check Kubecost pod status:
   ```bash
   kubectl get pods -n kubecost
   ```
3. Verify metrics collection:
   ```bash
   kubectl logs -l app=cost-analyzer -n kubecost
   ```

### SSM Tunnel Connection Failed
1. Verify bastion instance is running:
   ```bash
   aws ec2 describe-instances --instance-ids i-02c424847cd5f557e --query 'Reservations[0].Instances[0].State.Name'
   ```
2. Check SSM agent status (may take 1-2 min after instance start)
3. Verify IAM permissions for SSM

---

## Key Resources

| Resource | ID/Name |
|----------|---------|
| EKS Cluster | `infra-agent-dev-cluster` |
| Bastion Instance | `i-02c424847cd5f557e` |
| ALB DNS | `infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com` |
| Cognito User Pool | `us-east-1_49eiiC4Ew` |
| Region | `us-east-1` |
