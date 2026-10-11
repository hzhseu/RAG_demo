param([string]$TargetDirectory = $PSScriptRoot)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$utf8 = New-Object System.Text.UTF8Encoding($false)
$written = New-Object System.Collections.Generic.List[object]
$backup = $null

function Child-Path([string]$Root, [string]$Relative) {
    if ([IO.Path]::IsPathRooted($Relative) -or $Relative.Contains(':')) { throw "Invalid relative path: $Relative" }
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $path = [IO.Path]::GetFullPath((Join-Path $base $Relative))
    if (-not $path.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Path outside update directory: $Relative" }
    $current = $path
    while ($current.Length -ge $base.Length) {
        if (Test-Path -LiteralPath $current) {
            if ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Junction/symbolic link is not supported: $current"
            }
        }
        if ($current -eq $base) { break }
        $current = [IO.Path]::GetDirectoryName($current)
    }
    return $path
}

function Hash-File([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose(); $stream.Dispose() }
}

try {
    $target = (Resolve-Path -LiteralPath $TargetDirectory).ProviderPath
    $manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'update-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.format -ne 1) { throw 'Unsupported update manifest.' }
    $allowed = @('nord-chat.exe', '_internal/base_library.zip', 'docs/RERANKING.md')
    if (@($manifest.files.PSObject.Properties).Count -ne $allowed.Count) { throw 'Incomplete update payload.' }
    foreach ($name in $allowed) {
        $source = Child-Path (Join-Path $PSScriptRoot 'payload') $name
        if (-not $manifest.files.PSObject.Properties[$name] -or (Hash-File $source) -ne $manifest.files.$name) {
            throw "Update file verification failed: $name"
        }
    }
    # Fail before modifying anything when the old package has different dependencies.
    Write-Host 'Checking existing program dependencies...'
    foreach ($item in $manifest.dependencies.PSObject.Properties) {
        if (-not $item.Name.StartsWith('_internal/')) { throw 'Invalid dependency manifest.' }
        $path = Child-Path $target $item.Name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or (Hash-File $path) -ne $item.Value) {
            throw "Existing version is incompatible with this incremental package: $($item.Name). No files have been changed."
        }
    }
    $configPath = Child-Path $target 'runtime.json'
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $config.reranker_model -or ($config.reranker_top_k -and $config.reranker_top_k -gt 16)) {
        throw 'Existing runtime.json is not a compatible reranking configuration.'
    }
    $config | Add-Member -NotePropertyName 'reranker_candidates' -NotePropertyValue 16 -Force
    $checksumPath = Child-Path $target 'checksums.json'
    $hasChecksums = Test-Path -LiteralPath $checksumPath -PathType Leaf
    if ($hasChecksums) {
        $checksums = Get-Content -LiteralPath $checksumPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    $names = @($allowed) + @('runtime.json')
    if ($hasChecksums) { $names += 'checksums.json' }
    if (-not (Test-Path -LiteralPath (Child-Path $target 'nord-chat.exe') -PathType Leaf)) {
        throw 'Choose the existing program directory containing nord-chat.exe.'
    }
    foreach ($process in Get-Process -Name 'nord-chat', 'kb-builder', 'acceleration-test' -ErrorAction SilentlyContinue) {
        if ($process.Path -and [IO.Path]::GetDirectoryName($process.Path) -eq $target) {
            throw 'Close the application and builder before applying this update.'
        }
    }
    # Check locks and write access for all existing destinations before the first write.
    foreach ($name in $names) {
        $path = Child-Path $target $name
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $handle = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            $handle.Dispose()
        }
    }
    $backup = Child-Path $target ('update-backups/rerank-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
    [IO.Directory]::CreateDirectory($backup) | Out-Null
    $records = @()
    foreach ($name in $names) {
        $path = Child-Path $target $name
        $old = Child-Path $backup ('files/' + $name)
        $staged = Child-Path $backup ('staged/' + $name)
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($old)) | Out-Null
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($staged)) | Out-Null
        $exists = Test-Path -LiteralPath $path -PathType Leaf
        if ($exists) { Copy-Item -LiteralPath $path -Destination $old }
        $records += [PSCustomObject]@{ Name=$name; Path=$path; Old=$old; Staged=$staged; Existed=$exists }
        if ($allowed -contains $name) {
            Copy-Item -LiteralPath (Child-Path (Join-Path $PSScriptRoot 'payload') $name) -Destination $staged
        } elseif ($name -eq 'runtime.json') {
            [IO.File]::WriteAllText($staged, ($config | ConvertTo-Json -Depth 100), $utf8)
        }
    }
    if ($hasChecksums) {
        foreach ($record in $records | Where-Object { $_.Name -ne 'checksums.json' }) {
            $checksums | Add-Member -NotePropertyName $record.Name -NotePropertyValue (Hash-File $record.Staged) -Force
        }
        [IO.File]::WriteAllText((Child-Path $backup 'staged/checksums.json'), ($checksums | ConvertTo-Json -Depth 100), $utf8)
    }
    [IO.File]::WriteAllText((Join-Path $backup 'backup-info.json'), ($records | Select-Object Name,Existed | ConvertTo-Json -Depth 10), $utf8)
    foreach ($record in $records) {
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($record.Path)) | Out-Null
        # Register before writing, so even an interrupted/failed copy is restored.
        $written.Add($record)
        if ($record.Existed) { [IO.File]::Replace($record.Staged, $record.Path, $record.Old) }
        else { [IO.File]::Move($record.Staged, $record.Path) }
    }
    foreach ($record in $records) {
        if ($allowed -contains $record.Name -and (Hash-File $record.Path) -ne $manifest.files.($record.Name)) {
            throw "Installed file verification failed: $($record.Name)"
        }
    }
    Write-Host 'SUCCESS: reranking candidates = 16; repeated tokenization/calls optimized.'
    Write-Host 'Model settings, knowledge bases and chat history are preserved. Restart nord-chat.exe.'
    Write-Host "Backup (copy files back to restore): $backup\files"
    exit 0
} catch {
    $failure = $_.Exception.Message
    $restoreFailures = @()
    for ($i = $written.Count - 1; $i -ge 0; $i--) {
        $record = $written[$i]
        try {
            if ($record.Existed) { Copy-Item -LiteralPath $record.Old -Destination $record.Path -Force }
            elseif (Test-Path -LiteralPath $record.Path -PathType Leaf) { Remove-Item -LiteralPath $record.Path -Force }
        } catch { $restoreFailures += $record.Name }
    }
    Write-Host "UPDATE FAILED: $failure" -ForegroundColor Red
    if ($restoreFailures.Count) { Write-Host "Restore these files from $backup\files : $($restoreFailures -join ', ')" -ForegroundColor Red }
    elseif ($written.Count) { Write-Host 'Original files have been restored.' }
    exit 1
}
