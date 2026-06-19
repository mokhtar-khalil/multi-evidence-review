from __future__ import annotations

import argparse
import csv
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def load_font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def make_sheet(csv_path: Path, repo_root: Path, out_dir: Path, split: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    font = load_font(18)
    small = load_font(14)
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    tile_w, tile_h = 360, 340
    margin = 20
    cols = 2
    rows_per_page = 3
    per_page = cols * rows_per_page

    for page_idx in range((len(rows) + per_page - 1) // per_page):
        page_rows = rows[page_idx * per_page : (page_idx + 1) * per_page]
        sheet = Image.new("RGB", (cols * tile_w + margin, rows_per_page * tile_h + margin), "white")
        draw = ImageDraw.Draw(sheet)
        for i, row in enumerate(page_rows):
            x = margin + (i % cols) * tile_w
            y = margin + (i // cols) * tile_h
            case = row["image_paths"].split("/")[2]
            title = f"{case} | {row['claim_object']} | {row['user_id']}"
            claim = row["user_claim"].replace(" | ", " ")
            draw.text((x, y), title, fill=(0, 0, 0), font=font)
            draw.text((x, y + 24), "\n".join(textwrap.wrap(claim, 54)[:4]), fill=(40, 40, 40), font=small)
            img_y = y + 100
            paths = row["image_paths"].split(";")
            thumb_w = max(1, (tile_w - 30) // len(paths))
            for j, rel in enumerate(paths):
                p = repo_root / "dataset" / rel if not rel.startswith("dataset/") else repo_root / rel
                with Image.open(p) as im:
                    im.thumbnail((thumb_w - 8, 200))
                    px = x + j * thumb_w
                    sheet.paste(im.convert("RGB"), (px, img_y))
                    draw.text((px, img_y + im.height + 4), Path(rel).stem, fill=(0, 0, 0), font=small)
            if "claim_status" in row and row.get("claim_status"):
                label = f"{row['claim_status']} | {row['issue_type']} | {row['object_part']}"
                draw.text((x, y + tile_h - 28), label, fill=(0, 90, 0), font=small)
        sheet.save(out_dir / f"{split}_sheet_{page_idx + 1:02d}.jpg", quality=92)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path("."), type=Path)
    parser.add_argument("--out-dir", default=Path("analysis_sheets"), type=Path)
    parser.add_argument("--split", required=True)
    args = parser.parse_args()
    make_sheet(args.csv, args.repo_root, args.out_dir, args.split)


if __name__ == "__main__":
    main()
