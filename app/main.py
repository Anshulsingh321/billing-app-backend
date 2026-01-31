from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
load_dotenv()

from .database import Base, engine
from .routes import customers, bills, voice, item_master, reports
from app.routes.vision import router as vision_router

# Create app 
app = FastAPI(title="Shop Billing MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# include routers
app.include_router(customers.router)
app.include_router(bills.router)
app.include_router(item_master.router)
app.include_router(voice.router)
app.include_router(reports.router)

app.include_router(vision_router)

# -------------------------------------------------
# Global Health Check
# -------------------------------------------------
@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "services": {
            "api": "ok"
        }
    }

# Create DB tables
Base.metadata.create_all(bind=engine)

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