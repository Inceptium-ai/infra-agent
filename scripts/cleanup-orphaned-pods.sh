#!/bin/bash
# Cleanup pods orphaned on terminated nodes
# Run after startup when tunnel is connected
#
# Why this is needed:
# When nodes terminate quickly during scale-down, pods scheduled to those nodes
# can get orphaned if the node object is removed before the pod is cleaned up.
# These pods stay in Pending state forever, scheduled to non-existent nodes.

set -e

echo "=== CLEANUP ORPHANED PODS ==="
echo "Start: $(date)"

# Get list of current Ready node names (exclude NotReady, SchedulingDisabled nodes)
READY_NODES=$(kubectl get nodes --no-headers 2>/dev/null | grep " Ready " | grep -v "NotReady" | grep -v "SchedulingDisabled" | awk '{print $1}')
if [ -z "$READY_NODES" ]; then
    echo "ERROR: No Ready nodes found. Is the tunnel running?"
    exit 1
fi

READY_NODE_COUNT=$(echo "$READY_NODES" | wc -l | tr -d ' ')
echo "Found $READY_NODE_COUNT Ready nodes"

# Find pods that are Pending and check if their node is Ready
ORPHANED=0
while IFS= read -r line; do
    if [ -z "$line" ]; then continue; fi

    NAMESPACE=$(echo "$line" | awk '{print $1}')
    POD=$(echo "$line" | awk '{print $2}')

    # Get the node this pod is assigned to
    NODE=$(kubectl get pod -n "$NAMESPACE" "$POD" -o jsonpath='{.spec.nodeName}' 2>/dev/null)

    if [ -n "$NODE" ]; then
        # Check if node exists in Ready nodes list
        if ! echo "$READY_NODES" | grep -q "^${NODE}$"; then
            echo "Deleting orphaned pod: $NAMESPACE/$POD (node $NODE is not Ready)"
            kubectl delete pod -n "$NAMESPACE" "$POD" --force --grace-period=0 2>/dev/null || true
            ORPHANED=$((ORPHANED + 1))
        fi
    fi
done <<< "$(kubectl get pods -A --field-selector=status.phase=Pending --no-headers 2>/dev/null)"

# Also clean up failed Velero Kopia jobs
FAILED_KOPIA=$(kubectl get pods -n velero --no-headers 2>/dev/null | grep -E "kopia.*Error" | awk '{print $1}' || true)
if [ -n "$FAILED_KOPIA" ]; then
    echo ""
    echo "Cleaning up failed Kopia maintenance jobs..."
    echo "$FAILED_KOPIA" | while read -r POD; do
        if [ -n "$POD" ]; then
            echo "  Deleting: $POD"
            kubectl delete pod -n velero "$POD" 2>/dev/null || true
        fi
    done
fi

echo ""
if [ "$ORPHANED" -gt 0 ]; then
    echo "=== CLEANED UP $ORPHANED ORPHANED POD(S) ==="
else
    echo "=== NO ORPHANED PODS FOUND ==="
fi
