"""K8s Agent - Kubernetes operations and Helm chart management."""

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage

from infra_agent.agents.base import BaseAgent
from infra_agent.config import get_aws_settings, get_settings
from infra_agent.core.state import AgentType, InfraAgentState


class K8sAgent(BaseAgent):
    """
    K8s Agent - Manages Kubernetes operations.

    Responsibilities:
    - Execute kubectl commands
    - Manage Helm chart deployments
    - Configure Istio service mesh
    - Deploy observability stack (Loki, Grafana, Tempo, Mimir, Prometheus, Kiali)
    """

    def __init__(self, **kwargs):
        """Initialize the K8s Agent."""
        super().__init__(agent_type=AgentType.K8S, **kwargs)
        self._helm_values_path = Path(__file__).parent.parent.parent.parent.parent / "infra" / "helm" / "values"
        self._kubeconfig_set = False

        # Register MCP tools for AWS and Git access
        self._register_mcp_tools()

    def _register_mcp_tools(self) -> None:
        """Register MCP tools for AWS API and Git repository access."""
        try:
            from infra_agent.mcp.client import get_aws_tools, get_git_tools
            self.register_tools(get_aws_tools())
            self.register_tools(get_git_tools())
        except Exception:
            pass  # MCP tools optional

    async def process_pipeline(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Process pipeline state for LangGraph workflow.

        Called by the LangGraph StateGraph for query requests.
        Handles kubectl and Helm queries.

        Args:
            state: PipelineState dictionary

        Returns:
            Updated state with query results
        """
        messages = state.get("messages", [])
        if not messages:
            return {"messages": [AIMessage(content="No query to process")]}

        # Get the last user message
        last_message = messages[-1]
        user_input = last_message.content if hasattr(last_message, "content") else str(last_message)

        # Ensure kubeconfig is set
        if not self._kubeconfig_set:
            self._setup_kubeconfig_simple()

        # Use tools for query execution
        query_prompt = f"""Execute this Kubernetes query and return the results:

Query: {user_input}

Use kubectl or helm commands as appropriate."""

        try:
            response, tool_calls = await self.invoke_with_tools(
                user_message=query_prompt,
                max_iterations=3,
            )

            return {"messages": [AIMessage(content=response)]}

        except Exception as e:
            # Fallback to direct handling
            response = await self._handle_query_direct(user_input.lower())
            return {"messages": [AIMessage(content=response)]}

    def _setup_kubeconfig_simple(self) -> None:
        """Simple kubeconfig setup without state."""
        settings = get_settings()
        aws_settings = get_aws_settings()
        cluster_name = settings.eks_cluster_name_computed

        try:
            subprocess.run(
                [
                    "aws", "eks", "update-kubeconfig",
                    "--name", cluster_name,
                    "--region", aws_settings.aws_region,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self._kubeconfig_set = True
        except Exception:
            pass

    async def _handle_query_direct(self, user_input: str) -> str:
        """Handle queries directly without tools."""
        if "pods" in user_input:
            namespace = self._extract_namespace(user_input) or "default"
            return self._kubectl_get("pods", namespace)
        elif "nodes" in user_input:
            return self._kubectl_get("nodes")
        elif "namespaces" in user_input:
            return self._kubectl_get("namespaces")
        elif "deployments" in user_input:
            namespace = self._extract_namespace(user_input)
            return self._kubectl_get("deployments", namespace)
        elif "services" in user_input:
            namespace = self._extract_namespace(user_input)
            return self._kubectl_get("services", namespace)
        elif "helm" in user_input and "list" in user_input:
            return self._helm_list(None)
        else:
            return f"Query not recognized: {user_input}"

    async def process(self, state: InfraAgentState) -> InfraAgentState:
        """
        Process K8s-related operations.

        Args:
            state: Current agent state

        Returns:
            Updated agent state
        """
        if not state.messages:
            return state

        last_message = state.messages[-1]
        if not isinstance(last_message, HumanMessage):
            return state

        user_input = last_message.content.lower()

        # Ensure kubeconfig is set
        if not self._kubeconfig_set:
            self._setup_kubeconfig(state)

        # Route to appropriate handler
        if "helm" in user_input:
            response = await self._handle_helm(user_input, state)
        elif "deploy" in user_input and "istio" in user_input:
            response = await self._handle_deploy_istio(state)
        elif "deploy" in user_input and ("lgtm" in user_input or "observability" in user_input):
            response = await self._handle_deploy_lgtm(state)
        elif "pods" in user_input or "get pods" in user_input:
            response = await self._handle_get_pods(user_input, state)
        elif "nodes" in user_input or "get nodes" in user_input:
            response = await self._handle_get_nodes(state)
        elif "namespaces" in user_input:
            response = await self._handle_get_namespaces(state)
        elif "logs" in user_input:
            response = await self._handle_get_logs(user_input, state)
        else:
            response = await self.invoke_llm(last_message.content, state)

        state.messages.append(AIMessage(content=response))
        return state

    def _setup_kubeconfig(self, state: InfraAgentState) -> None:
        """Set up kubeconfig for the EKS cluster."""
        settings = get_settings()
        aws_settings = get_aws_settings()

        cluster_name = settings.eks_cluster_name_computed

        try:
            # Update kubeconfig using AWS CLI
            result = subprocess.run(
                [
                    "aws", "eks", "update-kubeconfig",
                    "--name", cluster_name,
                    "--region", aws_settings.aws_region,
                ],
                capture_output=True,
                text=True,
                timeout=30,
                env={
                    "AWS_ACCESS_KEY_ID": aws_settings.aws_access_key_id,
                    "AWS_SECRET_ACCESS_KEY": aws_settings.aws_secret_access_key,
                    "AWS_REGION": aws_settings.aws_region,
                },
            )

            if result.returncode == 0:
                self._kubeconfig_set = True

        except Exception:
            pass  # Will retry on next command

    async def _handle_helm(self, user_input: str, state: InfraAgentState) -> str:
        """Handle Helm-related commands."""
        if "list" in user_input:
            return self._helm_list(state)
        elif "install" in user_input or "upgrade" in user_input:
            chart_name = self._extract_chart_name(user_input)
            if chart_name:
                return self._helm_install(chart_name, state)
            return "Please specify which Helm chart to install (e.g., 'helm install istio')"
        elif "status" in user_input:
            release_name = self._extract_release_name(user_input)
            if release_name:
                return self._helm_status(release_name, state)
            return "Please specify which release to check status (e.g., 'helm status istio-base')"
        else:
            return "Available Helm commands: list, install <chart>, upgrade <chart>, status <release>"

    async def _handle_deploy_istio(self, state: InfraAgentState) -> str:
        """Deploy Istio service mesh."""
        settings = get_settings()
        results = []

        results.append("**Deploying Istio Service Mesh**\n")

        # Step 1: Install Istio Base
        results.append("Step 1: Installing istio-base...")
        base_result = self._helm_install_chart(
            release_name="istio-base",
            chart="base",
            repo="https://istio-release.storage.googleapis.com/charts",
            namespace="istio-system",
            values_file=self._helm_values_path / "istio" / "base-values.yaml",
            create_namespace=True,
        )
        results.append(base_result)

        # Step 2: Install Istiod
        results.append("\nStep 2: Installing istiod...")
        istiod_result = self._helm_install_chart(
            release_name="istiod",
            chart="istiod",
            repo="https://istio-release.storage.googleapis.com/charts",
            namespace="istio-system",
            values_file=self._helm_values_path / "istio" / "istiod-values.yaml",
        )
        results.append(istiod_result)

        # Step 3: Install Istio Ingress Gateway
        results.append("\nStep 3: Installing istio-ingress...")
        ingress_result = self._helm_install_chart(
            release_name="istio-ingress",
            chart="gateway",
            repo="https://istio-release.storage.googleapis.com/charts",
            namespace="istio-system",
            values_file=self._helm_values_path / "istio" / "gateway-values.yaml",
        )
        results.append(ingress_result)

        self.log_action(
            state=state,
            action="deploy_istio",
            success=True,
            resource_type="helm_release",
            resource_id="istio",
        )

        return "\n".join(results)

    async def _handle_deploy_lgtm(self, state: InfraAgentState) -> str:
        """Deploy observability stack (Loki, Grafana, Mimir, Prometheus, Kiali)."""
        results = []

        results.append("**Deploying Observability Stack**\n")

        # Create observability namespace
        self._kubectl_apply_namespace("observability")

        # Step 1: Install Loki (Logs)
        results.append("Step 1: Installing Loki (Logs)...")
        loki_result = self._helm_install_chart(
            release_name="loki",
            chart="loki",
            repo="https://grafana.github.io/helm-charts",
            namespace="observability",
            values_file=self._helm_values_path / "lgtm" / "loki-values.yaml",
            create_namespace=True,
        )
        results.append(loki_result)

        # Step 2: Install Prometheus (Metrics Scraping)
        results.append("\nStep 2: Installing Prometheus (Metrics Scraping)...")
        prometheus_result = self._helm_install_chart(
            release_name="prometheus",
            chart="prometheus",
            repo="https://prometheus-community.github.io/helm-charts",
            namespace="observability",
            values_file=self._helm_values_path / "lgtm" / "prometheus-values.yaml",
        )
        results.append(prometheus_result)

        # Step 3: Install Mimir with Kafka (Metrics Storage)
        results.append("\nStep 3: Installing Mimir with Kafka (Metrics Storage)...")
        mimir_result = self._helm_install_chart(
            release_name="mimir",
            chart="mimir-distributed",
            repo="https://grafana.github.io/helm-charts",
            namespace="observability",
            values_file=self._helm_values_path / "lgtm" / "mimir-values.yaml",
        )
        results.append(mimir_result)

        # Step 4: Install Tempo (Distributed Tracing)
        results.append("\nStep 4: Installing Tempo (Distributed Tracing)...")
        tempo_result = self._helm_install_chart(
            release_name="tempo",
            chart="tempo",
            repo="https://grafana.github.io/helm-charts",
            namespace="observability",
            values_file=self._helm_values_path / "lgtm" / "tempo-values.yaml",
        )
        results.append(tempo_result)

        # Step 5: Install Grafana (Dashboards)
        results.append("\nStep 5: Installing Grafana (Dashboards)...")
        grafana_result = self._helm_install_chart(
            release_name="grafana",
            chart="grafana",
            repo="https://grafana.github.io/helm-charts",
            namespace="observability",
            values_file=self._helm_values_path / "lgtm" / "grafana-values.yaml",
        )
        results.append(grafana_result)

        # Step 6: Install Kiali (Istio Traffic Visualization)
        results.append("\nStep 6: Installing Kiali (Traffic Visualization)...")
        kiali_result = self._helm_install_chart(
            release_name="kiali",
            chart="kiali-operator",
            repo="https://kiali.org/helm-charts",
            namespace="istio-system",
            values_file=self._helm_values_path / "kiali" / "values.yaml",
        )
        results.append(kiali_result)

        self.log_action(
            state=state,
            action="deploy_observability",
            success=True,
            resource_type="helm_release",
            resource_id="observability-stack",
        )

        return "\n".join(results)

    async def _handle_get_pods(self, user_input: str, state: InfraAgentState) -> str:
        """Get pods in a namespace."""
        namespace = self._extract_namespace(user_input) or "default"
        return self._kubectl_get("pods", namespace)

    async def _handle_get_nodes(self, state: InfraAgentState) -> str:
        """Get cluster nodes."""
        return self._kubectl_get("nodes")

    async def _handle_get_namespaces(self, state: InfraAgentState) -> str:
        """Get cluster namespaces."""
        return self._kubectl_get("namespaces")

    async def _handle_get_logs(self, user_input: str, state: InfraAgentState) -> str:
        """Get pod logs."""
        # Extract pod name and namespace from input
        parts = user_input.split()
        pod_name = None
        namespace = "default"

        for i, part in enumerate(parts):
            if part == "logs" and i + 1 < len(parts):
                pod_name = parts[i + 1]
            if part in ["-n", "--namespace"] and i + 1 < len(parts):
                namespace = parts[i + 1]

        if not pod_name:
            return "Please specify a pod name (e.g., 'logs my-pod -n my-namespace')"

        return self._kubectl_logs(pod_name, namespace)

    def _helm_list(self, state: InfraAgentState) -> str:
        """List Helm releases."""
        try:
            result = subprocess.run(
                ["helm", "list", "-A", "-o", "json"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                return f"Error listing Helm releases: {result.stderr}"

            releases = json.loads(result.stdout) if result.stdout else []

            if not releases:
                return "No Helm releases found"

            lines = ["**Helm Releases:**\n"]
            lines.append(f"{'Name':<25} {'Namespace':<20} {'Chart':<30} {'Status'}")
            lines.append("-" * 95)

            for release in releases:
                name = release.get("name", "")
                namespace = release.get("namespace", "")
                chart = release.get("chart", "")
                status = release.get("status", "")
                lines.append(f"{name:<25} {namespace:<20} {chart:<30} {status}")

            return "\n".join(lines)

        except FileNotFoundError:
            return "⚠ Helm not installed. Install from: https://helm.sh/docs/intro/install/"
        except Exception as e:
            return f"Error: {str(e)}"

    def _helm_install(self, chart_name: str, state: InfraAgentState) -> str:
        """Install a Helm chart by name."""
        chart_configs = {
            "istio": ("istio-base", "base", "https://istio-release.storage.googleapis.com/charts", "istio-system"),
            "istiod": ("istiod", "istiod", "https://istio-release.storage.googleapis.com/charts", "istio-system"),
            "loki": ("loki", "loki", "https://grafana.github.io/helm-charts", "observability"),
            "grafana": ("grafana", "grafana", "https://grafana.github.io/helm-charts", "observability"),
            "prometheus": ("prometheus", "prometheus", "https://prometheus-community.github.io/helm-charts", "observability"),
            "mimir": ("mimir", "mimir-distributed", "https://grafana.github.io/helm-charts", "observability"),
            "tempo": ("tempo", "tempo", "https://grafana.github.io/helm-charts", "observability"),
            "kiali": ("kiali", "kiali-operator", "https://kiali.org/helm-charts", "istio-system"),
            "trivy": ("trivy-operator", "trivy-operator", "https://aquasecurity.github.io/helm-charts", "trivy-system"),
            "velero": ("velero", "velero", "https://vmware-tanzu.github.io/helm-charts", "velero"),
            "kubecost": ("kubecost", "cost-analyzer", "https://kubecost.github.io/cost-analyzer", "kubecost"),
            "headlamp": ("headlamp", "headlamp", "https://headlamp-k8s.github.io/headlamp", "headlamp"),
        }

        config = chart_configs.get(chart_name.lower())
        if not config:
            return f"Unknown chart: {chart_name}. Available: {', '.join(chart_configs.keys())}"

        release_name, chart, repo, namespace = config

        # Find values file
        values_dir = chart_name.lower()
        if chart_name.lower() in ["loki", "grafana", "mimir", "tempo", "prometheus"]:
            values_dir = "lgtm"
        values_file = self._helm_values_path / values_dir / f"{chart_name.lower()}-values.yaml"

        return self._helm_install_chart(
            release_name=release_name,
            chart=chart,
            repo=repo,
            namespace=namespace,
            values_file=values_file if values_file.exists() else None,
            create_namespace=True,
        )

    def _helm_install_chart(
        self,
        release_name: str,
        chart: str,
        repo: str,
        namespace: str,
        values_file: Optional[Path] = None,
        create_namespace: bool = False,
    ) -> str:
        """Install or upgrade a Helm chart."""
        try:
            cmd = [
                "helm", "upgrade", "--install",
                release_name, chart,
                "--repo", repo,
                "--namespace", namespace,
                "--wait", "--timeout", "10m",
            ]

            if create_namespace:
                cmd.append("--create-namespace")

            if values_file and values_file.exists():
                cmd.extend(["-f", str(values_file)])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes
            )

            if result.returncode == 0:
                return f"✓ {release_name} installed successfully"
            else:
                return f"✗ Failed to install {release_name}: {result.stderr}"

        except subprocess.TimeoutExpired:
            return f"⚠ Installation of {release_name} timed out"
        except FileNotFoundError:
            return "⚠ Helm not installed"
        except Exception as e:
            return f"✗ Error: {str(e)}"

    def _helm_status(self, release_name: str, state: InfraAgentState) -> str:
        """Get Helm release status."""
        try:
            result = subprocess.run(
                ["helm", "status", release_name, "-A"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                return result.stdout
            else:
                return f"Error getting status: {result.stderr}"

        except Exception as e:
            return f"Error: {str(e)}"

    def _check_tunnel_error(self, stderr: str) -> Optional[str]:
        """Check if error is due to missing SSM tunnel and return helpful message."""
        tunnel_indicators = [
            "connection refused",
            "localhost:6443",
            "Unable to connect to the server",
            "dial tcp",
            "no such host",
        ]
        if any(indicator in stderr.lower() for indicator in tunnel_indicators):
            return (
                "**SSM Tunnel Required**\n\n"
                "The EKS cluster has a private endpoint. Start the tunnel first:\n\n"
                "```bash\n"
                "./scripts/tunnel.sh\n"
                "```\n\n"
                "Keep the tunnel running in a separate terminal, then try again."
            )
        return None

    def _kubectl_get(self, resource: str, namespace: Optional[str] = None) -> str:
        """Execute kubectl get command."""
        try:
            cmd = ["kubectl", "get", resource, "-o", "wide"]
            if namespace:
                cmd.extend(["-n", namespace])
            else:
                cmd.append("-A")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                return f"**{resource.title()}:**\n```\n{result.stdout}\n```"
            else:
                # Check for tunnel error first
                tunnel_msg = self._check_tunnel_error(result.stderr)
                if tunnel_msg:
                    return tunnel_msg
                return f"Error: {result.stderr}"

        except FileNotFoundError:
            return "⚠ kubectl not installed"
        except Exception as e:
            return f"Error: {str(e)}"

    def _kubectl_logs(self, pod_name: str, namespace: str, tail: int = 100) -> str:
        """Get pod logs."""
        try:
            result = subprocess.run(
                ["kubectl", "logs", pod_name, "-n", namespace, "--tail", str(tail)],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                return f"**Logs for {pod_name}:**\n```\n{result.stdout}\n```"
            else:
                tunnel_msg = self._check_tunnel_error(result.stderr)
                if tunnel_msg:
                    return tunnel_msg
                return f"Error: {result.stderr}"

        except Exception as e:
            return f"Error: {str(e)}"

    def _kubectl_apply_namespace(self, namespace: str) -> str:
        """Create a namespace if it doesn't exist."""
        try:
            subprocess.run(
                ["kubectl", "create", "namespace", namespace],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return f"Namespace {namespace} created/verified"
        except Exception:
            return f"Namespace {namespace} may already exist"

    def _extract_chart_name(self, user_input: str) -> Optional[str]:
        """Extract chart name from user input."""
        charts = ["istio", "istiod", "loki", "grafana", "tempo", "mimir", "trivy", "velero", "kubecost", "headlamp"]
        for chart in charts:
            if chart in user_input.lower():
                return chart
        return None

    def _extract_release_name(self, user_input: str) -> Optional[str]:
        """Extract release name from user input."""
        parts = user_input.split()
        for i, part in enumerate(parts):
            if part == "status" and i + 1 < len(parts):
                return parts[i + 1]
        return None

    def _extract_namespace(self, user_input: str) -> Optional[str]:
        """Extract namespace from user input."""
        parts = user_input.split()
        for i, part in enumerate(parts):
            if part in ["-n", "--namespace", "namespace"] and i + 1 < len(parts):
                return parts[i + 1]

        # Check for known namespaces
        namespaces = ["istio-system", "observability", "kube-system", "default", "trivy-system", "velero", "kubecost"]
        for ns in namespaces:
            if ns in user_input:
                return ns

        return None
