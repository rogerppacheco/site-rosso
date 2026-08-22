@echo off
set EXT=C:\site-record\chrome_extension_inclusao_forms
set EDGE=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe

echo Fechando Edge...
taskkill /F /IM msedge.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

echo Abrindo Edge com a extensao Inclusao Forms...
start "" "%EDGE%" --load-extension="%EXT%" "https://www.recordpap.com.br/auditoria/" "edge://extensions/"
echo Pronto. Na Auditoria, recarregue (F5) e veja se a extensao fica ativa.
