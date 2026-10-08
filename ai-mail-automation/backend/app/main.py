import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure UTF-8 output on Windows consoles to prevent cp1252 charmap encoding errors
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .api.scheduler import router as scheduler_router
from .api.auth import router as auth_router
from .database import Base, engine, SessionLocal
from .models import SchedulerConfig
from .scheduler_worker import start_worker, stop_worker


def init_database_tables():
    """Ensures all PostgreSQL tables and default config are created on startup."""
    try:
        from sqlalchemy import text
        print("[Database] Checking database connection and initializing tables...")
        Base.metadata.create_all(bind=engine)
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE company_mail_accounts ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;"))
            conn.execute(text("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;"))
            conn.execute(text("ALTER TABLE scheduler_runs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;"))
            conn.execute(text("ALTER TABLE sent_mails ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;"))
            conn.commit()
        print("[Database] Database tables and user_id foreign keys verified/created in PostgreSQL!")

        with SessionLocal() as db:
            config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
            if not config:
                config = SchedulerConfig(
                    id=1,
                    is_running=False,
                    interval_seconds=60,
                    search_query="",
                    scrape_batch_size=5,
                    send_batch_size=5,
                    total_runs=0,
                    campaign_name="",
                    email_subject="",
                    email_body="",
                    smtp_host="",
                    smtp_port=None,
                )
                db.add(config)
                db.commit()
            else:
                if "isSelectedEnd" in (config.email_body or "") or "Our platform automates B2B" in (config.email_body or ""):
                    config.email_body = ""
                    config.email_subject = ""
                    db.commit()
                print("[Database] Existing SchedulerConfig preserved and ready.")
    except Exception as e:
        print(f"[Database] Error during database initialization: {e}")


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
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scheduler_router)
app.include_router(auth_router)


@app.get("/")
def root():
    return {
        "success": True,
        "service": "Automated Outreach Pipeline API",
        "database": "PostgreSQL Connected",
    }