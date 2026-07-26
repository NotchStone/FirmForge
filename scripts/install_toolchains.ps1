<#
.SYNOPSIS
    FirmForge Toolchain Installer — installs AVR build/flash/analysis tools.
.DESCRIPTION
    Installs to B区 (~/.firmforge/toolchains/). Detects existing installs.
    Idempotent: safe to re-run.

    Tools:
      - avr-gcc  (compiler)     → ~/.firmforge/toolchains/avr-gcc/
      - avrdude (flasher)       → ~/.firmforge/toolchains/avrdude/
      - cppcheck (static analysis) → ~/.firmforge/toolchains/cppcheck/
      - arduino-avr-core (SDK)  → ~/.firmforge/packages/arduino/avr/1.8.6/
      - Python packages (pyserial, mcp)
#>

$ErrorActionPreference = "Stop"
$B = "$env:USERPROFILE\.firmforge\toolchains"
$TEMP = "$env:TEMP\firmforge-toolchains"
$SCRIPT_VERSION = "1.0.0"

# ============================================================
# Download source configuration — edit mirrors here
# ============================================================
# Set $UseMirror = $true to prefer domestic (China) mirrors.
# Set $UseMirror = $false to use GitHub (global) sources.
$UseMirror = $false

# avr-gcc + avrdude (ZakKemble builds)
$AVR_GCC_GITHUB = "https://github.com/ZakKemble/avr-gcc-build/releases/download/v14.1.0-1/avr-gcc-14.1.0-x64-windows.zip"
$AVR_GCC_MIRROR = "https://mirrors.tuna.tsinghua.edu.cn/github-release/ZakKemble/avr-gcc-build/v14.1.0-1/avr-gcc-14.1.0-x64-windows.zip"
$AVRDUDE_GITHUB = "https://github.com/ZakKemble/avr-gcc-build/releases/download/v14.1.0-1/avrdude-8.1-x64-windows.zip"
$AVRDUDE_MIRROR = "https://mirrors.tuna.tsinghua.edu.cn/github-release/ZakKemble/avr-gcc-build/v14.1.0-1/avrdude-8.1-x64-windows.zip"

# Cppcheck
$CPPCHECK_GITHUB = "https://github.com/cppcheck-opensource/cppcheck/releases/download/2.21.0/cppcheck-2.21.0-x64-Setup.msi"
$CPPCHECK_MIRROR = "https://sourceforge.net/projects/cppcheck/files/cppcheck/2.21.0/cppcheck-2.21.0-x64-Setup.msi/download"

# ArduinoCore-avr (git clone)
$ARDUINO_CORE_GITHUB = "https://github.com/arduino/ArduinoCore-avr.git"
$ARDUINO_CORE_MIRROR = "https://gitee.com/mirrors/ArduinoCore-avr.git"

function Get-Url($primary, $mirror) {
    if ($UseMirror) { return $mirror }
    return $primary
}

function Invoke-Download($primaryUrl, $mirrorUrl, $outFile, $description) {
    $urls = if ($UseMirror) { @($mirrorUrl, $primaryUrl) } else { @($primaryUrl, $mirrorUrl) }
    foreach ($url in $urls) {
        $label = if ($url -eq $primaryUrl) { "GitHub" } else { "mirror" }
        Write-Do "  Trying $label: $url"
        try {
            Invoke-WebRequest -Uri $url -OutFile $outFile -TimeoutSec 120 -ErrorAction Stop
            if ((Get-Item $outFile).Length -gt 1024) {
                Write-Ok "Downloaded $description ($([math]::Round((Get-Item $outFile).Length/1MB,1))MB)"
                return $true
            }
        } catch {
            Write-Host "  Failed, trying next source..." -ForegroundColor Yellow
        }
    }
    return $false
}

# Prerequisites
Write-Header "Prerequisites"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Fail "git is not installed. Please install Git from https://git-scm.com/download/win"
}
Write-Ok "git: $(git --version)"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Fail "python is not installed. Please install Python 3.12+ from https://python.org"
}
Write-Ok "python: $(python --version)"

if ($UseMirror) {
    Write-Host "  Mirror mode: domestic (China) sources" -ForegroundColor Yellow
} else {
    Write-Host "  Source: GitHub (global). Set -UseMirror = true to use domestic mirrors." -ForegroundColor Gray
}
Write-Host ""
# ============================================================
# Helpers
# ============================================================
function Write-Header { Write-Host "`n=== $args[0] ===" -ForegroundColor Cyan }
function Write-Ok   { Write-Host "  ✅ $args[0]" -ForegroundColor Green }
function Write-Skip { Write-Host "  ⏭️  $args[0]" -ForegroundColor Yellow }
function Write-Do   { Write-Host "  → $args[0]" -ForegroundColor Gray }
function Write-Fail { Write-Host "  ❌ $args[0]" -ForegroundColor Red; exit 1 }

function Test-Url($url) {
    try { Invoke-WebRequest -Uri $url -Method Head -TimeoutSec 5 | Out-Null; return $true }
    catch { return $false }
}

# ============================================================
# 1. avr-gcc 14.1.0
# ============================================================
Write-Header "1/5 — avr-gcc 14.1.0"

$AVR_DIR = "$B\avr-gcc"
$AVR_BIN = "$AVR_DIR\bin\avr-gcc.exe"
$AVR_VER = "14.1.0"
# microchip/mcu8 release: avr-gcc 14.1.0 Windows
$AVR_URL = Get-Url $AVR_GCC_GITHUB $AVR_GCC_MIRROR

if (Test-Path $AVR_BIN) {
    Write-Skip "avr-gcc already installed at $AVR_BIN"
} else {
    Write-Do "Downloading avr-gcc $AVR_VER..."
    New-Item -ItemType Directory -Force -Path $TEMP | Out-Null
    $zip = "$TEMP\avr-gcc.zip"
    if (-not (Invoke-Download $AVR_GCC_GITHUB $AVR_GCC_MIRROR $zip "avr-gcc")) {
        Write-Fail "Download failed from all sources"
    }
    Write-Do "Extracting to $AVR_DIR..."
    New-Item -ItemType Directory -Force -Path $AVR_DIR | Out-Null
    Expand-Archive -Path $zip -DestinationPath "$TEMP\avr-gcc-extracted" -Force
    # The zip contains a single top-level dir like avr-gcc-14.1.0-x64-windows/
    $extracted = Get-ChildItem "$TEMP\avr-gcc-extracted" -Directory | Select-Object -First 1
    if ($extracted) {
        Copy-Item -Recurse -Force "$($extracted.FullName)\*" $AVR_DIR
    } else {
        Copy-Item -Recurse -Force "$TEMP\avr-gcc-extracted\*" $AVR_DIR
    }
    Remove-Item -Recurse -Force "$TEMP\avr-gcc-extracted", $zip -ErrorAction SilentlyContinue
    Write-Ok "avr-gcc installed (run --version to verify)"
}
# Verify
if (Test-Path $AVR_BIN) {
    $ver = & $AVR_BIN --version 2>&1 | Select-String "gcc" | Select-Object -First 1
    Write-Ok "avr-gcc: $ver"
}

# ============================================================
# 2. avrdude 8.1
# ============================================================
Write-Header "2/5 — avrdude 8.1"

$AVRDUDE_DIR = "$B\avrdude"
$AVRDUDE_EXE = "$AVRDUDE_DIR\avrdude.exe"
$AVRDUDE_VER = "8.1"
$AVRDUDE_URL = Get-Url $AVRDUDE_GITHUB $AVRDUDE_MIRROR

if (Test-Path $AVRDUDE_EXE) {
    Write-Skip "avrdude already installed at $AVRDUDE_EXE"
} else {
    Write-Do "Downloading avrdude $AVRDUDE_VER..."
    New-Item -ItemType Directory -Force -Path $TEMP | Out-Null
    $zip = "$TEMP\avrdude.zip"
    if (-not (Invoke-Download $AVRDUDE_GITHUB $AVRDUDE_MIRROR $zip "avrdude")) {
        Write-Fail "Download failed from all sources"
    }
    Write-Do "Extracting to $AVRDUDE_DIR..."
    New-Item -ItemType Directory -Force -Path $AVRDUDE_DIR | Out-Null
    Expand-Archive -Path $zip -DestinationPath "$TEMP\avrdude-extracted" -Force
    $extracted = Get-ChildItem "$TEMP\avrdude-extracted" -Directory | Select-Object -First 1
    if ($extracted) {
        Copy-Item -Recurse -Force "$($extracted.FullName)\*" $AVRDUDE_DIR
    } else {
        Copy-Item -Recurse -Force "$TEMP\avrdude-extracted\*" $AVRDUDE_DIR
    }
    Remove-Item -Recurse -Force "$TEMP\avrdude-extracted", $zip -ErrorAction SilentlyContinue
    Write-Ok "avrdude installed"
}
if (Test-Path $AVRDUDE_EXE) {
    $ver = & $AVRDUDE_EXE -? 2>&1 | Select-String "avrdude version" | Select-Object -First 1
    Write-Ok "avrdude: $ver"
}

# ============================================================
# 3. Cppcheck 2.21
# ============================================================
Write-Header "3/5 — Cppcheck 2.21"

$CPP_DIR = "$B\cppcheck"
$CPP_EXE = "$CPP_DIR\cppcheck.exe"
$CPP_VER = "2.21.0"

if (Test-Path $CPP_EXE) {
    Write-Skip "Cppcheck already installed at $CPP_EXE"
} else {
    Write-Do "Downloading Cppcheck $CPP_VER..."
    New-Item -ItemType Directory -Force -Path $TEMP | Out-Null
    $msi = "$TEMP\cppcheck.msi"
    if (-not (Invoke-Download $CPPCHECK_GITHUB $CPPCHECK_MIRROR $msi "cppcheck")) {
        Write-Fail "Download failed from all sources"
    }
    Write-Do "Extracting MSI to $CPP_DIR..."
    New-Item -ItemType Directory -Force -Path $CPP_DIR | Out-Null
    # Use msiexec /a for admin-free extraction
    $log = "$TEMP\cppcheck-install.log"
    Start-Process msiexec -ArgumentList "/a `"$msi`" /qb TARGETDIR=`"$CPP_DIR`" /log `"$log`"" -Wait
    # Move files from subdirectory (PFiles/Cppcheck/) up one level
    if (Test-Path "$CPP_DIR\PFiles\Cppcheck") {
        Copy-Item -Recurse -Force "$CPP_DIR\PFiles\Cppcheck\*" $CPP_DIR
        Remove-Item -Recurse -Force "$CPP_DIR\PFiles" -ErrorAction SilentlyContinue
    }
    Remove-Item -Force $msi -ErrorAction SilentlyContinue
    Write-Ok "Cppcheck installed"
}
if (Test-Path $CPP_EXE) {
    $ver = & $CPP_EXE --version 2>&1 | Select-Object -First 1
    Write-Ok "cppcheck: $ver"
}

# ============================================================
# 4. ArduinoCore-avr 1.8.6
# ============================================================
Write-Header "4/4 — ArduinoCore-avr 1.8.6"

$CORE_DIR = "$env:USERPROFILE\.firmforge\packages\arduino\avr\1.8.6"
$CORE_HEADER = "$CORE_DIR\cores\arduino\Arduino.h"

if (Test-Path $CORE_HEADER) {
    Write-Skip "ArduinoCore-avr already installed at $CORE_DIR"
} else {
    Write-Do "Cloning ArduinoCore-avr..."
    New-Item -ItemType Directory -Force -Path $CORE_DIR | Out-Null
    $repos = if ($UseMirror) { @($ARDUINO_CORE_MIRROR, $ARDUINO_CORE_GITHUB) } else { @($ARDUINO_CORE_GITHUB, $ARDUINO_CORE_MIRROR) }
    $cloned = $false
    foreach ($repo in $repos) {
        $label = if ($repo -eq $ARDUINO_CORE_GITHUB) { "GitHub" } else { "Gitee" }
        Write-Do "  Trying $label: $repo"
        try {
            git clone --depth 1 --branch 1.8.6 $repo "$TEMP\arduino-core" 2>&1 | Out-Null
            if (Test-Path "$TEMP\arduino-core\cores\arduino\Arduino.h") {
                $cloned = $true
                Write-Ok "Cloned from $label"
                break
            }
        } catch {
            Write-Host "  Failed, trying next source..." -ForegroundColor Yellow
        }
    }
    if (-not $cloned) {
        Write-Fail "git clone failed from all sources"
    }
    Write-Do "Copying to $CORE_DIR..."
    Copy-Item -Recurse -Force "$TEMP\arduino-core\*" $CORE_DIR
    Remove-Item -Recurse -Force "$TEMP\arduino-core" -ErrorAction SilentlyContinue
    Write-Ok "ArduinoCore-avr installed"
}
if (Test-Path $CORE_HEADER) {
    Write-Ok "ArduinoCore-avr: Arduino.h found"
}

# ============================================================
# 5. Python dependencies
# ============================================================
Write-Header "5/5 — Python packages"
$PYTHON = (Get-Command python).Source
$DEPS = @("pyserial", "mcp>=1.2,<2", "pyyaml")

foreach ($dep in $DEPS) {
    Write-Do "Installing $dep..."
    & $PYTHON -m pip install $dep -q --no-warn-script-location 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "$dep OK"
    } else {
        Write-Fail "pip install $dep failed"
    }
}

# ============================================================
# 6. FirmForge itself (pip install -e .)
# ============================================================
Write-Header "6/6 — FirmForge project"

$ROOT = Split-Path -Parent $PSScriptRoot
$ROOT = Split-Path -Parent $ROOT

Write-Do "Installing firmforge from $ROOT..."
Push-Location $ROOT
try {
    & $PYTHON -m pip install -e . -q --no-warn-script-location 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "firmforge installed"
    } else {
        Write-Fail "pip install firmforge failed"
    }
} finally {
    Pop-Location
}

# ============================================================
# Cleanup
# ============================================================
Write-Header "Cleanup"
Remove-Item -Recurse -Force $TEMP -ErrorAction SilentlyContinue
Write-Ok "Temp files removed"

Write-Header "All done!"
Write-Host "  Toolchain root: $B" -ForegroundColor Cyan
Write-Host "  FirmForge will auto-detect these tools." -ForegroundColor Cyan
Write-Host "  Run 'python -m firmforge build arduino_mega --app <dir>' to test." -ForegroundColor Cyan
