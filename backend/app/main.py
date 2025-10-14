from fastapi import FastAPI

app = FastAPI(title="Naviera API")

@app.get("/")
async def root():
    return {"message": "Hello, Naviera!"}
