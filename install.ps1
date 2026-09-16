[CmdletBinding(SupportsShouldProcess)]
param(
    [string[]] $Targets,

    [ValidateSet('User', 'Project')]
    [string] $Scope = 'User',

    [string] $ProjectRoot = (Get-Location).Path,

    [switch] $Force,

    [switch] $SkipTokenPrompt
)

$ErrorActionPreference = 'Stop'
$skillName = 'novelai-image'
$source = Join-Path $PSScriptRoot "skills/$skillName"
$credentialTarget = 'NovelAISkill:NOVELAI_API_TOKEN'

function Select-InstallTargets {
    $options = @(
        [pscustomobject]@{ Name = 'Codex'; Selected = $true }
        [pscustomobject]@{ Name = 'Claude'; Selected = $true }
        [pscustomobject]@{ Name = 'Copilot'; Selected = $true }
    )
    $position = 0

    Write-Host 'Select platforms (Up/Down: move, Space: check/uncheck, Enter: install)'
    $startRow = [Console]::CursorTop
    $oldCursorVisible = [Console]::CursorVisible
    [Console]::CursorVisible = $false
    try {
        while ($true) {
            [Console]::SetCursorPosition(0, $startRow)
            for ($index = 0; $index -lt $options.Count; $index++) {
                $cursor = if ($index -eq $position) { '>' } else { ' ' }
                $check = if ($options[$index].Selected) { '[x]' } else { '[ ]' }
                $line = "$cursor $check $($options[$index].Name)"
                $width = [Math]::Max(20, [Console]::WindowWidth - 1)
                Write-Host $line.PadRight($width)
            }

            $key = [Console]::ReadKey($true).Key
            switch ($key) {
                'UpArrow' { $position = ($position - 1 + $options.Count) % $options.Count }
                'DownArrow' { $position = ($position + 1) % $options.Count }
                'Spacebar' { $options[$position].Selected = -not $options[$position].Selected }
                'Enter' {
                    $selected = @($options | Where-Object Selected | ForEach-Object Name)
                    if ($selected.Count -gt 0) {
                        [Console]::SetCursorPosition(0, $startRow + $options.Count)
                        Write-Host "Selected: $($selected -join ', ')"
                        return $selected
                    }
                    [Console]::Beep()
                }
            }
        }
    }
    finally {
        [Console]::CursorVisible = $oldCursorVisible
    }
}

function Initialize-CredentialApi {
    if ('NovelAiSkill.CredentialNative' -as [type]) {
        return
    }

    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace NovelAiSkill {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct CREDENTIAL {
        public UInt32 Flags;
        public UInt32 Type;
        public string TargetName;
        public string Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public UInt32 CredentialBlobSize;
        public IntPtr CredentialBlob;
        public UInt32 Persist;
        public UInt32 AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
    }

    public static class CredentialNative {
        [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool CredWrite(ref CREDENTIAL credential, UInt32 flags);

        [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool CredRead(string target, UInt32 type, UInt32 flags, out IntPtr credential);

        [DllImport("advapi32.dll", SetLastError = true)]
        public static extern void CredFree(IntPtr credential);
    }
}
'@
}

function Test-NovelAiCredential {
    param([string] $Target)

    Initialize-CredentialApi
    $credentialPointer = [IntPtr]::Zero
    if ([NovelAiSkill.CredentialNative]::CredRead($Target, 1, 0, [ref] $credentialPointer)) {
        [NovelAiSkill.CredentialNative]::CredFree($credentialPointer)
        return $true
    }
    $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    if ($errorCode -eq 1168) {
        return $false
    }
    throw [ComponentModel.Win32Exception]::new($errorCode)
}

function Save-NovelAiCredential {
    param(
        [string] $Target,
        [Security.SecureString] $Secret
    )

    Initialize-CredentialApi
    $secretPointer = [IntPtr]::Zero
    $plainSecret = $null
    try {
        $secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToCoTaskMemUnicode($Secret)
        $plainSecret = [Runtime.InteropServices.Marshal]::PtrToStringUni($secretPointer)
        if ([string]::IsNullOrWhiteSpace($plainSecret)) {
            throw 'The NovelAI token cannot contain only whitespace.'
        }

        $credential = [NovelAiSkill.CREDENTIAL]::new()
        $credential.Type = 1
        $credential.TargetName = $Target
        $credential.CredentialBlobSize = [Text.Encoding]::Unicode.GetByteCount($plainSecret)
        $credential.CredentialBlob = $secretPointer
        $credential.Persist = 2
        $credential.UserName = [Environment]::UserName

        if (-not [NovelAiSkill.CredentialNative]::CredWrite([ref] $credential, 0)) {
            $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
            throw [ComponentModel.Win32Exception]::new($errorCode)
        }
    }
    finally {
        if ($secretPointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeCoTaskMemUnicode($secretPointer)
        }
        $plainSecret = $null
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $source 'SKILL.md') -PathType Leaf)) {
    throw "Skill source is incomplete: $source"
}

$userProfilePath = [Environment]::GetFolderPath('UserProfile')
if ([string]::IsNullOrWhiteSpace($userProfilePath)) {
    throw 'Could not determine the current user profile directory.'
}

$validTargets = @('Codex', 'Claude', 'Copilot')
$targetsWereSupplied = $PSBoundParameters.ContainsKey('Targets')
$interactiveSelection = -not $targetsWereSupplied -and -not $WhatIfPreference
if ($targetsWereSupplied) {
    $requestedTargets = @($Targets | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
}
elseif ($WhatIfPreference) {
    $requestedTargets = $validTargets
}
elseif ([Console]::IsInputRedirected) {
    throw 'Interactive platform selection requires a terminal. Supply -Targets Codex,Claude,Copilot for unattended installation.'
}
else {
    $requestedTargets = @(Select-InstallTargets)
}

foreach ($target in $requestedTargets) {
    if ($target -notin $validTargets) {
        throw "Unknown target '$target'. Valid targets: $($validTargets -join ', ')."
    }
}

$resolvedProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

$destinations = @{
    User = @{
        Codex   = Join-Path $userProfilePath ".codex/skills/$skillName"
        Claude  = Join-Path $userProfilePath ".claude/skills/$skillName"
        Copilot = Join-Path $userProfilePath ".copilot/skills/$skillName"
    }
    Project = @{
        Codex   = Join-Path $resolvedProjectRoot ".agents/skills/$skillName"
        Claude  = Join-Path $resolvedProjectRoot ".claude/skills/$skillName"
        Copilot = Join-Path $resolvedProjectRoot ".github/skills/$skillName"
    }
}

foreach ($target in $requestedTargets) {
    $destination = $destinations[$Scope][$target]
    $parent = Split-Path -Parent $destination

    if (Test-Path -LiteralPath $destination) {
        if ((Split-Path -Leaf $destination) -ne $skillName) {
            throw "Refusing to replace an unexpected path: $destination"
        }
        if (-not $Force -and -not $interactiveSelection) {
            throw "$target already has this skill at $destination. Re-run with -Force to replace only that skill directory."
        }
        if ($interactiveSelection) {
            Write-Host "Updating existing ${target} installation: $destination"
        }
    }

    if ($PSCmdlet.ShouldProcess($destination, "Install $skillName for $target ($Scope scope)")) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        $cacheBackupRoot = $null
        $installedCache = Join-Path $destination 'cache'
        if (Test-Path -LiteralPath $installedCache) {
            $cacheBackupRoot = Join-Path ([IO.Path]::GetTempPath()) ("NovelAISkill-cache-" + [guid]::NewGuid().ToString('N'))
            New-Item -ItemType Directory -Force -Path $cacheBackupRoot | Out-Null
            Copy-Item -LiteralPath $installedCache -Destination (Join-Path $cacheBackupRoot 'cache') -Recurse -Force
        }
        if (Test-Path -LiteralPath $destination) {
            Remove-Item -LiteralPath $destination -Recurse -Force
        }
        try {
            Copy-Item -LiteralPath $source -Destination $destination -Recurse
            if ($cacheBackupRoot) {
                $backupCache = Join-Path $cacheBackupRoot 'cache'
                $restoredCache = Join-Path $destination 'cache'
                if (Test-Path -LiteralPath $restoredCache) {
                    Remove-Item -LiteralPath $restoredCache -Recurse -Force
                }
                Copy-Item -LiteralPath $backupCache -Destination $restoredCache -Recurse -Force
                Remove-Item -LiteralPath $cacheBackupRoot -Recurse -Force
            }
        }
        catch {
            if ($cacheBackupRoot -and (Test-Path -LiteralPath $cacheBackupRoot)) {
                Write-Warning "The previous Prompt Chunk cache is preserved at: $cacheBackupRoot"
            }
            throw
        }
        Write-Host "Installed for ${target}: $destination"
    }
}

Write-Host ''

if (-not $SkipTokenPrompt -and -not $WhatIfPreference) {
    $isWindows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
    if (-not $isWindows) {
        Write-Warning 'Windows Credential Manager is unavailable. Set NOVELAI_API_TOKEN through your platform secret manager.'
    }
    else {
        $credentialExists = Test-NovelAiCredential -Target $credentialTarget
        $tokenPrompt = if (-not $credentialExists) {
            'NovelAI Persistent API Token (input hidden; press Enter to skip)'
        }
        else {
            'NovelAI Persistent API Token (input hidden; press Enter to keep the existing credential)'
        }

        $secureToken = Read-Host $tokenPrompt -AsSecureString
        if ($secureToken.Length -gt 0) {
            if ($PSCmdlet.ShouldProcess(
                $credentialTarget,
                'Store the NovelAI token in Windows Credential Manager'
            )) {
                Save-NovelAiCredential -Target $credentialTarget -Secret $secureToken
                [Environment]::SetEnvironmentVariable('NOVELAI_API_TOKEN', $null, [EnvironmentVariableTarget]::User)
                [Environment]::SetEnvironmentVariable('NOVELAI_API_TOKEN', $null, [EnvironmentVariableTarget]::Process)
                Write-Host 'Saved the NovelAI token in Windows Credential Manager.'
            }
            $secureToken.Dispose()
        }
        elseif (-not $credentialExists) {
            $secureToken.Dispose()
            Write-Warning 'Token setup was skipped. Store the credential or set NOVELAI_API_TOKEN before using the skill.'
        }
        else {
            $secureToken.Dispose()
            Write-Host 'Kept the existing NovelAI credential.'
        }
    }
}
elseif ($SkipTokenPrompt) {
    Write-Host 'Skipped NovelAI token setup because -SkipTokenPrompt was supplied.'
}

Write-Host 'Restart the agent, or reload its skills, so it can see the installation.'
