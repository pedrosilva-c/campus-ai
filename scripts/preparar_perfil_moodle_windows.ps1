param(
    [switch]$Prepare,
    [switch]$VerifyOnly,
    [switch]$Restore,
    [string]$BackupPath
)

# ACL preflight only. Never opens AEDB or changes other folders.
$ErrorActionPreference = 'Stop'
function Assert-Directory($Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw 'Diretório ausente.' }
    if ((Get-Item -LiteralPath $Path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Diretório redirecionado.' }
}
function Assert-Inventory($Root) {
    $allowed = @{
        'browser_profile' = 'Directory'; 'config.json' = 'File'
        'demo.db' = 'File'; 'demo.db-journal' = 'File'; 'demo.db-wal' = 'File'; 'demo.db-shm' = 'File'
        'live.db' = 'File'; 'live.db-journal' = 'File'; 'live.db-wal' = 'File'; 'live.db-shm' = 'File'
    }
    foreach ($item in Get-ChildItem -LiteralPath $Root -Force) {
        if (-not $allowed.ContainsKey($item.Name) -or
            ($item.PSIsContainer -and $allowed[$item.Name] -ne 'Directory') -or
            (-not $item.PSIsContainer -and $allowed[$item.Name] -ne 'File') -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Pasta CampusAI contém entrada não reconhecida.'
        }
    }
}
function Assert-PrivateAcl($Path, $Required) {
    $acl = Get-Acl -LiteralPath $Path
    if (-not $acl.AreAccessRulesProtected) { throw 'Herança de permissões ativa.' }
    if ($acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -notin $Required) { throw 'Proprietário não permitido.' }
    $seen = @{}
    foreach ($rule in $acl.Access) {
        if ($rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow) { throw 'Regra de negação inesperada.' }
        $sid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
        if ($sid -notin $Required) { throw 'Permissão ampla.' }
        if (($rule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -eq
            [Security.AccessControl.FileSystemRights]::FullControl) { $seen[$sid] = $true }
    }
    foreach ($sid in $Required) { if (-not $seen[$sid]) { throw 'Permissão necessária ausente.' } }
}
function Set-PrivateAcl($Path, $Required, $Directory) {
    $acl = Get-Acl -LiteralPath $Path
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) { $acl.RemoveAccessRuleSpecific($rule) | Out-Null }
    $flags = [Security.AccessControl.InheritanceFlags]::None
    if ($Directory) {
        $flags = [Security.AccessControl.InheritanceFlags](
            [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit)
    }
    foreach ($sidValue in $Required) {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            [System.Security.Principal.SecurityIdentifier]::new($sidValue),
            [Security.AccessControl.FileSystemRights]::FullControl, $flags,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow)
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}
function Resolve-BackupPath($Path, $Root) {
    if (-not $Path -or -not [IO.Path]::IsPathRooted($Path)) { throw 'Informe BackupPath absoluto.' }
    $resolved = [IO.Path]::GetFullPath($Path)
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    if ($resolved.Equals($rootFull, [StringComparison]::OrdinalIgnoreCase) -or
        $resolved.StartsWith($rootFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Backup deve ficar fora de CampusAI.'
    }
    Assert-Directory ([IO.Path]::GetDirectoryName($resolved))
    return $resolved
}
try {
    Add-Type -AssemblyName System.Security
    if (@($Prepare, $VerifyOnly, $Restore).Where({ $_ }).Count -ne 1) { throw 'Escolha uma operação.' }
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA ausente.' }
    $root = Join-Path $env:LOCALAPPDATA 'CampusAI'
    $profile = Join-Path $root 'browser_profile'
    $current = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $required = @($current, 'S-1-5-18', 'S-1-5-32-544')
    Assert-Directory $root
    Assert-Directory $profile
    Assert-Inventory $root
    if ($Prepare) {
        $backup = Resolve-BackupPath $BackupPath $root
        if (Test-Path -LiteralPath $backup) { throw 'Backup já existe; escolha outro caminho.' }
        $record = @{
            version = 1
            root = [IO.Path]::GetFullPath($root)
            profile = [IO.Path]::GetFullPath($profile)
            rootSddl = (Get-Acl -LiteralPath $root).Sddl
            profileSddl = (Get-Acl -LiteralPath $profile).Sddl
        }
        $json = $record | ConvertTo-Json -Compress
        # DPAPI CurrentUser detects a replaced/tampered backup before restoration.
        $bytes = [Security.Cryptography.ProtectedData]::Protect(
            [Text.Encoding]::UTF8.GetBytes($json), $null,
            [Security.Cryptography.DataProtectionScope]::CurrentUser)
        $stream = [IO.File]::Open($backup, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush() } finally { $stream.Dispose() }
        Set-PrivateAcl $backup $required $false
        Assert-PrivateAcl $backup $required
        $saved = [Text.Encoding]::UTF8.GetString(
            [Security.Cryptography.ProtectedData]::Unprotect(
                [IO.File]::ReadAllBytes($backup), $null,
                [Security.Cryptography.DataProtectionScope]::CurrentUser)) | ConvertFrom-Json
        if ($saved.rootSddl -ne $record.rootSddl -or $saved.profileSddl -ne $record.profileSddl) {
            throw 'Backup da ACL não pôde ser confirmado.'
        }
        # No target ACL changes before both original SDDL values are saved and readable.
        Set-PrivateAcl $root $required $true
        Set-PrivateAcl $profile $required $true
    } elseif ($Restore) {
        $backup = Resolve-BackupPath $BackupPath $root
        if (-not (Test-Path -LiteralPath $backup -PathType Leaf) -or
            ((Get-Item -LiteralPath $backup -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Backup ausente ou redirecionado.'
        }
        Assert-PrivateAcl $backup $required
        $saved = [Text.Encoding]::UTF8.GetString(
            [Security.Cryptography.ProtectedData]::Unprotect(
                [IO.File]::ReadAllBytes($backup), $null,
                [Security.Cryptography.DataProtectionScope]::CurrentUser)) | ConvertFrom-Json
        if ($saved.version -ne 1 -or
            $saved.root -ne [IO.Path]::GetFullPath($root) -or
            $saved.profile -ne [IO.Path]::GetFullPath($profile) -or
            -not $saved.rootSddl -or -not $saved.profileSddl) {
            throw 'Backup não corresponde a este perfil.'
        }
        $profileAcl = Get-Acl -LiteralPath $profile
        $profileAcl.SetSecurityDescriptorSddlForm($saved.profileSddl)
        Set-Acl -LiteralPath $profile -AclObject $profileAcl
        $rootAcl = Get-Acl -LiteralPath $root
        $rootAcl.SetSecurityDescriptorSddlForm($saved.rootSddl)
        Set-Acl -LiteralPath $root -AclObject $rootAcl
    }
    if (-not $Restore) {
        Assert-PrivateAcl $root $required
        Assert-PrivateAcl $profile $required
        Write-Output 'CampusAI e browser_profile: ACLs restritas confirmadas.'
    } else {
        Write-Output 'ACLs originais de CampusAI e browser_profile restauradas.'
    }
    exit 0
} catch {
    [Console]::Error.WriteLine('Falha na preparação/verificação da ACL do Campus AI. Nenhum detalhe da ACL foi exibido.')
    exit 1
}
