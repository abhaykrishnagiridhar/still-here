"""A printable sheet of ArUco markers for the blocks.

    python marker_sheet.py --out markers.png
    python marker_sheet.py --out markers.png --ids 1 2 3 4 5 6 7 8 9

Print it at 100 percent (actual size, no "fit to page"), then measure the 50 mm bar at the
bottom with a ruler. If it is not 50 mm, the print was scaled: print again. Cut out each square,
which is the size of a block face (block size from config.toml), and stick it on a face the
camera will see. The marker is smaller than the face so a white border is left around it,
which the camera needs to read it. Put markers on the SIDE faces the camera looks at: a marker
on the top of a bottom block is hidden by the block resting on it.

Each id is labelled bottom, top or heavy using the rules in config.toml.
"""

import argparse
import sys
from typing import Optional, Sequence

import cv2
import numpy as np

from aruco import DICTIONARY, BlockRules, load_config

DPI = 300
PAGE_MM = (210.0, 297.0)  # A4, width and height
MARGIN_MM = 10.0
LABEL_MM = 7.0  # room under each block-face square for the id and role
BAR_MM = 50.0
BAR_ZONE_MM = 22.0  # reserved at the bottom of the page for the scale bar
MAX_ID = 49  # the 4x4_50 dictionary
PX_PER_MM = DPI / 25.4


def _px(mm: float) -> int:
    return round(mm * PX_PER_MM)


def scale_bar_px() -> int:
    return _px(BAR_MM)


def role_of(marker_id: int, rules: BlockRules) -> str:
    roles = []
    if marker_id in rules.top_ids:
        roles.append("top")
    if marker_id in rules.heavy_ids:
        roles.append("heavy")
    return ", ".join(roles) if roles else "bottom"


def _capacity(block_mm: float) -> tuple[int, int]:
    columns = int((PAGE_MM[0] - 2 * MARGIN_MM) // block_mm)
    rows = int((PAGE_MM[1] - 2 * MARGIN_MM - BAR_ZONE_MM) // (block_mm + LABEL_MM))
    return columns, rows


def make_sheet(
    ids: Sequence[int], marker_mm: float, block_mm: float, rules: Optional[BlockRules] = None
) -> np.ndarray:
    """The sheet as a picture (BGR). One square per id, the size of a block face."""
    if not ids or not all(isinstance(i, int) and not isinstance(i, bool) and 0 <= i <= MAX_ID for i in ids):
        raise ValueError(f"ids must be whole numbers from 0 to {MAX_ID}, got {list(ids)!r}")
    if len(set(ids)) != len(ids):
        raise ValueError("each id can only be on the sheet once")
    if marker_mm >= block_mm:
        raise ValueError(
            f"the marker ({marker_mm:g} mm) must fit on the block face ({block_mm:g} mm) with a white border"
        )
    columns, rows = _capacity(block_mm)
    if len(ids) > columns * rows:
        raise ValueError(f"at most {columns * rows} markers fit on one sheet, got {len(ids)}")

    sheet = np.full((_px(PAGE_MM[1]), _px(PAGE_MM[0]), 3), 255, dtype=np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(DICTIONARY)
    side = _px(marker_mm)
    cell = _px(block_mm)
    for n, marker_id in enumerate(ids):
        row, column = divmod(n, columns)
        left = _px(MARGIN_MM) + column * cell
        top = _px(MARGIN_MM) + row * _px(block_mm + LABEL_MM)
        cv2.rectangle(sheet, (left, top), (left + cell, top + cell), (170, 170, 170), 1)  # cut line
        inset = (cell - side) // 2
        tile = cv2.aruco.generateImageMarker(dictionary, marker_id, side)
        sheet[top + inset : top + inset + side, left + inset : left + inset + side] = cv2.cvtColor(
            tile, cv2.COLOR_GRAY2BGR
        )
        label = f"id {marker_id}" + (f" {role_of(marker_id, rules)}" if rules is not None else "")
        cv2.putText(
            sheet, label, (left + 4, top + cell + _px(LABEL_MM) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2
        )

    bar_y = sheet.shape[0] - _px(BAR_ZONE_MM) + _px(6)
    bar_x = _px(MARGIN_MM)
    cv2.rectangle(sheet, (bar_x, bar_y), (bar_x + scale_bar_px(), bar_y + _px(3)), (0, 0, 0), -1)
    cv2.putText(
        sheet, "this bar must measure 50 mm: print at 100% actual size", (bar_x, bar_y - 14),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2,
    )
    return sheet


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Make a printable sheet of ArUco block markers")
    parser.add_argument("--out", default="markers.png", help="where to write the sheet (a PNG)")
    parser.add_argument("--ids", type=int, nargs="+", help="marker ids (default: the ones config.toml uses)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        config = load_config()
        ids = args.ids or sorted({1, 2, 3, 4, *config.top_marker_ids, *config.heavy_marker_ids})
        sheet = make_sheet(ids, config.marker_mm, config.block_mm, config.rules)
    except ValueError as error:
        print(f"Could not make the sheet: {error}", file=sys.stderr)
        return 1
    if not cv2.imwrite(args.out, sheet):
        print(f"Could not write {args.out}", file=sys.stderr)
        return 1
    print(f"Wrote {args.out} with ids {ids}.")
    print(
        f"Print it at 100% (actual size), then check the 50 mm bar with a ruler. "
        f"Marker {config.marker_mm:g} mm on a {config.block_mm:g} mm block face."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
