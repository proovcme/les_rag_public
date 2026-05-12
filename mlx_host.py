import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
import logging
import os

# Подтягиваем менеджер памяти. Запускать нужно из корня проекта LES_v2
from backend.mlx_adapter import MLXMemoryManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] MLX Host: %(message)s")

app = FastAPI(title="LES MLX Native Host")

# Берем модель из ENV или используем дефолт Gemma 4
MODEL_PATH = os.getenv("MLX_MODEL", "mlx-community/gemma-4-26b-a4b-it-4bit")

engine = MLXMemoryManager(model_path=MODEL_PATH, ttl_seconds=300)

class GenerateRequest(BaseModel):
    model: str
    prompt: str
    stream: bool = False

@app.get("/api/health")
async def health():
    return {"status": "ok", "model": engine.model_path}

@app.post("/api/generate")
async def generate(req: GenerateRequest):
    if engine.model_path != req.model:
        engine.model_path = req.model
        engine.force_unload()
        
    answer = await engine.generate_text(prompt=req.prompt, max_tokens=2048)
    return {
        "model": req.model,
        "response": answer, 
        "eval_count": len(answer.split())
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
