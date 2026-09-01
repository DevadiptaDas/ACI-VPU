# ACI installer (Windows) — installs the FULL experience by default (semantic memory +
# the UQRT-MCA NLP cost engine). Double-click install.bat, or:
#   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$nlp = Join-Path $repo "..\uqrt-mca-nlp"
Write-Host "==== Installing ACI-VPU + UQRT-MCA NLP ====" -ForegroundColor Cyan

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Host "Python launcher 'py' not found. Install Python 3.10+ from python.org, then re-run." -ForegroundColor Red
    exit 1
}
py --version

$mode = Read-Host "`nInstall the FULL experience — semantic memory + cost engine (~1-2 GB download)? [Y/n]"
$full = ($mode -ne "n")

if ($full) {
    Write-Host "`n[1/6] Installing ACI-VPU + full power-ups (semantic search, ANN, encryption)..."
    py -m pip install -e "$repo[full]"
    Write-Host "`n[2/6] Downloading the language model for extraction (spaCy)..."
    py -m spacy download en_core_web_sm
    if (Test-Path $nlp) {
        Write-Host "`n[3/6] Installing the UQRT-MCA NLP brain (cost engine + bundled local model)..."
        py -m pip install -e $nlp
        py -m pip install llama-cpp-python        # prebuilt CPU wheels; powers the free local model
    } else {
        Write-Host "      NLP package not found beside ACI. Install it separately for the cost engine:" -ForegroundColor Yellow
        Write-Host "        pip install uqrt-mca-nlp" -ForegroundColor Yellow
    }
} else {
    Write-Host "`n[1/6] Installing the lightweight ACI core (stdlib only — lexical search, no cost engine)..."
    py -m pip install -e $repo
    Write-Host "      Lite mode. Re-run and choose Y for semantic memory + the cost engine."
}

Write-Host "`n[4/6] Enabling always-on (start hidden on login)..."
py -m aci.cli autostart

Write-Host "`n[5/6] AI bridge — register ACI with Claude Code / Cursor:" -ForegroundColor Yellow
Write-Host "      claude mcp add aci --env ACI_URL=http://127.0.0.1:7077 -- py `"$repo\mcp_aci.py`""

Write-Host "`n[6/6] Browser capture — chrome://extensions -> Developer mode -> Load unpacked:" -ForegroundColor Yellow
Write-Host "      $repo\clients\browser-extension"

Write-Host "`n==== Installed ====" -ForegroundColor Green
Write-Host "See it work  : py `"$repo\demo.py`"        <- 60-second proof (memory + truth + cost)" -ForegroundColor Cyan
Write-Host "Console      : py `"$repo\quickstart.py`""
Write-Host "Check setup  : py -m aci.cli onboard"
Write-Host "Encrypt data : py -m aci.cli set-key --passphrase `"your phrase`""
