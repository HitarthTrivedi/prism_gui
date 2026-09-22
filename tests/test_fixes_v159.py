import os
import pytest
from PySide6.QtWidgets import QApplication
import workspace
import paths
import dashboard_data as DATA
from prism_terminal.core import router
from widgets.agents_panel import PlanRow, AgentsPanel, default_prompt_for_stage
from widgets.panel_base import AddonFrontDoor


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_research_guardrail():
    routing = {}
    agents = {"research": "Perplexity", "brains": "ChatGPT"}
    query = "Please do deep research on EV battery technology trends"
    
    forced = router.apply_research_guardrail(query, routing, agents)
    assert forced is True
    assert routing["research"]["needed"] is True
    assert len(routing["research"]["questions"]) > 0
    assert "deep research" in routing["research"]["questions"][0].lower() or "research" in routing["research"]["questions"][0].lower()

    # Now verify apply_research_reasoning_guardrail also picks it up
    reasoning_forced = router.apply_research_reasoning_guardrail(routing, agents)
    assert reasoning_forced is True
    assert routing["brains"]["needed"] is True


def test_plan_row_toggle_auto_prompts(qapp):
    row = PlanRow("research", {"label": "Research"}, current="Perplexity", included=False, questions=[])
    row._query = "Investigate quantum computing"
    assert not row.questions()
    assert not row.is_checked()

    # Toggle on
    row.toggle()
    assert row.is_checked()
    assert len(row.questions()) == 1
    assert "quantum computing" in row.questions()[0]


def test_agents_panel_ensure_prompts(qapp):
    panel = AgentsPanel()
    panel.set_content(
        routing={"development": {"needed": True, "questions": []}},
        agents_cfg={"development": "Claude"},
        query="Develop a new Python backend"
    )
    # Ticked row with no question gets prompt populated by ensure_prompts
    panel.ensure_prompts()
    unprompted = panel.unprompted_steps()
    assert len(unprompted) == 0


def test_addon_front_door_no_ai_tools_listing(qapp):
    class DummyAddon(AddonFrontDoor):
        TITLE = "Dummy"
        ACTION = "Test Action"
        ACTION_ICON = "play"

    door = DummyAddon(cfg={"agents": {"research": "Perplexity"}})
    door.build()
    
    # Check header actions: only primary action button, no "AI tools"
    actions = door.header_actions()
    action_texts = [btn.text().strip() for btn in actions]
    assert "AI tools" not in action_texts
    assert "Test Action" in action_texts


def test_runs_dir_and_dashboard_fallback(tmp_path, monkeypatch):
    # Setup mock user_dir runs folder with a run file
    mock_prism = tmp_path / "mock_prism"
    mock_runs = mock_prism / "runs"
    mock_runs.mkdir(parents=True)
    run_file = mock_runs / "run_12345.json"
    run_file.write_text('{"title": "Test Run", "query": "hello"}', encoding="utf-8")

    monkeypatch.setattr(paths, "user_dir", lambda *parts: os.path.join(str(mock_prism), *parts))

    # Test when workspace root points to a non-existent or empty folder
    cfg = {"workspace_root": str(tmp_path / "nonexistent_ws")}
    resolved = workspace.runs_dir("personal", cfg)
    assert resolved == str(mock_runs)

    files = DATA._run_files(cfg, "personal")
    assert len(files) == 1
    assert files[0] == str(run_file)


def test_theme_c_rgba_parsing():
    import theme
    col = theme.c("rgba(0, 0, 0, 0.03)")
    assert col.isValid()
    assert col.alpha() < 30  # Should be ~7, NOT 255 (opaque black)
    assert col.alpha() > 0

    col2 = theme.c("rgba(255, 255, 255, 0.65)")
    assert col2.isValid()
    assert col2.red() == 255
    assert col2.green() == 255
    assert col2.blue() == 255
    assert col2.alpha() > 100


