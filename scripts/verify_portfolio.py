#!/usr/bin/env python3
"""Check publication integrity; does not validate business or causal claims."""

import csv
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]


def slug(text):
    text = re.sub(r"[`*_]", "", text).lower().strip()
    text = "".join(c for c in text if not unicodedata.category(c).startswith("P") or c in "-_")
    return re.sub(r"\s", "-", text)


def check():
    failures = []
    manifest = json.loads((ROOT / "evidence/source-manifest.json").read_text())
    source = next(s for s in manifest["sources"] if s["source_id"] == "S1")
    original = ROOT / source["public_copy"]
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    if digest != source["sha256"]:
        failures.append("Original presentation hash differs from the source manifest")

    public_files = [p for p in ROOT.rglob("*") if p.is_file() and not any(
        part in {".git", "__pycache__"} for part in p.relative_to(ROOT).parts
    )]
    forbidden = {".private", ".work", "node_modules"}
    for p in public_files:
        if forbidden.intersection(p.relative_to(ROOT).parts):
            failures.append(f"Private/build content in repository: {p.relative_to(ROOT)}")
        if p.suffix.lower() in {".pptx", ".ppt"}:
            failures.append(f"Only the original PDF should be published: {p.name}")
        if p.suffix.lower() == ".pdf" and p != original:
            failures.append(f"Unexpected additional PDF: {p.name}")

    link_count = 0
    for p in sorted(ROOT.rglob("*.md")):
        if ".git" in p.parts:
            continue
        body = p.read_text()
        if "/Users/" in body or re.search(r"R\d{8}", body):
            failures.append(f"Local path or student identifier in public text: {p.name}")
        for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", body):
            link = match.group(1).strip().split(" ", 1)[0]
            if re.match(r"^[a-zA-Z]+:", link):
                continue
            target, _, fragment = unquote(link).partition("#")
            resolved = (p.parent / target).resolve() if target else p
            link_count += 1
            if not resolved.exists():
                failures.append(f"Broken local link in {p.name}: {link}")
            elif fragment and resolved.suffix == ".md":
                headings = re.findall(r"^#{1,6}\s+(.+)$", resolved.read_text(), re.M)
                if fragment not in {slug(h) for h in headings}:
                    failures.append(f"Missing heading in {p.name}: {link}")

    with (ROOT / "evidence/evidence-register.csv").open(newline="") as f:
        evidence = list(csv.DictReader(f))
    ids = {r["evidence_id"] for r in evidence}
    if len(ids) != len(evidence):
        failures.append("Duplicate evidence IDs")
    for row in evidence:
        if row["source_id"] != "S1" or not all(1 <= int(p) <= 32 for p in row["pages"].split(";")):
            failures.append(f"Invalid source/page mapping: {row['evidence_id']}")

    with (ROOT / "evidence/claims-register.csv").open(newline="") as f:
        claims = list(csv.DictReader(f))
    claim_ids = {r["claim_id"] for r in claims}
    if len(claim_ids) != len(claims):
        failures.append("Duplicate claim IDs")
    for row in claims:
        if set(filter(None, row["evidence_ids"].split(";"))) - ids:
            failures.append(f"Unknown evidence reference in {row['claim_id']}")
        if set(filter(None, row["theory_ids"].split(";"))) - {"T1", "T2", "T3", "T4", "T5"}:
            failures.append(f"Unknown theory reference in {row['claim_id']}")
        if row["claim_type"] == "proposition" and row["current_status"] != "not_empirically_tested":
            failures.append(f"Unsupported empirical status in {row['claim_id']}")
    validation_text = (ROOT / "docs/validation-design.md").read_text()
    for proposition in ("P1", "P2", "P3", "P4"):
        if proposition not in claim_ids or f"## {proposition}：" not in validation_text:
            failures.append(f"Missing proposition documentation: {proposition}")

    report = {
        "status": "PASS" if not failures else "FAIL",
        "files_checked": len(public_files),
        "local_links_checked": link_count,
        "evidence_records": len(evidence),
        "claim_records": len(claims),
        "original_sha256": digest,
        "original_unchanged": digest == source["sha256"],
        "failures": failures,
        "scope": "Publication integrity only; no empirical validation of propositions.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return not failures


if __name__ == "__main__":
    sys.exit(0 if check() else 1)
