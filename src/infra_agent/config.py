"""Configuration management for the Infrastructure Agent."""

from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Deployment environments."""

    DEV = "dev"
    TST = "tst"
    PRD = "prd"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="INFRA_AGENT_",
    )

    # Environment
    environment: Environment = Field(default=Environment.DEV, description="Deployment environment")

    # AWS Configuration
    aws_region: str = Field(default="us-east-1", description="AWS region")
    aws_profile: Optional[str] = Field(default=None, description="AWS profile name")

    # Bedrock Configuration
    bedrock_model_id: str = Field(
        default="anthropic.claude-3-sonnet-20240229-v1:0",
        description="Bedrock model ID for Claude",
    )
    bedrock_max_tokens: int = Field(default=4096, description="Max tokens for LLM response")

    # EKS Configuration
    eks_cluster_name: str = Field(
        default="infra-agent-dev-cluster", description="EKS cluster name"
    )

    # Project Configuration
    project_name: str = Field(default="infra-agent", description="Project name for resource naming")

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

    @property
    def resource_prefix(self) -> str:
        """Generate resource prefix following kebab-case naming convention."""
        return f"{self.project_name}-{self.environment.value}"

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == Environment.PRD


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
