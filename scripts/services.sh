#!/bin/bash
# Port forward all services
# Usage: ./services.sh
#
# Run this AFTER the tunnel is established (./tunnel.sh in another terminal)

set -e

echo "Port forwarding services..."
echo ""

# Kill any existing port-forwards on these ports
lsof -ti:3000 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti:8080 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti:9090 2>/dev/null | xargs kill -9 2>/dev/null || true

# Start port forwards in background
kubectl port-forward svc/grafana 3000:3000 -n observability &
kubectl port-forward svc/headlamp 8080:80 -n headlamp &
kubectl port-forward svc/kubecost-cost-analyzer 9090:9090 -n kubecost &

echo ""
echo "Services available at:"
echo "  Grafana:  http://localhost:3000"
echo "  Headlamp: http://localhost:8080"
echo "  Kubecost: http://localhost:9090"
echo ""
echo "Grafana credentials: admin / e3GJubngHenyPktuxI7nIFexnD323flPhtPgCnjO"
echo ""
echo "Headlamp token:"
kubectl create token headlamp -n headlamp
echo ""
echo "Press Ctrl+C to stop all port forwards"
wait
