# Safe extraction of the offline models ZIP, used by the installer.
# Same rules as utvfx.core.downloads.extract_models_zip: only files under models/,
# no code or executables, no path tricks, and a size cap against zip bombs.
# Exit codes: 0 ok, 2 cannot open, 3 too large.
param(
    [Parameter(Mandatory = $true)][string]$Zip,
    [Parameter(Mandatory = $true)][string]$Dest
)

Add-Type -AssemblyName System.IO.Compression.FileSystem
$blocked = @('.py', '.pyd', '.pyc', '.pyw', '.dll', '.exe', '.bat', '.cmd', '.ps1', '.js', '.vbs', '.lnk', '.msi', '.scr')
$maxTotal = 200GB

try {
    $archive = [IO.Compression.ZipFile]::OpenRead($Zip)
} catch {
    exit 2
}

try {
    $total = 0
    foreach ($entry in $archive.Entries) { $total += $entry.Length }
    if ($total -gt $maxTotal) { exit 3 }

    $destFull = [IO.Path]::GetFullPath($Dest).TrimEnd('\') + '\'
    $extracted = 0
    $skipped = 0
    foreach ($entry in $archive.Entries) {
        $name = $entry.FullName.Replace('\', '/')
        if ($name.EndsWith('/')) { continue }
        $ext = [IO.Path]::GetExtension($name).ToLowerInvariant()
        if (-not $name.StartsWith('models/') -or $name.Contains('..') -or $name.Contains(':') -or $blocked -contains $ext) {
            $skipped++
            continue
        }
        $target = [IO.Path]::GetFullPath((Join-Path $destFull $name))
        if (-not $target.StartsWith($destFull, [StringComparison]::OrdinalIgnoreCase)) {
            $skipped++
            continue
        }
        New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, "$target.part", $true)
        Move-Item -Force -LiteralPath "$target.part" -Destination $target
        $extracted++
    }
    Write-Output "Extracted $extracted file(s), skipped $skipped."
} finally {
    $archive.Dispose()
}
exit 0
