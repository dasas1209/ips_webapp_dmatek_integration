@echo off
color 0A
cd /d "%~dp0"
echo ===================================================
echo       Metric4 - SISTEMA DE MONITORIZACAO INTEGRADO
echo ===================================================
echo.
echo [1] A instalar/atualizar dependencias (requirements.txt)...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERRO: Falha ao instalar requirements.
    echo Verifica o Python/PIP e tenta novamente.
    pause
    exit /b 1
)

echo [2] A ligar o Motor de Escuta (Websockets -^> InfluxDB)...
:: Abre um terminal isolado para o script que alimenta a base de dados
start "Escuta Metric4" cmd /k "python escuta_dmatek.py"

echo [3] A aguardar 2 segundos para ligar o proximo motor...
timeout /t 2 /nobreak > NUL

echo [4] A ligar o Porteiro e API (Uvicorn)...
:: Abre um segundo terminal isolado para a API
start "Servidor API Metric4" cmd /k "uvicorn api_dmatek:app --reload"

echo [5] A aguardar 3 segundos para a maquina estabilizar...
timeout /t 3 /nobreak > NUL

echo [6] A abrir a interface (WebApp) no teu browser principal...
:: Abre o browser
start http://127.0.0.1:8000/app

echo.
echo ===================================================
echo PROCESSO CONCLUIDO! 
echo Há 2 janelas pretas a correr:
echo - Uma a mostrar as coordenadas a entrar (Escuta)
echo - Outra a gerir a ligacao web (Servidor)
echo.
echo ESTA janela pode ser fechada.
echo ===================================================
pause > NUL