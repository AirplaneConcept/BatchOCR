# Batch OCR Pipeline

This was created to execute OCR on many PDFs in a folder containing many files, some of which are PDFs that need OCR, some are PDFs that don't need OCR, and some are not PDFs. Install Python, Tesseract, Ghostscript, and ocrmypdf. Download the files. Doubleclick on RunBatchOCR. Point it at the folder you want processed. The originals are left in place but the file name is tagged. The OCR'd files that get created are tagged seperatly. This was created by AI. 

A safe, parallel batch OCR pipeline for Windows that scans a folder tree for PDF files, detects which ones lack searchable text, and runs [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) on them. Originals are never overwritten — they are renamed with a `__OCRPIPE_ORIG__` tag only after a successful OCR output has been produced.

## Features

- **Non-destructive by design** — original PDFs are renamed, not replaced
- **Dry-run mode** — preview what would be processed before making any changes
- **Smart detection** — samples pages to determine if a PDF already has sufficient text, skipping those that do
- **Parallel processing** — processes multiple PDFs concurrently
- **Auto-retry** — retries failed files with a lower optimization level
- **Optional deskew** — can apply deskew on retry or always
- **JSONL logging** — full per-file log for auditing

---

## Requirements

### 1. Python 3.8+

Download from [python.org](https://www.python.org/downloads/). During installation, check **"Add Python to PATH"**.

### 2. Tesseract OCR (Windows)

Tesseract is the OCR engine used under the hood. The easiest way to install it is via **winget** (built into Windows 10/11):

```
winget install UB-Mannheim.TesseractOCR
```

Verify: open a new terminal and run `tesseract --version`

<details>
<summary>Manual install (no winget)</summary>

1. Download the installer from the [UB-Mannheim Tesseract releases page](https://github.com/UB-Mannheim/tesseract/wiki)
2. Run the installer (default path: `C:\Program Files\Tesseract-OCR`)
3. Add `C:\Program Files\Tesseract-OCR` to your system PATH via **Start → Environment Variables → System Variables → Path**

</details>

### 3. Ghostscript (Windows)

Ghostscript is required by OCRmyPDF for PDF rendering and optimization. It is not currently available via winget. The quickest way to install it from a terminal is to download and run the installer directly (check [ghostscript.com/releases](https://ghostscript.com/releases/gsdnld.html) for the latest version number and update the URL accordingly):

```powershell
Invoke-WebRequest "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10051/gs10051w64.exe" -OutFile "$env:TEMP\gs_installer.exe"
& "$env:TEMP\gs_installer.exe"
```

After installing, add the `bin` folder to your system PATH:
- The path is typically `C:\Program Files\gs\gs10.x.x\bin`
- Open **Start → Search "Environment Variables" → System Variables → Path → Edit** and add it

Verify: open a new terminal and run `gswin64c --version`

### 4. Python Packages

Install all required Python packages:

```bash
pip install ocrmypdf pymupdf
```

> `pymupdf` provides the `fitz` module used for text-coverage detection.

---

## Additional Languages

By default the pipeline uses English (`eng`). If your PDFs contain other languages, you need to install the corresponding Tesseract language data and pass them via `--lang`.

**Install language packs via winget:**

```
winget install UB-Mannheim.TesseractOCR.Tessdata.Best
```

Or download individual `.traineddata` files from the [tessdata_best repository](https://github.com/tesseract-ocr/tessdata_best) into `C:\Program Files\Tesseract-OCR\tessdata`. For example, to download Spanish, Russian, and German from a PowerShell terminal:

```powershell
$tessdata = "C:\Program Files\Tesseract-OCR\tessdata"
$base = "https://github.com/tesseract-ocr/tessdata_best/raw/main"

foreach ($lang in @("spa", "rus", "deu")) {
    Invoke-WebRequest "$base/$lang.traineddata" -OutFile "$tessdata\$lang.traineddata"
}
```

Then pass the languages you need when running the script:

```bash
python safe_tagged_ocr_parallel_strict.py --root "C:\path\to\pdfs" --lang eng+spa+rus+deu
```

To see which languages are currently installed:

```
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs
```

---

## File Overview

| File | Description |
|---|---|
| `RunBatchOCR.bat` | Double-click launcher. Runs the PowerShell script using PowerShell 7 if available, otherwise Windows PowerShell. |
| `BatchOCR.ps1` | PowerShell wrapper that sets configuration and calls the Python script. Edit this file to set your folder path and options. |
| `safe_tagged_ocr_parallel_strict.py` | Core Python script. Handles detection, OCR, file management, and logging. |

---

## Quick Start

### Option A: Double-click launcher

1. Double-click `RunBatchOCR.bat`

### Option B: Run the Python script directly

**Dry run first (no changes made):**

```bash
python safe_tagged_ocr_parallel_strict.py --root "C:\path\to\your\pdfs"
```

**Execute for real:**

```bash
python safe_tagged_ocr_parallel_strict.py --root "C:\path\to\your\pdfs" --execute
```

---

## All Options

| Argument | Default | Description |
|---|---|---|
| `--root` | *(required)* | Root folder to scan recursively for PDFs |
| `--execute` | False | Actually make changes. Without this flag, runs as a dry run. |
| `--log` | *(none)* | Path to write a JSONL log file |
| `--lang` | `eng` | OCR language(s), e.g. `eng+spa+rus+deu` |
| `--renderer` | `sandwich` | OCRmyPDF renderer (`sandwich` or `hocr`) |
| `--ocr-jobs` | `2` | Threads per PDF (passed to `ocrmypdf --jobs`) |
| `--parallel-files` | `4` | Number of PDFs to process concurrently |
| `--sample-pages` | `20` | Number of pages to sample for text detection |
| `--page-min-chars` | `150` | Minimum characters on a page to consider it "texty" |
| `--min-coverage` | `0.30` | Fraction of sampled pages that must be texty to skip OCR |
| `--deskew` | False | Enable deskewing |
| `--deskew-mode` | `retry` | Apply deskew on `retry` only, or `always` |
| `--extra` | *(none)* | Any additional arguments to pass directly to `ocrmypdf` |

---

## How It Works

1. **Scan** — finds all PDFs under `--root` that are not already tagged
2. **Detect** — samples up to `--sample-pages` pages per PDF and checks for existing text
3. **Skip** — PDFs with sufficient text coverage are left untouched
4. **OCR** — for PDFs that need it:
   - Runs `ocrmypdf` with `--skip-text` to a temporary file (`__OCRPIPE_TMP__`)
   - On failure, retries with `--optimize 0` (and optionally `--deskew`)
   - On success, renames the original to `__OCRPIPE_ORIG__` and promotes the temp file to `__OCRPIPE_OCR__`
5. **Log** — optionally writes a JSONL record for every file processed

### Output file naming

Given an input file `MyBook.pdf`:

| File | Meaning |
|---|---|
| `MyBook __OCRPIPE_ORIG__.pdf` | The original, unmodified PDF |
| `MyBook __OCRPIPE_OCR__.pdf` | The new OCR'd, searchable PDF |

---

## Tips

- Always do a **dry run first** to see what will be processed
- The `--min-coverage 0.30` default means a PDF is skipped if at least 30% of sampled pages already have text — adjust this if you're getting false positives or false negatives
- For large libraries, increase `--parallel-files` and decrease `--ocr-jobs` to balance CPU load
- Use `--log ocr_results.jsonl` to keep a record of every action taken

---

## License

MIT
