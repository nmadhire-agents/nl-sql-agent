from pathlib import Path


def test_openai_agents_sdk_is_installed_and_importable() -> None:
    from agents import Agent, RunConfig, Runner, function_tool

    assert Agent.__module__.startswith("agents.")
    assert Runner.run
    assert function_tool
    assert RunConfig.__module__.startswith("agents.")


def test_agent_module_uses_openai_agents_sdk_primitives() -> None:
    source = Path("src/nl_sql_agent/agent.py").read_text(encoding="utf-8")

    assert "from agents import Agent" in source
    assert "Runner.run" in source
    assert "@function_tool" in source
    assert "RunConfig(" in source
    assert "Agent(" in source
