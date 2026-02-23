from __future__ import annotations

import argparse
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

# ----------------------------
# Distinctive tags (unlikely to collide)
# ----------------------------
TAG_ORIG = " __OCRPIPE_ORIG__"
TAG_OCR  = " __OCRPIPE_OCR__"
TAG_TMP  = " __OCRPIPE_TMP__"

# ----------------------------
# Detection defaults (tuned for illustrated books)
# ----------------------------
DEFAULT_SAMPLE_PAGES = 20
DEFAULT_PAGE_MIN_CHARS = 150
DEFAULT_MIN_COVERAGE = 0.30

# ----------------------------
# OCR defaults (books)
# ----------------------------
DEFAULT_LANG = "eng"
DEFAULT_OPTIMIZE = "1"          # retry uses 0
DEFAULT_RENDERER = "sandwich"
DEFAULT_OCR_JOBS = 2            # per-file internal parallelism
DEFAULT_PARALLEL_FILES = 4      # number of PDFs processed concurrently


@dataclass
class DetectResult:
    sampled_pages: int
    texty_pages: int
    coverage: float


def is_tagged(p: Path) -> bool:
    n = p.name
    return (TAG_ORIG in n) or (TAG_OCR in n) or (TAG_TMP in n)


def unique_path(path: Path) -> Path:
    """If path exists, append (1), (2), ... before extension."""
    if not path.exists():
        return path
    parent = path.parent
    stem = path.stem
    suffix = path.suffix
    i = 1
    while True:
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def sampled_page_indices(n_pages: int, sample_pages: int) -> List[int]:
    if n_pages <= 0:
        return []
    if n_pages <= sample_pages:
        return list(range(n_pages))
    idxs = set()
    for i in range(sample_pages):
        j = round(i * (n_pages - 1) / (sample_pages - 1))
        idxs.add(int(j))
    return sorted(idxs)


def detect_text_coverage(pdf_path: Path, sample_pages: int, page_min_chars: int) -> DetectResult:
    """Fraction of sampled pages with meaningful text."""
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return DetectResult(sampled_pages=0, texty_pages=0, coverage=0.0)

    n = doc.page_count
    idxs = sampled_page_indices(n, sample_pages)
    texty = 0

    for i in idxs:
        try:
            txt = doc.load_page(i).get_text().strip()
            if len(txt) >= page_min_chars:
                texty += 1
        except Exception:
            pass

    doc.close()
    sampled = len(idxs)
    cov = (texty / sampled) if sampled else 0.0
    return DetectResult(sampled_pages=sampled, texty_pages=texty, coverage=cov)


def run_ocrmypdf(src: Path, out_path: Path,
                 lang: str, optimize: str, renderer: str, jobs: int,
                 continue_soft: bool,
                 output_type: str,
                 extra_args: List[str]) -> Tuple[int, str, str]:
    cmd = [
        "ocrmypdf",
        "--skip-text",
        "--output-type", output_type,              # avoid PDF/A banner + bloat
        "--pdf-renderer", renderer,
        "--jobs", str(jobs),
        "-l", lang,
    ]
    if continue_soft:
        cmd.append("--continue-on-soft-render-error")

    cmd += ["--optimize", optimize]
    cmd += extra_args
    cmd += [str(src), str(out_path)]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def process_one_pdf(src: Path, args: argparse.Namespace) -> Dict:
    """Process a single PDF: detect -> OCR to temp -> rename original -> promote temp."""
    det = detect_text_coverage(src, args.sample_pages, args.page_min_chars)
    needs_ocr = (det.sampled_pages == 0) or (det.coverage < args.min_coverage)

    record: Dict = {
        "file": str(src),
        "sampled_pages": det.sampled_pages,
        "texty_pages": det.texty_pages,
        "coverage": det.coverage,
        "needs_ocr": needs_ocr,
        "action": None,
        "error": None,
        "returncode": None,
        "attempts": 0,
    }

    if not needs_ocr:
        record["action"] = "skip"
        return record

    base = src.with_suffix("")
    orig_tagged = unique_path(Path(str(base) + TAG_ORIG + ".pdf"))
    ocr_final   = unique_path(Path(str(base) + TAG_OCR  + ".pdf"))
    ocr_tmp     = unique_path(Path(str(base) + TAG_TMP  + ".pdf"))

    record["tmp"] = str(ocr_tmp)
    record["ocr"] = str(ocr_final)
    record["orig"]= str(orig_tagged)

    if not args.execute:
        record["action"] = "would_ocr"
        return record

    # Attempt 1: optimize=DEFAULT (usually 1)
    attempts = [
        ("1", False),  # (optimize, deskew_on_retry?) -> we keep deskew out by default
        ("0", False),  # retry: optimize=0
    ]

    # If user explicitly asked for deskew always, apply to both attempts.
    # If user asked for deskew on retry, only apply to second attempt.
    for attempt_idx, (opt_level, _) in enumerate(attempts, start=1):
        record["attempts"] = attempt_idx

        extra = list(args.extra)
        if args.deskew and (args.deskew_mode == "always" or (args.deskew_mode == "retry" and attempt_idx == 2)):
            extra.append("--deskew")

        rc, out, err = run_ocrmypdf(
            src=src,
            out_path=ocr_tmp,
            lang=args.lang,
            optimize=opt_level,
            renderer=args.renderer,
            jobs=args.ocr_jobs,
            continue_soft=True,
            output_type="pdf",
            extra_args=extra,
        )

        record["returncode"] = rc
        if rc == 0 and ocr_tmp.exists():
            break

        # cleanup temp between attempts
        if ocr_tmp.exists():
            try:
                ocr_tmp.unlink()
            except Exception:
                pass

        record["error"] = (err.strip()[:800] if err else "ocrmypdf failed")

    # If still no temp output, fail safely
    if not ocr_tmp.exists():
        record["action"] = "ocr_failed"
        return record

    # Rename original -> ORIG
    try:
        src.rename(orig_tagged)
    except Exception as e:
        record["action"] = "rename_orig_failed"
        record["error"] = str(e)
        # keep temp for manual review
        return record

    # Promote temp -> OCR
    try:
        ocr_tmp.rename(ocr_final)
    except Exception as e:
        record["action"] = "promote_failed"
        record["error"] = str(e)
        # rollback original name best-effort
        try:
            orig_tagged.rename(src)
        except Exception:
            record["error"] += " | rollback_failed"
        return record

    record["action"] = "ocr_success"
    return record


def main() -> int:
    ap = argparse.ArgumentParser(
        description="STRICT safe OCR pipeline: no overwrite; create __OCRPIPE_OCR__ output, rename original to __OCRPIPE_ORIG__ only after success; parallel across files."
    )
    ap.add_argument("--root", default="", help="REQUIRED. Root folder to scan recursively for PDFs.")
    ap.add_argument("--execute", action="store_true", help="Actually make changes. Otherwise DRY-RUN.")
    ap.add_argument("--log", default="", help="Optional path to write JSONL log.")

    ap.add_argument("--lang", default=DEFAULT_LANG)
    ap.add_argument("--renderer", default=DEFAULT_RENDERER)
    ap.add_argument("--ocr-jobs", type=int, default=DEFAULT_OCR_JOBS, help="Per-file OCRmyPDF --jobs")
    ap.add_argument("--parallel-files", type=int, default=DEFAULT_PARALLEL_FILES, help="Number of PDFs to OCR concurrently")

    ap.add_argument("--sample-pages", type=int, default=DEFAULT_SAMPLE_PAGES)
    ap.add_argument("--page-min-chars", type=int, default=DEFAULT_PAGE_MIN_CHARS)
    ap.add_argument("--min-coverage", type=float, default=DEFAULT_MIN_COVERAGE)

    ap.add_argument("--deskew", action="store_true", help="Enable deskew per your chosen mode")
    ap.add_argument("--deskew-mode", choices=["retry", "always"], default="retry",
                    help="If --deskew is set: deskew only on retry (default) or always.")

    ap.add_argument("--extra", nargs="*", default=[], help="Extra args passed to ocrmypdf (advanced).")

    args = ap.parse_args()

    if not args.root.strip():
        print('ERROR: --root is required. Example:\n  python safe_tagged_ocr_parallel_strict.py --root "K:\\eBooks\\Test Folder"\n'
              "Add --execute only when you are satisfied with the dry-run.")
        return 2

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: root not found: {root}")
        return 2

    log_path = Path(args.log) if args.log else None
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    pdfs = [p for p in root.rglob("*.pdf") if not is_tagged(p)]
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"Mode: {mode}")
    print(f"Root: {root}")
    print(f"Found {len(pdfs)} untagged PDFs")
    print(f"Parallel files: {args.parallel_files} | Per-file ocrmypdf --jobs: {args.ocr_jobs}")
    if args.deskew:
        print(f"Deskew: ON ({args.deskew_mode})")
    else:
        print("Deskew: OFF")

    counts = {"skip": 0, "would_ocr": 0, "ocr_success": 0, "ocr_failed": 0, "rename_orig_failed": 0, "promote_failed": 0}

    with ThreadPoolExecutor(max_workers=args.parallel_files) as ex:
        futures = {ex.submit(process_one_pdf, p, args): p for p in pdfs}
        for fut in as_completed(futures):
            rec = fut.result()
            action = rec.get("action") or "unknown"
            counts[action] = counts.get(action, 0) + 1

            # Print concise progress for OCR-related actions
            if action in ("would_ocr", "ocr_success", "ocr_failed", "rename_orig_failed", "promote_failed"):
                src = Path(rec["file"]).name
                cov = rec.get("coverage", 0.0)
                print(f"{action:18} cov={cov:.2f}  {src}")
                if action in ("ocr_failed", "rename_orig_failed", "promote_failed") and rec.get("error"):
                    print(f"  error: {rec['error'][:200]}")

            if log_path:
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print("\nSummary:")
    print(f"  Total PDFs scanned:   {len(pdfs)}")
    print(f"  Skipped (searchable): {counts.get('skip', 0)}")
    print(f"  Needs OCR (dry-run):  {counts.get('would_ocr', 0)}")
    print(f"  OCR succeeded:        {counts.get('ocr_success', 0)}")
    print(f"  OCR failed:           {counts.get('ocr_failed', 0)}")
    print(f"  Rename orig failed:   {counts.get('rename_orig_failed', 0)}")
    print(f"  Promote failed:       {counts.get('promote_failed', 0)}")
    if log_path:
        print(f"  Log: {log_path}")
    if not args.execute:
        print("\nNOTE: DRY-RUN mode. Re-run with --execute to make changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())