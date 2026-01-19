# Infra-Agent Requirements

This document defines the functional requirements for the AI Infrastructure Agent.

---

## 1. Core Pipeline Requirements (AGT-001 to AGT-009)

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-001 | Pipeline SHALL use LangGraph StateGraph for workflow orchestration | Must | Implemented | `core/graph.py` |
| AGT-002 | Pipeline SHALL support async execution | Must | Implemented | `core/graph.py` |
| AGT-003 | Pipeline SHALL maintain conversation state across agent transitions | Must | Implemented | `PipelineState` TypedDict |
| AGT-004 | Pipeline SHALL classify user intent (change/query/conversation) | Must | Implemented | `core/router.py` |
| AGT-005 | Pipeline SHALL support retry loops (Review → IaC) with max 3 attempts | Must | Implemented | `route_from_review()` |
| AGT-006 | Pipeline SHALL support dry-run mode (no deployment) | Must | Implemented | `dry_run` flag |
| AGT-007 | Pipeline SHALL produce artifacts in `.infra-agent/requests/{id}/` | Must | Implemented | All agents |
| AGT-008 | Pipeline SHALL require approval gates for PRD changes | Must | Implemented | `requires_approval` |
| AGT-009 | Pipeline SHALL support Ctrl+C cancellation at any stage | Should | Implemented | Signal handling |

---

## 2. Chat Agent / Orchestrator Requirements (AGT-010 to AGT-019)

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-010 | Orchestrator SHALL classify user intent using keywords and LLM fallback | Must | Implemented | `agents/chat/agent.py` |
| AGT-011 | Orchestrator SHALL route change requests to Planning Agent | Must | Implemented | `route_from_orchestrator()` |
| AGT-012 | Orchestrator SHALL route query requests to K8s Agent | Must | Implemented | `route_from_orchestrator()` |
| AGT-013 | Orchestrator SHALL handle conversational requests directly | Should | Implemented | `route_from_orchestrator()` |
| AGT-014 | Orchestrator SHALL provide real-time progress feedback | Should | Implemented | `ProgressCallback` |
| AGT-015 | Orchestrator SHALL support `/status` command for task tracking | Should | Implemented | `show_status()` |
| AGT-016 | Orchestrator SHALL use exact word matching for intent classification | Must | Implemented | Regex `\b\w+\b` |
| AGT-017 | Orchestrator SHALL route drift queries to combined Git+AWS tools | Must | Implemented | `_handle_drift_query()` |
| AGT-018 | Orchestrator SHALL avoid duplicate tool registration | Must | Implemented | Check `_tool_map` |
| AGT-019 | Orchestrator SHALL load tools dynamically based on query type | Should | Implemented | Lazy loading |

---

## 3. Planning Agent Requirements (AGT-020 to AGT-029)

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-020 | Planning Agent SHALL generate requirements from user request | Must | Implemented | `agents/planning/agent.py` |
| AGT-021 | Planning Agent SHALL generate testable acceptance criteria | Must | Implemented | `AcceptanceCriteria` model |
| AGT-022 | Planning Agent SHALL identify files to modify | Must | Implemented | `FileToModify` model |
| AGT-023 | Planning Agent SHALL map requirements to NIST controls | Should | Implemented | `Requirement.nist_controls` |
| AGT-024 | Planning Agent SHALL assess impact level (low/medium/high) | Must | Implemented | `PlanningOutput.estimated_impact` |
| AGT-025 | Planning Agent SHALL flag PRD changes as requiring approval | Must | Implemented | `PlanningOutput.requires_approval` |
| AGT-026 | Planning Agent SHALL estimate monthly cost impact | Should | Implemented | `estimated_monthly_cost` |
| AGT-027 | Planning Agent SHALL output structured YAML (`requirements.yaml`) | Must | Implemented | Pydantic serialization |

---

## 4. IaC Agent Requirements (AGT-030 to AGT-039)

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-030 | IaC Agent SHALL implement changes based on PlanningOutput | Must | Implemented | `agents/iac/agent.py` |
| AGT-031 | IaC Agent SHALL modify CloudFormation templates | Must | Implemented | `_generate_file_change()` |
| AGT-032 | IaC Agent SHALL modify Helm values files | Must | Implemented | `_generate_file_change()` |
| AGT-033 | IaC Agent SHALL self-validate with cfn-lint before Review | Must | Implemented | `_validate_with_cfn_lint()` |
| AGT-034 | IaC Agent SHALL self-validate with kube-linter before Review | Must | Implemented | `_validate_with_kube_linter()` |
| AGT-035 | IaC Agent SHALL create feature branch per environment | Must | Implemented | `GitBranchConfig` |
| AGT-036 | IaC Agent SHALL commit changes with Co-Authored-By | Must | Implemented | `_create_git_commit()` |
| AGT-037 | IaC Agent SHALL push to remote origin | Must | Implemented | `_create_git_commit()` |
| AGT-038 | IaC Agent SHALL create pull request | Should | Implemented | `_create_pull_request()` |
| AGT-039 | IaC Agent SHALL retry on validation failure (max 3 times) | Must | Implemented | Retry loop |

---

## 5. Review Agent Requirements (AGT-040 to AGT-049)

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-040 | Review Agent SHALL run cfn-guard for NIST compliance | Must | Implemented | `agents/review/agent.py` |
| AGT-041 | Review Agent SHALL run cfn-lint for CloudFormation best practices | Must | Implemented | `_run_cfn_lint()` |
| AGT-042 | Review Agent SHALL run kube-linter for Kubernetes best practices | Must | Implemented | `_run_kube_linter()` |
| AGT-043 | Review Agent SHALL scan for exposed secrets | Must | Implemented | `_security_scan()` |
| AGT-044 | Review Agent SHALL estimate cost impact | Should | Implemented | `_estimate_cost()` |
| AGT-045 | Review Agent SHALL return PASS/FAIL/NEEDS_REVISION status | Must | Implemented | `ReviewStatus` enum |
| AGT-046 | Review Agent SHALL provide detailed findings for failures | Must | Implemented | `ReviewOutput.findings` |
| AGT-047 | Review Agent SHALL output structured YAML (`review.yaml`) | Must | Implemented | Pydantic serialization |

---

## 6. Deploy & Validate Agent Requirements (AGT-050 to AGT-059)

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-050 | Deploy Agent SHALL execute CloudFormation deployments | Must | Implemented | `agents/deploy_validate/agent.py` |
| AGT-051 | Deploy Agent SHALL execute Helm upgrades | Must | Implemented | `_deploy_helm()` |
| AGT-052 | Deploy Agent SHALL run acceptance criteria tests | Must | Implemented | `_run_validation()` |
| AGT-053 | Deploy Agent SHALL report SUCCESS/FAILURE status | Must | Implemented | `ValidationOutput.status` |
| AGT-054 | Deploy Agent SHALL capture deployment duration | Should | Implemented | `deployment_duration_seconds` |
| AGT-055 | Deploy Agent SHALL output structured YAML (`validation.yaml`) | Must | Implemented | Pydantic serialization |
| AGT-056 | Deploy Agent SHALL skip deployment in dry-run mode | Must | Implemented | `dry_run` check |

---

## 7. MCP Tool Requirements (AGT-060 to AGT-079)

### 7.1 MCP Tool Availability

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-060 | Agent SHALL support generic AWS API calls via boto3 | Must | Implemented | `mcp/aws_server.py` |
| AGT-061 | Agent SHALL support reading files from GitHub repositories | Must | Implemented | `mcp/git_server.py` |
| AGT-062 | Agent SHALL support reading files from GitLab repositories | Should | Implemented | `mcp/git_server.py` |
| AGT-063 | Agent SHALL support IaC drift detection (Git vs AWS) | Must | Implemented | `git_compare_with_deployed` |
| AGT-064 | Agent SHALL discover IaC files in repositories | Should | Implemented | `git_get_iac_files` |
| AGT-065 | Agent SHALL list available AWS services | Should | Implemented | `list_aws_services` |
| AGT-066 | Agent SHALL list operations for AWS services | Should | Implemented | `list_service_operations` |

### 7.2 MCP Tools in All Agents

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-070 | ALL pipeline agents SHALL have access to AWS MCP tools | Must | Implemented | `_register_mcp_tools()` |
| AGT-071 | ALL pipeline agents SHALL have access to Git MCP tools | Must | Implemented | `_register_mcp_tools()` |
| AGT-072 | MCP tool registration SHALL be fault-tolerant (silent fail) | Must | Implemented | try/except in init |
| AGT-073 | ChatAgent SHALL load MCP tools dynamically based on query | Should | Implemented | `_handle_*_query()` |

**Agent MCP Tool Status:**

| Agent | AWS Tools | Git Tools | Total Tools |
|-------|-----------|-----------|-------------|
| ChatAgent | Dynamic | Dynamic | On-demand |
| AuditAgent | YES | YES | 22 |
| PlanningAgent | YES | YES | 12 |
| IaCAgent | YES | YES | 8 |
| ReviewAgent | YES | YES | 14 |
| DeployValidateAgent | YES | YES | 14 |
| InvestigationAgent | YES | YES | 23 |
| K8sAgent | YES | YES | 8 |

### 7.3 Available MCP Tools

| Tool | Purpose | Used By |
|------|---------|---------|
| `aws_api_call(service, operation, parameters)` | Execute any boto3 operation | All agents |
| `list_aws_services()` | Discover AWS services | All agents |
| `list_service_operations(service)` | List operations for service | All agents |
| `git_read_file(repo, path, ref)` | Read file from repository | All agents |
| `git_list_files(repo, path, ref)` | List files in directory | All agents |
| `git_get_iac_files(repo, ref)` | Get all IaC files | All agents |
| `git_list_repos(org)` | List repositories | All agents |
| `git_compare_with_deployed(repo, path, content)` | Compare Git vs deployed | All agents |

---

## 8. Investigation Agent Requirements (AGT-070 to AGT-079)

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-070 | Investigation Agent SHALL diagnose pod health issues | Must | Implemented | `pod_health_check` tool |
| AGT-071 | Investigation Agent SHALL retrieve pod logs | Must | Implemented | `pod_logs` tool |
| AGT-072 | Investigation Agent SHALL check Kubernetes events | Must | Implemented | `pod_events` tool |
| AGT-073 | Investigation Agent SHALL query SigNoz metrics | Should | Implemented | `signoz_metrics` tool |
| AGT-074 | Investigation Agent SHALL query SigNoz logs | Should | Implemented | `signoz_logs` tool |
| AGT-075 | Investigation Agent SHALL query AWS resource status | Should | Implemented | `ec2_status` tool |
| AGT-076 | Investigation Agent SHALL produce root cause analysis | Must | Implemented | Output format |
| AGT-077 | Investigation Agent SHALL recommend remediation steps | Must | Implemented | Output format |

---

## 9. Audit Agent Requirements (AGT-080 to AGT-089)

| ID | Requirement | Priority | Status | Implementation |
|----|-------------|----------|--------|----------------|
| AGT-080 | Audit Agent SHALL check NIST 800-53 compliance | Must | Implemented | Compliance tools |
| AGT-081 | Audit Agent SHALL run security scans | Must | Implemented | Security tools |
| AGT-082 | Audit Agent SHALL identify cost optimization opportunities | Should | Implemented | Cost tools |
| AGT-083 | Audit Agent SHALL detect configuration drift | Must | Implemented | Drift tools |
| AGT-084 | Audit Agent SHALL score compliance (0-100%) | Should | Implemented | `compliance_score` |
| AGT-085 | Audit Agent SHALL list findings with severity | Must | Implemented | `findings` list |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-19 | AI Agent | Initial agent requirements document |
