$ErrorActionPreference = 'Stop'
$softwareRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
foreach ($part in @('', 'babel_client', 'software_native/engine')) {
    Push-Location (Join-Path $softwareRoot $part)
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "Dependency install failed: $part" }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Native build failed: $part" }
    } finally { Pop-Location }
}
