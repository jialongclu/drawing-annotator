#!/usr/bin/env python3
"""Generate a multi-page sample drawing set.

No sample PDF came with the brief, so this writes a valid one to develop
against: numbered sheets with a title block and a bit of linework, so you can
tell at a glance which page you are on and have something to draw over.

Usage:  python scripts/make_sample_pdf.py [pages] [output.pdf]
"""

import sys
from pathlib import Path

WIDTH, HEIGHT = 842, 595  # A4 landscape, points

SHEET_TITLES = [
    "GENERAL ARRANGEMENT",
    "FOUNDATION PLAN",
    "LEVEL 1 FLOOR PLAN",
    "LEVEL 2 FLOOR PLAN",
    "ROOF PLAN",
    "NORTH ELEVATION",
    "SOUTH ELEVATION",
    "SECTION A-A",
    "STAIR DETAILS",
    "DOOR SCHEDULE",
    "WINDOW SCHEDULE",
    "REFLECTED CEILING PLAN",
]


def escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def page_content(index: int, total: int) -> str:
    title = SHEET_TITLES[index % len(SHEET_TITLES)]
    number = f"A-{101 + index}"

    parts = [
        # Border
        "0.6 w 0.2 0.2 0.2 RG",
        f"20 20 {WIDTH - 40} {HEIGHT - 40} re S",
        f"28 28 {WIDTH - 56} {HEIGHT - 56} re S",
        # Title block, bottom right
        f"0.9 w {WIDTH - 250} 28 222 110 re S",
        f"0.4 w {WIDTH - 250} 100 m {WIDTH - 28} 100 l S",
        f"{WIDTH - 250} 64 m {WIDTH - 28} 64 l S",
        # Some linework to annotate over
        "0.35 w 0.45 0.45 0.5 RG",
    ]

    for row in range(6):
        y = 200 + row * 46
        parts.append(f"70 {y} m {WIDTH - 280} {y} l S")
    for column in range(7):
        x = 70 + column * 70
        parts.append(f"{x} 200 m {x} 430 l S")

    parts.append("1.1 w 0.15 0.15 0.15 RG")
    parts.append(f"120 250 240 130 re S")
    parts.append(f"420 290 130 90 re S")

    # Text
    parts.append("BT 0 0 0 rg /F1 22 Tf 70 {} Td ({}) Tj ET".format(HEIGHT - 70, escape(title)))
    parts.append(
        "BT /F1 11 Tf 70 {} Td (PROVISION TAKEHOME - SAMPLE DRAWING SET) Tj ET".format(HEIGHT - 92)
    )
    parts.append(
        "BT /F1 30 Tf {} 40 Td ({}) Tj ET".format(WIDTH - 240, escape(number))
    )
    parts.append(
        "BT /F1 10 Tf {} 76 Td (SHEET {} OF {}) Tj ET".format(WIDTH - 240, index + 1, total)
    )
    parts.append(
        "BT /F1 10 Tf {} 112 Td ({}) Tj ET".format(WIDTH - 240, escape(title[:24]))
    )
    parts.append(
        "BT /F1 9 Tf 70 160 Td (CONTRACTOR: ACME CONSTRUCTION  -  REV C  -  NOT FOR CONSTRUCTION) Tj ET"
    )

    return "\n".join(parts)


def build(pages: int) -> bytes:
    objects: list[bytes] = []

    def add(body: str | bytes) -> int:
        objects.append(body.encode("latin-1") if isinstance(body, str) else body)
        return len(objects)  # 1-based object number

    # Reserve object 1 for the catalog and 2 for the page tree so their numbers
    # are known before the pages that reference them are written.
    catalog_id = add("")
    pages_id = add("")
    font_id = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids: list[int] = []
    for index in range(pages):
        stream = page_content(index, pages).encode("latin-1")
        content_id = add(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        page_ids.append(
            add(
                f"<< /Type /Page /Parent {pages_id} 0 R "
                f"/MediaBox [0 0 {WIDTH} {HEIGHT}] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            )
        )

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Count {pages} /Kids [{kids}] >>".encode("latin-1")
    objects[catalog_id - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("latin-1")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode("latin-1")

    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode("latin-1")

    return bytes(out)


def main() -> None:
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("sample-drawings.pdf")
    target.write_bytes(build(pages))
    print(f"Wrote {target} ({pages} pages, {target.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
