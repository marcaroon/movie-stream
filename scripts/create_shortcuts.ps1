# Creates "MarTube" shortcuts on the Desktop and in the Start Menu.
# They run launcher.py with pythonw (no console window) from the project's .venv: it starts the
# local server if needed and opens http://127.0.0.1:8765 in the default browser.
# Re-run after moving the project folder; run with -Remove to delete the shortcuts.
param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$name = 'MarTube'
$project = Split-Path -Parent $PSScriptRoot
$folders = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))

if ($Remove) {
    foreach ($folder in $folders) {
        $path = Join-Path $folder "$name.lnk"
        if (Test-Path $path) { Remove-Item $path; Write-Output "Removed $path" }
    }
    return
}

$pythonw = Join-Path $project '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) {
    $pythonw = (Get-Command pythonw.exe).Source
}

$shell = New-Object -ComObject WScript.Shell
foreach ($folder in $folders) {
    $link = $shell.CreateShortcut((Join-Path $folder "$name.lnk"))
    $link.TargetPath = $pythonw
    $link.Arguments = '"' + (Join-Path $project 'launcher.py') + '"'
    $link.WorkingDirectory = $project
    $link.Description = $name
    $link.Save()
    Write-Output "Created $($link.FullName)"
}
