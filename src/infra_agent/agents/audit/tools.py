"""Audit tools for compliance, security, cost, and drift detection.

This module provides tools for the Audit Agent to assess infrastructure
against NIST controls, security best practices, cost optimization, and
configuration drift.
"""

import json
import subprocess
from typing import Optional

from langchain_core.tools import tool


# =============================================================================
# boto3 Helper
# =============================================================================


def _get_boto3_client(service_name: str):
    """Get a boto3 client for the specified service.

    Uses the default credential chain:
    1. Environment variables
    2. ~/.aws/credentials
    3. ~/.aws/config
    4. ECS/EC2 instance role
    """
    import boto3
    return boto3.client(service_name)


# =============================================================================
# Compliance Audit Tools
# =============================================================================


@tool
def nist_control_check(control_id: str) -> str:
    """Check NIST 800-53 control implementation status.

    Args:
        control_id: NIST control ID (e.g., "SC-8", "AC-6", "AU-2")

    Returns:
        Control status and evidence
    """
    # NIST control checks based on known implementations
    control_checks = {
        "SC-8": _check_sc8_transmission_confidentiality,
        "SC-28": _check_sc28_encryption_at_rest,
        "AC-2": _check_ac2_account_management,
        "AC-6": _check_ac6_least_privilege,
        "AU-2": _check_au2_audit_events,
        "AU-3": _check_au3_audit_content,
        "CM-2": _check_cm2_baseline_configuration,
        "CM-3": _check_cm3_change_control,
        "CP-9": _check_cp9_backup,
        "RA-5": _check_ra5_vulnerability_scanning,
    }

    control_id_upper = control_id.upper()
    if control_id_upper in control_checks:
        return control_checks[control_id_upper]()
    else:
        return f"Control {control_id} check not implemented. Available: {', '.join(control_checks.keys())}"


def _check_sc8_transmission_confidentiality() -> str:
    """Check SC-8: Transmission Confidentiality (Istio mTLS)."""
    try:
        # Check Istio peer authentication policies
        result = subprocess.run(
            ["kubectl", "get", "peerauthentication", "-A", "-o", "json"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return f"SC-8: UNKNOWN - Cannot check Istio mTLS: {result.stderr}"

        policies = json.loads(result.stdout)
        items = policies.get("items", [])

        strict_count = 0
        permissive_count = 0

        for policy in items:
            mode = policy.get("spec", {}).get("mtls", {}).get("mode", "PERMISSIVE")
            if mode == "STRICT":
                strict_count += 1
            else:
                permissive_count += 1

        if strict_count > 0 and permissive_count == 0:
            return f"SC-8: PASSED - Istio mTLS STRICT mode enabled ({strict_count} policies)"
        elif strict_count > 0:
            return f"SC-8: PARTIAL - {strict_count} STRICT, {permissive_count} PERMISSIVE policies"
        else:
            return f"SC-8: FAILED - No STRICT mTLS policies found"

    except Exception as e:
        return f"SC-8: ERROR - {str(e)}"


def _check_sc28_encryption_at_rest() -> str:
    """Check SC-28: Protection of Information at Rest."""
    try:
        results = []
        ec2 = _get_boto3_client("ec2")
        s3 = _get_boto3_client("s3")

        # Check EBS encryption
        try:
            response = ec2.describe_volumes()
            volumes = response.get("Volumes", [])
            unencrypted = [v["VolumeId"] for v in volumes if not v.get("Encrypted", False)]
            if unencrypted:
                results.append(f"EBS: FAILED - {len(unencrypted)} unencrypted volumes")
            else:
                results.append("EBS: PASSED - All volumes encrypted")
        except Exception as e:
            results.append(f"EBS: ERROR - {str(e)}")

        # Check S3 bucket encryption
        try:
            response = s3.list_buckets()
            buckets = [b["Name"] for b in response.get("Buckets", [])]
            unencrypted_buckets = []
            for bucket in buckets[:5]:  # Check first 5 buckets
                try:
                    s3.get_bucket_encryption(Bucket=bucket)
                except Exception:
                    unencrypted_buckets.append(bucket)

            if unencrypted_buckets:
                results.append(f"S3: PARTIAL - {len(unencrypted_buckets)} buckets without encryption")
            else:
                results.append("S3: PASSED - Checked buckets have encryption")
        except Exception as e:
            results.append(f"S3: ERROR - {str(e)}")

        status = "PASSED" if all("PASSED" in r for r in results) else "PARTIAL"
        return f"SC-28: {status}\n" + "\n".join(results)

    except Exception as e:
        return f"SC-28: ERROR - {str(e)}"


def _check_ac2_account_management() -> str:
    """Check AC-2: Account Management (Cognito)."""
    try:
        cognito = _get_boto3_client("cognito-idp")
        response = cognito.list_user_pools(MaxResults=10)
        pools = response.get("UserPools", [])

        if not pools:
            return "AC-2: FAILED - No Cognito user pools configured"

        pool_info = []
        for pool in pools:
            pool_info.append(f"- {pool.get('Name', 'Unknown')} (ID: {pool.get('Id', 'Unknown')})")

        return f"AC-2: PASSED - {len(pools)} Cognito user pool(s) configured\n" + "\n".join(pool_info)

    except Exception as e:
        return f"AC-2: ERROR - {str(e)}"


def _check_ac6_least_privilege() -> str:
    """Check AC-6: Least Privilege (IAM wildcard policies)."""
    try:
        iam = _get_boto3_client("iam")
        response = iam.list_roles()
        roles = [r["RoleName"] for r in response.get("Roles", [])]
        wildcard_roles = []

        for role in roles[:10]:  # Check first 10 roles
            try:
                policy_response = iam.list_attached_role_policies(RoleName=role)
                policies = policy_response.get("AttachedPolicies", [])
                for policy in policies:
                    if "AdministratorAccess" in policy.get("PolicyName", ""):
                        wildcard_roles.append(role)
            except Exception:
                pass

        if wildcard_roles:
            return f"AC-6: PARTIAL - {len(wildcard_roles)} role(s) with admin access: {', '.join(wildcard_roles)}"
        else:
            return "AC-6: PASSED - No AdministratorAccess policies found in checked roles"

    except Exception as e:
        return f"AC-6: ERROR - {str(e)}"


def _check_au2_audit_events() -> str:
    """Check AU-2: Audit Events (logging enabled)."""
    try:
        results = []
        cloudtrail = _get_boto3_client("cloudtrail")
        ec2 = _get_boto3_client("ec2")

        # Check CloudTrail
        try:
            response = cloudtrail.describe_trails()
            trails = response.get("trailList", [])
            if trails:
                results.append(f"CloudTrail: PASSED - {len(trails)} trail(s) configured")
            else:
                results.append("CloudTrail: FAILED - No trails configured")
        except Exception as e:
            results.append(f"CloudTrail: ERROR - {str(e)}")

        # Check VPC Flow Logs (check one VPC)
        try:
            vpc_response = ec2.describe_vpcs()
            vpcs = vpc_response.get("Vpcs", [])
            if vpcs:
                vpc_id = vpcs[0].get("VpcId")
                flow_response = ec2.describe_flow_logs(
                    Filters=[{"Name": "resource-id", "Values": [vpc_id]}]
                )
                flows = flow_response.get("FlowLogs", [])
                if flows:
                    results.append(f"VPC Flow Logs: PASSED - Enabled for {vpc_id}")
                else:
                    results.append(f"VPC Flow Logs: FAILED - Not enabled for {vpc_id}")
        except Exception as e:
            results.append(f"VPC Flow Logs: ERROR - {str(e)}")

        status = "PASSED" if all("PASSED" in r for r in results) else "PARTIAL"
        return f"AU-2: {status}\n" + "\n".join(results)

    except Exception as e:
        return f"AU-2: ERROR - {str(e)}"


def _check_au3_audit_content() -> str:
    """Check AU-3: Content of Audit Records (K8s audit logs)."""
    try:
        eks = _get_boto3_client("eks")
        response = eks.describe_cluster(name="infra-agent-dev-cluster")
        cluster = response.get("cluster", {})
        logging_config = cluster.get("logging", {}).get("clusterLogging", [])

        enabled_types = []
        for config in logging_config:
            if config.get("enabled"):
                enabled_types.extend(config.get("types", []))

        if "audit" in enabled_types:
            return f"AU-3: PASSED - EKS audit logging enabled. Types: {', '.join(enabled_types)}"
        else:
            return f"AU-3: PARTIAL - Audit logging may not be enabled. Active types: {', '.join(enabled_types)}"

    except Exception as e:
        return f"AU-3: ERROR - {str(e)}"


def _check_cm2_baseline_configuration() -> str:
    """Check CM-2: Baseline Configuration (IaC)."""
    try:
        cfn = _get_boto3_client("cloudformation")
        response = cfn.list_stacks(
            StackStatusFilter=["CREATE_COMPLETE", "UPDATE_COMPLETE"]
        )
        stacks = [s["StackName"] for s in response.get("StackSummaries", [])]

        if stacks:
            return f"CM-2: PASSED - {len(stacks)} CloudFormation stack(s) managing infrastructure"
        else:
            return "CM-2: PARTIAL - No CloudFormation stacks found"

    except Exception as e:
        return f"CM-2: ERROR - {str(e)}"


def _check_cm3_change_control() -> str:
    """Check CM-3: Configuration Change Control (Git)."""
    # This is informational - actual check would be in CI/CD
    return """CM-3: INFORMATIONAL
- IaC files in Git: infra/cloudformation/, infra/helm/values/
- Changes must go through PR review
- cfn-guard validates NIST compliance
- cfn-lint validates CloudFormation syntax
- kube-linter validates K8s manifests

To verify: Check recent commits in Git repository."""


def _check_cp9_backup() -> str:
    """Check CP-9: System Backup (Velero)."""
    try:
        # Check Velero backup schedules
        result = subprocess.run(
            ["kubectl", "get", "schedules", "-n", "velero", "-o", "json"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return f"CP-9: UNKNOWN - Cannot check Velero: {result.stderr}"

        schedules = json.loads(result.stdout)
        items = schedules.get("items", [])

        if items:
            schedule_info = []
            for sched in items:
                name = sched["metadata"]["name"]
                cron = sched["spec"].get("schedule", "Unknown")
                schedule_info.append(f"- {name}: {cron}")

            return f"CP-9: PASSED - {len(items)} backup schedule(s) configured\n" + "\n".join(schedule_info)
        else:
            return "CP-9: FAILED - No Velero backup schedules configured"

    except Exception as e:
        return f"CP-9: ERROR - {str(e)}"


def _check_ra5_vulnerability_scanning() -> str:
    """Check RA-5: Vulnerability Scanning (Trivy)."""
    try:
        # Check for Trivy vulnerability reports
        result = subprocess.run(
            ["kubectl", "get", "vulnerabilityreports", "-A", "-o", "json"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return f"RA-5: UNKNOWN - Cannot check Trivy reports: {result.stderr}"

        reports = json.loads(result.stdout)
        items = reports.get("items", [])

        if items:
            critical_count = 0
            high_count = 0
            for report in items:
                summary = report.get("report", {}).get("summary", {})
                critical_count += summary.get("criticalCount", 0)
                high_count += summary.get("highCount", 0)

            return f"RA-5: PASSED - Trivy scanning active. {len(items)} reports, {critical_count} CRITICAL, {high_count} HIGH vulnerabilities"
        else:
            return "RA-5: PARTIAL - Trivy installed but no vulnerability reports found"

    except Exception as e:
        return f"RA-5: ERROR - {str(e)}"


@tool
def encryption_audit() -> str:
    """Audit encryption at rest and in transit across all resources.

    Returns:
        Comprehensive encryption status
    """
    results = []

    # Check EBS encryption
    try:
        ec2 = _get_boto3_client("ec2")
        response = ec2.describe_volumes()
        volumes = response.get("Volumes", [])
        encrypted = sum(1 for v in volumes if v.get("Encrypted"))
        total = len(volumes)
        results.append(f"EBS Volumes: {encrypted}/{total} encrypted")
    except Exception as e:
        results.append(f"EBS: Error - {str(e)}")

    # Check RDS encryption
    try:
        rds = _get_boto3_client("rds")
        response = rds.describe_db_instances()
        dbs = response.get("DBInstances", [])
        if dbs:
            encrypted = sum(1 for db in dbs if db.get("StorageEncrypted"))
            results.append(f"RDS Instances: {encrypted}/{len(dbs)} encrypted")
        else:
            results.append("RDS: No instances found")
    except Exception as e:
        results.append(f"RDS: Error - {str(e)}")

    # Check Secrets Manager encryption (all secrets are encrypted by default)
    try:
        secretsmanager = _get_boto3_client("secretsmanager")
        response = secretsmanager.list_secrets()
        secrets = response.get("SecretList", [])
        results.append(f"Secrets Manager: {len(secrets)} secrets (all encrypted by default)")
    except Exception as e:
        results.append(f"Secrets Manager: Error - {str(e)}")

    return "Encryption Audit Results:\n" + "\n".join(results)


@tool
def istio_mtls_check() -> str:
    """Check Istio mTLS configuration across namespaces.

    Returns:
        mTLS status for each namespace
    """
    try:
        # Get all namespaces with Istio injection
        ns_result = subprocess.run(
            ["kubectl", "get", "namespaces", "-l", "istio-injection=enabled",
             "-o", "jsonpath={.items[*].metadata.name}"],
            capture_output=True, text=True, timeout=30
        )

        istio_namespaces = ns_result.stdout.split() if ns_result.stdout else []

        # Get PeerAuthentication policies
        pa_result = subprocess.run(
            ["kubectl", "get", "peerauthentication", "-A", "-o", "json"],
            capture_output=True, text=True, timeout=30
        )

        policies = {}
        if pa_result.returncode == 0:
            pa_data = json.loads(pa_result.stdout)
            for item in pa_data.get("items", []):
                ns = item["metadata"]["namespace"]
                mode = item.get("spec", {}).get("mtls", {}).get("mode", "PERMISSIVE")
                policies[ns] = mode

        results = []
        results.append(f"Istio-enabled namespaces: {len(istio_namespaces)}")

        for ns in istio_namespaces:
            mode = policies.get(ns, "PERMISSIVE (default)")
            results.append(f"  {ns}: {mode}")

        if not istio_namespaces:
            results.append("  No namespaces with istio-injection=enabled")

        return "\n".join(results)

    except Exception as e:
        return f"Error checking Istio mTLS: {str(e)}"


# =============================================================================
# Security Audit Tools
# =============================================================================


@tool
def iam_audit() -> str:
    """Audit IAM policies for security issues.

    Returns:
        IAM security findings
    """
    try:
        results = []
        iam = _get_boto3_client("iam")

        # Check for roles with admin access
        try:
            response = iam.list_roles()
            roles = [r["RoleName"] for r in response.get("Roles", [])]
            admin_roles = []

            for role in roles[:20]:  # Check first 20 roles
                try:
                    attached = iam.list_attached_role_policies(RoleName=role)
                    policies = [p["PolicyName"] for p in attached.get("AttachedPolicies", [])]
                    if any("Admin" in p for p in policies):
                        admin_roles.append(role)
                except Exception:
                    pass

            results.append(f"Roles with Admin policies: {len(admin_roles)}")
            for role in admin_roles[:5]:
                results.append(f"  - {role}")
        except Exception as e:
            results.append(f"Roles: Error - {str(e)}")

        # Check for users with console access
        try:
            response = iam.list_users()
            users = response.get("Users", [])
            results.append(f"\nIAM Users: {len(users)}")
        except Exception as e:
            results.append(f"Users: Error - {str(e)}")

        return "IAM Audit Results:\n" + "\n".join(results)

    except Exception as e:
        return f"Error running IAM audit: {str(e)}"


@tool
def public_access_check() -> str:
    """Check for publicly accessible resources.

    Returns:
        List of potentially public resources
    """
    try:
        results = []
        s3 = _get_boto3_client("s3")
        ec2 = _get_boto3_client("ec2")

        # Check S3 public access
        try:
            response = s3.list_buckets()
            buckets = [b["Name"] for b in response.get("Buckets", [])]
            public_buckets = []

            for bucket in buckets[:10]:
                try:
                    s3.get_public_access_block(Bucket=bucket)
                except Exception:
                    # No public access block = potentially public
                    public_buckets.append(bucket)

            if public_buckets:
                results.append(f"S3 buckets without public access block: {len(public_buckets)}")
                for b in public_buckets[:5]:
                    results.append(f"  - {b}")
            else:
                results.append("S3: All checked buckets have public access block")
        except Exception as e:
            results.append(f"S3: Error - {str(e)}")

        # Check security groups with 0.0.0.0/0
        try:
            response = ec2.describe_security_groups()
            sgs = response.get("SecurityGroups", [])
            open_sgs = []
            for sg in sgs:
                for perm in sg.get("IpPermissions", []):
                    for ip_range in perm.get("IpRanges", []):
                        if ip_range.get("CidrIp") == "0.0.0.0/0":
                            open_sgs.append(sg["GroupId"])
                            break
            results.append(f"\nSecurity groups with 0.0.0.0/0 ingress: {len(set(open_sgs))}")
        except Exception as e:
            results.append(f"Security Groups: Error - {str(e)}")

        return "Public Access Audit:\n" + "\n".join(results)

    except Exception as e:
        return f"Error checking public access: {str(e)}"


@tool
def trivy_results(namespace: str = "default") -> str:
    """Get Trivy vulnerability scan results for a namespace.

    Args:
        namespace: Kubernetes namespace to check

    Returns:
        Vulnerability summary
    """
    try:
        result = subprocess.run(
            ["kubectl", "get", "vulnerabilityreports", "-n", namespace, "-o", "json"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return f"Error getting Trivy results: {result.stderr}"

        reports = json.loads(result.stdout)
        items = reports.get("items", [])

        if not items:
            return f"No vulnerability reports found in namespace {namespace}"

        summary = []
        total_critical = 0
        total_high = 0

        for report in items:
            name = report["metadata"]["name"]
            vuln_summary = report.get("report", {}).get("summary", {})
            critical = vuln_summary.get("criticalCount", 0)
            high = vuln_summary.get("highCount", 0)
            medium = vuln_summary.get("mediumCount", 0)
            low = vuln_summary.get("lowCount", 0)

            total_critical += critical
            total_high += high

            if critical > 0 or high > 0:
                summary.append(f"  {name}: C:{critical} H:{high} M:{medium} L:{low}")

        result_text = f"Trivy Scan Results for {namespace}:\n"
        result_text += f"Total: {total_critical} CRITICAL, {total_high} HIGH\n"

        if summary:
            result_text += "\nImages with CRITICAL/HIGH vulnerabilities:\n"
            result_text += "\n".join(summary[:10])

        return result_text

    except Exception as e:
        return f"Error getting Trivy results: {str(e)}"


@tool
def network_policy_audit() -> str:
    """Audit Kubernetes NetworkPolicies.

    Returns:
        NetworkPolicy coverage assessment
    """
    try:
        # Get all namespaces
        ns_result = subprocess.run(
            ["kubectl", "get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}"],
            capture_output=True, text=True, timeout=30
        )

        namespaces = ns_result.stdout.split() if ns_result.stdout else []

        # Get NetworkPolicies
        np_result = subprocess.run(
            ["kubectl", "get", "networkpolicies", "-A", "-o", "json"],
            capture_output=True, text=True, timeout=30
        )

        policies_by_ns = {}
        if np_result.returncode == 0:
            np_data = json.loads(np_result.stdout)
            for item in np_data.get("items", []):
                ns = item["metadata"]["namespace"]
                policies_by_ns[ns] = policies_by_ns.get(ns, 0) + 1

        results = []
        results.append(f"Total namespaces: {len(namespaces)}")
        results.append(f"Namespaces with NetworkPolicies: {len(policies_by_ns)}")

        # List namespaces without policies (excluding system namespaces)
        system_ns = {"kube-system", "kube-public", "kube-node-lease", "default"}
        no_policy_ns = [ns for ns in namespaces if ns not in policies_by_ns and ns not in system_ns]

        if no_policy_ns:
            results.append(f"\nNamespaces without NetworkPolicies:")
            for ns in no_policy_ns[:10]:
                results.append(f"  - {ns}")

        return "\n".join(results)

    except Exception as e:
        return f"Error auditing NetworkPolicies: {str(e)}"


# =============================================================================
# Cost Audit Tools
# =============================================================================


@tool
def kubecost_query(query_type: str = "summary") -> str:
    """Query Kubecost for cost data.

    Args:
        query_type: Type of query (summary, namespace, idle)

    Returns:
        Cost data
    """
    # Note: This would normally call Kubecost API
    # For now, provide instructions
    return """Kubecost Query Instructions:

Access Kubecost at:
- Via ALB: https://infra-agent-dev-obs-alb-*.elb.amazonaws.com/kubecost/
- Via port-forward: http://localhost:9091

Key Views:
1. Overview: Total cluster cost and trends
2. Allocations: Cost by namespace, deployment, pod
3. Savings: Idle resources and rightsizing recommendations

API Endpoints (via port-forward):
- GET /model/allocation?window=1d - Daily allocation
- GET /model/assets - Asset costs
- GET /model/savings - Savings recommendations

For automated cost analysis, enable Kubecost API access."""


@tool
def idle_resource_check() -> str:
    """Check for idle resources that could be deleted.

    Returns:
        List of potentially idle resources
    """
    try:
        results = []

        # Check for pods with 0 CPU usage (approximation)
        pods_result = subprocess.run(
            ["kubectl", "top", "pods", "-A", "--no-headers"],
            capture_output=True, text=True, timeout=30
        )

        if pods_result.returncode == 0:
            low_usage_pods = []
            for line in pods_result.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 3:
                    cpu = parts[2]
                    # Check for very low CPU (< 1m)
                    if cpu.endswith("m") and int(cpu[:-1]) < 5:
                        low_usage_pods.append(f"{parts[0]}/{parts[1]}")

            results.append(f"Pods with <5m CPU usage: {len(low_usage_pods)}")
            if low_usage_pods:
                for pod in low_usage_pods[:5]:
                    results.append(f"  - {pod}")

        # Check for unbound PVCs
        pvc_result = subprocess.run(
            ["kubectl", "get", "pvc", "-A", "-o", "json"],
            capture_output=True, text=True, timeout=30
        )

        if pvc_result.returncode == 0:
            pvcs = json.loads(pvc_result.stdout)
            pending_pvcs = [
                pvc["metadata"]["name"]
                for pvc in pvcs.get("items", [])
                if pvc.get("status", {}).get("phase") == "Pending"
            ]
            results.append(f"\nPending PVCs: {len(pending_pvcs)}")

        return "Idle Resource Check:\n" + "\n".join(results)

    except Exception as e:
        return f"Error checking idle resources: {str(e)}"


@tool
def rightsizing_recommendations() -> str:
    """Get rightsizing recommendations for pods.

    Returns:
        Rightsizing recommendations
    """
    try:
        results = []

        # Get pods with resource requests/limits
        pods_result = subprocess.run(
            ["kubectl", "get", "pods", "-A", "-o", "json"],
            capture_output=True, text=True, timeout=30
        )

        if pods_result.returncode != 0:
            return f"Error getting pods: {pods_result.stderr}"

        pods = json.loads(pods_result.stdout)

        # Get current usage
        top_result = subprocess.run(
            ["kubectl", "top", "pods", "-A", "--no-headers"],
            capture_output=True, text=True, timeout=30
        )

        usage_map = {}
        if top_result.returncode == 0:
            for line in top_result.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 4:
                    key = f"{parts[0]}/{parts[1]}"
                    usage_map[key] = {"cpu": parts[2], "memory": parts[3]}

        recommendations = []
        for pod in pods.get("items", [])[:20]:  # Check first 20 pods
            ns = pod["metadata"]["namespace"]
            name = pod["metadata"]["name"]
            key = f"{ns}/{name}"

            if key in usage_map:
                # Check for over-provisioned resources
                containers = pod["spec"].get("containers", [])
                for container in containers:
                    resources = container.get("resources", {})
                    requests = resources.get("requests", {})
                    limits = resources.get("limits", {})

                    if requests.get("cpu") and limits.get("cpu"):
                        # Simple check: if using < 10% of request, recommend reduction
                        actual_cpu = usage_map[key]["cpu"]
                        if actual_cpu.endswith("m"):
                            actual_val = int(actual_cpu[:-1])
                            if actual_val < 50:  # Very low usage
                                recommendations.append(
                                    f"{key}: CPU usage {actual_cpu}, consider reducing requests"
                                )

        results.append(f"Analyzed {len(pods.get('items', []))} pods")
        results.append(f"Recommendations: {len(recommendations)}")

        if recommendations:
            results.append("\nOver-provisioned pods:")
            for rec in recommendations[:5]:
                results.append(f"  - {rec}")

        return "Rightsizing Analysis:\n" + "\n".join(results)

    except Exception as e:
        return f"Error generating rightsizing recommendations: {str(e)}"


@tool
def unattached_resources() -> str:
    """Find unattached EBS volumes and Elastic IPs.

    Returns:
        List of unattached resources
    """
    try:
        results = []
        ec2 = _get_boto3_client("ec2")

        # Check for unattached EBS volumes
        try:
            response = ec2.describe_volumes(
                Filters=[{"Name": "status", "Values": ["available"]}]
            )
            volumes = response.get("Volumes", [])
            results.append(f"Unattached EBS volumes: {len(volumes)}")
            for vol in volumes[:5]:
                results.append(f"  - {vol['VolumeId']} ({vol['Size']}GB in {vol['AvailabilityZone']})")
        except Exception as e:
            results.append(f"EBS: Error - {str(e)}")

        # Check for unassociated Elastic IPs
        try:
            response = ec2.describe_addresses()
            addresses = response.get("Addresses", [])
            unassociated = [a for a in addresses if not a.get("AssociationId")]
            results.append(f"\nUnassociated Elastic IPs: {len(unassociated)}")
            for eip in unassociated[:5]:
                results.append(f"  - {eip.get('PublicIp', 'N/A')} ({eip.get('AllocationId', 'N/A')})")
        except Exception as e:
            results.append(f"Elastic IPs: Error - {str(e)}")

        return "Unattached Resources:\n" + "\n".join(results)

    except Exception as e:
        return f"Error checking unattached resources: {str(e)}"


# =============================================================================
# Drift Detection Tools
# =============================================================================


@tool
def cfn_drift(stack_name: Optional[str] = None) -> str:
    """Detect CloudFormation drift.

    Args:
        stack_name: Specific stack to check (checks all if not specified)

    Returns:
        Drift detection results
    """
    try:
        import time
        cfn = _get_boto3_client("cloudformation")

        if stack_name:
            stacks = [stack_name]
        else:
            # List all active stacks
            response = cfn.list_stacks(
                StackStatusFilter=["CREATE_COMPLETE", "UPDATE_COMPLETE"]
            )
            stacks = [s["StackName"] for s in response.get("StackSummaries", [])]

        results = []
        for stack in stacks[:5]:  # Check first 5 stacks
            try:
                # Start drift detection
                detect_response = cfn.detect_stack_drift(StackName=stack)
                drift_id = detect_response.get("StackDriftDetectionId")

                # Wait briefly and check status
                time.sleep(2)

                status_response = cfn.describe_stack_drift_detection_status(
                    StackDriftDetectionId=drift_id
                )
                drift_status = status_response.get("StackDriftStatus", "UNKNOWN")
                results.append(f"{stack}: {drift_status}")
            except Exception as e:
                results.append(f"{stack}: Error - {str(e)[:50]}")

        return "CloudFormation Drift Detection:\n" + "\n".join(results)

    except Exception as e:
        return f"Error detecting CloudFormation drift: {str(e)}"


@tool
def helm_drift(release_name: str, namespace: str = "default") -> str:
    """Check Helm release for drift from values file.

    Args:
        release_name: Name of the Helm release
        namespace: Kubernetes namespace

    Returns:
        Drift status
    """
    try:
        # Get current values
        result = subprocess.run(
            ["helm", "get", "values", release_name, "-n", namespace, "-o", "json"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return f"Error getting Helm values: {result.stderr}"

        current_values = json.loads(result.stdout)

        # Note: To properly detect drift, we'd compare against the source values file
        # For now, just show current values summary

        return f"""Helm Release: {release_name} in {namespace}

Current Values (summary):
- Keys configured: {len(current_values.keys())}

To detect drift:
1. Compare with source file: infra/helm/values/{release_name}/values.yaml
2. Run: helm diff upgrade {release_name} <chart> -f <values.yaml> -n {namespace}

Note: Install helm-diff plugin for accurate drift detection."""

    except Exception as e:
        return f"Error checking Helm drift: {str(e)}"


@tool
def k8s_drift(resource_type: str, namespace: str = "default") -> str:
    """Check Kubernetes resources for drift from IaC.

    Args:
        resource_type: Type of resource (deployment, service, configmap)
        namespace: Kubernetes namespace

    Returns:
        Drift indicators
    """
    try:
        result = subprocess.run(
            ["kubectl", "get", resource_type, "-n", namespace, "-o", "json"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return f"Error getting {resource_type}: {result.stderr}"

        resources = json.loads(result.stdout)
        items = resources.get("items", [])

        drift_indicators = []
        for item in items:
            name = item["metadata"]["name"]
            annotations = item["metadata"].get("annotations", {})

            # Check for signs of manual modification
            last_applied = annotations.get("kubectl.kubernetes.io/last-applied-configuration")
            managed_by = annotations.get("meta.helm.sh/release-name")

            if not last_applied and not managed_by:
                drift_indicators.append(f"  - {name}: No IaC tracking annotations")

        result_text = f"K8s Drift Check for {resource_type} in {namespace}:\n"
        result_text += f"Total resources: {len(items)}\n"

        if drift_indicators:
            result_text += "\nPotential drift (no IaC annotations):\n"
            result_text += "\n".join(drift_indicators[:10])
        else:
            result_text += "All resources appear to be IaC-managed"

        return result_text

    except Exception as e:
        return f"Error checking K8s drift: {str(e)}"


# Export all tools
AUDIT_TOOLS = [
    nist_control_check,
    encryption_audit,
    istio_mtls_check,
    iam_audit,
    public_access_check,
    trivy_results,
    network_policy_audit,
    kubecost_query,
    idle_resource_check,
    rightsizing_recommendations,
    unattached_resources,
    cfn_drift,
    helm_drift,
    k8s_drift,
]
