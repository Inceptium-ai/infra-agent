# Deployment Pipeline Workflow

This document describes the CI/CD deployment pipeline and Blue/Green deployment strategy for the Infrastructure Agent.

## Overview

The deployment pipeline automates application deployments through a multi-stage process with security gates and Blue/Green deployment for zero-downtime releases.

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DEPLOYMENT PIPELINE                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐  │
│   │  Build  │───▶│  Test   │───▶│  Scan   │───▶│ Deploy  │───▶│ Verify  │  │
│   │         │    │         │    │         │    │         │    │         │  │
│   └─────────┘    └─────────┘    └─────────┘    └─────────┘    └─────────┘  │
│        │              │              │              │              │        │
│        ▼              ▼              ▼              ▼              ▼        │
│   Container      Unit Tests    Trivy Scan    Blue/Green    Health Check    │
│   Image Push     Integration   NIST Check    ALB Switch    Smoke Tests     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## GitHub Actions Workflows

### CI Pipeline (.github/workflows/ci.yaml)

```yaml
name: CI Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          pip install uv
          uv pip install --system -e ".[dev]"

      - name: Run linters
        run: |
          ruff check src/
          mypy src/

  test:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          pip install uv
          uv pip install --system -e ".[dev]"

      - name: Run tests
        run: pytest tests/ -v --cov=src/

  cfn-validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install cfn-lint
        run: pip install cfn-lint

      - name: Validate CloudFormation templates
        run: cfn-lint infra/cloudformation/stacks/**/*.yaml

  cfn-guard:
    runs-on: ubuntu-latest
    needs: cfn-validate
    steps:
      - uses: actions/checkout@v4

      - name: Install cfn-guard
        run: |
          curl --proto '=https' --tlsv1.2 -sSf https://raw.githubusercontent.com/aws-cloudformation/cloudformation-guard/main/install-guard.sh | sh
          echo "$HOME/.guard/bin" >> $GITHUB_PATH

      - name: Run NIST compliance checks
        run: |
          cfn-guard validate \
            --data infra/cloudformation/stacks/ \
            --rules infra/cloudformation/cfn-guard-rules/nist-800-53/ \
            --output-format json

  security-scan:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4

      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: 'fs'
          scan-ref: '.'
          severity: 'CRITICAL,HIGH'
          exit-code: '1'
```

### Deploy to DEV (.github/workflows/deploy-dev.yaml)

```yaml
name: Deploy to DEV

on:
  push:
    branches: [develop]

env:
  AWS_REGION: us-east-1
  ENVIRONMENT: dev
  PROJECT_NAME: infra-agent

jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      image_tag: ${{ steps.meta.outputs.tags }}
    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_DEV }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build and push Docker image
        id: meta
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build -t $ECR_REGISTRY/$PROJECT_NAME:$IMAGE_TAG .
          docker push $ECR_REGISTRY/$PROJECT_NAME:$IMAGE_TAG
          echo "tags=$ECR_REGISTRY/$PROJECT_NAME:$IMAGE_TAG" >> $GITHUB_OUTPUT

  scan:
    runs-on: ubuntu-latest
    needs: build
    steps:
      - name: Run Trivy on image
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{ needs.build.outputs.image_tag }}
          severity: 'CRITICAL'
          exit-code: '1'

  deploy:
    runs-on: ubuntu-latest
    needs: [build, scan]
    environment: dev
    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_DEV }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Update kubeconfig
        run: |
          aws eks update-kubeconfig \
            --name $PROJECT_NAME-$ENVIRONMENT-cluster \
            --region $AWS_REGION

      - name: Deploy to EKS
        run: |
          helm upgrade --install $PROJECT_NAME ./helm/infra-agent \
            --namespace $PROJECT_NAME \
            --create-namespace \
            --set image.tag=${{ github.sha }} \
            --set environment=$ENVIRONMENT \
            --wait --timeout 5m

  verify:
    runs-on: ubuntu-latest
    needs: deploy
    steps:
      - name: Run smoke tests
        run: |
          # Health check
          curl -f https://api.infra-agent-dev.example.com/health

          # Basic functionality test
          curl -f https://api.infra-agent-dev.example.com/status
```

### Deploy to PRD (.github/workflows/deploy-prd.yaml)

```yaml
name: Deploy to PRD

on:
  workflow_dispatch:
    inputs:
      image_tag:
        description: 'Image tag to deploy'
        required: true

env:
  AWS_REGION: us-east-1
  ENVIRONMENT: prd
  PROJECT_NAME: infra-agent

jobs:
  pre-deploy-checks:
    runs-on: ubuntu-latest
    steps:
      - name: Verify TST deployment
        run: |
          # Ensure TST has the same version deployed
          echo "Verifying TST deployment..."

      - name: Run E2E tests against TST
        run: |
          echo "Running E2E tests..."

  deploy:
    runs-on: ubuntu-latest
    needs: pre-deploy-checks
    environment: prd  # Requires manual approval
    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials (JIT)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_PRD }}
          role-session-name: prd-deploy-${{ github.run_id }}
          aws-region: ${{ env.AWS_REGION }}
          role-duration-seconds: 3600  # 1 hour JIT access

      - name: Blue/Green Deploy
        run: |
          # Deploy to Green environment
          ./scripts/blue-green-deploy.sh \
            --environment prd \
            --image-tag ${{ github.event.inputs.image_tag }}

  verify:
    runs-on: ubuntu-latest
    needs: deploy
    steps:
      - name: Run production smoke tests
        run: |
          curl -f https://api.infra-agent-prd.example.com/health

      - name: Monitor for 10 minutes
        run: |
          # Watch error rates
          ./scripts/monitor-deployment.sh --duration 600
```

## Blue/Green Deployment

### Architecture

```
                    ┌───────────────────────────────────────┐
                    │            Route 53                   │
                    │     api.infra-agent.example.com       │
                    └───────────────────┬───────────────────┘
                                        │
                    ┌───────────────────▼───────────────────┐
                    │      Application Load Balancer        │
                    │         (HTTPS Listener)              │
                    └───────────────────┬───────────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                   │                   │
           ┌────────▼────────┐ ┌────────▼────────┐ Weighted
           │  Target Group   │ │  Target Group   │ Routing
           │     BLUE        │ │     GREEN       │
           │   (Current)     │ │    (New)        │
           └────────┬────────┘ └────────┬────────┘
                    │                   │
           ┌────────▼────────┐ ┌────────▼────────┐
           │   EKS Pods      │ │   EKS Pods      │
           │   v1.2.0        │ │   v1.3.0        │
           └─────────────────┘ └─────────────────┘
```

### Deployment Process

1. **Prepare Green Environment**
   - Deploy new version to Green target group
   - Run health checks on Green pods
   - Verify readiness

2. **Traffic Shift**
   - Start with 10% traffic to Green
   - Monitor error rates and latency
   - Gradually increase: 10% → 25% → 50% → 100%

3. **Verification**
   - Monitor for 10 minutes at 100%
   - Check Grafana dashboards
   - Verify no anomalies

4. **Finalize**
   - Mark Green as active
   - Blue becomes standby for rollback

### Agent Commands

```
You: Deploy version 1.3.0 to prd using blue-green

Agent: Starting Blue/Green deployment to PRD...

Pre-deployment checks:
  ✓ MFA verified
  ✓ TST deployment successful (v1.3.0)
  ✓ E2E tests passed
  ✓ No CRITICAL vulnerabilities

Current state:
  Blue (Active):  v1.2.0  ← 100% traffic
  Green (Standby): v1.2.0

Phase 1: Deploying v1.3.0 to Green target group...
  ✓ Image pulled: 123456789012.dkr.ecr.us-east-1.amazonaws.com/infra-agent:1.3.0
  ✓ Pods deployed: 3/3 ready
  ✓ Health checks passing

Phase 2: Traffic shift starting...
  [10%] Blue: 90% | Green: 10%  ✓ Error rate: 0.01%
  [25%] Blue: 75% | Green: 25%  ✓ Error rate: 0.01%
  [50%] Blue: 50% | Green: 50%  ✓ Error rate: 0.02%
  [100%] Blue: 0% | Green: 100% ✓ Error rate: 0.01%

Phase 3: Verification (10 minutes)...
  ✓ Error rate stable: 0.01%
  ✓ P99 latency: 45ms (baseline: 42ms)
  ✓ No anomalies detected

Deployment successful!
  Blue (Standby): v1.2.0  ← Ready for rollback
  Green (Active): v1.3.0  ← 100% traffic
```

### Rollback

```
You: Rollback prd to previous version

Agent: Initiating rollback...

Current state:
  Blue (Standby): v1.2.0
  Green (Active): v1.3.0 ← 100% traffic

Rollback will shift all traffic to Blue (v1.2.0).

Confirm rollback? (yes/no): yes

Rolling back...
  [100%] Blue: 100% | Green: 0%

✓ Rollback complete
  Blue (Active): v1.2.0 ← 100% traffic
  Green (Standby): v1.3.0

Post-rollback actions:
  • Investigate v1.3.0 issues
  • Check logs: kubectl logs -n infra-agent -l version=1.3.0
  • Review metrics: https://grafana.infra-agent-prd.example.com
```

## Environment Promotion

### DEV → TST → PRD Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    PROMOTION WORKFLOW                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  DEV                                                            │
│  ────                                                           │
│  • Auto-deploy on develop branch push                           │
│  • Unit tests + integration tests                               │
│  • Manual testing by developers                                 │
│                                                                 │
│          │                                                      │
│          │ Manual promotion trigger                             │
│          ▼                                                      │
│                                                                 │
│  TST                                                            │
│  ────                                                           │
│  • Requires DEV tests passed                                    │
│  • Full integration test suite                                  │
│  • QA team validation                                           │
│  • Performance testing                                          │
│                                                                 │
│          │                                                      │
│          │ Manual approval + E2E tests                          │
│          ▼                                                      │
│                                                                 │
│  PRD                                                            │
│  ────                                                           │
│  • Requires TST validation                                      │
│  • MFA verification                                             │
│  • Blue/Green deployment                                        │
│  • 10-minute verification window                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Promotion Command

```
You: Promote version 1.3.0 from tst to prd

Agent: Starting promotion from TST to PRD...

Pre-promotion checklist:
  ✓ TST deployment status: SUCCESSFUL
  ✓ TST version: 1.3.0
  ✓ Integration tests: 156/156 passed
  ✓ Performance tests: P99 < 100ms
  ✓ Security scan: No CRITICAL vulnerabilities
  ✓ NIST compliance: 23/23 controls passed

PRD deployment requires:
  • MFA verification
  • Manual approval in GitHub Actions
  • Blue/Green deployment strategy

Proceed with PRD promotion? (yes/no): yes

Please verify MFA...
Enter TOTP code: ******
✓ MFA verified

GitHub Actions workflow triggered:
  Run ID: 12345678
  URL: https://github.com/org/infra-agent/actions/runs/12345678

⏳ Waiting for manual approval...
```

## Monitoring & Alerts

### Deployment Metrics

```
You: Show deployment metrics for last 7 days

Agent: Deployment metrics (2024-12-28 to 2025-01-04):

Environment  Deployments  Success  Failed  MTTR
────────────────────────────────────────────────
DEV          23           22       1       5m
TST          8            8        0       -
PRD          2            2        0       -

Recent Deployments:
────────────────────────────────────────────────
Date        Env   Version  Duration  Status
────────────────────────────────────────────────
2025-01-04  DEV   1.3.1    4m 32s    SUCCESS
2025-01-04  TST   1.3.0    6m 15s    SUCCESS
2025-01-03  PRD   1.3.0    12m 45s   SUCCESS (B/G)
2025-01-03  DEV   1.3.0    4m 12s    SUCCESS
2025-01-02  DEV   1.2.9    5m 01s    FAILED
  └─ Reason: Health check timeout
2025-01-02  DEV   1.2.9    4m 28s    SUCCESS (retry)
```

### Alert Configuration

```yaml
# Grafana Alert Rules
groups:
  - name: deployment-alerts
    rules:
      - alert: DeploymentFailed
        expr: deployment_status{status="failed"} > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Deployment failed in {{ $labels.environment }}"

      - alert: HighErrorRateDuringDeployment
        expr: |
          rate(http_requests_total{status=~"5.."}[5m])
          / rate(http_requests_total[5m]) > 0.05
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Error rate > 5% during deployment"

      - alert: RollbackTriggered
        expr: deployment_rollback_total > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Rollback triggered in {{ $labels.environment }}"
```

## Security Considerations

### Secrets Management

```yaml
# Kubernetes Secret (encrypted with KMS)
apiVersion: v1
kind: Secret
metadata:
  name: infra-agent-secrets
  namespace: infra-agent
  annotations:
    kubernetes.io/service-account.name: infra-agent
type: Opaque
data:
  # Stored in AWS Secrets Manager, referenced via External Secrets
  DATABASE_URL: <base64>
  API_KEY: <base64>
```

### IRSA Configuration

```yaml
# Service Account with IAM Role
apiVersion: v1
kind: ServiceAccount
metadata:
  name: infra-agent
  namespace: infra-agent
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/infra-agent-prd-app-role
```

### Network Policies

```yaml
# Allow only necessary egress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: infra-agent-egress
  namespace: infra-agent
spec:
  podSelector:
    matchLabels:
      app: infra-agent
  policyTypes:
    - Egress
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: observability
      ports:
        - port: 3100  # Loki
        - port: 4317  # Tempo
    - to:
        - ipBlock:
            cidr: 10.0.0.0/16  # VPC
      ports:
        - port: 5432  # RDS
```

## Troubleshooting

### Common Issues

```
You: Deployment failed - how do I troubleshoot?

Agent: Here's a troubleshooting guide for failed deployments:

1. Check Pod Status
   kubectl get pods -n infra-agent -o wide

2. View Pod Logs
   kubectl logs -n infra-agent -l app=infra-agent --tail=100

3. Describe Failed Pod
   kubectl describe pod -n infra-agent <pod-name>

4. Check Events
   kubectl get events -n infra-agent --sort-by='.lastTimestamp'

5. Verify Image Pull
   kubectl get events -n infra-agent | grep -i pull

Common failure reasons:
  • ImagePullBackOff: ECR authentication or image not found
  • CrashLoopBackOff: Application startup failure
  • OOMKilled: Insufficient memory
  • Readiness probe failed: Health endpoint not responding

Need me to run diagnostics on the current deployment?
```

### Deployment History

```
You: Show deployment history for prd

Agent: PRD Deployment History:

Version  Date        Duration  Strategy    Deployer       Status
─────────────────────────────────────────────────────────────────
1.3.0    2025-01-03  12m 45s   Blue/Green  alice@org.com  SUCCESS
1.2.0    2024-12-20  11m 30s   Blue/Green  bob@org.com    SUCCESS
1.1.5    2024-12-15  13m 12s   Blue/Green  alice@org.com  ROLLBACK
  └─ Reason: P99 latency spike detected
1.1.4    2024-12-10  10m 45s   Blue/Green  carol@org.com  SUCCESS

Rollback events: 1 in last 30 days
Average deployment time: 12m 03s
Success rate: 75% (3/4)
```
