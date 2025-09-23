from __future__ import annotations
import os
import secrets
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, redirect, url_for, request, flash, send_file
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from wtforms import StringField, TextAreaField, BooleanField
from wtforms.validators import DataRequired
from flask_wtf import FlaskForm

from models import SessionLocal, init_db, User as UserModel, Bot as BotModel, BotStats
from process_manager import start_bot_process, stop_bot_process, is_process_running, find_entrypoint
from repo_manager import clone_or_open_repo, pull_latest
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

    ensure_root_user()

    # Start background scheduler
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
                b.status = "running" if is_process_running(b.process_pid) else "stopped"
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
                repo = clone_or_open_repo(repo_url, workdir, branch=branch)
                current_head = repo.head.commit.hexsha if repo.head.is_valid() else None

                env_path = os.path.join(workdir, ".env")
                with open(env_path, "w", encoding="utf-8") as f:
                    full_env = env_text or ""
                    if "BOT_TOKEN" not in full_env:
                        full_env += ("\n" if full_env else "") + f"BOT_TOKEN={token}"
                    if db_url:
                        full_env += f"\nDATABASE_URL={db_url}"
                    f.write(full_env)

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
                    status="stopped",
                    process_pid=None,
                    last_commit=current_head,
                    log_path=os.path.join(log_dir, "bot.out.log"),
                )
                db.add(bot)
                db.flush()
                db.add(BotStats(bot_id=bot.id))
                db.commit()
                flash("Бот создан", "success")
                return redirect(url_for("dashboard"))
            finally:
                db.close()
        return render_template("bot_form.html", form=form, action="Создать")

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

    @app.route("/bots/<int:bot_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_bot(bot_id: int):
        db = SessionLocal()
        try:
            bot = db.get(BotModel, bot_id)
            if not bot:
                flash("Бот не найден", "warning")
                return redirect(url_for("dashboard"))
            form = BotForm(obj=bot)
            if form.validate_on_submit():
                bot.name = form.name.data
                bot.token = form.token.data
                bot.repo_url = form.repo_url.data
                bot.branch = form.branch.data or "master"
                bot.env_text = form.env_text.data or ""
                bot.db_url = form.db_url.data or None
                bot.enabled = form.enabled.data

                env_path = os.path.join(bot.workdir, ".env")
                full_env = bot.env_text
                if "BOT_TOKEN" not in full_env:
                    full_env += ("\n" if full_env else "") + f"BOT_TOKEN={bot.token}"
                if bot.db_url and "DATABASE_URL" not in full_env:
                    full_env += f"\nDATABASE_URL={bot.db_url}"
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write(full_env)

                db.commit()
                flash("Сохранено", "success")
                return redirect(url_for("bot_detail", bot_id=bot.id))
            return render_template("bot_form.html", form=form, action="Сохранить")
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
            if is_process_running(bot.process_pid):
                flash("Уже запущен", "info")
                return redirect(url_for("bot_detail", bot_id=bot.id))
            entrypoint = find_entrypoint(bot.workdir)
            pid = start_bot_process(bot.workdir, entrypoint=entrypoint, venv_path=None, log_path=bot.log_path)
            bot.process_pid = pid
            bot.status = "running"
            bot.last_started_at = datetime.utcnow()
            db.commit()
            flash("Бот запущен", "success")
            return redirect(url_for("bot_detail", bot_id=bot.id))
        finally:
            db.close()

    @app.route("/bots/<int:bot_id>/stop", methods=["POST"])
    @login_required
    def stop_bot(bot_id: int):
        db = SessionLocal()
        try:
            bot = db.get(BotModel, bot_id)
            if not bot:
                flash("Бот не найден", "warning")
                return redirect(url_for("dashboard"))
            if bot.process_pid:
                stop_bot_process(bot.process_pid)
            bot.process_pid = None
            bot.status = "stopped"
            bot.last_stopped_at = datetime.utcnow()
            db.commit()
            flash("Бот остановлен", "success")
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
            pid = start_bot_process(bot.workdir, entrypoint=entrypoint, venv_path=None, log_path=bot.log_path)
            bot.process_pid = pid
            bot.status = "running"
            bot.last_started_at = datetime.utcnow()
            db.commit()
            flash("Перезапущен", "success")
            return redirect(url_for("bot_detail", bot_id=bot.id))
        finally:
            db.close()

    @app.route("/bots/<int:bot_id>/logs")
    @login_required
    def view_logs(bot_id: int):
        db = SessionLocal()
        try:
            bot = db.get(BotModel, bot_id)
            if not bot:
                flash("Бот не найден", "warning")
                return redirect(url_for("dashboard"))
            log_file = bot.log_path
            if not os.path.isfile(log_file):
                return render_template("logs.html", bot=bot, logs="Лог файл отсутствует")
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()[-20000:]
            except Exception as e:
                content = f"Ошибка чтения логов: {e}"
            return render_template("logs.html", bot=bot, logs=content)
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
