"""CityBot2 Web Dashboard - FastAPI application."""

import os
import sys
import json
import secrets
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, inspect as sa_inspect

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database.operations import DatabaseManager
from database.models import (
    WeatherReport, WeatherAlert, Earthquake, NewsArticle, PostHistory,
    User, SocialAccount, Announcement, EmailSubscriber,
    DataSource, KeywordFilter, PostQueue,
)
from web.auth import (
    hash_password, verify_password, create_session_token,
    validate_session_token, SESSION_COOKIE, generate_invite_token,
    has_role,
)

logger = logging.getLogger("CityBot2.web")

app = FastAPI(title="CityBot2", docs_url=None, redoc_url=None)

# Trust proxy headers (X-Forwarded-For, X-Forwarded-Proto) when behind Caddy/nginx
# FastAPI/Starlette handle this via --proxy-headers in uvicorn (set below)

# Mount static files and templates
WEB_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

# Database manager (lazy init)
_db: Optional[DatabaseManager] = None


def get_db() -> DatabaseManager:
    """Get or create the database manager."""
    global _db
    if _db is None:
        data_dir = PROJECT_ROOT / "data"
        data_dir.mkdir(exist_ok=True)
        db_url = f"sqlite:///{data_dir}/citybot.db"
        _db = DatabaseManager(db_url)
    return _db


def load_city_config_safe() -> Dict[str, Any]:
    """Load city config without raising on missing env vars."""
    try:
        city_name = os.getenv("CITY_NAME")
        if not city_name:
            cities_dir = PROJECT_ROOT / "config" / "cities"
            if cities_dir.exists():
                configs = list(cities_dir.glob("*.json"))
                if configs:
                    city_name = configs[0].stem
                    os.environ["CITY_NAME"] = city_name

        if not city_name:
            return {"name": "Unknown", "state": "", "_error": "CITY_NAME not set"}

        config_path = PROJECT_ROOT / "config" / "cities" / f"{city_name}.json"
        if not config_path.exists():
            return {"name": city_name, "state": "", "_error": f"Config file not found: {config_path}"}

        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"name": "Error", "state": "", "_error": str(e)}


def fmt_timestamp(dt: Optional[datetime]) -> str:
    """Format a datetime for display."""
    if dt is None:
        return "N/A"
    return dt.strftime("%b %d, %Y %I:%M %p")


def fmt_relative(dt: Optional[datetime]) -> str:
    """Format a datetime as relative time."""
    if dt is None:
        return "N/A"
    now = datetime.utcnow()
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        mins = seconds // 60
        return f"{mins}m ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    days = seconds // 86400
    return f"{days}d ago"


# Register template filters
templates.env.filters["fmt_ts"] = fmt_timestamp
templates.env.filters["fmt_rel"] = fmt_relative


# ─── Auth Helpers ──────────────────────────────────────────────────────────────

def get_current_user_or_none(request: Request):
    """Return the logged-in User or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    uid = validate_session_token(token)
    if uid is None:
        return None
    db = get_db()
    with db.Session() as session:
        user = session.query(User).filter_by(id=uid, is_active=True).first()
        if user:
            session.expunge(user)
        return user


def require_login(request: Request):
    """Return user or None (caller should redirect if None)."""
    return get_current_user_or_none(request)


def user_count() -> int:
    """Return total number of users in the database."""
    db = get_db()
    with db.Session() as session:
        return session.query(func.count(User.id)).scalar() or 0


def _is_https(request: Request) -> bool:
    """Detect HTTPS via scheme or X-Forwarded-Proto header."""
    if request.url.scheme == "https":
        return True
    return request.headers.get("x-forwarded-proto", "") == "https"


def _set_session_cookie(response, token: str, request: Request):
    """Set the session cookie with appropriate secure flags."""
    secure = _is_https(request)
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=86400, httponly=True,
        secure=secure, samesite="lax",
    )


def get_base_url(request: Request) -> str:
    """Return the public base URL (e.g. https://ventura.news).
    Uses CITYBOT_DOMAIN env var if set, otherwise builds from request."""
    domain = os.getenv("CITYBOT_DOMAIN", "")
    if domain:
        scheme = "https" if _is_https(request) or domain != "localhost" else "http"
        return f"{scheme}://{domain}"
    return str(request.base_url).rstrip("/")


def _flash(response, message, category="success"):
    """Set a flash cookie."""
    response.set_cookie("flash_msg", message, max_age=10, httponly=True)


def _get_flash(request):
    """Read flash from cookies."""
    msg = request.cookies.get("flash_msg", "")
    cat = request.cookies.get("flash_cat", "success")
    return msg, cat


def _base_context(request: Request, **kwargs):
    """Build base template context with user and flash."""
    user = get_current_user_or_none(request)
    flash_msg, flash_cat = _get_flash(request)
    ctx = {
        "request": request,
        "city": load_city_config_safe(),
        "user": user,
        "has_role": has_role,
        "flash_msg": flash_msg,
        "flash_cat": flash_cat,
        "now": datetime.utcnow(),
        "base_url": get_base_url(request),
    }
    ctx.update(kwargs)
    return ctx


def _clear_flash(response):
    """Clear flash cookies."""
    response.delete_cookie("flash_msg")
    response.delete_cookie("flash_cat")
    return response


def _table_exists(session, table_name: str) -> bool:
    """Check if a table exists in the database."""
    try:
        inspector = sa_inspect(session.bind)
        return table_name in inspector.get_table_names()
    except Exception:
        return False


# ─── Public Routes ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def feed_page(request: Request):
    """Public community news feed homepage."""
    db = get_db()
    current_type = request.query_params.get("type")
    page = int(request.query_params.get("page", 1))
    per_page = 20

    feed_items = []
    has_more = False
    weather = None
    alerts = []
    recent_earthquakes = []

    with db.Session() as session:
        # Latest weather for hero
        weather = (
            session.query(WeatherReport)
            .order_by(WeatherReport.timestamp.desc())
            .first()
        )
        # Active alerts
        try:
            alerts = (
                session.query(WeatherAlert)
                .filter(WeatherAlert.expires > datetime.utcnow())
                .order_by(WeatherAlert.severity.desc())
                .all()
            )
        except Exception:
            alerts = []

        # Recent earthquakes for sidebar
        eq_cutoff = datetime.utcnow() - timedelta(hours=24)
        recent_earthquakes = (
            session.query(Earthquake)
            .filter(Earthquake.timestamp >= eq_cutoff)
            .order_by(Earthquake.timestamp.desc())
            .limit(3)
            .all()
        )

        # Feed items from PostQueue
        if _table_exists(session, 'post_queue'):
            try:
                q = session.query(PostQueue).filter(
                    PostQueue.status == 'posted',
                    PostQueue.is_public == True,
                )
                if current_type:
                    q = q.filter(PostQueue.content_type == current_type)
                q = q.order_by(PostQueue.posted_at.desc())

                total = q.count()
                feed_items = q.offset((page - 1) * per_page).limit(per_page + 1).all()

                if len(feed_items) > per_page:
                    has_more = True
                    feed_items = feed_items[:per_page]
            except Exception:
                feed_items = []

    ctx = _base_context(
        request,
        feed_items=feed_items,
        current_type=current_type,
        page=page,
        has_more=has_more,
        weather=weather,
        alerts=alerts,
        recent_earthquakes=recent_earthquakes,
    )
    resp = templates.TemplateResponse("feed.html", ctx)
    return _clear_flash(resp)


@app.get("/weather", response_class=HTMLResponse)
async def weather_page(request: Request):
    """Weather history and current conditions."""
    db = get_db()

    with db.Session() as session:
        reports = (
            session.query(WeatherReport)
            .order_by(WeatherReport.timestamp.desc())
            .limit(50)
            .all()
        )
        active_alerts = (
            session.query(WeatherAlert)
            .filter(WeatherAlert.expires > datetime.utcnow())
            .order_by(WeatherAlert.onset.desc())
            .all()
        )
        all_alerts = (
            session.query(WeatherAlert)
            .order_by(WeatherAlert.timestamp.desc())
            .limit(20)
            .all()
        )

    ctx = _base_context(
        request,
        reports=reports,
        active_alerts=active_alerts,
        all_alerts=all_alerts,
    )
    resp = templates.TemplateResponse("weather.html", ctx)
    return _clear_flash(resp)


@app.get("/earthquakes", response_class=HTMLResponse)
async def earthquakes_page(request: Request):
    """Earthquake history."""
    db = get_db()

    with db.Session() as session:
        earthquakes = (
            session.query(Earthquake)
            .order_by(Earthquake.timestamp.desc())
            .limit(100)
            .all()
        )
        eq_24h = datetime.utcnow() - timedelta(hours=24)
        count_24h = (
            session.query(func.count(Earthquake.id))
            .filter(Earthquake.timestamp >= eq_24h)
            .scalar() or 0
        )
        max_mag = (
            session.query(func.max(Earthquake.magnitude))
            .filter(Earthquake.timestamp >= eq_24h)
            .scalar()
        )

    ctx = _base_context(
        request,
        earthquakes=earthquakes,
        count_24h=count_24h,
        max_mag=max_mag,
    )
    resp = templates.TemplateResponse("earthquakes.html", ctx)
    return _clear_flash(resp)


@app.get("/news", response_class=HTMLResponse)
async def news_page(request: Request):
    """News articles feed."""
    db = get_db()

    with db.Session() as session:
        articles = (
            session.query(NewsArticle)
            .order_by(NewsArticle.timestamp.desc())
            .limit(100)
            .all()
        )

    ctx = _base_context(request, articles=articles)
    resp = templates.TemplateResponse("news.html", ctx)
    return _clear_flash(resp)


@app.get("/posts", response_class=HTMLResponse)
async def posts_page(request: Request):
    """Posting history across platforms."""
    user = require_login(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    db = get_db()

    with db.Session() as session:
        posts = (
            session.query(PostHistory)
            .order_by(PostHistory.timestamp.desc())
            .limit(200)
            .all()
        )
        stats = _get_posting_stats(session)

    ctx = _base_context(request, posts=posts, stats=stats)
    resp = templates.TemplateResponse("posts.html", ctx)
    return _clear_flash(resp)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """View current configuration (read-only)."""
    user = require_login(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    city_config = load_city_config_safe()
    env_path = PROJECT_ROOT / "config" / "credentials.env"
    env_vars = {}
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    if any(s in key.lower() for s in ["secret", "password", "token", "key"]):
                        env_vars[key] = "****" + val[-4:] if len(val) > 4 else "****"
                    else:
                        env_vars[key] = val

    ctx = _base_context(request, env_vars=env_vars)
    resp = templates.TemplateResponse("settings.html", ctx)
    return _clear_flash(resp)


# ─── Public: Subscribe ─────────────────────────────────────────────────────────

@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe_page(request: Request):
    ctx = _base_context(request)
    resp = templates.TemplateResponse("subscribe.html", ctx)
    return _clear_flash(resp)


@app.post("/subscribe")
async def subscribe_submit(request: Request, email: str = Form(...)):
    form = await request.form()
    prefs = []
    for p in ["weather", "earthquakes", "news", "announcements"]:
        if form.get(p):
            prefs.append(p)

    db = get_db()
    with db.Session() as session:
        existing = session.query(EmailSubscriber).filter_by(email=email).first()
        if existing:
            resp = RedirectResponse("/subscribe", status_code=303)
            _flash(resp, "This email is already subscribed.", "error")
            return resp

        confirm_token = secrets.token_urlsafe(32)
        unsub_token = secrets.token_urlsafe(32)
        sub = EmailSubscriber(
            email=email,
            confirm_token=confirm_token,
            unsubscribe_token=unsub_token,
            preferences=json.dumps(prefs),
            confirmed=False,
        )
        session.add(sub)
        session.commit()

    # TODO: wire SMTP — send a real confirmation email to `email` containing
    # the link /confirm/{confirm_token}. Email sending is not yet implemented;
    # the confirmation token is saved to the database but no email is dispatched.
    # Configure EMAIL_SMTP_HOST/PORT/USER/PASSWORD in credentials.env and add
    # an smtplib/aiosmtplib call here before redirecting.
    resp = RedirectResponse("/subscribe", status_code=303)
    _flash(resp, f"Please check your email to confirm your subscription. (Email delivery not yet configured — confirmation link: /confirm/{confirm_token})")
    return resp


@app.get("/confirm/{token}", response_class=HTMLResponse)
async def confirm_subscription(request: Request, token: str):
    db = get_db()
    with db.Session() as session:
        sub = session.query(EmailSubscriber).filter_by(confirm_token=token).first()
        if sub:
            sub.confirmed = True
            session.commit()
            resp = RedirectResponse("/subscribe", status_code=303)
            _flash(resp, "Your subscription has been confirmed!")
            return resp

    resp = RedirectResponse("/subscribe", status_code=303)
    _flash(resp, "Invalid confirmation link.", "error")
    return resp


@app.get("/unsubscribe/{token}", response_class=HTMLResponse)
async def unsubscribe(request: Request, token: str):
    db = get_db()
    with db.Session() as session:
        sub = session.query(EmailSubscriber).filter_by(unsubscribe_token=token).first()
        if sub:
            sub.is_active = False
            session.commit()
            resp = RedirectResponse("/subscribe", status_code=303)
            _flash(resp, "You have been unsubscribed.")
            return resp

    resp = RedirectResponse("/subscribe", status_code=303)
    _flash(resp, "Invalid unsubscribe link.", "error")
    return resp


# ─── Auth Routes ───────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    show_setup = user_count() == 0
    ctx = _base_context(request, show_setup=show_setup)
    resp = templates.TemplateResponse("login.html", ctx)
    return _clear_flash(resp)


@app.post("/login")
async def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    db = get_db()
    with db.Session() as session:
        u = session.query(User).filter_by(email=email).first()
        if u and u.is_active and u.password_hash and verify_password(password, u.password_hash):
            u.last_login = datetime.utcnow()
            session.commit()
            token = create_session_token(u.id)
            resp = RedirectResponse("/admin/dashboard", status_code=303)
            _set_session_cookie(resp, token, request)
            return resp
    # Failed
    ctx = _base_context(request, error="Invalid email or password", show_setup=user_count() == 0)
    return templates.TemplateResponse("login.html", ctx)


@app.get("/logout")
async def logout(request: Request):
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    if user_count() > 0:
        return RedirectResponse("/login", status_code=303)
    ctx = _base_context(request)
    return templates.TemplateResponse("setup.html", ctx)


@app.post("/setup")
async def setup_submit(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(""),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    if user_count() > 0:
        return RedirectResponse("/login", status_code=303)
    if password != confirm_password:
        ctx = _base_context(request, error="Passwords do not match")
        return templates.TemplateResponse("setup.html", ctx)
    if len(password) < 8:
        ctx = _base_context(request, error="Password must be at least 8 characters")
        return templates.TemplateResponse("setup.html", ctx)

    db = get_db()
    with db.Session() as session:
        u = User(
            email=email,
            display_name=display_name or email.split("@")[0],
            password_hash=hash_password(password),
            role="superadmin",
            is_active=True,
        )
        session.add(u)
        session.commit()
        token = create_session_token(u.id)

    resp = RedirectResponse("/admin/dashboard", status_code=303)
    _set_session_cookie(resp, token, request)
    _flash(resp, "Admin account created successfully!")
    return resp


@app.get("/invite/{token}", response_class=HTMLResponse)
async def invite_page(request: Request, token: str):
    db = get_db()
    with db.Session() as session:
        u = session.query(User).filter_by(invite_token=token).first()
        if not u or (u.invite_expires and u.invite_expires < datetime.utcnow()):
            ctx = _base_context(request, error="Invalid or expired invite link")
            return templates.TemplateResponse("login.html", ctx)
    ctx = _base_context(request, invite_token=token, invite_email=u.email)
    return templates.TemplateResponse("invite.html", ctx)


@app.post("/invite/{token}")
async def invite_submit(
    request: Request,
    token: str,
    display_name: str = Form(""),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    if password != confirm_password:
        ctx = _base_context(request, invite_token=token, error="Passwords do not match")
        return templates.TemplateResponse("invite.html", ctx)
    if len(password) < 8:
        ctx = _base_context(request, invite_token=token, error="Password must be at least 8 characters")
        return templates.TemplateResponse("invite.html", ctx)

    db = get_db()
    with db.Session() as session:
        u = session.query(User).filter_by(invite_token=token).first()
        if not u or (u.invite_expires and u.invite_expires < datetime.utcnow()):
            ctx = _base_context(request, error="Invalid or expired invite link")
            return templates.TemplateResponse("login.html", ctx)
        u.password_hash = hash_password(password)
        u.display_name = display_name or u.email.split("@")[0]
        u.invite_token = None
        u.invite_expires = None
        u.is_active = True
        session.commit()
        sess_token = create_session_token(u.id)

    resp = RedirectResponse("/admin/dashboard", status_code=303)
    _set_session_cookie(resp, sess_token, request)
    _flash(resp, "Account created successfully!")
    return resp


# ─── Admin: Dashboard ─────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def admin_redirect(request: Request):
    return RedirectResponse("/admin/dashboard", status_code=303)


@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """Admin dashboard page (old homepage)."""
    user = require_login(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    db = get_db()

    with db.Session() as session:
        latest_weather = (
            session.query(WeatherReport)
            .order_by(WeatherReport.timestamp.desc())
            .first()
        )
        active_alerts = (
            session.query(WeatherAlert)
            .filter(WeatherAlert.expires > datetime.utcnow())
            .order_by(WeatherAlert.severity.desc())
            .all()
        )
        eq_cutoff = datetime.utcnow() - timedelta(hours=24)
        recent_earthquakes = (
            session.query(Earthquake)
            .filter(Earthquake.timestamp >= eq_cutoff)
            .order_by(Earthquake.timestamp.desc())
            .limit(5)
            .all()
        )
        recent_news = (
            session.query(NewsArticle)
            .order_by(NewsArticle.timestamp.desc())
            .limit(5)
            .all()
        )
        stats = _get_posting_stats(session)
        status_cutoff = datetime.utcnow() - timedelta(hours=7)
        recent_activity = (
            session.query(func.count(PostHistory.id))
            .filter(PostHistory.timestamp >= status_cutoff)
            .scalar()
        )
        bot_running = (recent_activity or 0) > 0
        recent_data = (
            session.query(func.count(WeatherReport.id))
            .filter(WeatherReport.timestamp >= status_cutoff)
            .scalar()
        )
        bot_running = bot_running or (recent_data or 0) > 0

    ctx = _base_context(
        request,
        weather=latest_weather,
        alerts=active_alerts,
        earthquakes=recent_earthquakes,
        news=recent_news,
        stats=stats,
        bot_running=bot_running,
    )
    resp = templates.TemplateResponse("dashboard.html", ctx)
    return _clear_flash(resp)


# ─── Admin: City Settings ─────────────────────────────────────────────────────

@app.get("/admin/city", response_class=HTMLResponse)
async def admin_city_page(request: Request):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)
    city_config = load_city_config_safe()
    ctx = _base_context(request, city_config=city_config)
    resp = templates.TemplateResponse("admin/city.html", ctx)
    return _clear_flash(resp)


@app.post("/admin/city")
async def admin_city_save(
    request: Request,
    city_name: str = Form(...),
    state: str = Form(""),
    description: str = Form(""),
    timezone: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
    weather_zone: str = Form(""),
    radar_station: str = Form(""),
):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    # Load existing config to preserve other fields
    slug = os.getenv("CITY_NAME", "")
    if not slug:
        cities_dir = PROJECT_ROOT / "config" / "cities"
        if cities_dir.exists():
            configs = list(cities_dir.glob("*.json"))
            if configs:
                slug = configs[0].stem

    config_path = PROJECT_ROOT / "config" / "cities" / f"{slug}.json"
    existing = {}
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            existing = json.load(f)

    existing["name"] = city_name
    existing["state"] = state
    existing["description"] = description
    existing["timezone"] = timezone
    if "coordinates" not in existing:
        existing["coordinates"] = {}
    try:
        existing["coordinates"]["latitude"] = float(latitude) if latitude else 0
        existing["coordinates"]["longitude"] = float(longitude) if longitude else 0
    except ValueError:
        pass
    if "weather" not in existing:
        existing["weather"] = {}
    existing["weather"]["zone"] = weather_zone
    existing["weather"]["radar_station"] = radar_station

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)

    resp = RedirectResponse("/admin/city", status_code=303)
    _flash(resp, "City settings saved!")
    return resp


# ─── Admin: Users ──────────────────────────────────────────────────────────────

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    db = get_db()
    with db.Session() as session:
        users = session.query(User).order_by(User.created_at.desc()).all()
        for u in users:
            session.expunge(u)

    ctx = _base_context(request, users=users)
    resp = templates.TemplateResponse("admin/users.html", ctx)
    return _clear_flash(resp)


@app.post("/admin/users/invite")
async def admin_users_invite(
    request: Request,
    email: str = Form(...),
    role: str = Form("editor"),
):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    db = get_db()
    with db.Session() as session:
        existing = session.query(User).filter_by(email=email).first()
        if existing:
            resp = RedirectResponse("/admin/users", status_code=303)
            _flash(resp, f"User with email {email} already exists", "error")
            return resp

        token = generate_invite_token()
        u = User(
            email=email,
            role=role if role in ("editor", "admin") else "editor",
            invite_token=token,
            invite_expires=datetime.utcnow() + timedelta(days=7),
            invited_by_id=user.id,
            is_active=False,
        )
        session.add(u)
        session.commit()

    resp = RedirectResponse("/admin/users", status_code=303)
    _flash(resp, f"Invite created! Link: /invite/{token}")
    return resp


@app.post("/admin/users/{user_id}/toggle")
async def admin_users_toggle(request: Request, user_id: int):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    db = get_db()
    with db.Session() as session:
        target = session.query(User).filter_by(id=user_id).first()
        if target and target.id != user.id:
            target.is_active = not target.is_active
            session.commit()

    resp = RedirectResponse("/admin/users", status_code=303)
    _flash(resp, "User status updated")
    return resp


# ─── Admin: Social Accounts ───────────────────────────────────────────────────

PLATFORM_FIELDS = {
    "twitter": ["api_key", "api_secret", "access_token", "access_secret"],
    "bluesky": ["handle", "password"],
    "facebook": ["page_id", "access_token"],
    "linkedin": ["client_id", "client_secret", "access_token"],
    "reddit": ["client_id", "client_secret", "username", "password"],
    "threads": ["access_token", "user_id"],
    "instagram": ["access_token", "business_account_id"],
    "nextdoor": ["access_token", "agency_id"],
}


@app.get("/admin/social", response_class=HTMLResponse)
async def admin_social_page(request: Request):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    db = get_db()
    with db.Session() as session:
        accounts = session.query(SocialAccount).all()
        for a in accounts:
            session.expunge(a)

    connected = {a.platform: a for a in accounts if a.is_active}
    ctx = _base_context(
        request,
        platform_fields=PLATFORM_FIELDS,
        connected=connected,
        accounts=accounts,
    )
    resp = templates.TemplateResponse("admin/social.html", ctx)
    return _clear_flash(resp)


@app.post("/admin/social/connect")
async def admin_social_connect(request: Request):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    platform = form.get("platform", "")
    if platform not in PLATFORM_FIELDS:
        resp = RedirectResponse("/admin/social", status_code=303)
        _flash(resp, "Unknown platform", "error")
        return resp

    creds = {}
    for field in PLATFORM_FIELDS[platform]:
        creds[field] = form.get(field, "")

    account_name = creds.get("handle") or creds.get("username") or creds.get("page_id") or platform

    db = get_db()
    with db.Session() as session:
        existing = session.query(SocialAccount).filter_by(platform=platform).first()
        if existing:
            existing.credentials_json = json.dumps(creds)
            existing.account_name = account_name
            existing.is_active = True
            existing.connected_by_id = user.id
            existing.connected_at = datetime.utcnow()
        else:
            sa = SocialAccount(
                platform=platform,
                account_name=account_name,
                credentials_json=json.dumps(creds),
                connected_by_id=user.id,
            )
            session.add(sa)
        session.commit()

    resp = RedirectResponse("/admin/social", status_code=303)
    _flash(resp, f"{platform.title()} connected!")
    return resp


@app.post("/admin/social/{account_id}/disconnect")
async def admin_social_disconnect(request: Request, account_id: int):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    db = get_db()
    with db.Session() as session:
        acct = session.query(SocialAccount).filter_by(id=account_id).first()
        if acct:
            acct.is_active = False
            session.commit()

    resp = RedirectResponse("/admin/social", status_code=303)
    _flash(resp, "Account disconnected")
    return resp


# ─── Admin: Announcements ─────────────────────────────────────────────────────

@app.get("/admin/announcements", response_class=HTMLResponse)
async def admin_announcements_page(request: Request):
    user = require_login(request)
    if not has_role(user, "editor"):
        return RedirectResponse("/login", status_code=303)

    db = get_db()
    with db.Session() as session:
        announcements = session.query(Announcement).order_by(Announcement.created_at.desc()).all()
        ann_list = []
        for a in announcements:
            creator = None
            if a.created_by_id:
                creator = session.query(User).filter_by(id=a.created_by_id).first()
            ann_list.append({
                "id": a.id,
                "title": a.title,
                "body": a.body,
                "created_at": a.created_at,
                "scheduled_for": a.scheduled_for,
                "posted": a.posted,
                "posted_at": a.posted_at,
                "creator_name": creator.display_name if creator else "Unknown",
            })

    ctx = _base_context(request, announcements=ann_list)
    resp = templates.TemplateResponse("admin/announcements.html", ctx)
    return _clear_flash(resp)


@app.post("/admin/announcements")
async def admin_announcements_create(
    request: Request,
    title: str = Form(...),
    body: str = Form(...),
    scheduled_for: str = Form(""),
):
    user = require_login(request)
    if not has_role(user, "editor"):
        return RedirectResponse("/login", status_code=303)

    sched = None
    if scheduled_for:
        try:
            sched = datetime.fromisoformat(scheduled_for)
        except ValueError:
            pass

    db = get_db()
    with db.Session() as session:
        a = Announcement(
            title=title,
            body=body,
            created_by_id=user.id,
            scheduled_for=sched,
        )
        session.add(a)
        session.commit()

    resp = RedirectResponse("/admin/announcements", status_code=303)
    _flash(resp, "Announcement created!")
    return resp


# ─── Admin: Data Sources ──────────────────────────────────────────────────────

@app.get("/admin/sources", response_class=HTMLResponse)
async def admin_sources_page(request: Request):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    db = get_db()
    with db.Session() as session:
        sources = session.query(DataSource).order_by(DataSource.created_at.desc()).all()
        # Eagerly load keyword_filters
        for src in sources:
            _ = src.keyword_filters  # force load
        for src in sources:
            session.expunge(src)

    ctx = _base_context(request, sources=sources)
    resp = templates.TemplateResponse("admin/sources.html", ctx)
    return _clear_flash(resp)


@app.post("/admin/sources")
async def admin_sources_create(
    request: Request,
    name: str = Form(...),
    source_type: str = Form(...),
    url: str = Form(""),
    priority: int = Form(2),
    check_interval: int = Form(30),
):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    db = get_db()
    with db.Session() as session:
        src = DataSource(
            name=name,
            source_type=source_type,
            url=url or None,
            priority=priority,
            check_interval=check_interval * 60,  # convert to seconds
            is_enabled=True,
            created_by_id=user.id,
        )
        session.add(src)
        session.commit()

    resp = RedirectResponse("/admin/sources", status_code=303)
    _flash(resp, f"Source '{name}' created!")
    return resp


@app.post("/admin/sources/{source_id}/toggle")
async def admin_sources_toggle(request: Request, source_id: int):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    db = get_db()
    with db.Session() as session:
        src = session.query(DataSource).filter_by(id=source_id).first()
        if src:
            src.is_enabled = not src.is_enabled
            session.commit()

    resp = RedirectResponse("/admin/sources", status_code=303)
    _flash(resp, "Source updated")
    return resp


@app.post("/admin/sources/{source_id}/delete")
async def admin_sources_delete(request: Request, source_id: int):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    db = get_db()
    with db.Session() as session:
        src = session.query(DataSource).filter_by(id=source_id).first()
        if src:
            # Delete associated keyword filters first
            session.query(KeywordFilter).filter_by(data_source_id=source_id).delete()
            session.delete(src)
            session.commit()

    resp = RedirectResponse("/admin/sources", status_code=303)
    _flash(resp, "Source deleted")
    return resp


@app.post("/admin/sources/{source_id}/keywords")
async def admin_sources_add_keyword(
    request: Request,
    source_id: int,
    keyword: str = Form(...),
    filter_type: str = Form(...),
):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    if filter_type not in ("must_include", "at_least_one", "exclude"):
        resp = RedirectResponse("/admin/sources", status_code=303)
        _flash(resp, "Invalid filter type", "error")
        return resp

    db = get_db()
    with db.Session() as session:
        kw = KeywordFilter(
            data_source_id=source_id,
            keyword=keyword.strip(),
            filter_type=filter_type,
        )
        session.add(kw)
        session.commit()

    resp = RedirectResponse("/admin/sources", status_code=303)
    _flash(resp, f"Keyword '{keyword}' added")
    return resp


@app.post("/admin/sources/{source_id}/keywords/{keyword_id}/delete")
async def admin_sources_delete_keyword(request: Request, source_id: int, keyword_id: int):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    db = get_db()
    with db.Session() as session:
        kw = session.query(KeywordFilter).filter_by(id=keyword_id, data_source_id=source_id).first()
        if kw:
            session.delete(kw)
            session.commit()

    resp = RedirectResponse("/admin/sources", status_code=303)
    _flash(resp, "Keyword removed")
    return resp


# ─── Admin: Post Queue ────────────────────────────────────────────────────────

@app.get("/admin/queue", response_class=HTMLResponse)
async def admin_queue_page(request: Request):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    db = get_db()
    with db.Session() as session:
        pending_items = (
            session.query(PostQueue)
            .filter(PostQueue.status == 'pending')
            .order_by(PostQueue.created_at.desc())
            .all()
        )
        recent_posts = (
            session.query(PostQueue)
            .filter(PostQueue.status == 'posted')
            .order_by(PostQueue.posted_at.desc())
            .limit(20)
            .all()
        )
        failed_items = (
            session.query(PostQueue)
            .filter(PostQueue.status == 'failed')
            .order_by(PostQueue.created_at.desc())
            .all()
        )

        # Stats
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        posted_today = (
            session.query(func.count(PostQueue.id))
            .filter(PostQueue.status == 'posted', PostQueue.posted_at >= today_start)
            .scalar() or 0
        )

        # Drip rate: posts in last hour
        hour_ago = datetime.utcnow() - timedelta(hours=1)
        drip_rate = (
            session.query(func.count(PostQueue.id))
            .filter(PostQueue.status == 'posted', PostQueue.posted_at >= hour_ago)
            .scalar() or 0
        )

    queue_stats = {
        "pending": len(pending_items),
        "posted_today": posted_today,
        "failed": len(failed_items),
        "drip_rate": drip_rate,
    }

    ctx = _base_context(
        request,
        pending_items=pending_items,
        recent_posts=recent_posts,
        failed_items=failed_items,
        queue_stats=queue_stats,
    )
    resp = templates.TemplateResponse("admin/queue.html", ctx)
    return _clear_flash(resp)


@app.post("/admin/queue/{item_id}/post-now")
async def admin_queue_post_now(request: Request, item_id: int):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    db = get_db()
    with db.Session() as session:
        item = session.query(PostQueue).filter_by(id=item_id).first()
        if item and item.status in ('pending', 'failed'):
            item.status = 'posted'
            item.posted_at = datetime.utcnow()
            item.error_message = None
            session.commit()

    resp = RedirectResponse("/admin/queue", status_code=303)
    _flash(resp, "Item marked as posted")
    return resp


@app.post("/admin/queue/{item_id}/cancel")
async def admin_queue_cancel(request: Request, item_id: int):
    user = require_login(request)
    if not has_role(user, "admin"):
        return RedirectResponse("/login", status_code=303)

    db = get_db()
    with db.Session() as session:
        item = session.query(PostQueue).filter_by(id=item_id).first()
        if item and item.status == 'pending':
            item.status = 'cancelled'
            session.commit()

    resp = RedirectResponse("/admin/queue", status_code=303)
    _flash(resp, "Item cancelled")
    return resp


# ─── RSS Feed ──────────────────────────────────────────────────────────────────

@app.get("/feed.xml")
async def rss_feed(request: Request):
    from feedgen.feed import FeedGenerator

    city_config = load_city_config_safe()
    city_name = city_config.get("name", "CityBot2")
    base_url = get_base_url(request)

    fg = FeedGenerator()
    fg.title(f"{city_name} - CityBot2 Feed")
    fg.link(href=base_url, rel="alternate")
    fg.link(href=f"{base_url}/feed.xml", rel="self")
    fg.description(f"Latest updates from {city_name} via CityBot2")
    fg.language("en")

    db = get_db()
    with db.Session() as session:
        # Recent weather
        reports = (
            session.query(WeatherReport)
            .order_by(WeatherReport.timestamp.desc())
            .limit(10)
            .all()
        )
        for r in reports:
            fe = fg.add_entry()
            fe.id(f"{base_url}/weather#report-{r.id}")
            fe.title(f"Weather Update: {r.temperature}F" if r.temperature else "Weather Update")
            fe.description(r.forecast or "No forecast available")
            fe.link(href=f"{base_url}/weather")
            if r.timestamp:
                fe.published(r.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"))
                fe.updated(r.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"))

        # Recent earthquakes
        quakes = (
            session.query(Earthquake)
            .order_by(Earthquake.timestamp.desc())
            .limit(10)
            .all()
        )
        for q in quakes:
            fe = fg.add_entry()
            fe.id(f"{base_url}/earthquakes#eq-{q.id}")
            fe.title(f"M{q.magnitude} Earthquake - {q.location}" if q.magnitude else "Earthquake")
            fe.description(f"Magnitude {q.magnitude} at depth {q.depth}km near {q.location}")
            fe.link(href=f"{base_url}/earthquakes")
            if q.timestamp:
                fe.published(q.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"))
                fe.updated(q.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"))

        # Recent news
        articles = (
            session.query(NewsArticle)
            .order_by(NewsArticle.timestamp.desc())
            .limit(10)
            .all()
        )
        for a in articles:
            fe = fg.add_entry()
            fe.id(f"{base_url}/news#article-{a.id}")
            fe.title(a.title or "News Article")
            fe.description(a.content_snippet or "")
            fe.link(href=a.url or f"{base_url}/news")
            ts = a.published_date or a.timestamp
            if ts:
                fe.published(ts.strftime("%Y-%m-%dT%H:%M:%SZ"))
                fe.updated(ts.strftime("%Y-%m-%dT%H:%M:%SZ"))

        # Announcements
        anns = (
            session.query(Announcement)
            .filter_by(posted=True)
            .order_by(Announcement.created_at.desc())
            .limit(10)
            .all()
        )
        for ann in anns:
            fe = fg.add_entry()
            fe.id(f"{base_url}/admin/announcements#ann-{ann.id}")
            fe.title(ann.title)
            fe.description(ann.body)
            fe.link(href=base_url)
            if ann.created_at:
                fe.published(ann.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"))
                fe.updated(ann.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"))

    xml = fg.rss_str(pretty=True)
    return Response(content=xml, media_type="application/rss+xml")


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _get_posting_stats(session) -> Dict[str, Any]:
    """Compute posting statistics."""
    cutoff_30d = datetime.utcnow() - timedelta(days=30)
    cutoff_24h = datetime.utcnow() - timedelta(hours=24)

    total = (
        session.query(func.count(PostHistory.id))
        .filter(PostHistory.timestamp >= cutoff_30d)
        .scalar() or 0
    )

    total_24h = (
        session.query(func.count(PostHistory.id))
        .filter(PostHistory.timestamp >= cutoff_24h)
        .scalar() or 0
    )

    platform_counts = dict(
        session.query(PostHistory.platform, func.count(PostHistory.id))
        .filter(PostHistory.timestamp >= cutoff_30d)
        .group_by(PostHistory.platform)
        .all()
    )

    type_counts = dict(
        session.query(PostHistory.item_type, func.count(PostHistory.id))
        .filter(PostHistory.timestamp >= cutoff_30d)
        .group_by(PostHistory.item_type)
        .all()
    )

    return {
        "total_30d": total,
        "total_24h": total_24h,
        "daily_avg": round(total / 30, 1) if total else 0,
        "by_platform": platform_counts,
        "by_type": type_counts,
    }


# ─── Entry point ───────────────────────────────────────────────────────────────

def main():
    """Run the web dashboard."""
    import uvicorn
    uvicorn.run(
        "web.app:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
