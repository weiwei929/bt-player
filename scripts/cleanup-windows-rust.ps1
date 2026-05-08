# BT-Player Windows Rust cleanup script
# Run as Administrator after WSL migration is confirmed working.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\cleanup-windows-rust.ps1

Write-Host "===========================================" -ForegroundColor Cyan
Write-Host " BT-Player Windows Rust Toolchain Cleanup" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""

# ===== Confirmation =====
$confirmation = Read-Host "This will delete Rust toolchain and Windows files (~4GB). Continue? (y/N)"
if ($confirmation -ne "y") {
    Write-Host "Cancelled" -ForegroundColor Yellow
    exit
}

# ===== Step 1: Clean Rust toolchain =====
Write-Host ""
Write-Host "[Step 1/4] Cleaning Rust toolchain..." -ForegroundColor Yellow

$cargoPath = "$env:USERPROFILE\.cargo"
$rustupPath = "$env:USERPROFILE\.rustup"

# Check and delete junctions/symlinks to D:\UserData
if (Test-Path $cargoPath) {
    $item = Get-Item $cargoPath -Force -ErrorAction SilentlyContinue
    if ($item.LinkType -eq "Junction" -or $item.LinkType -eq "SymbolicLink") {
        Write-Host "  Removing junction: $cargoPath"
        Remove-Item $cargoPath -Force -Recurse -ErrorAction SilentlyContinue
    }
}
if (Test-Path $rustupPath) {
    $item = Get-Item $rustupPath -Force -ErrorAction SilentlyContinue
    if ($item.LinkType -eq "Junction" -or $item.LinkType -eq "SymbolicLink") {
        Write-Host "  Removing junction: $rustupPath"
        Remove-Item $rustupPath -Force -Recurse -ErrorAction SilentlyContinue
    }
}

# Delete actual data on D:\UserData
$userDataCargo = "D:\UserData\.cargo"
$userDataRustup = "D:\UserData\.rustup"

if (Test-Path $userDataCargo) {
    $size = "{0:N2} MB" -f ((Get-ChildItem $userDataCargo -Recurse -ErrorAction SilentlyContinue | Measure-Object Length -Sum -ErrorAction SilentlyContinue).Sum / 1MB)
    Write-Host "  Deleting $userDataCargo ($size)"
    Remove-Item $userDataCargo -Force -Recurse -ErrorAction SilentlyContinue
}
if (Test-Path $userDataRustup) {
    $size = "{0:N2} MB" -f ((Get-ChildItem $userDataRustup -Recurse -ErrorAction SilentlyContinue | Measure-Object Length -Sum -ErrorAction SilentlyContinue).Sum / 1MB)
    Write-Host "  Deleting $userDataRustup ($size)"
    Remove-Item $userDataRustup -Force -Recurse -ErrorAction SilentlyContinue
}

Write-Host "  [Done]" -ForegroundColor Green

# ===== Step 2: Clean PATH environment =====
Write-Host ""
Write-Host "[Step 2/4] Cleaning Rust PATH entries..." -ForegroundColor Yellow

$targets = @("User", "Machine")
foreach ($scope in $targets) {
    $currentPath = [Environment]::GetEnvironmentVariable("Path", $scope)
    if ($currentPath) {
        $segments = $currentPath -split ';'
        $clean = @()
        foreach ($seg in $segments) {
            if ($seg -notmatch '\.cargo\\bin' -and $seg -notmatch '\.rustup') {
                $clean += $seg
            }
        }
        $newPath = $clean -join ';'
        if ($currentPath -ne $newPath) {
            [Environment]::SetEnvironmentVariable("Path", $newPath, $scope)
            Write-Host "  Cleaned cargo/rustup from $scope PATH"
        }
    }
}

Write-Host "  [Done]" -ForegroundColor Green

# ===== Step 3: Clean project Windows files =====
Write-Host ""
Write-Host "[Step 3/4] Cleaning project Windows-specific files..." -ForegroundColor Yellow

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$mpvDir = Join-Path $projectRoot "src-tauri\mpv"
$scriptsDir = Join-Path $projectRoot "scripts"

$mpvFiles = @(
    "mpv-1.dll", "libmpv-2.dll", "libmpv.dll.a",
    "mpv.lib", "mpv.exp", "libmpv.def",
    "mpv-dev.7z", "mpv-dev-msvc.7z"
)

$deleted = 0
foreach ($file in $mpvFiles) {
    $path = Join-Path $mpvDir $file
    if (Test-Path $path) {
        Remove-Item $path -Force -ErrorAction SilentlyContinue
        Write-Host "  Deleted: src-tauri\mpv\$file"
        $deleted++
    }
}

# Remove mpv/include
$mpvInclude = Join-Path $mpvDir "include"
if (Test-Path $mpvInclude) {
    Remove-Item $mpvInclude -Force -Recurse -ErrorAction SilentlyContinue
    Write-Host "  Deleted: src-tauri\mpv\include"
    $deleted++
}

# Remove Windows-only scripts
$windowsScripts = @(
    "fetch-mpv.ps1",
    "cleanup-browser-cache.ps1",
    "cleanup-orphaned-appdata.ps1",
    "migrate-to-d.ps1"
)

foreach ($script in $windowsScripts) {
    $path = Join-Path $scriptsDir $script
    if (Test-Path $path) {
        Remove-Item $path -Force -ErrorAction SilentlyContinue
        Write-Host "  Deleted: scripts\$script"
        $deleted++
    }
}

if ($deleted -eq 0) {
    Write-Host "  (already cleaned - nothing to delete)"
}
Write-Host "  [Done]" -ForegroundColor Green

# ===== Step 4: Check for MSVC Build Tools =====
Write-Host ""
Write-Host "[Step 4/4] Checking for MSVC Build Tools..." -ForegroundColor Yellow

$vsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $vsWhere) {
    $vsInstances = & $vsWhere -products * -legacy -format json | ConvertFrom-Json
    $found = $false
    foreach ($instance in $vsInstances) {
        if ($instance.description -match "Build Tools|Visual Studio") {
            Write-Host "  Found: $($instance.description)"
            Write-Host "  Path: $($instance.installationPath)"
            Write-Host "  => Uninstall via: Settings > Apps > Installed apps"
            $found = $true
        }
    }
    if (-not $found) {
        Write-Host "  No MSVC Build Tools found (may have been uninstalled already)"
    }
} else {
    Write-Host "  vswhere not found (VS Installer not detected)"
}

Write-Host "  [Done]" -ForegroundColor Green

# ===== Done =====
Write-Host ""
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host " Cleanup Complete!" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Manual steps to check:" -ForegroundColor Yellow
Write-Host "  - Settings > Apps > Installed apps: search for Rust, uninstall if found"
Write-Host "  - Settings > Apps > Installed apps: search for Visual Studio, uninstall if found"
Write-Host "  - If D:\UserData\.cargo or .rustup still exist, delete manually"
Write-Host ""
Write-Host "WSL has its own Rust toolchain and is not affected."
