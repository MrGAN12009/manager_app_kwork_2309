from __future__ import annotations
import os
import secrets
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from wtforms import StringField, TextAreaField, BooleanField
from wtforms.validators import DataRequired
from flask_wtf import FlaskForm

from models import SessionLocal, init_db, User as UserModel, Bot as BotModel, BotStats
from process_manager import start_bot_process, stop_bot_process, is_process_running, find_entrypoint, resolve_python_executable, create_virtualenv
from repo_manager import clone_or_open_repo
from scheduler import start_scheduler


class LoginUser(UserMixin):
    def __init__(self, id: int, username: str, password_hash: str, is_active: bool = True):
        self.id = str(id)
        self.username = username
        self.password_hash = password_hash
        self._active = is_active

    def is_active(self):
        return self._active


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", secrets.token_hex(16))

    init_db()

    login_manager = LoginManager(app)
    login_manager.login_view = "login"

    @login_manager.user_loader
    def load_user(user_id: str):
        db = SessionLocal()
        try:
            u = db.get(UserModel, int(user_id))
            if not u:
                return None
            return LoginUser(u.id, u.username, u.password_hash, u.is_active)
        finally:
            db.close()

    # expose helper to check endpoint existence in templates
    @app.context_processor
    def inject_has_endpoint():
        def has_endpoint(name: str) -> bool:
            return name in app.view_functions
        return dict(has_endpoint=has_endpoint)

    ensure_root_user()
    start_scheduler()

    class BotForm(FlaskForm):
        name = StringField("Название", validators=[DataRequired()])
        token = StringField("Token", validators=[DataRequired()])
        repo_url = StringField("Repo URL", validators=[DataRequired()])
        branch = StringField("Branch", default="master")
        env_text = TextAreaField(".env content")
        db_url = StringField("DB URL (optional)")
        enabled = BooleanField("Enabled", default=True)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username")
            password = request.form.get("password")
            db = SessionLocal()
            try:
                user = db.query(UserModel).filter_by(username=username).first()
                if user and check_password_hash(user.password_hash, password):
                    login_user(LoginUser(user.id, user.username, user.password_hash, user.is_active))
                    return redirect(url_for("dashboard"))
                flash("Неверный логин или пароль", "danger")
            finally:
                db.close()
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def dashboard():
        db = SessionLocal()
        try:
            bots = db.query(BotModel).all()
            for b in bots:
                b.status = "running" if is_process_running(b.process_pid) else (b.status or "stopped")
            return render_template("dashboard.html", bots=bots)
        finally:
            db.close()

    @app.route("/bots/new", methods=["GET", "POST"])
    @login_required
    def create_bot():
        form = BotForm()
        if form.validate_on_submit():
            db = SessionLocal()
            try:
                name = form.name.data
                token = form.token.data
                repo_url = form.repo_url.data
                branch = form.branch.data or "master"
                env_text = form.env_text.data or ""
                db_url = form.db_url.data or None
                enabled = form.enabled.data

                workdir = os.path.join("bots", name)
                Path(workdir).mkdir(parents=True, exist_ok=True)

                log_dir = os.path.join(workdir, "logs")
                Path(log_dir).mkdir(parents=True, exist_ok=True)

                bot = BotModel(
                    name=name,
                    token=token,
                    repo_url=repo_url,
                    branch=branch,
                    workdir=workdir,
                    env_text=env_text,
                    db_url=db_url,
                    enabled=enabled,
                    status="setting_up",
                    process_pid=None,
                    last_commit=None,
                    log_path=os.path.join(log_dir, "bot.out.log"),
                    venv_path=os.path.join(workdir, ".venv"),
                    setup_status="running",
                    setup_step=0,
                    setup_total=10,
                    setup_message="Инициализация",
                )
                db.add(bot)
                db.flush()
                db.add(BotStats(bot_id=bot.id))
                db.commit()

                threading.Thread(target=_run_bot_setup, args=(bot.id,), daemon=True).start()
                return redirect(url_for("bot_setup_progress", bot_id=bot.id))
            finally:
                db.close()
        return render_template("bot_form.html", form=form, action="Создать")

    def _update_progress(bot_id: int, step: int, message: str, total: int = 10, status: str = "running"):
        db = SessionLocal()
        try:
            bot = db.get(BotModel, bot_id)
            if not bot:
                return
            bot.setup_step = step
            bot.setup_total = total
            bot.setup_message = message
            bot.setup_status = status
            db.commit()
        finally:
            db.close()

    def _run_bot_setup(bot_id: int):
        steps = [
            (1, "Клонируем репозиторий"),
            (2, "Записываем .env"),
            (3, "Создаём venv"),
            (4, "Обновляем pip"),
            (5, "Устанавливаем зависимости"),
            (6, "Определяем entrypoint"),
            (7, "Сохранение состояния"),
            (8, "Финализация"),
            (9, "Готово"),
            (10, "Завершено"),
        ]
        def get_bot(db):
            return db.get(BotModel, bot_id)
        db = SessionLocal()
        try:
            bot = get_bot(db)
            if not bot:
                return
            try:
                _update_progress(bot_id, steps[0][0], steps[0][1])
                repo = clone_or_open_repo(bot.repo_url, bot.workdir, branch=bot.branch)
                bot.last_commit = repo.head.commit.hexsha if repo.head.is_valid() else None
                db.commit()

                _update_progress(bot_id, steps[1][0], steps[1][1])
                bot = get_bot(db)
                env_path = os.path.join(bot.workdir, ".env")
                full_env = bot.env_text or ""
                if "BOT_TOKEN" not in full_env:
                    full_env += ("\n" if full_env else "") + f"BOT_TOKEN={bot.token}"
                if bot.db_url:
                    full_env += f"\nDATABASE_URL={bot.db_url}"
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write(full_env)

                _update_progress(bot_id, steps[2][0], steps[2][1])
                bot = get_bot(db)
                venv_path = bot.venv_path or os.path.join(bot.workdir, ".venv")
                create_virtualenv(venv_path)

                _update_progress(bot_id, steps[3][0], steps[3][1])
                vpy = resolve_python_executable(venv_path)
                if venv_path and (venv_path not in vpy):
                    raise RuntimeError("Python из venv не найден. Установите python3-venv: sudo apt install -y python3-venv")
                subprocess.check_call([vpy, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], cwd=None)

                _update_progress(bot_id, steps[4][0], steps[4][1])
                req_path = os.path.join(bot.workdir, "requirements.txt")
                abs_req = os.path.abspath(req_path)
                # retry a few times if FS not yet synced
                attempts = 0
                while attempts < 5 and not os.path.exists(abs_req):
                    time.sleep(0.4)
                    attempts += 1
                if os.path.exists(abs_req):
                    subprocess.check_call([vpy, "-m", "pip", "install", "-r", abs_req], cwd=None)
                # if no requirements.txt, skip silently

                _update_progress(bot_id, steps[5][0], steps[5][1])
                entrypoint = find_entrypoint(bot.workdir)

                _update_progress(bot_id, steps[6][0], steps[6][1])
                bot = get_bot(db)
                bot.venv_path = venv_path
                db.commit()

                _update_progress(bot_id, steps[7][0], steps[7][1])
                _update_progress(bot_id, steps[8][0], steps[8][1])
                _update_progress(bot_id, steps[9][0], steps[9][1], status="done")

                bot = get_bot(db)
                bot.status = "stopped"
                db.commit()
            except Exception as e:
                _update_progress(bot_id, 10, f"Ошибка: {e}", status="failed")
                bot = get_bot(db)
                if bot:
                    bot.status = "errored"
                    db.commit()
        finally:
            db.close()

    @app.route("/bots/<int:bot_id>/setup")
    @login_required
    def bot_setup_progress(bot_id: int):
        db = SessionLocal()
        try:
            bot = db.get(BotModel, bot_id)
            if not bot:
                flash("Бот не найден", "warning")
                return redirect(url_for("dashboard"))
            return render_template("setup_progress.html", bot=bot)
        finally:
            db.close()

    @app.route("/api/bots/<int:bot_id>/setup_status")
    @login_required
    def api_setup_status(bot_id: int):
        db = SessionLocal()
        try:
            bot = db.get(BotModel, bot_id)
            if not bot:
                return jsonify({"error": "not_found"}), 404
            return jsonify({
                "status": bot.setup_status,
                "step": bot.setup_step,
                "total": bot.setup_total,
                "message": bot.setup_message,
            })
        finally:
            db.close()

    @app.route("/bots/<int:bot_id>/start", methods=["POST"])
    @login_required
    def start_bot(bot_id: int):
        db = SessionLocal()
        try:
            bot = db.get(BotModel, bot_id)
            if not bot:
                flash("Бот не найден", "warning")
                return redirect(url_for("dashboard"))
            if bot.setup_status != "done":
                flash("Сначала дождитесь завершения установки", "warning")
                return redirect(url_for("bot_setup_progress", bot_id=bot.id))
            if is_process_running(bot.process_pid):
                flash("Уже запущен", "info")
                return redirect(url_for("bot_detail", bot_id=bot.id))
            entrypoint = find_entrypoint(bot.workdir)
            pid = start_bot_process(bot.workdir, entrypoint=entrypoint, venv_path=bot.venv_path, log_path=bot.log_path)
            bot.process_pid = pid
            bot.status = "running"
            bot.last_started_at = datetime.utcnow()
            db.commit()
            flash("Бот запущен", "success")
            return redirect(url_for("bot_detail", bot_id=bot.id))
        finally:
            db.close()

    @app.route("/bots/<int:bot_id>/restart", methods=["POST"])
    @login_required
    def restart_bot(bot_id: int):
        db = SessionLocal()
        try:
            bot = db.get(BotModel, bot_id)
            if not bot:
                flash("Бот не найден", "warning")
                return redirect(url_for("dashboard"))
            if bot.process_pid:
                stop_bot_process(bot.process_pid)
            entrypoint = find_entrypoint(bot.workdir)
            pid = start_bot_process(bot.workdir, entrypoint=entrypoint, venv_path=bot.venv_path, log_path=bot.log_path)
            bot.process_pid = pid
            bot.status = "running"
            bot.last_started_at = datetime.utcnow()
            db.commit()
            flash("Перезапущен", "success")
            return redirect(url_for("bot_detail", bot_id=bot.id))
        finally:
            db.close()

    @app.route("/bots/<int:bot_id>")
    @login_required
    def bot_detail(bot_id: int):
        db = SessionLocal()
        try:
            bot = db.get(BotModel, bot_id)
            if not bot:
                flash("Бот не найден", "warning")
                return redirect(url_for("dashboard"))
            runtime_status = "running" if is_process_running(bot.process_pid) else "stopped"
            return render_template("bot_detail.html", bot=bot, runtime_status=runtime_status)
        finally:
            db.close()

    return app


def ensure_root_user() -> None:
    db = SessionLocal()
    try:
        user = db.query(UserModel).filter_by(username="root").first()
        if not user:
            user = UserModel(username="root", password_hash=generate_password_hash("root"))
            db.add(user)
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
