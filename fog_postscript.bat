@echo off
REM ===========================================================================
REM  Lanzador del primer arranque — registro automatico del equipo clonado
REM ---------------------------------------------------------------------------
REM  Este .bat NO lo copia FOG al escritorio: lo deja fog_postscript.sh en la
REM  carpeta StartUp de todos los usuarios, para que corra solo en el primer
REM  login de Windows. Si el envio sale bien, se borra a si mismo (si no,
REM  reenviaria el mismo equipo en cada login).
REM
REM  Lo que fog_postscript.sh deja en CARPETA:
REM
REM      REPORTE3.exe + _internal\   la carpeta COMPLETA del build onedir
REM      id_clonado                  la clave privada SSH  <-- SIN esto no envia
REM
REM  La clave DEBE viajar junto al .exe: el equipo clonado tiene otro perfil de
REM  usuario y la ruta C:\Users\Tomas\.ssh no existe ahi. El programa la busca
REM  primero al lado del ejecutable, justamente por esto.
REM
REM  Antes de clonar, en la PC central: abrir REPORTE3 -> PANEL DE CLONACION ->
REM  "Publicar OT activa". Todo lo que se clone despues cae en esa OT.
REM ===========================================================================

setlocal
set "CARPETA=%PUBLIC%\Desktop\Reporte"
set "LOG=%CARPETA%\registro_clonacion.log"

REM Sin ventanas. Si alguien lo corre a mano desde un cmd, igual puede escribir
REM las observaciones por consola antes del envio; sin consola (arranque real
REM de FOG) se manda directo. No hay envio automatico por tiempo.
set "MODO=--sin-ui"
REM Para volver a la ventana grafica de observaciones: set "MODO="

if not exist "%CARPETA%\REPORTE3.exe" (
    echo No se encontro REPORTE3.exe en %CARPETA%
    exit /b 10
)

echo. >> "%LOG%"
echo ===== %DATE% %TIME% - %COMPUTERNAME% ===== >> "%LOG%"

REM La red tarda en levantar despues del primer arranque; sin esto el envio
REM falla con codigo 2 en equipos que bootean rapido.
timeout /t 30 /nobreak >nul

"%CARPETA%\REPORTE3.exe" --clonacion %MODO% >> "%LOG%" 2>&1
set CODIGO=%ERRORLEVEL%

if "%CODIGO%"=="0" (
    echo Equipo registrado y enviado correctamente. >> "%LOG%"
    echo Codigo de salida: %CODIGO% >> "%LOG%"
    REM Ya se registro: este lanzador no tiene que volver a correr.
    del "%~f0"
    exit /b 0
)
if "%CODIGO%"=="1" echo El operador cancelo el registro. >> "%LOG%"
if "%CODIGO%"=="2" echo ERROR: sin conexion al servidor. >> "%LOG%"
if "%CODIGO%"=="3" echo ERROR: no hay OT publicada en el servidor. >> "%LOG%"
if "%CODIGO%"=="4" echo ERROR: fallo el escaneo de hardware. >> "%LOG%"
if "%CODIGO%"=="5" echo ERROR: fallo inesperado al enviar. >> "%LOG%"

echo Codigo de salida: %CODIGO% >> "%LOG%"
REM Sin borrarse: si fallo, reintenta en el proximo login.
exit /b %CODIGO%
