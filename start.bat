@echo off
setlocal EnableExtensions
chcp 65001 >nul
pushd "%~dp0"
title contract-review-assistant 一键启动

set "BACKEND_PORT=8082"
set "FRONTEND_PORT=5173"
set "PYTHON_LAUNCHER="

echo.
echo ==================================================
echo   contract-review-assistant 合同智能审查助手
echo ==================================================
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_LAUNCHER=py -3"
)

if not defined PYTHON_LAUNCHER (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON_LAUNCHER=python"
    )
)

if not defined PYTHON_LAUNCHER (
    echo [错误] 未找到 Python 3.10 或更高版本。
    echo 请安装 Python 3.10+，并在安装时勾选“Add Python to PATH”。
    goto :failed
)

where node >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Node.js。请安装 Node.js 后重新运行本脚本。
    goto :failed
)

where npm >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 npm。请重新安装包含 npm 的 Node.js。
    goto :failed
)

for /f "delims=" %%V in ('%PYTHON_LAUNCHER% --version 2^>^&1') do set "PYTHON_VERSION=%%V"
for /f "delims=" %%V in ('node --version 2^>^&1') do set "NODE_VERSION=%%V"
echo [环境] %PYTHON_VERSION%
echo [环境] Node.js %NODE_VERSION%

if not exist ".env" (
    if not exist ".env.example" (
        echo [错误] 根目录缺少 .env 和 .env.example，无法加载环境配置。
        goto :failed
    )
    copy /Y ".env.example" ".env" >nul
    if errorlevel 1 (
        echo [错误] 无法从 .env.example 创建 .env，请检查目录写入权限。
        goto :failed
    )
    echo [配置] 未找到 .env，已自动复制 .env.example。正式使用前请修改其中的密钥。
) else (
    echo [配置] 已读取根目录 .env。
)

if not exist "venv\Scripts\python.exe" (
    echo [准备] 未发现 ./venv，正在创建 Python 虚拟环境...
    %PYTHON_LAUNCHER% -m venv venv
    if errorlevel 1 (
        echo [错误] Python 虚拟环境创建失败，请检查 Python venv 组件和目录权限。
        goto :failed
    )
)

echo [准备] 正在安装或校验后端依赖...
"venv\Scripts\python.exe" -m pip install --timeout 120 --retries 5 -r requirements.txt
if errorlevel 1 (
    echo [错误] 后端依赖安装失败。请检查网络、代理和 requirements.txt。
    goto :failed
)

if not exist "frontend\node_modules\.bin\vite.cmd" (
    echo [准备] 未发现前端依赖，正在执行 npm install...
    call npm --prefix frontend install --fetch-timeout=120000 --fetch-retries=5
    if errorlevel 1 (
        echo [错误] 前端依赖安装失败。请检查网络、npm 镜像和 frontend/package.json。
        goto :failed
    )
) else (
    echo [准备] 已发现前端依赖。
)

:find_backend_port
"venv\Scripts\python.exe" -c "import socket,sys; p=int(sys.argv[1]); c=socket.socket(); c.settimeout(.3); busy=c.connect_ex(('127.0.0.1',p))==0; c.close(); checks=[(socket.AF_INET,('0.0.0.0',p))]; checks += [(socket.AF_INET6,('::',p))] if socket.has_ipv6 else []; sockets=[]; [sockets.append(socket.socket(f,socket.SOCK_STREAM)) for f,a in checks]; [s.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1) for s in sockets if hasattr(socket,'SO_EXCLUSIVEADDRUSE')]; [s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1) for s,(f,a) in zip(sockets,checks) if f==socket.AF_INET6 and hasattr(socket,'IPV6_V6ONLY')]; [s.bind(a) for s,(f,a) in zip(sockets,checks)]; [s.close() for s in sockets]; sys.exit(1 if busy else 0)" %BACKEND_PORT% >nul 2>nul
if not errorlevel 1 goto :backend_port_ready
echo [端口] 后端端口 %BACKEND_PORT% 已被占用，自动顺延至下一个端口...
set /a BACKEND_PORT+=1
if %BACKEND_PORT% GTR 65535 goto :port_scan_failed
goto :find_backend_port

:backend_port_ready
:find_frontend_port
if not "%FRONTEND_PORT%"=="%BACKEND_PORT%" goto :probe_frontend_port
echo [端口] 前端候选端口 %FRONTEND_PORT% 与后端冲突，自动顺延至下一个端口...
set /a FRONTEND_PORT+=1
if %FRONTEND_PORT% GTR 65535 goto :port_scan_failed
goto :find_frontend_port

:probe_frontend_port
"venv\Scripts\python.exe" -c "import socket,sys; p=int(sys.argv[1]); c=socket.socket(); c.settimeout(.3); busy=c.connect_ex(('127.0.0.1',p))==0; c.close(); checks=[(socket.AF_INET,('0.0.0.0',p))]; checks += [(socket.AF_INET6,('::',p))] if socket.has_ipv6 else []; sockets=[]; [sockets.append(socket.socket(f,socket.SOCK_STREAM)) for f,a in checks]; [s.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1) for s in sockets if hasattr(socket,'SO_EXCLUSIVEADDRUSE')]; [s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1) for s,(f,a) in zip(sockets,checks) if f==socket.AF_INET6 and hasattr(socket,'IPV6_V6ONLY')]; [s.bind(a) for s,(f,a) in zip(sockets,checks)]; [s.close() for s in sockets]; sys.exit(1 if busy else 0)" %FRONTEND_PORT% >nul 2>nul
if not errorlevel 1 goto :ports_ready
echo [端口] 前端开发端口 %FRONTEND_PORT% 已被占用，自动顺延至下一个端口...
set /a FRONTEND_PORT+=1
if %FRONTEND_PORT% GTR 65535 goto :port_scan_failed
goto :find_frontend_port

:ports_ready
echo [端口] 后端将使用 %BACKEND_PORT%，前端开发服务将使用 %FRONTEND_PORT%。

echo.
echo [启动] 正在启动 FastAPI 后端，随后启动 Vue 3 前端...
echo [提示] 当前部分业务模块尚未编码完成，部分接口返回 404。
echo.

powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; $root=(Get-Location).Path; $backend=$null; $frontend=$null; $failed=$false; $requestedStop=$false; $oldCtrlMode=[Console]::TreatControlCAsInput; [Console]::TreatControlCAsInput=$true;" ^
  "function Stop-ProcessTree($process) { if ($null -ne $process -and -not $process.HasExited) { $null=Start-Process -FilePath 'taskkill.exe' -ArgumentList @('/PID',$process.Id,'/T','/F') -WindowStyle Hidden -Wait -PassThru } };" ^
  "try {" ^
  "  foreach ($line in [IO.File]::ReadAllLines((Join-Path $root '.env'))) { if ($line -match '^\s*([^#][^=]*)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim().Trim([char]34).Trim([char]39), 'Process') } };" ^
  "  $backend=Start-Process -FilePath (Join-Path $root 'venv\Scripts\python.exe') -ArgumentList @('-m','uvicorn','backend.main:app','--host','0.0.0.0','--port','%BACKEND_PORT%') -WorkingDirectory $root -WindowStyle Hidden -PassThru;" ^
  "  $ready=$false; for ($i=0; $i -lt 30; $i++) { if ($backend.HasExited) { throw '后端进程提前退出。' }; try { $response=Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 'http://127.0.0.1:%BACKEND_PORT%/api/health'; if ($response.StatusCode -eq 200) { $ready=$true; break } } catch {}; Start-Sleep -Seconds 1 }; if (-not $ready) { throw '后端在 30 秒内未能就绪。' };" ^
  "  Start-Sleep -Seconds 2; $npm=(Get-Command npm.cmd).Source; $frontend=Start-Process -FilePath $npm -ArgumentList @('run','dev','--','--port','%FRONTEND_PORT%') -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden -PassThru;" ^
  "  Start-Sleep -Seconds 3; if ($frontend.HasExited) { throw '前端进程启动失败，请检查上方 npm 输出。' };" ^
  "  Write-Host ''; Write-Host '==================================================' -ForegroundColor Cyan; Write-Host ' 启动成功：http://localhost:%BACKEND_PORT%' -ForegroundColor Green; Write-Host ' 前端开发服务：http://localhost:%FRONTEND_PORT%' -ForegroundColor Cyan; Write-Host ' 当前部分业务模块尚未编码完成，部分接口返回 404。' -ForegroundColor Yellow; Write-Host ' 关闭所有前端页面后，前后端服务会自动退出。' -ForegroundColor Cyan; Write-Host '==================================================' -ForegroundColor Cyan; Write-Host '';" ^
  "  if ($env:CONTRACT_REVIEW_NO_BROWSER -ne '1') { Start-Process 'http://localhost:%BACKEND_PORT%' };" ^
  "  while (-not $backend.HasExited -and -not $frontend.HasExited) { if ([Console]::KeyAvailable) { $key=[Console]::ReadKey($true); if ($key.Key -eq [ConsoleKey]::C -and ($key.Modifiers -band [ConsoleModifiers]::Control)) { $requestedStop=$true; break } }; try { $runtime=Invoke-RestMethod -TimeoutSec 1 'http://127.0.0.1:%BACKEND_PORT%/api/runtime/status'; if ($runtime.client_seen -and $runtime.shutdown_requested) { Write-Host '[关闭] 已检测到所有前端页面关闭。' -ForegroundColor Cyan; $requestedStop=$true; break } } catch {}; Start-Sleep -Milliseconds 500 }; if (-not $requestedStop) { if ($backend.HasExited) { throw '后端服务意外退出。' } else { throw '前端服务意外退出。' } }" ^
  "} catch { Write-Host ('[错误] ' + $_.Exception.Message) -ForegroundColor Red; $failed=$true } finally { [Console]::TreatControlCAsInput=$oldCtrlMode; Write-Host ''; Write-Host '[关闭] 正在停止前端和后端进程...' -ForegroundColor Yellow; Stop-ProcessTree $frontend; Stop-ProcessTree $backend }; if ($failed) { exit 1 }"

if errorlevel 1 goto :failed
popd
endlocal
exit /b 0

:failed
echo.
echo 启动未完成。按任意键关闭窗口...
pause >nul
popd
endlocal
exit /b 1

:port_scan_failed
echo [错误] 没有可用端口（已扫描到 65535），请释放端口后重试。
goto :failed
