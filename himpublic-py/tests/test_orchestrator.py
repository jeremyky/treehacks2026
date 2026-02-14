"""Minimal test: imports and mock orchestrator run."""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture
def mock_config():
    from himpublic.orchestrator.config import OrchestratorConfig
    return OrchestratorConfig(
        robot_adapter="mock",
        mock_search_iterations_to_detect=2,
        command_center_url="",
        log_level="WARNING",
    )


def test_import_orchestrator():
    from himpublic.orchestrator import OrchestratorAgent, MissionState
    assert MissionState.SEARCH is not None
    assert OrchestratorAgent is not None


def test_orchestrator_run(mock_config):
    from himpublic.orchestrator.agent import OrchestratorAgent
    agent = OrchestratorAgent(mock_config)
    asyncio.run(agent.run())
    assert agent.state.value == "done"
