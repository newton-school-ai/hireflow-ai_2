from fastapi import FastAPI

app = FastAPI(
    title="HireFlow API"
)

@app.get("/")
async def root():
    return {"status": "ok"}