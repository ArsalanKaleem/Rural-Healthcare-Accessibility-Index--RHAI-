#!/usr/bin/env python
"""
rhai_10_parse_pphi.py — Parse PPHI Sindh facility PDFs into a table.

WHY
    PPHI publishes district-wise health facility lists as PDFs. They give facility name,
    district and type, but no coordinates. This turns them into a CSV so rhai_11 can
    geocode them, and so you have a DENOMINATOR — the number of facilities that should
    exist — to compare against open data.

INPUT
    Download these six from https://pphisindh.org/home/pic/contact-us/ into data/pphi_pdfs/
        HF-HYD.pdf   Region I   Hyderabad
        HF-MIR.pdf   Region II  Mirpurkhas
        HF-LAR.pdf   Region III Larkana
        HF-SUK.pdf   Region IV  Sukkur
        HF-SBA.pdf   Region V   Shaheed Benazirabad
        HF-KHI.pdf   Region VI  Karachi

    pip install pdfplumber --break-system-packages

USAGE
    python scripts/rhai_10_parse_pphi.py

OUTPUTS
    data/pphi_facilities.csv        one row per facility
    data/pphi_district_counts.csv   the denominator table — Figure 1 of the paper
    data/pphi_unknown_types.csv     rows whose type code was not recognised

FACILITY TYPE CODES
    Confirmed by expansion in PPHI's own materials:
        BHU  Basic Health Unit
        RHC  Rural Health Centre
        GD   Government Dispensary
        MCH  Mother and Child Health centre (also written MCHC)
        DCD  dispensary variant
    NOT confirmed — treated as primary care and flagged for disclosure:
        ED   appears throughout, in both urban colonies and rural villages. Most likely
             "Extended Dispensary". Mapped to Dispensary but retained as a separate
             raw code so the assumption stays visible.
        USK  three occurrences only (Dig Mori, Gull Buriro, Doulatpur). Unresolved.

    If you cannot confirm ED and USK from a PPHI legend page or their website, say so
    in the methods: "two PPHI facility codes (ED, n=46; USK, n=3) could not be resolved
    from published sources and were treated as primary-tier facilities." A documented
    uncertainty is acceptable; a silent guess is not.

VERIFY
    Ghotki should be 50 and Khairpur 151 — both confirmed against the PDFs.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "data" / "pphi_pdfs"
OUT_CSV = ROOT / "data" / "pphi_facilities.csv"
OUT_COUNTS = ROOT / "data" / "pphi_district_counts.csv"
OUT_UNKNOWN = ROOT / "data" / "pphi_unknown_types.csv"

REGIONS = {
    "HF-HYD": "Hyderabad", "HF-MIR": "Mirpurkhas", "HF-LAR": "Larkana",
    "HF-SUK": "Sukkur", "HF-SBA": "Shaheed Benazirabad", "HF-KHI": "Karachi",
}

# Order matters — first match wins. Specific codes before generic words.
TYPE_MAP = [
    (r"^B\.?H\.?U", "BHU"),
    (r"BASIC\s+HEALTH", "BHU"),
    (r"^R\.?H\.?C", "RHC"),
    (r"RURAL\s+HEALTH", "RHC"),
    (r"^M\.?C\.?H", "MCH"),
    (r"MOTHER|MATERNAL|MATERNITY", "MCH"),
    (r"^U\.?S\.?K", "USK"),                     # unresolved code, kept distinct
    (r"^E\.?D\.?$|^ED\b", "ED"),                # likely Extended Dispensary
    (r"^G\.?D\.?$|^GD\b", "GD"),
    (r"^D\.?C\.?D", "DCD"),
    (r"DISPENSARY", "GD"),
    (r"^T\.?H\.?Q|TALUKA\s+HEAD", "THQ"),
    (r"^D\.?H\.?Q|DISTRICT\s+HEAD", "DHQ"),
    (r"HOSP|CIVIL\s+HOSPITAL", "Hospital"),
]

# Grouping used for the summary table and for tiering.
TYPE_GROUP = {
    "BHU": "BHU", "RHC": "RHC", "MCH": "MCH",
    "GD": "Dispensary", "ED": "Dispensary", "DCD": "Dispensary", "USK": "USK",
    "THQ": "Hospital", "DHQ": "Hospital", "Hospital": "Hospital",
    "Other": "Other",
}

TIER_OF_GROUP = {
    "BHU": "primary", "Dispensary": "primary", "MCH": "primary", "RHC": "primary",
    "USK": "primary",           # assumed — see the note above
    "Hospital": "secondary",
    "Other": "unclassified",
}

# Codes whose meaning is not confirmed from a published source.
UNCONFIRMED = {"ED", "USK"}


def norm_type(raw: str) -> str:
    s = str(raw).upper().strip()
    for pat, out in TYPE_MAP:
        if re.search(pat, s):
            return out
    return "Other"


def clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def looks_like_header(cells: list[str]) -> bool:
    joined = " ".join(cells).lower()
    return any(k in joined for k in ("s.no", "sr.", "district", "health facility", "hf type"))


def main() -> int:
    try:
        import pdfplumber
    except ImportError:
        print("[FATAL] pip install pdfplumber --break-system-packages")
        return 1

    if not PDF_DIR.exists():
        print(f"[FATAL] {PDF_DIR} not found.")
        print("        Download the six HF-*.pdf from")
        print("        https://pphisindh.org/home/pic/contact-us/")
        return 1

    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"[FATAL] no PDFs in {PDF_DIR}")
        return 1

    rows: list[dict] = []
    for pdf_path in pdfs:
        stem = pdf_path.stem.upper()
        region = next((v for k, v in REGIONS.items() if k in stem), stem)
        print(f"[read] {pdf_path.name}  (region: {region})")

        n_before = len(rows)
        with pdfplumber.open(pdf_path) as pdf:
            for pageno, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables() or []
                if not tables:
                    text = page.extract_text() or ""
                    for line in text.split("\n"):
                        m = re.match(r"^\s*(\d{1,4})[.\s]+(.+)$", line)
                        if not m:
                            continue
                        rest = clean(m.group(2))
                        if len(rest) < 4:
                            continue
                        rows.append({"region": region, "district": "", "name": rest,
                                     "hf_type_raw": "", "source_pdf": pdf_path.name,
                                     "page": pageno, "parse_mode": "text"})
                    continue

                for tbl in tables:
                    for raw in tbl:
                        cells = [clean(c) for c in raw if c is not None]
                        cells = [c for c in cells if c != ""]
                        if len(cells) < 2 or looks_like_header(cells):
                            continue
                        if re.fullmatch(r"\d{1,4}", cells[0]):
                            cells = cells[1:]          # drop serial number
                        if not cells:
                            continue

                        if len(cells) >= 3:
                            district, name, hf_type = cells[0], cells[1], cells[2]
                        elif len(cells) == 2:
                            district, name, hf_type = "", cells[0], cells[1]
                        else:
                            district, name, hf_type = "", cells[0], ""

                        if len(clean(name)) < 4:
                            continue

                        rows.append({
                            "region": region,
                            "district": clean(district),
                            "name": clean(name),
                            "hf_type_raw": clean(hf_type),
                            "source_pdf": pdf_path.name,
                            "page": pageno,
                            "parse_mode": "table",
                        })
        print(f"       {len(rows) - n_before:,} rows")

    if not rows:
        print("[FATAL] parsed 0 rows. The PDFs may be scanned images.")
        print("        Open one and try to select text. If you cannot, OCR is needed.")
        return 1

    df = pd.DataFrame(rows)

    # Code from the explicit type column; fall back to inferring from the name.
    df["hf_code"] = df["hf_type_raw"].map(norm_type)
    inferred = df["hf_code"] == "Other"
    df.loc[inferred, "hf_code"] = df.loc[inferred, "name"].map(norm_type)

    df["hf_type"] = df["hf_code"].map(TYPE_GROUP).fillna("Other")
    df["tier"] = df["hf_type"].map(TIER_OF_GROUP).fillna("unclassified")
    df["type_confirmed"] = ~df["hf_code"].isin(UNCONFIRMED)

    # District column is sometimes blank on continuation rows; these lists are
    # grouped by district, so forward-fill within each PDF.
    df["district"] = df["district"].replace("", pd.NA)
    df["district"] = df.groupby("source_pdf")["district"].ffill()
    df["district"] = df["district"].fillna("")

    before = len(df)
    df = df.drop_duplicates(subset=["name", "district", "region"])
    print(f"\n[INFO] deduplicated {before:,} -> {len(df):,}")

    df.to_csv(OUT_CSV, index=False)

    counts = df.groupby(["region", "district", "hf_type"]).size().unstack(fill_value=0)
    counts["TOTAL"] = counts.sum(axis=1)
    counts = counts.sort_values("TOTAL", ascending=False)
    counts.to_csv(OUT_COUNTS)

    unknown = df[df["hf_code"] == "Other"]
    if len(unknown):
        unknown.to_csv(OUT_UNKNOWN, index=False)

    print()
    print("=" * 74)
    print("PPHI FACILITIES PARSED")
    print("=" * 74)
    print(f"Total facilities : {len(df):,}")
    print(f"Districts        : {df['district'].nunique()}")
    print()
    print("By raw code:")
    print(df["hf_code"].value_counts().to_string())
    print()
    print("By group:")
    print(df["hf_type"].value_counts().to_string())
    print()
    print("By tier:")
    print(df["tier"].value_counts().to_string())
    print()
    print("By district:")
    print(counts.to_string())
    print()

    n_unconf = int((~df["type_confirmed"]).sum())
    if n_unconf:
        print(f"[DISCLOSE] {n_unconf:,} facilities carry a type code whose meaning is not")
        print("           confirmed from published PPHI sources:")
        for code in sorted(UNCONFIRMED):
            n = int((df["hf_code"] == code).sum())
            if n:
                print(f"             {code}: {n:,}")
        print("           All are treated as primary-tier. Say so in the methods section,")
        print("           or confirm the expansion from a PPHI legend page and update")
        print("           the UNCONFIRMED set at the top of this script.")
        print()

    if len(unknown):
        print(f"[WARN] {len(unknown):,} rows still unrecognised -> {OUT_UNKNOWN.name}")
        print("       Raw type values present:")
        print("       " + ", ".join(sorted(unknown['hf_type_raw'].unique())[:20]))
        print()

    blank = int((df["district"] == "").sum())
    if blank:
        print(f"[WARN] {blank:,} rows have no district. Check the CSV.")
        print()

    print("VERIFY AGAINST THE PDFs BEFORE QUOTING:")
    for d, expected in (("Ghotki", 50), ("Khairpur", 151)):
        hit = counts[counts.index.get_level_values("district")
                     .str.contains(d, case=False, na=False)]
        got = int(hit["TOTAL"].sum()) if len(hit) else 0
        flag = "OK" if got == expected else "MISMATCH — investigate"
        print(f"   {d}: {got}  (expected {expected})  {flag}")

    print()
    print("NOTE ON DISTRICT NAMES")
    print("   PPHI spellings differ from GADM. You will need a crosswalk before joining:")
    print("     Tharparkar/Mithi, Kamber/Qambar, Naushero Feroze/Naushahro Firoz,")
    print("     Shaheed Benazirabad/Nawab Shah, Jacobabad/Jakobabad,")
    print("     Tando Muhammad Khan/Tando M. Khan")
    print("   Sujawal and Keamari appear in PPHI but not in the routed district set.")
    print()
    print(f"Wrote {OUT_CSV.name}, {OUT_COUNTS.name}"
          + (f", {OUT_UNKNOWN.name}" if len(unknown) else ""))
    print("NEXT: python scripts/rhai_11_geocode_pphi.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())