@echo off
color 0A
echo ===================================================
echo       Metric4 - SISTEMA DE MONITORIZACAO INTEGRADO
echo ===================================================
echo.
echo [1] A ligar o Motor de Escuta (Websockets -^> InfluxDB)...
:: Abre um terminal isolado para o script que alimenta a base de dados
start "Escuta DMATEK" cmd /k "python escuta_dmatek.py"

echo [2] A aguardar 2 segundos para ligar o proximo motor...
timeout /t 2 /nobreak > NUL

echo [3] A ligar o Porteiro e API (Uvicorn)...
:: Abre um segundo terminal isolado para a API
start "Servidor API DMATEK" cmd /k "uvicorn api_dmatek:app --reload"

echo [4] A aguardar 3 segundos para a maquina estabilizar...
timeout /t 3 /nobreak > NUL

echo [5] A abrir a interface (WebApp) no teu browser principal...
:: Abre o browser
start http://127.0.0.1:8000/app

echo.
echo ===================================================
echo PROCESSO CONCLUIDO! 
echo Vais notar que tens 2 janelas pretas a correr:
echo - Uma a mostrar as coordenadas a entrar (Escuta)
echo - Outra a gerir a ligacao web (Servidor)
echo.
echo Podes fechar ESTA janela verde premindo qualquer tecla.
echo ===================================================
pause > NUL