import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app():
    from prisonbot.app import App
    try:
        a = App()
    except tk.TclError:
        pytest.skip("no display for Tk")
    yield a
    a.root.destroy()


def test_window_tabs(app):
    g = app.gui
    assert [g.nb.tab(i, "text").strip() for i in range(5)] == ["Autoclick", "Auto-hunt", "Vision", "Stats", "Sequences"]


def test_stats_tab_shows_the_counters_and_the_interval_is_saved(app):
    from prisonbot import stats
    stats.reset()
    stats.add("fights_done", 3)
    g = app.gui
    g.stats_refresh()
    texts = [g.statstree.item(i, "text") for i in g.statstree.get_children()]
    assert "Fights" in texts
    leaves = [g.statstree.item(c, "values") for i in g.statstree.get_children() for c in g.statstree.get_children(i)]
    assert any(v[0] == "3" for v in leaves)
    g.statsint.set("10")
    g.apply()
    assert app.cfg["stats_interval"] == 10
    stats.reset()


def test_ollama_settings_are_applied_and_saved(app):
    g = app.gui
    g.llmvar.set(True)
    g.llmurl.set("http://192.168.1.50:11434")
    g.llmmodel.set("qwen3-vl:8b-instruct")
    g.llmmode.set("decide")
    g.llmtimeout.set("12")
    g.llmwidth.set("896")
    g.apply()
    c = app.cfg
    assert (c["llm_enabled"], c["ollama_url"], c["ollama_model"], c["llm_mode"]) == (
        True, "http://192.168.1.50:11434", "qwen3-vl:8b-instruct", "decide")
    assert c["llm_timeout"] == 12 and c["llm_max_width"] == 896


def test_settings_are_applied_and_saved(app):
    g = app.gui
    g.gap.set("9")
    g.hmin.set("60")
    g.lootwait.set("3")
    g.walkvar.set(True)
    g.apply()
    assert app.cfg["hunt_gap"] == pytest.approx(0.09)
    assert app.cfg["hunt_min_health"] == pytest.approx(0.6)
    assert app.cfg["loot_again_delay"] == 3
    assert app.cfg["hunt_walk"] is True


def test_half_typed_value_is_ignored(app):
    g = app.gui
    before = app.cfg["hunt_gap"]
    g.gap.set("")
    g.apply()
    assert app.cfg["hunt_gap"] == before


def test_turning_the_helper_off_greys_out_its_settings(app):
    g = app.gui
    g.llmvar.set(True)
    g.apply()
    assert str(g.llm_fields[0][0].cget("state")) == "normal"
    g.llmvar.set(False)
    g.apply()
    assert app.cfg["llm_enabled"] is False
    assert all(str(w.cget("state")) == "disabled" for w, _ in g.llm_fields)
