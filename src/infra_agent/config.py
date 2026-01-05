"""Configuration management for the Infrastructure Agent."""

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Deployment environments."""

    DEV = "dev"
    TST = "tst"
    PRD = "prd"


class AWSSettings(BaseSettings):
    """AWS-specific settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # AWS Credentials (loaded from standard AWS env vars)
    aws_access_key_id: Optional[str] = Field(default=None, description="AWS Access Key ID")
    aws_secret_access_key: Optional[str] = Field(default=None, description="AWS Secret Access Key")
    aws_session_token: Optional[str] = Field(default=None, description="AWS Session Token (for temporary credentials)")
    aws_region: str = Field(default="us-east-1", description="AWS region")
    aws_account_id: Optional[str] = Field(default=None, description="AWS Account ID")
    aws_profile: Optional[str] = Field(default=None, description="AWS profile name")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Environment
    environment: Environment = Field(default=Environment.DEV, description="Deployment environment")

    # Project Configuration
    project_name: str = Field(default="infra-agent", description="Project name for resource naming")
    owner: str = Field(default="platform-team", description="Team or individual owner")

    # AWS Configuration (delegated to AWSSettings)
    aws_region: str = Field(default="us-east-1", description="AWS region")
    aws_account_id: Optional[str] = Field(default=None, description="AWS Account ID")

    # Domain Configuration
    domain_name: Optional[str] = Field(default=None, description="Base domain name")
    hosted_zone_id: Optional[str] = Field(default=None, description="Route53 Hosted Zone ID")

    # Bedrock Configuration
    bedrock_model_id: str = Field(
        default="anthropic.claude-3-5-sonnet-20241022-v2:0",
        description="Bedrock model ID for Claude",
    )
    bedrock_region: str = Field(default="us-east-1", description="AWS region for Bedrock")
    bedrock_max_tokens: int = Field(default=4096, description="Max tokens for LLM response")

    # EKS Configuration
    eks_cluster_name: Optional[str] = Field(default=None, description="EKS cluster name")
    eks_cluster_version: str = Field(default="1.32", description="EKS Kubernetes version")

    # Database Configuration
    database_host: Optional[str] = Field(default=None, description="RDS database host")
    database_port: int = Field(default=5432, description="Database port")
    database_name: str = Field(default="infra_agent", description="Database name")
    database_user: Optional[str] = Field(default=None, description="Database username")
    database_password: Optional[str] = Field(default=None, description="Database password")

    # S3 Buckets
    velero_bucket: Optional[str] = Field(default=None, description="S3 bucket for Velero backups")
    logs_bucket: Optional[str] = Field(default=None, description="S3 bucket for logs")

    # Observability URLs
    grafana_url: Optional[str] = Field(default=None, description="Grafana dashboard URL")
    loki_url: Optional[str] = Field(default=None, description="Loki logs URL")
    tempo_url: Optional[str] = Field(default=None, description="Tempo traces URL")
    headlamp_url: Optional[str] = Field(default=None, description="Headlamp admin console URL")

    # Network Configuration
    allowed_cidr_blocks: str = Field(
        default="10.0.0.0/8", description="Allowed CIDR blocks for bastion access"
    )

    # Compliance
    nist_controls_enabled: bool = Field(
        default=True, description="Enable NIST 800-53 R5 compliance checks"
    )

    # MFA
    mfa_required_for_prd: bool = Field(
        default=True, description="Require MFA for production operations"
    )

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")

    # IaC Version
    iac_version: str = Field(default="1.0.0", description="Infrastructure as Code version")

    @property
    def resource_prefix(self) -> str:
        """Generate resource prefix following kebab-case naming convention."""
        return f"{self.project_name}-{self.environment.value}"

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == Environment.PRD

    @property
    def eks_cluster_name_computed(self) -> str:
        """Get EKS cluster name, computing default if not set."""
        if self.eks_cluster_name:
            return self.eks_cluster_name
        return f"{self.resource_prefix}-cluster"

    @property
    def allowed_cidr_list(self) -> list[str]:
        """Get allowed CIDR blocks as a list."""
        return [cidr.strip() for cidr in self.allowed_cidr_blocks.split(",")]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


@lru_cache
def get_aws_settings() -> AWSSettings:
    """Get cached AWS settings instance."""
    return AWSSettings()


def get_env_file_path() -> Path:
    """Get the path to the .env file."""
    return Path(__file__).parent.parent.parent / ".env"
