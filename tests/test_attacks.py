"""The ATAQUES digit reader, with digits drawn from the stored glyph bitmaps (no screenshots in the repository)."""
from conftest import blank, paint
from prisonbot import vision

ORANGE, RED = (250, 170, 30), (225, 30, 30)


def render(glyph, color, w=40, h=70, scale=3, label=True):
    """A buffer with the glyph (8x12 cells) drawn scale*scale pixels per cell, and the small word above it."""
    buf = blank(w, h, (30, 30, 30))
    if label:
        paint(buf, w, 4, 4, 30, 12, color)  # the word ATAQUES: wide, but short
    gx, gy = 8, 20
    for j, row in enumerate(glyph):
        for i, c in enumerate(row):
            if c == "#":
                paint(buf, w, gx + i * scale, gy + j * scale, gx + (i + 1) * scale, gy + (j + 1) * scale, color)
    return buf, w, h


def test_reads_one_and_two():
    for n in (1, 2):
        buf, w, h = render(vision.ATTACK_GLYPHS[n], ORANGE)
        assert vision.attacks_from_buf(buf, w, h) == n


def test_red_digit_is_zero():
    buf, w, h = render(vision.ATTACK_GLYPHS[2], RED)  # the shape does not matter: red means 0
    assert vision.attacks_from_buf(buf, w, h) == 0


def test_a_wide_unknown_digit_is_three():
    three = ("..####..", ".######.", "##....##", "......##", "....###.", "....###.",
             "......##", "......##", "##....##", "##....##", ".######.", "..####..")
    buf, w, h = render(three, ORANGE)
    assert vision.attacks_from_buf(buf, w, h) == 3


def test_empty_box_is_none():
    assert vision.attacks_from_buf(blank(40, 70, (30, 30, 30)), 40, 70) is None


def test_only_the_label_is_none():
    buf = blank(40, 70, (30, 30, 30))
    paint(buf, 40, 4, 4, 30, 12, ORANGE)
    assert vision.attacks_from_buf(buf, 40, 70) is None
