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
    scheduler = BackgroundScheduler()  # server local time
    scheduler.add_job(daily_update_job, "cron", hour=0, minute=0, id="daily_update")
    scheduler.add_job(log_scan_job, "interval", minutes=1, id="log_scan")
    scheduler.start()
    return scheduler


def daily_update_job():
    db = SessionLocal()
    try:
        bots = db.query(BotModel).all()
        for bot in bots:
            try:
                repo = clone_or_open_repo(bot.repo_url, bot.workdir, branch=bot.branch)
                before, after = pull_latest(repo, branch=bot.branch)
                if before != after:
                    bot.last_commit = after
                    if bot.enabled:
                        if bot.process_pid and is_process_running(bot.process_pid):
                            stop_bot_process(bot.process_pid)
                        entrypoint = find_entrypoint(bot.workdir)
                        pid = start_bot_process(bot.workdir, entrypoint=entrypoint, venv_path=None, log_path=bot.log_path)
                        bot.process_pid = pid
                db.commit()
            except Exception:
                db.rollback()
    finally:
        db.close()


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
