from fastapi import FastAPI

app = FastAPI(
    title="HireFlow AI API",
    description="Career autopilot for students. Discovers jobs, tailors resumes, applies, and prepares mock interviews.",
    version="0.1.0"
)

@app.get("/")
def read_root():
    return {
        "status": "online",
        "service": "HireFlow AI API",
        "version": "0.1.0"
    }
