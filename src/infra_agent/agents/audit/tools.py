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

        # Check EBS encryption
        ebs_result = subprocess.run(
            ["aws", "ec2", "describe-volumes", "--query",
             "Volumes[?Encrypted==`false`].VolumeId", "--output", "json"],
            capture_output=True, text=True, timeout=30
        )
        if ebs_result.returncode == 0:
            unencrypted = json.loads(ebs_result.stdout)
            if unencrypted:
                results.append(f"EBS: FAILED - {len(unencrypted)} unencrypted volumes")
            else:
                results.append("EBS: PASSED - All volumes encrypted")

        # Check S3 bucket encryption
        buckets_result = subprocess.run(
            ["aws", "s3api", "list-buckets", "--query", "Buckets[].Name", "--output", "json"],
            capture_output=True, text=True, timeout=30
        )
        if buckets_result.returncode == 0:
            buckets = json.loads(buckets_result.stdout)
            unencrypted_buckets = []
            for bucket in buckets[:5]:  # Check first 5 buckets
                enc_result = subprocess.run(
                    ["aws", "s3api", "get-bucket-encryption", "--bucket", bucket],
                    capture_output=True, text=True, timeout=10
                )
                if enc_result.returncode != 0:
                    unencrypted_buckets.append(bucket)

            if unencrypted_buckets:
                results.append(f"S3: PARTIAL - {len(unencrypted_buckets)} buckets without encryption")
            else:
                results.append("S3: PASSED - Checked buckets have encryption")

        status = "PASSED" if all("PASSED" in r for r in results) else "PARTIAL"
        return f"SC-28: {status}\n" + "\n".join(results)

    except Exception as e:
        return f"SC-28: ERROR - {str(e)}"


def _check_ac2_account_management() -> str:
    """Check AC-2: Account Management (Cognito)."""
    try:
        # Check for Cognito user pools
        result = subprocess.run(
            ["aws", "cognito-idp", "list-user-pools", "--max-results", "10", "--output", "json"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return f"AC-2: UNKNOWN - Cannot check Cognito: {result.stderr}"

        pools = json.loads(result.stdout).get("UserPools", [])

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
        # List roles and check for wildcard policies
        result = subprocess.run(
            ["aws", "iam", "list-roles", "--query", "Roles[].RoleName", "--output", "json"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return f"AC-6: UNKNOWN - Cannot list IAM roles: {result.stderr}"

        roles = json.loads(result.stdout)
        wildcard_roles = []

        for role in roles[:10]:  # Check first 10 roles
            policy_result = subprocess.run(
                ["aws", "iam", "list-attached-role-policies", "--role-name", role, "--output", "json"],
                capture_output=True, text=True, timeout=10
            )
            if policy_result.returncode == 0:
                policies = json.loads(policy_result.stdout).get("AttachedPolicies", [])
                for policy in policies:
                    if "AdministratorAccess" in policy.get("PolicyName", ""):
                        wildcard_roles.append(role)

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

        # Check CloudTrail
        trail_result = subprocess.run(
            ["aws", "cloudtrail", "describe-trails", "--output", "json"],
            capture_output=True, text=True, timeout=30
        )
        if trail_result.returncode == 0:
            trails = json.loads(trail_result.stdout).get("trailList", [])
            if trails:
                results.append(f"CloudTrail: PASSED - {len(trails)} trail(s) configured")
            else:
                results.append("CloudTrail: FAILED - No trails configured")

        # Check VPC Flow Logs (check one VPC)
        vpc_result = subprocess.run(
            ["aws", "ec2", "describe-vpcs", "--query", "Vpcs[0].VpcId", "--output", "text"],
            capture_output=True, text=True, timeout=30
        )
        if vpc_result.returncode == 0:
            vpc_id = vpc_result.stdout.strip()
            flow_result = subprocess.run(
                ["aws", "ec2", "describe-flow-logs", "--filter",
                 f"Name=resource-id,Values={vpc_id}", "--output", "json"],
                capture_output=True, text=True, timeout=30
            )
            if flow_result.returncode == 0:
                flows = json.loads(flow_result.stdout).get("FlowLogs", [])
                if flows:
                    results.append(f"VPC Flow Logs: PASSED - Enabled for {vpc_id}")
                else:
                    results.append(f"VPC Flow Logs: FAILED - Not enabled for {vpc_id}")

        status = "PASSED" if all("PASSED" in r for r in results) else "PARTIAL"
        return f"AU-2: {status}\n" + "\n".join(results)

    except Exception as e:
        return f"AU-2: ERROR - {str(e)}"


def _check_au3_audit_content() -> str:
    """Check AU-3: Content of Audit Records (K8s audit logs)."""
    try:
        # Check if EKS cluster has audit logging enabled
        result = subprocess.run(
            ["aws", "eks", "describe-cluster", "--name", "infra-agent-dev-cluster",
             "--query", "cluster.logging.clusterLogging[?enabled==`true`].types",
             "--output", "json"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return f"AU-3: UNKNOWN - Cannot check EKS logging: {result.stderr}"

        log_types = json.loads(result.stdout)
        flat_types = [t for sublist in log_types for t in sublist] if log_types else []

        if "audit" in flat_types:
            return f"AU-3: PASSED - EKS audit logging enabled. Types: {', '.join(flat_types)}"
        else:
            return f"AU-3: PARTIAL - Audit logging may not be enabled. Active types: {', '.join(flat_types)}"

    except Exception as e:
        return f"AU-3: ERROR - {str(e)}"


def _check_cm2_baseline_configuration() -> str:
    """Check CM-2: Baseline Configuration (IaC)."""
    try:
        # Check for CloudFormation stacks
        result = subprocess.run(
            ["aws", "cloudformation", "list-stacks",
             "--stack-status-filter", "CREATE_COMPLETE", "UPDATE_COMPLETE",
             "--query", "StackSummaries[].StackName", "--output", "json"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return f"CM-2: UNKNOWN - Cannot list CloudFormation stacks: {result.stderr}"

        stacks = json.loads(result.stdout)

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
        ebs_result = subprocess.run(
            ["aws", "ec2", "describe-volumes",
             "--query", "Volumes[].{ID:VolumeId,Encrypted:Encrypted,KmsKeyId:KmsKeyId}",
             "--output", "json"],
            capture_output=True, text=True, timeout=30
        )
        if ebs_result.returncode == 0:
            volumes = json.loads(ebs_result.stdout)
            encrypted = sum(1 for v in volumes if v.get("Encrypted"))
            total = len(volumes)
            results.append(f"EBS Volumes: {encrypted}/{total} encrypted")
    except Exception as e:
        results.append(f"EBS: Error - {str(e)}")

    # Check RDS encryption
    try:
        rds_result = subprocess.run(
            ["aws", "rds", "describe-db-instances",
             "--query", "DBInstances[].{ID:DBInstanceIdentifier,Encrypted:StorageEncrypted}",
             "--output", "json"],
            capture_output=True, text=True, timeout=30
        )
        if rds_result.returncode == 0:
            dbs = json.loads(rds_result.stdout)
            if dbs:
                encrypted = sum(1 for db in dbs if db.get("Encrypted"))
                results.append(f"RDS Instances: {encrypted}/{len(dbs)} encrypted")
            else:
                results.append("RDS: No instances found")
    except Exception as e:
        results.append(f"RDS: Error - {str(e)}")

    # Check Secrets Manager encryption (all secrets are encrypted by default)
    try:
        secrets_result = subprocess.run(
            ["aws", "secretsmanager", "list-secrets",
             "--query", "SecretList[].Name", "--output", "json"],
            capture_output=True, text=True, timeout=30
        )
        if secrets_result.returncode == 0:
            secrets = json.loads(secrets_result.stdout)
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

        # Check for roles with admin access
        roles_result = subprocess.run(
            ["aws", "iam", "list-roles", "--query", "Roles[].RoleName", "--output", "json"],
            capture_output=True, text=True, timeout=30
        )

        if roles_result.returncode == 0:
            roles = json.loads(roles_result.stdout)
            admin_roles = []

            for role in roles[:20]:  # Check first 20 roles
                attached = subprocess.run(
                    ["aws", "iam", "list-attached-role-policies", "--role-name", role,
                     "--query", "AttachedPolicies[].PolicyName", "--output", "json"],
                    capture_output=True, text=True, timeout=10
                )
                if attached.returncode == 0:
                    policies = json.loads(attached.stdout)
                    if any("Admin" in p for p in policies):
                        admin_roles.append(role)

            results.append(f"Roles with Admin policies: {len(admin_roles)}")
            for role in admin_roles[:5]:
                results.append(f"  - {role}")

        # Check for users with console access
        users_result = subprocess.run(
            ["aws", "iam", "list-users", "--query", "Users[].UserName", "--output", "json"],
            capture_output=True, text=True, timeout=30
        )

        if users_result.returncode == 0:
            users = json.loads(users_result.stdout)
            results.append(f"\nIAM Users: {len(users)}")

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

        # Check S3 public access
        buckets_result = subprocess.run(
            ["aws", "s3api", "list-buckets", "--query", "Buckets[].Name", "--output", "json"],
            capture_output=True, text=True, timeout=30
        )

        if buckets_result.returncode == 0:
            buckets = json.loads(buckets_result.stdout)
            public_buckets = []

            for bucket in buckets[:10]:
                pab_result = subprocess.run(
                    ["aws", "s3api", "get-public-access-block", "--bucket", bucket],
                    capture_output=True, text=True, timeout=10
                )
                if pab_result.returncode != 0:  # No public access block = potentially public
                    public_buckets.append(bucket)

            if public_buckets:
                results.append(f"S3 buckets without public access block: {len(public_buckets)}")
                for b in public_buckets[:5]:
                    results.append(f"  - {b}")
            else:
                results.append("S3: All checked buckets have public access block")

        # Check security groups with 0.0.0.0/0
        sg_result = subprocess.run(
            ["aws", "ec2", "describe-security-groups",
             "--query", "SecurityGroups[?IpPermissions[?contains(IpRanges[].CidrIp, '0.0.0.0/0')]].GroupId",
             "--output", "json"],
            capture_output=True, text=True, timeout=30
        )

        if sg_result.returncode == 0:
            open_sgs = json.loads(sg_result.stdout)
            results.append(f"\nSecurity groups with 0.0.0.0/0 ingress: {len(open_sgs)}")

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

        # Check for unattached EBS volumes
        ebs_result = subprocess.run(
            ["aws", "ec2", "describe-volumes",
             "--filters", "Name=status,Values=available",
             "--query", "Volumes[].{ID:VolumeId,Size:Size,AZ:AvailabilityZone}",
             "--output", "json"],
            capture_output=True, text=True, timeout=30
        )

        if ebs_result.returncode == 0:
            volumes = json.loads(ebs_result.stdout)
            results.append(f"Unattached EBS volumes: {len(volumes)}")
            for vol in volumes[:5]:
                results.append(f"  - {vol['ID']} ({vol['Size']}GB in {vol['AZ']})")

        # Check for unassociated Elastic IPs
        eip_result = subprocess.run(
            ["aws", "ec2", "describe-addresses",
             "--query", "Addresses[?AssociationId==null].{IP:PublicIp,AllocId:AllocationId}",
             "--output", "json"],
            capture_output=True, text=True, timeout=30
        )

        if eip_result.returncode == 0:
            eips = json.loads(eip_result.stdout)
            results.append(f"\nUnassociated Elastic IPs: {len(eips)}")
            for eip in eips[:5]:
                results.append(f"  - {eip['IP']} ({eip['AllocId']})")

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
        if stack_name:
            stacks = [stack_name]
        else:
            # List all active stacks
            list_result = subprocess.run(
                ["aws", "cloudformation", "list-stacks",
                 "--stack-status-filter", "CREATE_COMPLETE", "UPDATE_COMPLETE",
                 "--query", "StackSummaries[].StackName", "--output", "json"],
                capture_output=True, text=True, timeout=30
            )
            if list_result.returncode != 0:
                return f"Error listing stacks: {list_result.stderr}"
            stacks = json.loads(list_result.stdout)

        results = []
        for stack in stacks[:5]:  # Check first 5 stacks
            # Start drift detection
            detect_result = subprocess.run(
                ["aws", "cloudformation", "detect-stack-drift", "--stack-name", stack],
                capture_output=True, text=True, timeout=30
            )

            if detect_result.returncode == 0:
                drift_id = json.loads(detect_result.stdout).get("StackDriftDetectionId")

                # Wait briefly and check status
                import time
                time.sleep(2)

                status_result = subprocess.run(
                    ["aws", "cloudformation", "describe-stack-drift-detection-status",
                     "--stack-drift-detection-id", drift_id, "--output", "json"],
                    capture_output=True, text=True, timeout=30
                )

                if status_result.returncode == 0:
                    status = json.loads(status_result.stdout)
                    drift_status = status.get("StackDriftStatus", "UNKNOWN")
                    results.append(f"{stack}: {drift_status}")
            else:
                results.append(f"{stack}: Error - {detect_result.stderr[:50]}")

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
