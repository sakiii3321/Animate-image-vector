param(
    [switch]$Apply,
    [string]$ReportPath
)

# This versioned allowlist only trims the reviewed Windows portable runtime.
# Without -Apply the command reports the candidates and does not remove them.
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath.TrimEnd('\')
$runtimePrefix = (Join-Path $projectRoot 'runtime') + '\'
$outputPrefix = (Join-Path $projectRoot 'outputs') + '\'
$rules = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'runtime-prune-rules.json') -Raw | ConvertFrom-Json
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'app\main.py'))) {
    throw 'Run this script from an ImageVector checkout.'
}
if (-not $ReportPath) {
    $ReportPath = Join-Path $projectRoot 'outputs\runtime-prune\report.json'
}
$ReportPath = [IO.Path]::GetFullPath($ReportPath)
if (-not $ReportPath.StartsWith($outputPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The report must be inside this project''s outputs directory.'
}

function Assert-PlainRuntimePath([string]$RelativePath) {
    if ([IO.Path]::IsPathRooted($RelativePath) -or $RelativePath -match '(^|[/\\])\.{1,2}([/\\]|$)') {
        throw "Target must be a relative path without traversal: $RelativePath"
    }
    $portablePath = $RelativePath.Replace('\', '/')
    $allowed = $portablePath -match '^runtime/potrace/node_modules/[^/]+$' -or
        $portablePath -match '^runtime/potrace/node_modules/\.bin/(mime|mkdirp|pixelmatch)(\.CMD|\.ps1)?$' -or
        $portablePath -match '^runtime/Lib/site-packages/(numpy|scipy|sklearn|networkx)/(.+/)?tests$' -or
        $portablePath -in @('runtime/Lib/site-packages/bin',
            'runtime/Lib/site-packages/cv2/opencv_videoio_ffmpeg500_64.dll',
            'runtime/Lib/site-packages/scipy-1.18.1-cp314-cp314-win_amd64.whl')
    if (-not $allowed -or $portablePath -eq 'runtime/Lib/site-packages/scipy/special/tests') {
        throw "Target is outside the reviewed resource categories: $RelativePath"
    }
    $absolute = [IO.Path]::GetFullPath((Join-Path $projectRoot $RelativePath))
    if (-not $absolute.StartsWith($runtimePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Target is outside the intended runtime: $RelativePath"
    }
    if ($RelativePath -match '(^|[/\\])\.pnpm([/\\]|$)' -or
        $RelativePath -match '^runtime[/\\](enhancement|node)([/\\]|$)' -or
        $RelativePath -match '^runtime[/\\]potrace[/\\]node_modules[/\\](potrace|sharp)([/\\]|$)') {
        throw "Target is a protected runtime component: $RelativePath"
    }
    $probe = $absolute
    while ($probe -ne $projectRoot) {
        if (Test-Path -LiteralPath $probe) {
            $item = Get-Item -LiteralPath $probe -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing a link or junction: $probe"
            }
        }
        $probe = [IO.Path]::GetDirectoryName($probe)
    }
    return $absolute
}

$present = [Collections.Generic.List[object]]::new()
$missing = [Collections.Generic.List[string]]::new()
foreach ($rule in $rules.targets) {
    $absolute = Assert-PlainRuntimePath $rule.path
    if (-not (Test-Path -LiteralPath $absolute)) {
        $missing.Add($rule.path)
        continue
    }
    $item = Get-Item -LiteralPath $absolute -Force
    if (($rule.kind -eq 'directory') -ne [bool]$item.PSIsContainer) {
        throw "Target type changed: $($rule.path)"
    }
    $children = if ($item.PSIsContainer) { @(Get-ChildItem -LiteralPath $absolute -Force -Recurse) } else { @($item) }
    if (@($children | Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 }).Count) {
        throw "Target contains links or junctions: $($rule.path)"
    }
    $files = @($children | Where-Object { -not $_.PSIsContainer })
    $bytes = [long](($files | Measure-Object Length -Sum).Sum)
    if ($files.Count -ne $rule.files -or $bytes -ne $rule.bytes) {
        throw "Target contents changed; review the allowlist before trimming: $($rule.path)"
    }
    $present.Add([pscustomobject]@{path=$rule.path; absolute=$absolute; kind=$rule.kind; category=$rule.category; files=$files.Count; bytes=$bytes})
}

if (@($present | Where-Object { $_.category -like 'node-*' }).Count) {
    $storePrefix = (Join-Path $projectRoot 'runtime\potrace\node_modules\.pnpm') + '\'
    foreach ($package in @('potrace', 'sharp')) {
        $entry = Get-Item -LiteralPath (Join-Path $projectRoot "runtime\potrace\node_modules\$package") -Force
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0 -or -not $entry.Target) {
            throw "Expected the active $package entry to link into .pnpm; no files removed."
        }
        $linkTarget = @($entry.Target)[0]
        if (-not [IO.Path]::IsPathRooted($linkTarget)) { $linkTarget = Join-Path $entry.Parent.FullName $linkTarget }
        $linkTarget = [IO.Path]::GetFullPath($linkTarget)
        if (-not $linkTarget.StartsWith($storePrefix, [StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-Path -LiteralPath (Join-Path $linkTarget 'package.json'))) {
            throw "Active $package does not resolve into the retained store; no files removed."
        }
    }
}

$removed = [Collections.Generic.List[string]]::new()
$failure = $null
if ($Apply) {
    foreach ($entry in $present) {
        try {
            # Recheck the concrete absolute path before each recursive operation.
            $absolute = Assert-PlainRuntimePath $entry.path
            Remove-Item -LiteralPath $absolute -Recurse -Force
            $removed.Add($entry.path)
        } catch {
            $failure = $_.Exception.Message
            break
        }
    }
}
$report = [ordered]@{
    schema_version=1
    mode=$(if ($Apply) { 'apply' } else { 'preview' })
    completed_utc=[DateTime]::UtcNow.ToString('o')
    target_count=$present.Count
    target_files=[long](($present | Measure-Object files -Sum).Sum)
    target_bytes=[long](($present | Measure-Object bytes -Sum).Sum)
    candidates=@($present | Select-Object path,kind,category,files,bytes)
    already_absent=@($missing.ToArray())
    removed=@($removed.ToArray())
    error=$failure
}
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($ReportPath)) | Out-Null
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding utf8
[pscustomobject]@{Mode=$report.mode; Targets=$present.Count; Files=$report.target_files; MiB=[math]::Round($report.target_bytes/1MB,2); Removed=$removed.Count; Report=$ReportPath}
if ($failure) { throw $failure }
