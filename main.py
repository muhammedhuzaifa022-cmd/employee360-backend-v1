from fastapi import FastAPI
from fastapi.responses import FileResponse

app = FastAPI()

@app.get("/")
def read_index():
    return FileResponse("frontend/index.html")