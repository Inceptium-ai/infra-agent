# Component Access URLs & Instructions

This document provides URLs and access instructions for all infrastructure components across environments.

---

## Environment Quick Reference

| Component | DEV | TST | PRD |
|-----------|-----|-----|-----|
| Grafana | https://grafana.dev.infra-agent.internal | https://grafana.tst.infra-agent.internal | https://grafana.infra-agent.com |
| Headlamp | https://headlamp.dev.infra-agent.internal | https://headlamp.tst.infra-agent.internal | https://headlamp.infra-agent.com |
| API ALB | https://api.dev.infra-agent.internal | https://api.tst.infra-agent.internal | https://api.infra-agent.com |

---

## Observability Stack (LGTM)

### Access Method: SSM Tunnel + Port Forward (DEV)

For DEV environment, we use SSM port forwarding for maximum security - no internet exposure.

**Prerequisites:**
1. AWS CLI configured with appropriate credentials
2. SSM Session Manager plugin installed
3. kubectl installed locally

**Step 1: Start SSM Tunnel to EKS API**
```bash
# Terminal 1 - Keep this running
aws ssm start-session \
  --target i-06b868c656de96829 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["C13DEB3971BF51477027AF0BEF0B1D0D.yl4.us-east-1.eks.amazonaws.com"],"portNumber":["443"],"localPortNumber":["6443"]}'
```

**Step 2: Configure kubectl (one-time)**
```bash
aws eks update-kubeconfig --name infra-agent-dev-cluster --region us-east-1
sed -i.bak 's|https://C13DEB3971BF51477027AF0BEF0B1D0D.yl4.us-east-1.eks.amazonaws.com|https://localhost:6443|' ~/.kube/config
kubectl config set-cluster arn:aws:eks:us-east-1:340752837296:cluster/infra-agent-dev-cluster --insecure-skip-tls-verify=true
```

**Step 3: Port Forward to Services**
```bash
# Grafana (http://localhost:3000)
kubectl port-forward svc/grafana 3000:3000 -n observability

# Loki (http://localhost:3100)
kubectl port-forward svc/loki-gateway 3100:3100 -n observability

# Tempo (http://localhost:3200)
kubectl port-forward svc/tempo 3200:3200 -n observability
```

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

### Tempo (Traces)
**Purpose:** Distributed tracing

| Environment | Internal URL | Protocol |
|-------------|--------------|----------|
| DEV | `http://tempo.observability.svc:3200` | OTLP/gRPC |
| TST | `http://tempo.observability.svc:3200` | OTLP/gRPC |
| PRD | `http://tempo.observability.svc:3200` | OTLP/gRPC |

**Access via Grafana:**
1. Open Grafana
2. Navigate to Explore
3. Select "Tempo" data source
4. Search by trace ID or use TraceQL

**Trace ID Propagation:**
All services inject `trace_id` into logs for correlation.

---

### Mimir (Metrics)
**Purpose:** Long-term metrics storage

| Environment | Internal URL | Query Language |
|-------------|--------------|----------------|
| DEV | `http://mimir.observability.svc:9009` | PromQL |
| TST | `http://mimir.observability.svc:9009` | PromQL |
| PRD | `http://mimir.observability.svc:9009` | PromQL |

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

**Purpose:** Web-based Kubernetes management with AI chat integration

| Environment | URL | Features |
|-------------|-----|----------|
| DEV | `https://headlamp.dev.infra-agent.internal` | Full admin access |
| TST | `https://headlamp.tst.infra-agent.internal` | Read + limited write |
| PRD | `https://headlamp.infra-agent.com` | Read-only + MFA for actions |

**Features:**
- Cluster health overview
- Node/pod management
- Log viewing
- Resource creation (DEV/TST only)
- Integrated AI Chat (connects to Chat Agent)

**Access Instructions:**
1. Navigate to Headlamp URL
2. Authenticate via AWS SSO
3. Select cluster from dropdown
4. Use sidebar to navigate resources

**AI Chat Integration:**
- Click chat icon in bottom-right
- Type natural language commands
- Examples:
  - "Show me pods with high CPU usage"
  - "Deploy version 1.2.3 to this namespace"
  - "What's the current drift status?"

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

### Dashboard

| Environment | URL |
|-------------|-----|
| DEV | `https://kubecost.dev.infra-agent.internal` |
| TST | `https://kubecost.tst.infra-agent.internal` |
| PRD | `https://kubecost.infra-agent.com` |

**Key Views:**
- Cost by Namespace
- Cost by Deployment
- Idle Resource Identification
- Efficiency Recommendations

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
