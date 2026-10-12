import uvicorn

if __name__ == '__main__':
    # Loopback-only by design. Do not expose the personal app to a network.
    uvicorn.run('jon.app:create_app', factory=True, host='127.0.0.1', port=8765, workers=1, access_log=False)
