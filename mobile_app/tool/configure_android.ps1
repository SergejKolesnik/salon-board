param(
    [string]$AppName = "Body Balance CRM"
)

$manifestPath = Join-Path $PSScriptRoot "..\android\app\src\main\AndroidManifest.xml"
if (-not (Test-Path $manifestPath)) {
    Write-Error "AndroidManifest.xml not found. Run: flutter create --platforms=android ."
    exit 1
}

$manifest = Get-Content -Raw -LiteralPath $manifestPath
if ($manifest -match 'android:label="[^"]*"') {
    $manifest = $manifest -replace 'android:label="[^"]*"', "android:label=`"$AppName`""
} else {
    $manifest = $manifest -replace '<application', "<application android:label=`"$AppName`""
}

Set-Content -LiteralPath $manifestPath -Value $manifest -Encoding UTF8
Write-Host "Android app label set to '$AppName'."
