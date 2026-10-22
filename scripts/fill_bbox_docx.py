#!/usr/bin/env python3
"""Remplit un DOCX de bboxes existant avec un DOCX non-textuel valide."""
from __future__ import annotations

import argparse
from pathlib import Path

from pdfexact.render.bbox_debug import fill_existing_bbox_docx_from_non_text_docx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bbox_docx", type=Path)
    parser.add_argument("non_text_docx", type=Path)
    parser.add_argument("destination_docx", type=Path)
    args = parser.parse_args()
    fill_existing_bbox_docx_from_non_text_docx(
        args.bbox_docx,
        args.non_text_docx,
        args.destination_docx,
    )
    print(args.destination_docx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
