import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

from .database import SessionLocal
from .models import SchedulerConfig, utc_now
from .scheduler_pipeline import run_scheduler_cycle

# Background worker task reference
_scheduler_task: Optional[asyncio.Task] = None
_is_cycle_in_progress: bool = False


async def scheduler_loop():
    """
    Background asynchronous loop that runs inside FastAPI.
    Monitors SchedulerConfig and triggers run_scheduler_cycle() when due.
    """
    global _is_cycle_in_progress
    print("🔔 Automated Outreach Scheduler Worker Started!")

    while True:
        try:
            await asyncio.sleep(4)
            if _is_cycle_in_progress:
                continue

            with SessionLocal() as db:
                config = db.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
                if not config or not config.is_running:
                    continue

                now = utc_now()
                # Check if it's time to run
                is_due = False
                if not config.last_run_at or not config.next_run_at:
                    is_due = True
                elif now >= config.next_run_at:
                    is_due = True

                if is_due:
                    _is_cycle_in_progress = True
                    print(f"[Scheduler] Interval Triggered! Running cycle #{config.total_runs + 1}...")
                    try:
                        # Run the 5-step pipeline cycle
                        run_scheduler_cycle(db)
                    except Exception as e:
                        print(f"[Scheduler] Error in scheduler cycle execution: {e}")
                    finally:
                        _is_cycle_in_progress = False

        except asyncio.CancelledError:
            print("[Scheduler] Worker task cancelled.")
            break
        except Exception as e:
            err_msg = str(e).lower()
            if "relation \"scheduler_config\" does not exist" in err_msg or "undefinedtable" in err_msg:
                print("[Scheduler] scheduler_config table missing! Auto-initializing PostgreSQL tables...")
                try:
                    from .database import Base, engine
                    Base.metadata.create_all(bind=engine)
                    with SessionLocal() as db_fix:
                        cfg = db_fix.query(SchedulerConfig).filter(SchedulerConfig.id == 1).first()
                        if not cfg:
                            db_fix.add(SchedulerConfig(id=1, is_running=False, interval_seconds=60, search_query="B2B Software and Tech Companies", scrape_batch_size=5, send_batch_size=5, total_runs=0))
                            db_fix.commit()
                    print("[Scheduler] Database tables and default SchedulerConfig created successfully!")
                except Exception as auto_init_err:
                    print(f"[Scheduler] Auto-init error: {auto_init_err}")
            else:
                print(f"[Scheduler] Worker loop error: {e}")
            await asyncio.sleep(5)


def start_worker():
    """Starts the background scheduler loop"""
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(scheduler_loop())


def stop_worker():
    """Stops the background scheduler loop"""
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        _scheduler_task = None
