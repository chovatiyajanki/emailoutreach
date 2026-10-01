from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.scheduler import router as scheduler_router
from .scheduler_worker import start_worker, stop_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start background scheduler worker
    start_worker()
    yield
    # Shutdown: Stop background worker
    stop_worker()


app = FastAPI(
    title="Automated Outreach Pipeline API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scheduler_router)


@app.get("/")
def root():
    return {
        "success": True,
        "service": "Automated Outreach Pipeline API",
        "database": "PostgreSQL Connected",
        "mailbox": "chovatiyajanki1913@gmail.com",
    }