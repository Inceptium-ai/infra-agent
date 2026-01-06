# Component Access URLs & Instructions

This document provides URLs and access instructions for all infrastructure components across environments.

---

## Environment Quick Reference

| Component | DEV Access | TST | PRD |
|-----------|------------|-----|-----|
| Grafana | `kubectl port-forward` → http://localhost:3000 | ALB (future) | ALB + MFA |
| Kiali | `kubectl port-forward` → http://localhost:20001 | ALB (future) | ALB + MFA |
| Headlamp | `kubectl port-forward` → http://localhost:8080 | ALB (future) | ALB + MFA |
| Kubecost | `kubectl port-forward` → http://localhost:9091 | ALB (future) | ALB + MFA |
| Prometheus | `kubectl port-forward` → http://localhost:9090 | Internal | Internal |
| Loki | Internal only (via Grafana) | Same | Same |
| Mimir | Internal only (via Grafana) | Same | Same |

---

## DEV Environment Access (SSM Tunnel Method)

For DEV environment, we use **SSM port forwarding** for maximum security - **no internet exposure**.

### Prerequisites
1. AWS CLI v2 configured with appropriate credentials
2. [SSM Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) installed
3. kubectl installed locally

### Step 1: Start SSM Tunnel to EKS API

**Keep this terminal open while working:**
```bash
aws ssm start-session \
  --target i-06b868c656de96829 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["C13DEB3971BF51477027AF0BEF0B1D0D.yl4.us-east-1.eks.amazonaws.com"],"portNumber":["443"],"localPortNumber":["6443"]}'
```

### Step 2: Configure kubectl (one-time setup)
```bash
# Get EKS config
aws eks update-kubeconfig --name infra-agent-dev-cluster --region us-east-1

# Point to localhost tunnel
sed -i.bak 's|https://C13DEB3971BF51477027AF0BEF0B1D0D.yl4.us-east-1.eks.amazonaws.com|https://localhost:6443|' ~/.kube/config

# Skip TLS verification (cert doesn't include localhost)
kubectl config set-cluster arn:aws:eks:us-east-1:340752837296:cluster/infra-agent-dev-cluster --insecure-skip-tls-verify=true
```

### Step 3: Port Forward to Services

Open separate terminals for each service you want to access:

```bash
# Grafana (dashboards, logs, metrics)
kubectl port-forward svc/grafana 3000:3000 -n observability
# Access: http://localhost:3000
# Credentials: admin / (get from: kubectl get secret grafana -n observability -o jsonpath='{.data.admin-password}' | base64 -d)

# Kiali (Istio traffic visualization)
kubectl port-forward svc/kiali 20001:20001 -n istio-system
# Access: http://localhost:20001/kiali
# Token: kubectl create token kiali-service-account -n istio-system

# Headlamp (K8s admin console)
kubectl port-forward svc/headlamp 8080:80 -n headlamp
# Access: http://localhost:8080
# Token: kubectl create token headlamp -n headlamp

# Kubecost (cost analysis)
kubectl port-forward svc/kubecost-cost-analyzer 9091:9090 -n kubecost
# Access: http://localhost:9091

# Prometheus (metrics - usually accessed via Grafana)
kubectl port-forward svc/prometheus-server 9090:80 -n observability
# Access: http://localhost:9090

# Loki API (usually accessed via Grafana)
kubectl port-forward svc/loki-gateway 3100:3100 -n observability

# Mimir API (usually accessed via Grafana)
kubectl port-forward svc/mimir-gateway 9080:80 -n observability
```

### Quick Access Script

Save this as `~/bin/infra-agent-tunnel.sh`:
```bash
#!/bin/bash
# Start SSM tunnel to EKS
echo "Starting SSM tunnel to EKS API..."
aws ssm start-session \
  --target i-06b868c656de96829 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["C13DEB3971BF51477027AF0BEF0B1D0D.yl4.us-east-1.eks.amazonaws.com"],"portNumber":["443"],"localPortNumber":["6443"]}'
```

### Multi-Service Port Forward Script

Save this as `~/bin/infra-agent-services.sh` or use `scripts/services.sh`:
```bash
#!/bin/bash
# Port forward all services (run after tunnel is established)
echo "Port forwarding all services..."
kubectl port-forward svc/grafana 3000:3000 -n observability &
kubectl port-forward svc/kiali 20001:20001 -n istio-system &
kubectl port-forward svc/headlamp 8080:80 -n headlamp &
kubectl port-forward svc/kubecost-cost-analyzer 9091:9090 -n kubecost &
kubectl port-forward svc/prometheus-server 9090:80 -n observability &
echo ""
echo "Services available at:"
echo "  Grafana:    http://localhost:3000"
echo "  Kiali:      http://localhost:20001/kiali"
echo "  Headlamp:   http://localhost:8080"
echo "  Kubecost:   http://localhost:9091"
echo "  Prometheus: http://localhost:9090"
echo ""
echo "Press Ctrl+C to stop all port forwards"
wait
```

---

## Service Details

---

### Grafana Dashboard
**Purpose:** Unified visualization for metrics, logs, and traces

| Environment | Access Method | Port |
|-------------|--------------|------|
| DEV | `kubectl port-forward svc/grafana 3000:3000 -n observability` | 3000 |
| TST | ALB + Cognito (future) | 443 |
| PRD | ALB + Cognito + MFA (future) | 443 |

**Credentials (DEV):**
- Username: `admin`
- Password: `e3GJubngHenyPktuxI7nIFexnD323flPhtPgCnjO`

**Pre-configured Dashboards:**
- EKS Cluster Overview
- Pod Resource Utilization
- Istio Service Mesh Metrics
- Loki Logs Dashboard

**Access Instructions (DEV):**
1. Ensure SSM tunnel is running (Step 1 above)
2. Run: `kubectl port-forward svc/grafana 3000:3000 -n observability`
3. Open browser: http://localhost:3000
4. Login with admin credentials above

---

### Loki (Logs)
**Purpose:** Log aggregation and querying

| Environment | Internal URL | Query Language |
|-------------|--------------|----------------|
| DEV | `http://loki.observability.svc:3100` | LogQL |
| TST | `http://loki.observability.svc:3100` | LogQL |
| PRD | `http://loki.observability.svc:3100` | LogQL |

**Access via Grafana:**
1. Open Grafana
2. Navigate to Explore
3. Select "Loki" data source
4. Use LogQL queries

**Example Queries:**
```logql
# All logs from infra-agent namespace
{namespace="infra-agent"}

# Error logs from chat-agent
{namespace="infra-agent", app="chat-agent"} |= "error"

# Logs with specific trace ID
{namespace="infra-agent"} | json | trace_id="abc123"
```

---

### Kiali (Traffic Visualization)
**Purpose:** Real-time Istio service mesh traffic visualization

| Environment | Access Method | Port |
|-------------|---------------|------|
| DEV | `kubectl port-forward svc/kiali 20001:20001 -n istio-system` | 20001 |
| TST | ALB + Cognito (future) | 443 |
| PRD | ALB + Cognito + MFA (future) | 443 |

**Features:**
- Real-time traffic flow graph between services
- Request rates, error rates, latency visualization
- Service dependency topology
- Istio configuration validation
- Traffic animation

**Access Instructions (DEV):**
1. Ensure SSM tunnel is running (Step 1 above)
2. Run: `kubectl port-forward svc/kiali 20001:20001 -n istio-system`
3. Open browser: http://localhost:20001/kiali
4. Generate token: `kubectl create token kiali-service-account -n istio-system`

---

### Prometheus (Metrics Scraper)
**Purpose:** Scrape Kubernetes metrics and push to Mimir

| Environment | Internal URL | Query Language |
|-------------|--------------|----------------|
| DEV | `http://prometheus-server.observability.svc:80` | PromQL |
| TST | `http://prometheus-server.observability.svc:80` | PromQL |
| PRD | `http://prometheus-server.observability.svc:80` | PromQL |

**Access Instructions (DEV):**
1. Ensure SSM tunnel is running
2. Run: `kubectl port-forward svc/prometheus-server 9090:80 -n observability`
3. Open browser: http://localhost:9090

**Data Flow:**
```
[K8s Pods/Nodes] → [Prometheus SCRAPES] → [remote_write] → [Mimir STORES]
```

---

### Mimir (Metrics Storage)
**Purpose:** Long-term metrics storage (S3-backed)

| Environment | Internal URL | Query Language |
|-------------|--------------|----------------|
| DEV | `http://mimir-gateway.observability.svc:80/prometheus` | PromQL |
| TST | `http://mimir-gateway.observability.svc:80/prometheus` | PromQL |
| PRD | `http://mimir-gateway.observability.svc:80/prometheus` | PromQL |

**Access via Grafana:**
1. Open Grafana
2. Navigate to Explore
3. Select "Mimir" data source
4. Use PromQL queries

**Example Queries:**
```promql
# CPU usage by pod
sum(rate(container_cpu_usage_seconds_total{namespace="infra-agent"}[5m])) by (pod)

# Memory usage
container_memory_working_set_bytes{namespace="infra-agent"}

# Request latency P99
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))
```

---

## Kubernetes Admin Console (Headlamp)

**Purpose:** Web-based Kubernetes management

| Environment | Access Method |
|-------------|---------------|
| DEV | `kubectl port-forward svc/headlamp 8080:80 -n headlamp` → http://localhost:8080 |
| TST | ALB + Cognito (future) |
| PRD | ALB + Cognito + MFA (future) |

**Features:**
- Cluster health overview
- Node/pod management
- Log viewing
- Resource creation (DEV/TST only)
- YAML editor for resources

**Access Instructions (DEV):**
1. Ensure SSM tunnel is running (Step 1 above)
2. Run: `kubectl port-forward svc/headlamp 8080:80 -n headlamp`
3. Open browser: http://localhost:8080
4. Generate auth token and copy it:
   ```bash
   kubectl create token headlamp -n headlamp
   ```
5. Paste the token into Headlamp login screen

**Token Notes:**
- Default token expires in **1 hour**
- Generate a new token anytime by running the command above
- For longer-lived token (8 hours): `kubectl create token headlamp -n headlamp --duration=8h`

---

## Application Load Balancers

### API Gateway ALB
**Purpose:** External API access

| Environment | URL | TLS |
|-------------|-----|-----|
| DEV | `https://api.dev.infra-agent.internal` | AWS ACM certificate |
| TST | `https://api.tst.infra-agent.internal` | AWS ACM certificate |
| PRD | `https://api.infra-agent.com` | AWS ACM certificate |

**Health Check Endpoint:**
```bash
curl https://api.dev.infra-agent.internal/health
```

### Internal ALB (Service-to-Service)
**Purpose:** Internal service communication

| Environment | DNS |
|-------------|-----|
| DEV | `internal-alb.dev.infra-agent.internal` |
| TST | `internal-alb.tst.infra-agent.internal` |
| PRD | `internal-alb.prd.infra-agent.internal` |

---

## Bastion Access

**Purpose:** Emergency cluster access (prefer Headlamp for normal operations)

### Access via AWS Session Manager (Recommended)

```bash
# Install Session Manager plugin
# https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html

# Start session
aws ssm start-session \
  --target i-0123456789abcdef0 \
  --region us-east-1

# Once connected, configure kubectl
aws eks update-kubeconfig --name infra-agent-dev-cluster --region us-east-1
```

### Instance Details

| Environment | Instance ID | Private IP |
|-------------|-------------|------------|
| DEV | Retrieve via: `aws ec2 describe-instances --filters "Name=tag:Name,Values=infra-agent-dev-bastion"` | 10.0.48.x |
| TST | Similar query with tst tag | 10.0.48.x |
| PRD | Similar query with prd tag | 10.0.48.x |

**Security Notes:**
- No SSH port exposed (Session Manager only)
- No public IP
- All sessions logged to CloudWatch
- 30-minute idle timeout

---

## AI Chat Agent (CLI)

**Purpose:** Primary operator interface

### Installation

```bash
# Clone repository
git clone https://github.com/your-org/infra-agent.git
cd infra-agent

# Install dependencies
pip install -e .

# Configure AWS credentials
aws configure

# Run chat agent
infra-agent chat
```

### CLI Commands

```bash
# Start interactive chat
infra-agent chat

# Execute single command
infra-agent exec "show cluster status"

# Deploy to environment
infra-agent deploy --env dev --version 1.2.3

# Check compliance
infra-agent compliance --control CM-8
```

### Example Session

```
$ infra-agent chat

🤖 AI Infrastructure Agent v0.1.0
Connected to: infra-agent-dev-cluster (us-east-1)

You: Show me the cluster status

Agent: Here's the current cluster status:

Cluster: infra-agent-dev-cluster
Version: 1.34
Status: ACTIVE
Nodes: 3/3 Ready
Pods: 47/50 Running

Namespaces:
- infra-agent: 12 pods
- observability: 18 pods
- istio-system: 8 pods
- kube-system: 9 pods

Would you like me to show detailed pod status for any namespace?

You: Check for drift

Agent: Running drift detection on all CloudFormation stacks...

Results:
✅ infra-agent-dev-vpc: IN_SYNC
✅ infra-agent-dev-eks: IN_SYNC
⚠️ infra-agent-dev-security-groups: DRIFTED
   - Resource: sg-0123456789 (EKSNodesSecurityGroup)
   - Difference: Inbound rule added manually

Would you like me to remediate the drift?

You: yes

Agent: Remediating drift for infra-agent-dev-security-groups...
✅ Drift remediated. Stack is now IN_SYNC.
```

---

## Database (RDS)

### Connection Details

| Environment | Endpoint | Port | Database |
|-------------|----------|------|----------|
| DEV | `infra-agent-dev-postgres.xxxxx.us-east-1.rds.amazonaws.com` | 5432 | infraagent |
| TST | `infra-agent-tst-postgres.xxxxx.us-east-1.rds.amazonaws.com` | 5432 | infraagent |
| PRD | `infra-agent-prd-postgres.xxxxx.us-east-1.rds.amazonaws.com` | 5432 | infraagent |

**Access from EKS Pods:**
Credentials stored in AWS Secrets Manager and injected via External Secrets Operator.

**Direct Access (Emergency):**
```bash
# From bastion
psql -h infra-agent-dev-postgres.xxxxx.us-east-1.rds.amazonaws.com \
     -U admin \
     -d infraagent
```

---

## Security Scanning (Trivy)

### Vulnerability Reports

**Via Grafana:**
1. Open Grafana
2. Navigate to Dashboards > Security
3. Select "Trivy Vulnerability Report"

**Via kubectl:**
```bash
# Get vulnerability reports
kubectl get vulnerabilityreports -A

# Get detailed report
kubectl describe vulnerabilityreport <name> -n <namespace>
```

**Via CLI:**
```bash
# Scan specific image
infra-agent security scan --image nginx:latest

# Get namespace report
infra-agent security report --namespace infra-agent
```

---

## Cost Management (Kubecost)

**Purpose:** Kubernetes cost analysis and optimization

| Environment | Access Method |
|-------------|---------------|
| DEV | `kubectl port-forward svc/kubecost-cost-analyzer 9091:9090 -n kubecost` → http://localhost:9091 |
| TST | ALB (future) |
| PRD | ALB + MFA (future) |

**Access Instructions (DEV):**
1. Ensure SSM tunnel is running (Step 1 above)
2. Run: `kubectl port-forward svc/kubecost-cost-analyzer 9091:9090 -n kubecost`
3. Open browser: http://localhost:9091
4. Wait ~25 minutes for initial data collection

**Key Views:**
- Cost by Namespace
- Cost by Deployment
- Idle Resource Identification
- Efficiency Recommendations

**Why Kubecost vs AWS Cost Explorer:**
- AWS Cost Explorer: Shows EC2/EBS costs (node-level)
- Kubecost: Shows cost per pod/namespace/deployment (K8s workload level)

---

## AWS Console Links

### Quick Links (replace ACCOUNT_ID)

| Service | URL |
|---------|-----|
| EKS Clusters | `https://us-east-1.console.aws.amazon.com/eks/home?region=us-east-1#/clusters` |
| CloudFormation | `https://us-east-1.console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks` |
| VPC | `https://us-east-1.console.aws.amazon.com/vpc/home?region=us-east-1#vpcs:` |
| RDS | `https://us-east-1.console.aws.amazon.com/rds/home?region=us-east-1#databases:` |
| CloudWatch Logs | `https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups` |

---

## Troubleshooting

### Cannot Access Grafana
1. Check VPN connection
2. Verify AWS SSO session is active
3. Check if ALB is healthy: `aws elbv2 describe-target-health --target-group-arn <arn>`

### Cannot Connect to EKS
1. Update kubeconfig: `aws eks update-kubeconfig --name infra-agent-dev-cluster`
2. Verify IAM permissions
3. Check if using VPN/bastion for private endpoint access

### Chat Agent Not Responding
1. Check Bedrock service status
2. Verify AWS credentials: `aws sts get-caller-identity`
3. Check agent logs: `kubectl logs -l app=chat-agent -n infra-agent`

---

## Contact & Support

| Issue Type | Contact |
|------------|---------|
| Infrastructure | infrastructure-team@company.com |
| Security | security-team@company.com |
| Access Issues | access-team@company.com |
