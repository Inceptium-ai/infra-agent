"""Investigation tools for troubleshooting and diagnostics.

This module provides tools for the Investigation Agent to diagnose issues
across Kubernetes, AWS, and observability systems.
"""

import json
import subprocess
from typing import Optional

from langchain_core.tools import tool


# =============================================================================
# Kubernetes Investigation Tools
# =============================================================================


@tool
def pod_health_check(namespace: str = "default", label_selector: Optional[str] = None) -> str:
    """Check pod health status in a namespace.

    Args:
        namespace: Kubernetes namespace to check
        label_selector: Optional label selector (e.g., "app=signoz")

    Returns:
        Pod status summary including restarts, phase, and conditions
    """
    try:
        cmd = ["kubectl", "get", "pods", "-n", namespace, "-o", "json"]
        if label_selector:
            cmd.extend(["-l", label_selector])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return f"Error: {result.stderr}"

        pods = json.loads(result.stdout)
        items = pods.get("items", [])

        if not items:
            return f"No pods found in namespace {namespace}"

        summary = []
        for pod in items:
            name = pod["metadata"]["name"]
            phase = pod["status"].get("phase", "Unknown")
            conditions = pod["status"].get("conditions", [])
            containers = pod["status"].get("containerStatuses", [])

            # Count restarts
            restarts = sum(c.get("restartCount", 0) for c in containers)

            # Check for issues
            issues = []
            for cond in conditions:
                if cond.get("status") != "True" and cond.get("type") in ["Ready", "ContainersReady"]:
                    issues.append(f"{cond['type']}: {cond.get('reason', 'Unknown')}")

            for container in containers:
                if container.get("ready") is False:
                    waiting = container.get("state", {}).get("waiting", {})
                    if waiting:
                        issues.append(f"Container {container['name']}: {waiting.get('reason', 'Not Ready')}")

            status_line = f"{name}: {phase}, Restarts: {restarts}"
            if issues:
                status_line += f", Issues: {'; '.join(issues)}"
            summary.append(status_line)

        return "\n".join(summary)

    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def pod_logs(pod_name: str, namespace: str = "default", container: Optional[str] = None,
             tail_lines: int = 100, previous: bool = False) -> str:
    """Get logs from a pod.

    Args:
        pod_name: Name of the pod
        namespace: Kubernetes namespace
        container: Specific container name (optional)
        tail_lines: Number of lines to retrieve
        previous: Get logs from previous container instance (useful for crashes)

    Returns:
        Pod logs
    """
    try:
        cmd = ["kubectl", "logs", pod_name, "-n", namespace, f"--tail={tail_lines}"]
        if container:
            cmd.extend(["-c", container])
        if previous:
            cmd.append("--previous")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return f"Error: {result.stderr}"

        return result.stdout if result.stdout else "No logs found"

    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def pod_events(namespace: str = "default", field_selector: Optional[str] = None) -> str:
    """Get Kubernetes events for a namespace.

    Args:
        namespace: Kubernetes namespace
        field_selector: Optional field selector (e.g., "involvedObject.name=my-pod")

    Returns:
        Recent events sorted by timestamp
    """
    try:
        cmd = ["kubectl", "get", "events", "-n", namespace, "--sort-by=.lastTimestamp", "-o", "json"]
        if field_selector:
            cmd.extend(["--field-selector", field_selector])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return f"Error: {result.stderr}"

        events = json.loads(result.stdout)
        items = events.get("items", [])

        if not items:
            return f"No events found in namespace {namespace}"

        # Get last 20 events
        summary = []
        for event in items[-20:]:
            event_time = event.get("lastTimestamp", event.get("eventTime", "Unknown"))
            event_type = event.get("type", "Unknown")
            reason = event.get("reason", "Unknown")
            message = event.get("message", "No message")
            obj = event.get("involvedObject", {})
            obj_name = f"{obj.get('kind', 'Unknown')}/{obj.get('name', 'Unknown')}"

            summary.append(f"[{event_time}] {event_type}: {reason} - {obj_name}: {message[:100]}")

        return "\n".join(summary)

    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def pod_describe(pod_name: str, namespace: str = "default") -> str:
    """Get detailed pod description including events and conditions.

    Args:
        pod_name: Name of the pod
        namespace: Kubernetes namespace

    Returns:
        Detailed pod description
    """
    try:
        result = subprocess.run(
            ["kubectl", "describe", "pod", pod_name, "-n", namespace],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return f"Error: {result.stderr}"

        return result.stdout

    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def resource_usage(namespace: str = "default") -> str:
    """Get CPU and memory usage for pods in a namespace.

    Args:
        namespace: Kubernetes namespace

    Returns:
        Resource usage for pods
    """
    try:
        result = subprocess.run(
            ["kubectl", "top", "pods", "-n", namespace],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return f"Error: {result.stderr}. Metrics server may not be available."

        return result.stdout if result.stdout else "No metrics available"

    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def node_status() -> str:
    """Get status of all cluster nodes.

    Returns:
        Node status including conditions and resource capacity
    """
    try:
        result = subprocess.run(
            ["kubectl", "get", "nodes", "-o", "json"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return f"Error: {result.stderr}"

        nodes = json.loads(result.stdout)
        items = nodes.get("items", [])

        summary = []
        for node in items:
            name = node["metadata"]["name"]
            conditions = node["status"].get("conditions", [])
            allocatable = node["status"].get("allocatable", {})

            # Find Ready condition
            ready = "Unknown"
            issues = []
            for cond in conditions:
                if cond["type"] == "Ready":
                    ready = cond["status"]
                elif cond["status"] == "True" and cond["type"] != "Ready":
                    issues.append(cond["type"])

            cpu = allocatable.get("cpu", "Unknown")
            memory = allocatable.get("memory", "Unknown")

            status_line = f"{name}: Ready={ready}, CPU={cpu}, Memory={memory}"
            if issues:
                status_line += f", Issues: {', '.join(issues)}"
            summary.append(status_line)

        return "\n".join(summary)

    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def pvc_status(namespace: str = "default") -> str:
    """Get PersistentVolumeClaim status in a namespace.

    Args:
        namespace: Kubernetes namespace

    Returns:
        PVC status including bound status and capacity
    """
    try:
        result = subprocess.run(
            ["kubectl", "get", "pvc", "-n", namespace, "-o", "json"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return f"Error: {result.stderr}"

        pvcs = json.loads(result.stdout)
        items = pvcs.get("items", [])

        if not items:
            return f"No PVCs found in namespace {namespace}"

        summary = []
        for pvc in items:
            name = pvc["metadata"]["name"]
            status = pvc["status"].get("phase", "Unknown")
            capacity = pvc["status"].get("capacity", {}).get("storage", "Unknown")
            volume = pvc["spec"].get("volumeName", "Not bound")
            storage_class = pvc["spec"].get("storageClassName", "Default")

            summary.append(f"{name}: {status}, Capacity={capacity}, StorageClass={storage_class}, Volume={volume}")

        return "\n".join(summary)

    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def service_endpoints(namespace: str = "default", service_name: Optional[str] = None) -> str:
    """Get service endpoints to check connectivity.

    Args:
        namespace: Kubernetes namespace
        service_name: Specific service name (optional)

    Returns:
        Service endpoints and their status
    """
    try:
        cmd = ["kubectl", "get", "endpoints", "-n", namespace, "-o", "json"]
        if service_name:
            cmd.insert(3, service_name)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return f"Error: {result.stderr}"

        endpoints = json.loads(result.stdout)

        # Handle single endpoint or list
        if "items" in endpoints:
            items = endpoints["items"]
        else:
            items = [endpoints]

        if not items:
            return f"No endpoints found in namespace {namespace}"

        summary = []
        for ep in items:
            name = ep["metadata"]["name"]
            subsets = ep.get("subsets", [])

            if not subsets:
                summary.append(f"{name}: No endpoints (service has no backing pods)")
                continue

            addresses = []
            for subset in subsets:
                for addr in subset.get("addresses", []):
                    ip = addr.get("ip", "Unknown")
                    target = addr.get("targetRef", {}).get("name", "Unknown")
                    addresses.append(f"{ip} ({target})")

            summary.append(f"{name}: {len(addresses)} endpoint(s) - {', '.join(addresses[:5])}")

        return "\n".join(summary)

    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


# =============================================================================
# AWS Investigation Tools
# =============================================================================


@tool
def ec2_status(instance_ids: Optional[str] = None) -> str:
    """Check EC2 instance status.

    Args:
        instance_ids: Comma-separated instance IDs (optional, gets all if not specified)

    Returns:
        EC2 instance status including health checks
    """
    try:
        cmd = ["aws", "ec2", "describe-instance-status", "--include-all-instances", "--output", "json"]
        if instance_ids:
            cmd.extend(["--instance-ids"] + instance_ids.split(","))

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            return f"Error: {result.stderr}"

        data = json.loads(result.stdout)
        statuses = data.get("InstanceStatuses", [])

        if not statuses:
            return "No instances found or no status available"

        summary = []
        for status in statuses:
            instance_id = status.get("InstanceId", "Unknown")
            state = status.get("InstanceState", {}).get("Name", "Unknown")
            system_status = status.get("SystemStatus", {}).get("Status", "Unknown")
            instance_status = status.get("InstanceStatus", {}).get("Status", "Unknown")
            az = status.get("AvailabilityZone", "Unknown")

            summary.append(
                f"{instance_id}: State={state}, System={system_status}, "
                f"Instance={instance_status}, AZ={az}"
            )

        return "\n".join(summary)

    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def eks_nodegroup_status(cluster_name: str, nodegroup_name: Optional[str] = None) -> str:
    """Check EKS node group status.

    Args:
        cluster_name: EKS cluster name
        nodegroup_name: Specific node group name (optional)

    Returns:
        Node group status including health and scaling
    """
    try:
        if nodegroup_name:
            cmd = ["aws", "eks", "describe-nodegroup",
                   "--cluster-name", cluster_name,
                   "--nodegroup-name", nodegroup_name,
                   "--output", "json"]
        else:
            cmd = ["aws", "eks", "list-nodegroups",
                   "--cluster-name", cluster_name,
                   "--output", "json"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            return f"Error: {result.stderr}"

        data = json.loads(result.stdout)

        if nodegroup_name:
            ng = data.get("nodegroup", {})
            return _format_nodegroup(ng)
        else:
            nodegroups = data.get("nodegroups", [])
            if not nodegroups:
                return f"No node groups found in cluster {cluster_name}"

            summaries = []
            for ng_name in nodegroups:
                ng_result = subprocess.run(
                    ["aws", "eks", "describe-nodegroup",
                     "--cluster-name", cluster_name,
                     "--nodegroup-name", ng_name,
                     "--output", "json"],
                    capture_output=True, text=True, timeout=30
                )
                if ng_result.returncode == 0:
                    ng = json.loads(ng_result.stdout).get("nodegroup", {})
                    summaries.append(_format_nodegroup(ng))

            return "\n\n".join(summaries)

    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


def _format_nodegroup(ng: dict) -> str:
    """Format node group info."""
    name = ng.get("nodegroupName", "Unknown")
    status = ng.get("status", "Unknown")
    scaling = ng.get("scalingConfig", {})
    desired = scaling.get("desiredSize", 0)
    min_size = scaling.get("minSize", 0)
    max_size = scaling.get("maxSize", 0)
    health = ng.get("health", {})
    issues = health.get("issues", [])

    result = f"NodeGroup: {name}\n"
    result += f"  Status: {status}\n"
    result += f"  Scaling: {desired} desired (min={min_size}, max={max_size})\n"

    if issues:
        result += "  Health Issues:\n"
        for issue in issues:
            result += f"    - {issue.get('code', 'Unknown')}: {issue.get('message', 'No message')}\n"
    else:
        result += "  Health: OK\n"

    return result


@tool
def cloudwatch_logs(log_group: str, filter_pattern: str = "", hours: int = 1) -> str:
    """Query CloudWatch Logs.

    Args:
        log_group: CloudWatch log group name
        filter_pattern: Filter pattern for logs (optional)
        hours: How many hours back to search

    Returns:
        Matching log events
    """
    try:
        import time
        end_time = int(time.time() * 1000)
        start_time = end_time - (hours * 60 * 60 * 1000)

        cmd = [
            "aws", "logs", "filter-log-events",
            "--log-group-name", log_group,
            "--start-time", str(start_time),
            "--end-time", str(end_time),
            "--limit", "50",
            "--output", "json"
        ]

        if filter_pattern:
            cmd.extend(["--filter-pattern", filter_pattern])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            return f"Error: {result.stderr}"

        data = json.loads(result.stdout)
        events = data.get("events", [])

        if not events:
            return f"No log events found matching criteria in {log_group}"

        summary = []
        for event in events:
            timestamp = event.get("timestamp", 0)
            message = event.get("message", "")[:200]
            summary.append(f"[{timestamp}] {message}")

        return "\n".join(summary)

    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def ebs_status(volume_ids: Optional[str] = None) -> str:
    """Check EBS volume status.

    Args:
        volume_ids: Comma-separated volume IDs (optional)

    Returns:
        EBS volume status including attachment state
    """
    try:
        cmd = ["aws", "ec2", "describe-volumes", "--output", "json"]
        if volume_ids:
            cmd.extend(["--volume-ids"] + volume_ids.split(","))

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            return f"Error: {result.stderr}"

        data = json.loads(result.stdout)
        volumes = data.get("Volumes", [])

        if not volumes:
            return "No volumes found"

        summary = []
        for vol in volumes:
            vol_id = vol.get("VolumeId", "Unknown")
            state = vol.get("State", "Unknown")
            size = vol.get("Size", 0)
            vol_type = vol.get("VolumeType", "Unknown")
            az = vol.get("AvailabilityZone", "Unknown")
            attachments = vol.get("Attachments", [])

            attach_info = "Not attached"
            if attachments:
                attach = attachments[0]
                attach_info = f"Attached to {attach.get('InstanceId', 'Unknown')} ({attach.get('State', 'Unknown')})"

            summary.append(f"{vol_id}: {state}, {size}GB {vol_type}, AZ={az}, {attach_info}")

        return "\n".join(summary)

    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


# =============================================================================
# Observability Investigation Tools (SigNoz)
# =============================================================================


@tool
def signoz_metrics(metric_name: str, namespace: Optional[str] = None, duration: str = "1h") -> str:
    """Query SigNoz metrics.

    Args:
        metric_name: Name of the metric (e.g., "k8s.pod.cpu.usage")
        namespace: Filter by namespace
        duration: Time range (e.g., "1h", "30m")

    Returns:
        Metric values
    """
    # Note: This would normally call SigNoz API, but for now we use kubectl
    # to query the otel-collector metrics endpoint
    try:
        # Get metrics from signoz-otel-collector
        cmd = [
            "kubectl", "exec", "-n", "signoz",
            "deploy/signoz-otel-collector",
            "--", "wget", "-qO-", "http://localhost:8888/metrics"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            # Try alternative approach
            return f"Could not query metrics directly. Use kubectl top pods -n {namespace or 'default'} for resource metrics."

        # Filter for requested metric
        lines = result.stdout.split("\n")
        matching = [l for l in lines if metric_name in l and not l.startswith("#")]

        if not matching:
            return f"No data found for metric {metric_name}"

        return "\n".join(matching[:20])

    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error querying metrics: {str(e)}. Try using kubectl top pods instead."


@tool
def signoz_logs(namespace: str, query: Optional[str] = None, severity: Optional[str] = None,
                duration: str = "1h") -> str:
    """Query SigNoz logs (via kubectl logs as fallback).

    Args:
        namespace: Kubernetes namespace
        query: Search query (optional)
        severity: Filter by severity (error, warn, info)
        duration: Time range

    Returns:
        Log entries
    """
    try:
        # Get pods in namespace
        pods_result = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace, "-o", "jsonpath={.items[*].metadata.name}"],
            capture_output=True, text=True, timeout=30
        )

        if pods_result.returncode != 0:
            return f"Error listing pods: {pods_result.stderr}"

        pod_names = pods_result.stdout.split()
        if not pod_names:
            return f"No pods found in namespace {namespace}"

        # Get logs from first few pods
        all_logs = []
        for pod in pod_names[:3]:  # Limit to first 3 pods
            log_cmd = ["kubectl", "logs", pod, "-n", namespace, "--tail=50"]
            log_result = subprocess.run(log_cmd, capture_output=True, text=True, timeout=30)

            if log_result.returncode == 0:
                logs = log_result.stdout
                # Filter by query if specified
                if query:
                    logs = "\n".join([l for l in logs.split("\n") if query.lower() in l.lower()])
                if severity:
                    logs = "\n".join([l for l in logs.split("\n") if severity.lower() in l.lower()])
                if logs:
                    all_logs.append(f"--- {pod} ---\n{logs[:2000]}")

        if not all_logs:
            return f"No matching logs found in namespace {namespace}"

        return "\n\n".join(all_logs)

    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def signoz_traces(service_name: str, operation: Optional[str] = None,
                  min_duration_ms: Optional[int] = None) -> str:
    """Query SigNoz traces (informational - directs user to SigNoz UI).

    Args:
        service_name: Name of the service
        operation: Filter by operation name
        min_duration_ms: Filter by minimum duration in milliseconds

    Returns:
        Instructions for viewing traces in SigNoz
    """
    # Traces are best viewed in SigNoz UI
    msg = f"""To view traces for service '{service_name}':

1. Access SigNoz:
   - Via ALB: https://infra-agent-dev-obs-alb-*.elb.amazonaws.com/
   - Via port-forward: http://localhost:3301

2. Navigate to Traces tab

3. Apply filters:
   - Service: {service_name}
"""
    if operation:
        msg += f"   - Operation: {operation}\n"
    if min_duration_ms:
        msg += f"   - Min Duration: {min_duration_ms}ms\n"

    msg += """
4. Look for:
   - High latency spans (red/orange)
   - Error spans
   - Missing spans (gaps in trace)

For automated analysis, check pod logs for trace IDs and correlate with events.
"""
    return msg


# Export all tools
INVESTIGATION_TOOLS = [
    pod_health_check,
    pod_logs,
    pod_events,
    pod_describe,
    resource_usage,
    node_status,
    pvc_status,
    service_endpoints,
    ec2_status,
    eks_nodegroup_status,
    cloudwatch_logs,
    ebs_status,
    signoz_metrics,
    signoz_logs,
    signoz_traces,
]
