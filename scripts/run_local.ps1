$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$EnvFile = Join-Path $ProjectRoot ".env"

if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $Line = $_.Trim()

        if ($Line -eq "" -or $Line.StartsWith("#")) {
            return
        }

        if ($Line -match "^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$") {
            $Key = $Matches[1]
            $Value = $Matches[2].Trim()

            # Strip matching outer quotes only when the value is at least 2 chars long.
            if ($Value.Length -ge 2) {
                if (($Value.StartsWith('"') -and $Value.EndsWith('"')) -or
                    ($Value.StartsWith("'") -and $Value.EndsWith("'"))) {
                    $Value = $Value.Substring(1, $Value.Length - 2)
                }
            }

            [Environment]::SetEnvironmentVariable($Key, $Value, "Process")
        }
    }
} else {
    Write-Warning ".env not found at $EnvFile — starting with system environment variables only."
}

$Port = $env:APP_PORT
if ([string]::IsNullOrWhiteSpace($Port)) {
    $Port = "8000"
}

$Uvicorn = Join-Path $ProjectRoot ".venv\Scripts\uvicorn.exe"
if (-not (Test-Path $Uvicorn)) {
    throw "Cannot find $Uvicorn. Create the virtual environment and install dependencies first."
}

Set-Location $ProjectRoot
& $Uvicorn app.main:app --host 0.0.0.0 --port $Port --reload
exit $LASTEXITCODE
