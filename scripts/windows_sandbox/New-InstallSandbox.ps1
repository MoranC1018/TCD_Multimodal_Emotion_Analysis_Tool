<#
.SYNOPSIS
Creates a Windows Sandbox configuration without enabling or launching Sandbox.
.PARAMETER Commit
The full SHA of a public commit containing scripts/test_windows_install.ps1.
.PARAMETER RunDirectory
A new local directory. Existing paths are rejected to preserve earlier evidence.
.PARAMETER SkipRemoteValidation
Generates offline for review/testing. The guest still verifies the fetched SHA.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Commit,
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [string]$RepositoryUrl = 'https://github.com/MoranC1018/TCD_Multimodal_Emotion_Analysis_Tool',
    [switch]$SkipRemoteValidation
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Sandbox.Common.ps1')
$repository = Get-SandboxRepository -RepositoryUrl $RepositoryUrl -Commit $Commit
$runPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RunDirectory)
if ($runPath -notmatch '^[A-Za-z]:\\' -or $runPath -match '[%\x00-\x1F]') {
    throw 'RunDirectory must be a local filesystem path without percent signs or control characters.'
}
if (Test-Path -LiteralPath $runPath) { throw "RunDirectory already exists; choose a new directory to preserve evidence: $runPath" }
$ancestor = Split-Path -Parent $runPath
while ($ancestor) {
    if (Test-Path -LiteralPath $ancestor) {
        $item = Get-Item -LiteralPath $ancestor -Force
        if ($item.LinkType -in @('Junction', 'SymbolicLink')) { throw 'RunDirectory must not traverse a junction or symbolic link.' }
    }
    $ancestor = Split-Path -Parent $ancestor
}
if (-not $SkipRemoteValidation) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $apiBase = "https://api.github.com/repos/$($repository.Slug)"
    $metadata = Invoke-RestMethod -Uri $apiBase -TimeoutSec 60
    if ($metadata.private) { throw 'The guest accepts public repositories only.' }
    $remote = Invoke-RestMethod -Uri "$apiBase/commits/$($repository.Commit)" -TimeoutSec 60
    if ($remote.sha -ine $repository.Commit) { throw 'Public commit identity did not match.' }
    # Resolve the harness at this exact revision before preparing a runnable configuration.
    $harness = Invoke-RestMethod -Uri "$apiBase/contents/scripts/test_windows_install.ps1?ref=$($repository.Commit)" -TimeoutSec 60
    if ($harness.type -cne 'file') { throw 'Target commit does not contain the common installation harness.' }
}
$bootstrap = Join-Path $runPath 'bootstrap'
$evidence = Join-Path $runPath 'evidence'
New-Item -ItemType Directory -Path $bootstrap | Out-Null
New-Item -ItemType Directory -Path $evidence | Out-Null
foreach ($name in @('Guest-Bootstrap.ps1', 'Sandbox.Common.ps1', 'install_winget.ps1', 'bootstrap-artifacts.json')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $bootstrap $name)
}
$manifest = [ordered]@{
    SchemaVersion = 1
    GeneratedUtc = [DateTime]::UtcNow.ToString('o')
    RepositoryUrl = $repository.Url
    Commit = $repository.Commit
    RemoteValidated = (-not $SkipRemoteValidation)
    GuestMemoryInMB = 6144
    EnvironmentKind = 'WindowsSandbox'
}
Save-SandboxJson -Value $manifest -Path (Join-Path $bootstrap 'run.json')
Save-SandboxJson -Value $manifest -Path (Join-Path $runPath 'run.json')
$xml = [xml]'<Configuration><vGPU>Disable</vGPU><Networking>Enable</Networking><MemoryInMB>6144</MemoryInMB><AudioInput>Disable</AudioInput><VideoInput>Disable</VideoInput><PrinterRedirection>Disable</PrinterRedirection><ClipboardRedirection>Disable</ClipboardRedirection><MappedFolders/><LogonCommand><Command>powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\SandboxBootstrap\Guest-Bootstrap.ps1</Command></LogonCommand></Configuration>'
foreach ($mapping in @(@($bootstrap, 'C:\SandboxBootstrap', 'true'), @($evidence, 'C:\Evidence', 'false'))) {
    $folder = $xml.CreateElement('MappedFolder')
    for ($index = 0; $index -lt 3; $index++) {
        $element = $xml.CreateElement(@('HostFolder', 'SandboxFolder', 'ReadOnly')[$index])
        $element.InnerText = $mapping[$index]
        $null = $folder.AppendChild($element)
    }
    $null = $xml.SelectSingleNode('/Configuration/MappedFolders').AppendChild($folder)
}
$configurationPath = Join-Path $runPath 'install-test.wsb'
$xml.Save($configurationPath)
Get-ChildItem -LiteralPath $bootstrap -File | Get-FileHash -Algorithm SHA256 | Select-Object @{n='File';e={Split-Path -Leaf $_.Path}},Hash | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runPath 'bootstrap-hashes.json') -Encoding UTF8
[pscustomobject]@{ ConfigurationPath = $configurationPath; EvidenceDirectory = $evidence; Commit = $repository.Commit; RemoteValidated = (-not $SkipRemoteValidation) }
