# silvercare 백엔드 실행 (8000번은 pose-server가 사용하므로 8001번 사용)
Set-Location $PSScriptRoot
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001
