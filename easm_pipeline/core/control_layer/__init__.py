"""Control layer for running agents with generated Agent Skills mounted."""

__all__ = [
    "DEFAULT_SKILL_AGENT_INSTRUCTIONS",
    "CONTAINER_SKILL_AGENT_INSTRUCTIONS",
    "AgentContainerConfig",
    "AgentContainerError",
    "AgentContainerLauncher",
    "AgentServiceClient",
    "MountedSkillAgent",
    "SkillAgentConfig",
    "SkillAgentDependencyError",
    "SkillAgentError",
    "SkillExecutionBackend",
    "SkillAgentFactory",
    "SkillAgentRunResult",
    "SkillDirectoryError",
]


def __getattr__(name: str):
    """Lazily expose control-layer symbols so bootstrap modules can run before deps are installed."""

    if name in {
        "DEFAULT_SKILL_AGENT_INSTRUCTIONS",
        "CONTAINER_SKILL_AGENT_INSTRUCTIONS",
        "MountedSkillAgent",
        "SkillAgentConfig",
        "SkillAgentDependencyError",
        "SkillAgentError",
        "SkillExecutionBackend",
        "SkillAgentFactory",
        "SkillAgentRunResult",
        "SkillDirectoryError",
    }:
        from . import skill_agent

        return getattr(skill_agent, name)
    if name in {
        "AgentContainerConfig",
        "AgentContainerError",
        "AgentContainerLauncher",
        "AgentServiceClient",
    }:
        from . import agent_container

        return getattr(agent_container, name)
    raise AttributeError(f"module 'easm_pipeline.core.control_layer' has no attribute {name!r}")
