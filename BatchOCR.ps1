# BatchOCR.ps1
# Prompts for a root folder, then runs safe_tagged_ocr_parallel_strict.py with your chosen options.

$ErrorActionPreference = "Stop"

function Prompt-Default([string]$Prompt, [string]$Default) {
  $v = Read-Host "$Prompt [$Default]"
  if ([string]::IsNullOrWhiteSpace($v)) { return $Default }
  return $v
}

# --- Locate script next to this .ps1 ---
$scriptPath = Join-Path -Path $PSScriptRoot -ChildPath "safe_tagged_ocr_parallel_strict.py"
if (-not (Test-Path -LiteralPath $scriptPath)) {
  Write-Host "ERROR: Couldn't find safe_tagged_ocr_parallel_strict.py next to this launcher." -ForegroundColor Red
  Write-Host "Expected: $scriptPath"
  Read-Host "Press Enter to exit"
  exit 1
}

# --- Root folder ---
$root = Read-Host 'Enter full root folder to scan (e.g. K:\eBooks\Book Files)'
if ([string]::IsNullOrWhiteSpace($root)) {
  Write-Host "No folder provided." -ForegroundColor Red
  Read-Host "Press Enter to exit"
  exit 1
}
if (-not (Test-Path -LiteralPath $root)) {
  Write-Host "Folder not found: $root" -ForegroundColor Red
  Read-Host "Press Enter to exit"
  exit 1
}

# --- Mode ---
$doExecute = Read-Host "Execute changes? Type Y to EXECUTE, anything else = DRY-RUN"
$executeFlag = ""
if ($doExecute -match '^(y|yes)$') { $executeFlag = "--execute" }

# --- Defaults (you can press Enter to keep) ---
$parallelFiles = Prompt-Default "Parallel PDFs to process (--parallel-files)" "6"
$ocrJobs       = Prompt-Default "OCRmyPDF jobs per file (--ocr-jobs)" "2"
$samplePages   = Prompt-Default "Sample pages for detection (--sample-pages)" "10"

$deskew = Read-Host "Deskew? (Y/N). If Y, deskew happens on retry by default."
$deskewFlags = @()
if ($deskew -match '^(y|yes)$') {
  $deskewMode = Prompt-Default "Deskew mode (--deskew-mode retry|always)" "retry"
  $deskewFlags = @("--deskew", "--deskew-mode", $deskewMode)
}

# --- Log path ---
$defaultLog = Join-Path -Path ([Environment]::GetFolderPath("Desktop")) -ChildPath "ocr_run_$(Get-Date -Format yyyyMMdd_HHmmss).jsonl"
$logPath = Prompt-Default "Log file path (--log). Put it somewhere safe" $defaultLog

# --- Choose Python launcher ---
# Prefer the Windows py launcher if present; otherwise fall back to python on PATH.
$pyCmd = $null
$pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
  $pyCmd = "py"
  $pyArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  $pyCmd = "python"
  $pyArgs = @()
} else {
  Write-Host "ERROR: Could not find 'py' or 'python' on PATH." -ForegroundColor Red
  Write-Host "Install Python or fix PATH, then try again."
  Read-Host "Press Enter to exit"
  exit 1
}

Write-Host ""
Write-Host "----------------------"
Write-Host "Batch OCR launch"
Write-Host "Script: $scriptPath"
Write-Host "Root:   $root"
Write-Host ("Mode:   " + ($(if ($executeFlag) {"EXECUTE"} else {"DRY-RUN"})))
Write-Host "Log:    $logPath"
Write-Host "----------------------"
Write-Host ""

# --- Run ---
$cmdArgs = @(
  $pyArgs
  $scriptPath
  "--root", $root
)
if ($executeFlag) { $cmdArgs += $executeFlag }

$cmdArgs += @("--parallel-files", $parallelFiles, "--ocr-jobs", $ocrJobs, "--sample-pages", $samplePages, "--log", $logPath)
if ($deskewFlags.Count -gt 0) { $cmdArgs += $deskewFlags }

Write-Host "Running:"
Write-Host ("  " + $pyCmd + " " + ($cmdArgs -join " "))
Write-Host ""

& $pyCmd @cmdArgs

Write-Host ""
Read-Host "Done. Press Enter to exit"
