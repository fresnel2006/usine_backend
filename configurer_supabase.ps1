# Configure l'application sur la base Supabase du projet.
# Usage (depuis le dossier du projet) :
#   powershell -ExecutionPolicy Bypass -File backend\configurer_supabase.ps1
#
# Le mot de passe est saisi au clavier (masqué) et enregistré uniquement dans backend\.env,
# fichier ignoré par git.

$ErrorActionPreference = 'Stop'
$ProjetRef = 'nciavyshfzeeasjjdgck'
$Region = 'eu-west-1'
$Backend = $PSScriptRoot
$Racine = Split-Path $Backend -Parent

Write-Host ''
Write-Host '=== Configuration Supabase - Gestion de l''usine ===' -ForegroundColor Cyan

# 1. psql
$psql = (Get-Command psql -ErrorAction SilentlyContinue).Source
if (-not $psql) {
    $psql = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\psql.exe' -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $psql) {
    Write-Host 'psql est introuvable. Installez PostgreSQL (il fournit psql) puis relancez ce script.' -ForegroundColor Red
    exit 1
}

# 2. Mot de passe de la base (champ "Database Password" choisi à la création du projet)
$secure = Read-Host 'Mot de passe de la base Supabase' -AsSecureString
$motDePasse = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
if ([string]::IsNullOrWhiteSpace($motDePasse)) {
    Write-Host 'Mot de passe vide : abandon.' -ForegroundColor Red
    exit 1
}
$mdpEncode = [uri]::EscapeDataString($motDePasse)

# 3. Recherche du serveur (selon l'ancienneté du projet, l'hôte est aws-0 ou aws-1)
$env:PGCONNECT_TIMEOUT = '10'
$env:PGCLIENTENCODING = 'UTF8'
$url = $null
foreach ($hote in "aws-0-$Region.pooler.supabase.com", "aws-1-$Region.pooler.supabase.com") {
    $essai = "postgresql://postgres.${ProjetRef}:$mdpEncode@${hote}:5432/postgres?sslmode=require"
    Write-Host "Connexion à $hote..."
    & $psql $essai -q -t -c 'select 1' *> $null
    if ($LASTEXITCODE -eq 0) { $url = $essai; break }
}
if (-not $url) {
    Write-Host ''
    Write-Host 'Connexion impossible. Vérifiez le mot de passe de la base' -ForegroundColor Red
    Write-Host '(Project Settings > Database > Reset database password) puis relancez le script.' -ForegroundColor Red
    exit 1
}
Write-Host 'Connexion réussie.' -ForegroundColor Green

# 4. Création des tables et des données de test
$reponse = Read-Host 'Créer (ou recréer) les 18 tables avec les données de test ? Les données existantes seront effacées. (O/N)'
if ($reponse -match '^[oO]') {
    & $psql $url -q -v ON_ERROR_STOP=1 -f (Join-Path $Racine 'database\gestion_usine_supabase.sql') *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Erreur pendant l''exécution du script SQL.' -ForegroundColor Red
        exit 1
    }
    Write-Host 'Tables et données créées.' -ForegroundColor Green
}

# 5. Mise à jour de backend\.env (seule la ligne DATABASE_URL change)
$fichierEnv = Join-Path $Backend '.env'
if (Test-Path $fichierEnv) {
    $lignes = Get-Content $fichierEnv -Encoding UTF8 | Where-Object { $_ -notmatch '^DATABASE_URL=' }
} else {
    $octets = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($octets)
    $secret = [Convert]::ToBase64String($octets).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $lignes = @("JWT_SECRET=$secret", 'JWT_EXPIRE_MINUTES=480', 'CORS_ORIGINS=http://localhost:5173', 'SEUIL_STOCK_FAIBLE=5')
}
$contenu = (@("DATABASE_URL=$url") + $lignes) -join "`n"
[IO.File]::WriteAllText($fichierEnv, $contenu + "`n", (New-Object Text.UTF8Encoding $false))
Write-Host 'backend\.env mis à jour.' -ForegroundColor Green

# 6. Vrais mots de passe des comptes de test
$python = Join-Path $Backend 'venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
Push-Location $Backend
$env:PYTHONIOENCODING = 'utf-8'
& $python seed_users.py
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) {
    Write-Host 'seed_users.py a échoué (voir le message ci-dessus).' -ForegroundColor Red
    exit 1
}

Write-Host ''
Write-Host 'Terminé. Redémarrez l''API (uvicorn) pour qu''elle utilise Supabase.' -ForegroundColor Cyan
