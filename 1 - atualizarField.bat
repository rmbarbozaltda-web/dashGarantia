@echo off
echo Iniciando processamento...

REM Rodando script 1
python baseOs.py
IF %ERRORLEVEL% NEQ 0 (
    echo Erro no passo 1!
    pause
    exit /b %ERRORLEVEL%
)

REM Rodando script 2
python atividades.py
IF %ERRORLEVEL% NEQ 0 (
    echo Erro no passo 2!
    pause
    exit /b %ERRORLEVEL%
)

REM Rodando script 3
python equipamentosOs.py
IF %ERRORLEVEL% NEQ 0 (
    echo Erro no passo 3!
    pause
    exit /b %ERRORLEVEL%
)


REM Rodando script 4
python formularios.py
IF %ERRORLEVEL% NEQ 0 (
    echo Erro no passo 3!
    pause
    exit /b %ERRORLEVEL%
)


REM Rodando script 5
python respostas.py
IF %ERRORLEVEL% NEQ 0 (
    echo Erro no passo 3!
    pause
    exit /b %ERRORLEVEL%
)

REM Rodando script 6
python orcamentos.py
IF %ERRORLEVEL% NEQ 0 (
    echo Erro no passo 3!
    pause
    exit /b %ERRORLEVEL%
)

echo Todos os scripts foram executados com sucesso!
pause