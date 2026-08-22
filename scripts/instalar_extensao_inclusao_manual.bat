@echo off
chcp 65001 >nul
set EXT=C:\site-record\chrome_extension_inclusao_forms

echo.
echo ========================================
echo  Instalacao da extensao Record Inclusao
echo ========================================
echo.
echo O Chrome 150 bloqueia instalacao automatica.
echo Faca estes 4 passos (uma vez):
echo.
echo  1. Na pagina de Extensoes que vai abrir,
echo     ative "Modo do desenvolvedor" (canto superior direito)
echo  2. Clique em "Carregar sem compactacao"
echo  3. Selecione a pasta:
echo     %EXT%
echo  4. Volte na Auditoria e pressione F5
echo.
echo Abrindo a pasta e o Chrome/Edge...
echo.

start "" "%EXT%"
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" chrome://extensions/
start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" edge://extensions/

pause
