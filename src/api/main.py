from fastapi import FastAPI

app = FastAPI(
    title="HireFlow API"
)

@app.get("/")
def health_check():
    return {"status": "ok"}