PYTHONPATH=. uvicorn saas_web:app --host 0.0.0.0 --port 8000 &
echo $! > server.pid
