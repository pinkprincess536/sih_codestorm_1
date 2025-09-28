from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import ocr_routes

app = FastAPI(title="PramaanVault API")

# Allow frontend to talk to backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ocr_routes.router)
