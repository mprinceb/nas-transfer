$ErrorActionPreference = 'Stop'
$InstallDir = Join-Path $env:LOCALAPPDATA 'EgoTrinetTransfer'
function Find-AppPython {
    $candidates = @()
    foreach ($cmd in @('python.exe', 'python3.exe')) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found -and $found.Source -notlike '*WindowsApps*') { $candidates += $found.Source }
    }
    foreach ($base in @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles", 'C:\')) {
        $candidates += @(Get-ChildItem -Path $base -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.FullName 'python.exe' })
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path $candidate)) { continue }
        try {
            & $candidate -c 'import sys, tkinter; assert sys.version_info >= (3,10)' 2>$null
            if ($LASTEXITCODE -eq 0 -and (Test-Path (Join-Path (Split-Path $candidate) 'pythonw.exe'))) { return $candidate }
        } catch { }
    }
    return $null
}
Write-Host 'Checking Python 3.10+ and Tkinter...'
$Python = Find-AppPython
if (-not $Python) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw 'Install Microsoft App Installer (winget), then rerun this installer; or install Python from python.org with Tcl/Tk enabled.'
    }
    Write-Host 'Installing Python with Tkinter using Windows Package Manager...'
    & winget.exe install --id Python.Python.3.12 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Python installation failed. Check the winget output above.' }
    $Python = Find-AppPython
    if (-not $Python) { throw 'Python/Tkinter could not be verified after installation.' }
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
foreach ($file in @('nas_transfer.py','nas_transfer_cli.py','nas_windows.py','nas_paths.py','nas_config.py','nas_video.py','README.md')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $InstallDir -Force
}
$PythonW = Join-Path (Split-Path $Python) 'pythonw.exe'
$Shell = New-Object -ComObject WScript.Shell
foreach ($location in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $Shortcut = $Shell.CreateShortcut((Join-Path $location 'Ego Trinet Transfer.lnk'))
    $Shortcut.TargetPath = $PythonW
    $Shortcut.Arguments = '"' + (Join-Path $InstallDir 'nas_transfer.py') + '"'
    $Shortcut.WorkingDirectory = $InstallDir
    $Shortcut.Description = 'Transfer and verify up to 15 SD cards to Ego NAS'
    $Shortcut.Save()
}
$Cli = '@echo off' + "`r`n" + '"' + $Python + '" "' + (Join-Path $InstallDir 'nas_transfer_cli.py') + '" %*' + "`r`n"
Set-Content -LiteralPath (Join-Path $InstallDir 'Ego-CLI.cmd') -Value $Cli -Encoding ASCII
Write-Host "Installed in $InstallDir"
Write-Host 'Open Ego Trinet Transfer from your desktop or Start menu.'
Write-Host 'The app uses the configured NAS credentials automatically.'
