from __future__ import annotations
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from models import SessionLocal, Bot as BotModel
from repo_manager import clone_or_open_repo, pull_latest
from process_manager import is_process_running, stop_bot_process, start_bot_process, find_entrypoint
from alerts import scan_log_for_errors


scheduler: Optional[BackgroundScheduler] = None


def start_scheduler():
    global scheduler
    if scheduler is not None and scheduler.running:
        return scheduler
    scheduler = BackgroundScheduler()
    # Removed auto repo update by timer as per requirement
    scheduler.add_job(log_scan_job, "interval", minutes=1, id="log_scan")
    scheduler.start()
    return scheduler


def daily_update_job():
    # deprecated
    pass


def log_scan_job():
    db = SessionLocal()
    try:
        bots = db.query(BotModel).all()
        for bot in bots:
            if not bot.log_path:
                continue
            try:
                scan_log_for_errors(bot.name, bot.log_path)
            except Exception:
                pass
    finally:
        db.close()
