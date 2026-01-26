from dotenv import load_dotenv
import os

# Load environment variables from .env
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routes import customers, bills, voice, item_master, reports

# Create all database tables
Base.metadata.create_all(bind=engine)

# Initialize FastAPI app
app = FastAPI(title="Shop Billing MVP")

# -------------------------------------------------
# Middleware: ngrok / browser warning bypass
# -------------------------------------------------
@app.middleware("http")
async def add_ngrok_skip_header(request, call_next):
    response = await call_next(request)
    response.headers["ngrok-skip-browser-warning"] = "true"
    return response

# -------------------------------------------------
# CORS (allow Flutter, Android, future web)
# -------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # later restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------
# API Routes
# -------------------------------------------------
app.include_router(customers.router)
app.include_router(bills.router)
app.include_router(item_master.router)
app.include_router(voice.router)
app.include_router(reports.router)