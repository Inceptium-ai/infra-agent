"""CloudFormation template validators for NIST compliance."""

import re
from pathlib import Path
from typing import Any

import yaml


class NistValidator:
    """
    Validates CloudFormation templates for NIST 800-53 Rev 5 compliance.

    This provides Python-based validation in addition to cfn-guard rules
    for more complex validation scenarios.
    """

    REQUIRED_TAGS = ["Environment", "Owner", "SecurityLevel", "IaC_Version"]
    VALID_ENVIRONMENTS = ["dev", "tst", "prd"]
    VALID_SECURITY_LEVELS = ["public", "internal", "confidential", "restricted"]

    def __init__(self, template_path: Path):
        """Initialize validator with template path."""
        self.template_path = template_path
        self.template = self._load_template()
        self.violations: list[dict[str, Any]] = []

    def _load_template(self) -> dict:
        """Load and parse CloudFormation template."""
        with open(self.template_path) as f:
            return yaml.safe_load(f)

    def validate_all(self) -> list[dict[str, Any]]:
        """Run all NIST validations and return violations."""
        self.violations = []

        self._validate_cm8_tagging()
        self._validate_ac6_iam_policies()
        self._validate_sc7_security_groups()
        self._validate_sc8_encryption()
        self._validate_au2_logging()
        self._validate_sc28_encryption_at_rest()

        return self.violations

    def _validate_cm8_tagging(self) -> None:
        """CM-8: Validate mandatory tags on all resources."""
        resources = self.template.get("Resources", {})

        for resource_name, resource_def in resources.items():
            resource_type = resource_def.get("Type", "")
            properties = resource_def.get("Properties", {})

            # Skip resources that don't support tags
            if resource_type in [
                "AWS::EC2::SubnetRouteTableAssociation",
                "AWS::EC2::SubnetNetworkAclAssociation",
                "AWS::EC2::VPCGatewayAttachment",
                "AWS::EC2::Route",
                "AWS::EC2::NetworkAclEntry",
                "AWS::EC2::SecurityGroupIngress",
                "AWS::EC2::SecurityGroupEgress",
            ]:
                continue

            tags = properties.get("Tags", [])

            # Handle both list format and intrinsic functions
            if isinstance(tags, list):
                tag_keys = [tag.get("Key") for tag in tags if isinstance(tag, dict)]

                for required_tag in self.REQUIRED_TAGS:
                    if required_tag not in tag_keys:
                        self.violations.append({
                            "control": "CM-8",
                            "resource": resource_name,
                            "resource_type": resource_type,
                            "severity": "MEDIUM",
                            "message": f"Missing required tag: {required_tag}",
                        })

    def _validate_ac6_iam_policies(self) -> None:
        """AC-6: Validate least privilege in IAM policies."""
        resources = self.template.get("Resources", {})

        for resource_name, resource_def in resources.items():
            resource_type = resource_def.get("Type", "")

            if resource_type not in ["AWS::IAM::Role", "AWS::IAM::Policy"]:
                continue

            properties = resource_def.get("Properties", {})

            # Check inline policies
            policies = properties.get("Policies", [])
            for policy in policies:
                policy_doc = policy.get("PolicyDocument", {})
                self._check_policy_document(resource_name, policy_doc)

            # Check assume role policy
            assume_policy = properties.get("AssumeRolePolicyDocument", {})
            if not assume_policy:
                self.violations.append({
                    "control": "AC-2",
                    "resource": resource_name,
                    "resource_type": resource_type,
                    "severity": "HIGH",
                    "message": "IAM Role missing AssumeRolePolicyDocument",
                })

    def _check_policy_document(self, resource_name: str, policy_doc: dict) -> None:
        """Check IAM policy document for violations."""
        statements = policy_doc.get("Statement", [])

        for statement in statements:
            actions = statement.get("Action", [])
            resources = statement.get("Resource", [])
            effect = statement.get("Effect", "")

            # Normalize to lists
            if isinstance(actions, str):
                actions = [actions]
            if isinstance(resources, str):
                resources = [resources]

            # Check for wildcard actions
            if "*" in actions:
                self.violations.append({
                    "control": "AC-6",
                    "resource": resource_name,
                    "resource_type": "IAM Policy",
                    "severity": "CRITICAL",
                    "message": "Policy uses wildcard (*) action",
                })

            # Check for wildcard resources in Allow statements
            if effect == "Allow" and "*" in resources:
                # Check if it's an admin action
                admin_actions = [a for a in actions if any(
                    x in a.lower() for x in ["create", "delete", "update", "put", "attach"]
                )]
                if admin_actions:
                    self.violations.append({
                        "control": "AC-6",
                        "resource": resource_name,
                        "resource_type": "IAM Policy",
                        "severity": "HIGH",
                        "message": f"Policy allows {admin_actions[0]} on wildcard resource",
                    })

    def _validate_sc7_security_groups(self) -> None:
        """SC-7: Validate security group boundary protection."""
        resources = self.template.get("Resources", {})

        for resource_name, resource_def in resources.items():
            if resource_def.get("Type") != "AWS::EC2::SecurityGroup":
                continue

            properties = resource_def.get("Properties", {})
            ingress_rules = properties.get("SecurityGroupIngress", [])

            for rule in ingress_rules:
                cidr = rule.get("CidrIp", "")
                cidr_v6 = rule.get("CidrIpv6", "")
                from_port = rule.get("FromPort")
                to_port = rule.get("ToPort")

                # Check for unrestricted access
                if cidr == "0.0.0.0/0" or cidr_v6 == "::/0":
                    # Port 443 (HTTPS) is acceptable from internet
                    if from_port == 443 and to_port == 443:
                        continue

                    # Port 80 (HTTP) is not acceptable
                    if from_port == 80 or to_port == 80:
                        self.violations.append({
                            "control": "SC-8",
                            "resource": resource_name,
                            "resource_type": "AWS::EC2::SecurityGroup",
                            "severity": "HIGH",
                            "message": "Security group allows unencrypted HTTP from internet",
                        })

                    # Port 22 (SSH) from internet is critical
                    if from_port == 22 or to_port == 22:
                        self.violations.append({
                            "control": "SC-7",
                            "resource": resource_name,
                            "resource_type": "AWS::EC2::SecurityGroup",
                            "severity": "CRITICAL",
                            "message": "Security group allows SSH from internet (0.0.0.0/0)",
                        })

                    # All ports from internet
                    if from_port == 0 and to_port == 65535:
                        self.violations.append({
                            "control": "SC-7",
                            "resource": resource_name,
                            "resource_type": "AWS::EC2::SecurityGroup",
                            "severity": "CRITICAL",
                            "message": "Security group allows all ports from internet",
                        })

    def _validate_sc8_encryption(self) -> None:
        """SC-8: Validate transmission confidentiality (TLS)."""
        resources = self.template.get("Resources", {})

        for resource_name, resource_def in resources.items():
            resource_type = resource_def.get("Type", "")

            # Check ALB listeners
            if resource_type == "AWS::ElasticLoadBalancingV2::Listener":
                properties = resource_def.get("Properties", {})
                protocol = properties.get("Protocol", "")
                port = properties.get("Port", 0)

                if protocol == "HTTP" and port == 80:
                    self.violations.append({
                        "control": "SC-8",
                        "resource": resource_name,
                        "resource_type": resource_type,
                        "severity": "HIGH",
                        "message": "ALB listener uses unencrypted HTTP",
                    })

    def _validate_au2_logging(self) -> None:
        """AU-2: Validate audit logging is enabled."""
        resources = self.template.get("Resources", {})

        # Check for VPC Flow Logs
        has_vpc = any(r.get("Type") == "AWS::EC2::VPC" for r in resources.values())
        has_flow_log = any(r.get("Type") == "AWS::EC2::FlowLog" for r in resources.values())

        if has_vpc and not has_flow_log:
            self.violations.append({
                "control": "AU-2",
                "resource": "VPC",
                "resource_type": "AWS::EC2::VPC",
                "severity": "HIGH",
                "message": "VPC does not have Flow Logs enabled",
            })

        # Check Flow Log traffic type
        for resource_name, resource_def in resources.items():
            if resource_def.get("Type") == "AWS::EC2::FlowLog":
                properties = resource_def.get("Properties", {})
                traffic_type = properties.get("TrafficType", "")

                if traffic_type != "ALL":
                    self.violations.append({
                        "control": "AU-3",
                        "resource": resource_name,
                        "resource_type": "AWS::EC2::FlowLog",
                        "severity": "MEDIUM",
                        "message": f"Flow Log should capture ALL traffic, not just {traffic_type}",
                    })

    def _validate_sc28_encryption_at_rest(self) -> None:
        """SC-28: Validate encryption at rest."""
        resources = self.template.get("Resources", {})

        for resource_name, resource_def in resources.items():
            resource_type = resource_def.get("Type", "")
            properties = resource_def.get("Properties", {})

            # Check S3 buckets
            if resource_type == "AWS::S3::Bucket":
                encryption = properties.get("BucketEncryption")
                if not encryption:
                    self.violations.append({
                        "control": "SC-28",
                        "resource": resource_name,
                        "resource_type": resource_type,
                        "severity": "HIGH",
                        "message": "S3 bucket does not have encryption enabled",
                    })

            # Check RDS instances
            if resource_type == "AWS::RDS::DBInstance":
                encrypted = properties.get("StorageEncrypted", False)
                if not encrypted:
                    self.violations.append({
                        "control": "SC-28",
                        "resource": resource_name,
                        "resource_type": resource_type,
                        "severity": "CRITICAL",
                        "message": "RDS instance does not have storage encryption enabled",
                    })

            # Check EBS volumes
            if resource_type == "AWS::EC2::Volume":
                encrypted = properties.get("Encrypted", False)
                if not encrypted:
                    self.violations.append({
                        "control": "SC-28",
                        "resource": resource_name,
                        "resource_type": resource_type,
                        "severity": "HIGH",
                        "message": "EBS volume is not encrypted",
                    })

    def get_report(self) -> str:
        """Generate a human-readable compliance report."""
        if not self.violations:
            return "✓ All NIST 800-53 Rev 5 controls passed"

        lines = ["**NIST 800-53 Rev 5 Compliance Report**\n"]
        lines.append(f"Template: {self.template_path.name}")
        lines.append(f"Violations: {len(self.violations)}\n")

        # Group by severity
        critical = [v for v in self.violations if v["severity"] == "CRITICAL"]
        high = [v for v in self.violations if v["severity"] == "HIGH"]
        medium = [v for v in self.violations if v["severity"] == "MEDIUM"]

        if critical:
            lines.append("**CRITICAL:**")
            for v in critical:
                lines.append(f"  [{v['control']}] {v['resource']}: {v['message']}")

        if high:
            lines.append("\n**HIGH:**")
            for v in high:
                lines.append(f"  [{v['control']}] {v['resource']}: {v['message']}")

        if medium:
            lines.append("\n**MEDIUM:**")
            for v in medium:
                lines.append(f"  [{v['control']}] {v['resource']}: {v['message']}")

        return "\n".join(lines)


def validate_template(template_path: Path) -> tuple[bool, str]:
    """
    Validate a CloudFormation template for NIST compliance.

    Args:
        template_path: Path to the template file

    Returns:
        Tuple of (passed, report)
    """
    validator = NistValidator(template_path)
    violations = validator.validate_all()

    passed = len(violations) == 0
    report = validator.get_report()

    return passed, report
