from prisonbot import config


def test_load_defaults_when_no_file():
    assert config.load()["hunt_gap"] == config.DEFAULTS["hunt_gap"]


def test_save_load_roundtrip():
    cfg = config.load()
    cfg["loot_command"] = "/botin"
    config.save(cfg)
    assert config.load()["loot_command"] == "/botin"


def test_old_hunt_gap_is_migrated():
    cfg = config.load()
    cfg["hunt_gap"] = 0.12
    config.save(cfg)
    assert config.load()["hunt_gap"] == config.DEFAULTS["hunt_gap"]


def test_custom_hunt_gap_is_kept():
    cfg = config.load()
    cfg["hunt_gap"] = 0.2
    config.save(cfg)
    assert config.load()["hunt_gap"] == 0.2
