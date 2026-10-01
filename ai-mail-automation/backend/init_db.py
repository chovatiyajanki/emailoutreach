from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

from app.database import Base, engine, SessionLocal
from app.models import SchedulerConfig

print("Creating all tables in PostgreSQL...")
Base.metadata.create_all(bind=engine)
print("Tables created successfully!")

# Ensure default scheduler config exists
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
            total_runs=0
        )
        db.add(config)
        db.commit()
        print("Default SchedulerConfig initialized!")
    else:
        print("SchedulerConfig already present.")
