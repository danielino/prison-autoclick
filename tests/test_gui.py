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


def test_window_has_three_tabs(app):
    g = app.gui
    assert [g.nb.tab(i, "text").strip() for i in range(3)] == ["Autoclick", "Auto-hunt", "Sequences"]


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
