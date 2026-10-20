"""The printable sheet of ArUco markers for the blocks."""

import cv2
import pytest

import marker_sheet
from aruco import BlockRules, Config, find_markers
from marker_sheet import DPI, make_sheet, main, role_of

PX_PER_MM = DPI / 25.4


def test_a_sheet_is_one_a4_page_at_the_print_resolution():
    sheet = make_sheet([1, 2], marker_mm=30, block_mm=40)

    assert sheet.shape == (round(297 * PX_PER_MM), round(210 * PX_PER_MM), 3)


def test_every_requested_marker_can_be_read_back_at_its_printed_size():
    ids = [1, 2, 5, 9]

    found = find_markers(make_sheet(ids, marker_mm=30, block_mm=40))

    assert [m.id for m in found] == ids
    for marker in found:
        assert marker.side == pytest.approx(30 * PX_PER_MM, abs=3)


def test_the_marker_size_follows_the_config():
    found = find_markers(make_sheet([3], marker_mm=25, block_mm=40))

    assert found[0].side == pytest.approx(25 * PX_PER_MM, abs=3)


def test_markers_sit_in_a_grid_without_overlapping():
    found = find_markers(make_sheet(list(range(1, 13)), marker_mm=30, block_mm=40))

    assert len(found) == 12
    centres = {(round(m.x), round(m.y)) for m in found}
    assert len(centres) == 12
    columns = sorted({round(m.x) for m in found})
    assert min(b - a for a, b in zip(columns, columns[1:], strict=False)) >= 40 * PX_PER_MM - 3  # at least a block apart


def test_the_sheet_has_a_50_mm_bar_to_check_the_print_scale():
    sheet = make_sheet([1], marker_mm=30, block_mm=40)
    bottom = cv2.cvtColor(sheet, cv2.COLOR_BGR2GRAY)[-int(30 * PX_PER_MM):, :]

    dark_columns = (bottom < 100).any(axis=0).nonzero()[0]

    assert marker_sheet.scale_bar_px() == pytest.approx(50 * PX_PER_MM, abs=1)
    assert dark_columns.size >= marker_sheet.scale_bar_px()


def test_too_many_markers_for_one_sheet_is_refused_with_the_limit():
    with pytest.raises(ValueError, match="at most"):
        make_sheet(list(range(0, 40)), marker_mm=30, block_mm=40)


@pytest.mark.parametrize("bad", [[-1], [50], [1, 1], [], ["a"], [1.5]])
def test_ids_that_cannot_be_printed_are_refused(bad):
    with pytest.raises(ValueError):
        make_sheet(bad, marker_mm=30, block_mm=40)


def test_a_marker_bigger_than_its_block_face_is_refused():
    with pytest.raises(ValueError, match="fit"):
        make_sheet([1], marker_mm=45, block_mm=40)


def test_each_id_is_labelled_top_heavy_or_bottom_by_the_block_rules():
    rules = BlockRules(top_ids=frozenset({5, 6}), heavy_ids=frozenset({9}))

    assert [role_of(i, rules) for i in (1, 5, 9)] == ["bottom", "top", "heavy"]
    assert role_of(9, BlockRules(top_ids=frozenset({9}), heavy_ids=frozenset({9}))) == "top, heavy"


def test_the_command_writes_a_sheet_with_the_config_ids_by_default(tmp_path, capsys):
    out = tmp_path / "markers.png"

    code = main(["--out", str(out)])

    assert code == 0
    sheet = cv2.imread(str(out))
    wanted = sorted({1, 2, 3, 4, *Config().top_marker_ids, *Config().heavy_marker_ids})
    assert [m.id for m in find_markers(sheet)] == wanted
    assert "100%" in capsys.readouterr().out


def test_the_command_takes_its_own_ids(tmp_path):
    out = tmp_path / "markers.png"

    assert main(["--out", str(out), "--ids", "7", "8"]) == 0
    assert [m.id for m in find_markers(cv2.imread(str(out)))] == [7, 8]


def test_the_command_reports_a_bad_id(tmp_path, capsys):
    out = tmp_path / "markers.png"

    assert main(["--out", str(out), "--ids", "99"]) == 1
    assert not out.exists()
    assert "99" in capsys.readouterr().err
