#!/bin/bash
# Port forward all observability services
# Usage: ./services.sh
#
# Run this AFTER the tunnel is established (./tunnel.sh in another terminal)

set -e

echo "Port forwarding all observability services..."
echo ""

# Kill any existing port-forwards on these ports
for port in 3000 3100 3200 8080 9080 9090 9091 20001; do
  lsof -ti:$port 2>/dev/null | xargs kill -9 2>/dev/null || true
done

# Start port forwards in background
# Observability - LGTM Stack
kubectl port-forward svc/grafana 3000:3000 -n observability &
kubectl port-forward svc/loki-gateway 3100:3100 -n observability &
kubectl port-forward svc/tempo 3200:3200 -n observability &
kubectl port-forward svc/prometheus-server 9090:80 -n observability &
kubectl port-forward svc/mimir-gateway 9080:80 -n observability &

# Service Mesh
kubectl port-forward svc/kiali 20001:20001 -n istio-system &

# Operations
kubectl port-forward svc/headlamp 8080:80 -n headlamp &
kubectl port-forward svc/kubecost-cost-analyzer 9091:9090 -n kubecost &

# Note: Keycloak removed - using AWS Cognito for authentication

echo ""
echo "Services available at:"
echo ""
echo "  INTERNET ACCESS (ALB + Cognito Auth):"
echo "    Grafana:    https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/"
echo "    Headlamp:   https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/headlamp"
echo "    Kiali:      https://infra-agent-dev-obs-alb-1650635651.us-east-1.elb.amazonaws.com/kiali"
echo ""
echo "  LOCAL ACCESS (port-forward):"
echo "    Grafana:    http://localhost:3000     (dashboards, logs, metrics)"
echo "    Loki:       http://localhost:3100     (log queries via gateway)"
echo "    Tempo:      http://localhost:3200     (distributed traces)"
echo "    Prometheus: http://localhost:9090     (metrics scraping)"
echo "    Mimir:      http://localhost:9080     (long-term metrics storage)"
echo "    Kiali:      http://localhost:20001/kiali  (traffic visualization)"
echo "    Headlamp:   http://localhost:8080     (K8s admin console)"
echo "    Kubecost:   http://localhost:9091     (cost analysis)"
echo ""
echo "Grafana credentials: admin / $(kubectl get secret grafana -n observability -o jsonpath='{.data.admin-password}' | base64 -d)"
echo ""
echo "Headlamp token:"
kubectl create token headlamp -n headlamp 2>/dev/null || echo "(run manually: kubectl create token headlamp -n headlamp)"
echo ""
echo "Port forwarding started for all services"
wait
