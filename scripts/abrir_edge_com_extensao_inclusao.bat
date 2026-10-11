@echo off
set EXT=C:\Projeto_Sysr\site-rosso\chrome_extension_inclusao_forms
set EDGE=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe

echo Fechando Edge...
taskkill /F /IM msedge.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

echo Abrindo Edge com a extensao Inclusao Forms...
start "" "%EDGE%" --load-extension="%EXT%" "https://site-rosso-production.up.railway.app/auditoria/" "edge://extensions/"
echo Pronto. Na Auditoria, recarregue (F5) e veja se a extensao fica ativa.
