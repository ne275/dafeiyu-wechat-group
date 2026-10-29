@echo off
REM 断开远程桌面之前双击运行：把会话移交控制台，保持渲染活跃（需管理员）
REM 之后直接关 RDP 窗口即可，桌面不会进入空闲降级
tscon %SESSIONNAME% /dest:console
