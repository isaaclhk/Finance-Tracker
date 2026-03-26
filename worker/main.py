from fastapi import FastAPI

app = FastAPI(title="Finance Tracker Worker")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
