from fastapi import FastAPI

app = FastAPI(title="Naviera API")


@app.get("/")
async def root():
    return {"message": "Hello, Naviera! Make sure to check out the docs at /docs."}
