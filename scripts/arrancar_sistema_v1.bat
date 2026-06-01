@echo off
color 0A
cd /d "%~dp0.."
:: garante que a raiz do projecto esta no PYTHONPATH para imports de app.* e config
set PYTHONPATH=%CD%;%PYTHONPATH%
echo ===================================================
echo       Metric4 RTLS  -  Sistema de Arranque
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

echo [2] A verificar/inicializar base de dados SQLite...
python scripts\database_setup.py
if errorlevel 1 (
    echo.
    echo ERRO: Falha na inicializacao da base de dados.
    echo Causa mais comum: a API ja esta a correr noutra janela e bloqueou a BD.
    echo Solucao: fecha as janelas "Escuta Metric4" e "Servidor API Metric4" e tenta novamente.
    pause
    exit /b 1
)

echo [3] A ligar o Motor de Escuta (WebSocket -^> InfluxDB)...
:: Abre um terminal isolado para o motor que recebe posicoes do servidor Dmatek
start "Escuta Metric4" cmd /k "python worker\escuta_dmatek.py"

echo [4] A aguardar 2 segundos para ligar o proximo servico...
timeout /t 2 /nobreak > NUL

echo [5] A ligar a API REST (Uvicorn)...
:: Liberta a porta 8000 se uma instancia antiga da API ainda estiver activa
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /PID %%P /F >nul 2>&1
)
:: Abre um segundo terminal isolado para a API FastAPI
start "Servidor API Metric4" cmd /k "uvicorn app.main:app --reload --reload-dir . --reload-include app"

echo [6] A aguardar 3 segundos para a API estabilizar...
timeout /t 3 /nobreak > NUL

echo [7] A abrir a WebApp no browser...
:: URL de desenvolvimento — alterar para o host real em producao
:: Ponto de entrada unico — o login faz routing automatico por role:
::   SUPERADMIN (cliente_admin)  ->  /admin.html  (gestao completa, todos os clientes)
::   ADMIN      (login via cliente) ->  /admin.html  (gestao do proprio cliente)
::   USER       (login via user)    ->  /app         (dashboard de supervisor)
set APP_URL=http://127.0.0.1:8000/app
set DOCS_URL=http://127.0.0.1:8000/docs
start "" %APP_URL%

echo.
echo ===================================================
echo SISTEMA INICIADO!
echo.
echo Janelas abertas:
echo   "Escuta Metric4"       — recebe posicoes UWB do servidor Dmatek
echo   "Servidor API Metric4" — serve a API REST e o frontend
echo.
echo Acesso:
echo   Browser   ->  %APP_URL%
echo   API Docs  ->  %DOCS_URL%
echo.
echo Roles disponiveis:
echo   SUPERADMIN — user da tabela users com cliente_id = cliente_admin
echo   ADMIN      — login com nome+password do cliente (tabela clientes)
echo   USER       — login com username+password da tabela users
echo.
echo Esta janela pode ser fechada.
echo ===================================================
pause > NUL