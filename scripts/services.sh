#!/bin/bash
# Port forward all observability services
# Usage: ./services.sh
#
# Run this AFTER the tunnel is established (./tunnel.sh in another terminal)
#
# Updated 2026-01-14: Migrated from LGTM stack to SigNoz

set -e

echo "Port forwarding all observability services..."
echo ""

# Kill any existing port-forwards on these ports
for port in 3301 8080 9091; do
  lsof -ti:$port 2>/dev/null | xargs kill -9 2>/dev/null || true
done

# Start port forwards in background
# Observability - SigNoz (unified metrics, logs, traces)
kubectl port-forward svc/signoz 3301:8080 -n signoz &

# Operations
kubectl port-forward svc/headlamp 8080:80 -n headlamp &
kubectl port-forward svc/kubecost-cost-analyzer 9091:9090 -n kubecost &

echo ""
echo "Services available at:"
echo ""
echo "  INTERNET ACCESS (ALB + Cognito Auth):"
echo "    SigNoz:     https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/"
echo "    Headlamp:   https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/headlamp"
echo ""
echo "  LOCAL ACCESS (port-forward):"
echo "    SigNoz:     http://localhost:3301     (metrics, logs, traces - unified UI)"
echo "    Headlamp:   http://localhost:8080     (K8s admin console)"
echo "    Kubecost:   http://localhost:9091     (cost analysis)"
echo ""
echo "Headlamp token:"
kubectl create token headlamp -n headlamp 2>/dev/null || echo "(run manually: kubectl create token headlamp -n headlamp)"
echo ""
echo "Port forwarding started for all services"
wait
