@echo off
set EXT=C:\site-record\chrome_extension_inclusao_forms
set CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe

echo Fechando Chrome...
taskkill /F /IM chrome.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

echo Abrindo Chrome com a extensao Inclusao Forms...
start "" "%CHROME%" --load-extension="%EXT%" "https://www.recordpap.com.br/auditoria/" "chrome://extensions/"
echo Pronto. Na Auditoria, recarregue (F5) e veja se a extensao fica ativa.
