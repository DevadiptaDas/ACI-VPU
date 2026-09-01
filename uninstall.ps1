# ACI uninstaller (Windows). Run: powershell -ExecutionPolicy Bypass -File uninstall.ps1
$repo = $PSScriptRoot
Write-Host "==== Uninstalling ACI ====" -ForegroundColor Cyan

Write-Host "[1/4] Removing login autostart..."
try { py -m aci.cli autostart --remove } catch {}

Write-Host "[2/4] Stopping the service (if running)..."
try { py -m aci.cli stop } catch {}

Write-Host "[3/4] AI bridge - to unregister: claude mcp remove aci" -ForegroundColor Yellow

$wipe = Read-Host "[4/4] Delete ALL stored ACI data too? [y/N]"
if ($wipe -eq "y") {
    try { py -m aci.cli wipe --confirm } catch {}
    Remove-Item "$repo\aci_data.db*" -ErrorAction SilentlyContinue
    Remove-Item "$env:USERPROFILE\.aci\key.dpapi" -ErrorAction SilentlyContinue
    Write-Host "      Data + encryption key removed."
} else {
    Write-Host "      Data kept at $repo\aci_data.db"
}

Write-Host "`nRemove the package:  py -m pip uninstall aci-vpu" -ForegroundColor Yellow
Write-Host "Done." -ForegroundColor Green
