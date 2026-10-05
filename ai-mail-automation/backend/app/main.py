from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.scheduler import router as scheduler_router
from .database import Base, engine, SessionLocal
from .models import SchedulerConfig
from .scheduler_worker import start_worker, stop_worker


def init_database_tables():
    """Ensures all PostgreSQL tables and default config are created on startup."""
    try:
        print(" Checking database connection and initializing tables...")
        Base.metadata.create_all(bind=engine)
        print(" Database tables verified/created in PostgreSQL!")

        with SessionLocal() as db:
            config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
            if not config:
                config = SchedulerConfig(
                    id=1,
                    is_running=False,
                    interval_seconds=60,
                    search_query="B2B Software and Tech Companies",
                    scrape_batch_size=5,
                    send_batch_size=5,
                    total_runs=0,
                )
                db.add(config)
                db.commit()
                print(" Default SchedulerConfig row (id=1) initialized!")
            else:
                print(" Default SchedulerConfig present and ready.")
    except Exception as e:
        print(f" Error during database initialization: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure database schema exists before background worker starts
    init_database_tables()
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
    allow_origins=[
        "https://emailoutreach-gamma.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
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
    }