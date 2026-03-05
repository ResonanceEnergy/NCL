@echo off
echo [NCL] Bootstrapping local folders under %USERPROFILE%\NCL ...

mkdir "%USERPROFILE%\NCL\data" 2>nul
mkdir "%USERPROFILE%\NCL\agents" 2>nul
mkdir "%USERPROFILE%\NCL\missions" 2>nul
mkdir "%USERPROFILE%\NCL\packs" 2>nul
mkdir "%USERPROFILE%\NCL\policies" 2>nul
mkdir "%USERPROFILE%\NCL\dist" 2>nul
mkdir "%USERPROFILE%\NCL\audit" 2>nul

mkdir "%USERPROFILE%\NCL\data\event_log" 2>nul
mkdir "%USERPROFILE%\NCL\data\derived" 2>nul
mkdir "%USERPROFILE%\NCL\data\quarantine" 2>nul
mkdir "%USERPROFILE%\NCL\data\indexes" 2>nul

mkdir "%USERPROFILE%\NCL\packs\candidate" 2>nul
mkdir "%USERPROFILE%\NCL\packs\shadow" 2>nul
mkdir "%USERPROFILE%\NCL\packs\active" 2>nul
mkdir "%USERPROFILE%\NCL\packs\archive" 2>nul

mkdir "%USERPROFILE%\NCL\dist\reports" 2>nul
mkdir "%USERPROFILE%\NCL\dist\exports" 2>nul

echo [NCL] Done. Canonical root: %USERPROFILE%\NCL
echo [NCL] NOTE: This runtime is local-only. No cloud paths configured.