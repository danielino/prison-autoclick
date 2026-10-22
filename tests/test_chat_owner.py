"""Who is acting, read from the last chat lines (synthetic lines: coloured bars as wide as the text they stand for)."""
import pytest

from conftest import blank, paint
from prisonbot import vision

YELLOW, RED, GREEN, BLUE, WHITE = (240, 235, 30), (225, 20, 20), (30, 230, 30), (30, 150, 255), (230, 230, 230)
W, H, CW = 1000, 200, 2000  # a chat strip; "client width" 2000, so one line is ~14 px tall every 25 px


def chat(*lines):
    """Lines from the top; each is a list of (colour, x0, x1) pieces."""
    buf = blank(W, H, (40, 40, 40))
    for n, pieces in enumerate(lines):
        y = 10 + n * 25
        for rgb, x0, x1 in pieces:
            paint(buf, W, x0, y, x1, y + 12, rgb)
    return buf


def owner(*lines):
    return vision.chat_owner_from_buf(chat(*lines), W, H, CW)


TURN = [(YELLOW, 10, 130)]
ATTACK = [(GREEN, 10, 600)]
ENEMY = [(RED, 10, 550)]
BLEED = [(BLUE, 10, 400)]
PLAYER = [(WHITE, 10, 70), (RED, 70, 110), (WHITE, 110, 600)]  # white text with a coloured name


def test_the_turn_line_newest_is_ours():
    assert owner(ENEMY, ENEMY, TURN) == "mine"


def test_our_attack_after_the_turn_line_means_the_turn_is_running():
    assert owner(ENEMY, TURN, ATTACK) == "theirs"
    assert owner(TURN, ATTACK, BLEED, ENEMY) == "theirs"


def test_other_players_chat_does_not_hide_the_turn_line():
    assert owner(ENEMY, TURN, PLAYER, PLAYER) == "mine"


def test_other_players_chat_does_not_hide_the_enemy_turn_either():
    assert owner(TURN, ATTACK, ENEMY, PLAYER) == "theirs"


def test_a_refused_command_answer_in_yellow_after_the_turn_line_is_still_our_turn():
    assert owner(ENEMY, TURN, [(YELLOW, 10, 480)]) == "mine"


def test_only_chat_of_players_is_unknown():
    assert owner(PLAYER, PLAYER, PLAYER) is None
    assert owner() is None


def test_works_at_other_window_sizes():
    for cw in (1280, 1920, 2560):
        k = cw / 2000.0
        buf = blank(int(W * k), int(H * k), (40, 40, 40))
        for n, (rgb, x1) in enumerate(((RED, 550), (YELLOW, 130), (WHITE, 500))):
            y = int((10 + n * 25) * k)
            paint(buf, int(W * k), int(10 * k), y, int(x1 * k), y + max(int(12 * k), 3), rgb)
        assert vision.chat_owner_from_buf(buf, int(W * k), int(H * k), cw) == "mine", cw


def test_chat_turn_is_mine_answers_true_when_nothing_can_be_told(monkeypatch):
    monkeypatch.setattr(vision, "client_rect", lambda h: (0, 0, 2000, 1000))
    monkeypatch.setattr(vision, "grab", lambda x, y, w, h: bytes(blank(w, h, (40, 40, 40))))
    assert vision.chat_turn_is_mine(1) is True
