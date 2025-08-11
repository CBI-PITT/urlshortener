"""
MiniShort — a tiny, ethical URL shortener built with Flask.

Features
- Create short links
- Optional custom slug
- Optional expiration (date/time) via calendar + time inputs
- "Never expires" checkbox (default ON) that disables date/time until unchecked
- Edit/delete with a per-link secret key
- Optional Google Analytics event on click via GTAG (GTAG_ID)
- **Admin page** to list/search/manage/delete all links (requires ADMIN_TOKEN)
- Stores data in a simple JSON text file (url_db.json)

Run:
    pip install flask python-dotenv
    python app.py

Then open http://127.0.0.1:5000

Security & ethics notes:
- We only allow http/https targets.
- Each link has an unguessable secret key required to edit/delete.
- Admin page is protected by a shared token. For production, prefer SSO or proper auth.
- If exposed publicly, use a reverse proxy with rate limiting.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import string
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv
load_dotenv()

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

APP_TITLE = "MiniShort — simple URL shortener"
DB_PATH = Path(os.environ.get("URL_DB_PATH", "url_db.json"))
BASE_URL = os.environ.get("BASE_URL")  # Optional: e.g., https://sho.rt
GTAG_ID = os.environ.get("GTAG_ID")    # Optional: e.g., G-XXXXXXXXXX
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")  # Required to access /admin

# --- App setup ---
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_urlsafe(32))
_lock = threading.Lock()

# --- Helpers ---
SLUG_ALPHABET = string.ascii_letters + string.digits
SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def dt_to_str(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.astimezone(timezone.utc).isoformat()


def dt_from_str(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        # Accept ISO 8601 with or without timezone, or "YYYY-MM-DD HH:MM"
        if "T" in s:
            dt = datetime.fromisoformat(s)
        else:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


class DB:
    def __init__(self, path: Path):
        self.path = path
        self.data: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text("utf-8"))
            except Exception:
                # Attempt recovery from a partial write
                backup = self.path.with_suffix(".bak")
                if backup.exists():
                    self.data = json.loads(backup.read_text("utf-8"))
                else:
                    self.data = {}
        else:
            self.data = {}

    def _save(self):
        # Atomic-ish write: write to .tmp then rename, keep .bak
        tmp = self.path.with_suffix(".tmp")
        bak = self.path.with_suffix(".bak")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), "utf-8")
        if self.path.exists():
            self.path.replace(bak)
        tmp.replace(self.path)

    def upsert(self, slug: str, record: dict):
        self.data[slug] = record
        self._save()

    def delete(self, slug: str):
        if slug in self.data:
            del self.data[slug]
            self._save()

    def get(self, slug: str) -> Optional[dict]:
        return self.data.get(slug)

    def exists(self, slug: str) -> bool:
        return slug in self.data

    def all(self):
        # Return newest first
        return sorted(self.data.values(), key=lambda r: r["created_at"], reverse=True)


db = DB(DB_PATH)


def generate_slug(length: int = 6) -> str:
    for _ in range(100):
        slug = "".join(secrets.choice(SLUG_ALPHABET) for _ in range(length))
        if not db.exists(slug):
            return slug
    # fallback: enlarge length
    return generate_slug(length + 1)


def is_valid_url(url: str) -> bool:
    url = (url or "").strip()
    return url.startswith("http://") or url.startswith("https://")


# --- Public routes ---
@app.get("/")
def index():
    return render_template(
        "index.html",
        title=APP_TITLE,
        app_title=APP_TITLE,
        created=None,
    )


@app.post("/create")
def create():
    target = (request.form.get("target") or "").strip()
    slug = (request.form.get("slug") or "").strip()

    never_expires = request.form.get("never_expires")
    expires_date = request.form.get("expires_date") or ""
    # Default time is 00:00 (midnight) when a date is chosen
    expires_time = request.form.get("expires_time") or ("00:00" if expires_date else "")
    expires_raw = (expires_date + ("T" + expires_time if expires_time else "")).strip()

    # Validate target
    if not is_valid_url(target):
        flash("Please provide a target that starts with http:// or https://")
        return render_template("index.html", title=APP_TITLE, app_title=APP_TITLE, created=None)

    # Validate/assign slug
    if slug:
        if not SLUG_RE.match(slug):
            flash("Custom slug must be 3–64 characters of letters, numbers, underscore, or hyphen.")
            return render_template("index.html", title=APP_TITLE, app_title=APP_TITLE, created=None)
        if db.exists(slug):
            flash("That slug is already taken. Try another.")
            return render_template("index.html", title=APP_TITLE, app_title=APP_TITLE, created=None)
    else:
        slug = generate_slug()

    # Parse expiration: if box checked or no date/time -> never expires
    expires_at = None if never_expires else (dt_from_str(expires_raw) if expires_raw else None)
    if (expires_raw and not never_expires) and not expires_at:
        flash("Couldn't parse expiration date/time.")
        return render_template("index.html", title=APP_TITLE, app_title=APP_TITLE, created=None)

    secret_key = secrets.token_urlsafe(16)

    record = {
        "slug": slug,
        "target": target,
        "created_at": dt_to_str(now_utc()),
        "expires_at": dt_to_str(expires_at),
        "secret": secret_key,
        "clicks": 0,
        "last_access": None,
    }

    with _lock:
        db.upsert(slug, record)

    full_url = (BASE_URL.rstrip("/") if BASE_URL else request.host_url.rstrip("/")) + "/" + slug
    created = {**record, "full_url": full_url}

    flash("Short link created. Save your secret key to edit or delete it.")

    return render_template("index.html", title=APP_TITLE, app_title=APP_TITLE, created=created)


@app.get("/manage")
@app.get("/manage/<slug>")
def manage(slug: Optional[str] = None):
    key = request.args.get("key")
    if not slug or not key:
        # Ask for slug+key
        return render_template("manage_select.html", title=f"Manage • {APP_TITLE}", slug=slug, key=key)

    rec = db.get(slug)
    if not rec:
        return render_template("notfound.html", title="Not found"), 404

    if key != rec.get("secret"):
        abort(403)

    # Pre-fill date/time inputs if present
    expires_date_input = ""
    expires_time_input = ""
    if rec.get("expires_at"):
        try:
            dt = datetime.fromisoformat(rec["expires_at"]).astimezone(timezone.utc)
            expires_date_input = dt.strftime("%Y-%m-%d")
            expires_time_input = dt.strftime("%H:%M")
        except Exception:
            expires_date_input = ""
            expires_time_input = ""

    full_url = (BASE_URL.rstrip("/") if BASE_URL else request.host_url.rstrip("/")) + "/" + slug

    return render_template(
        "manage_edit.html",
        title=f"Edit {slug} • {APP_TITLE}",
        slug=slug,
        key=key,
        rec={**rec, "expires_date_input": expires_date_input, "expires_time_input": expires_time_input},
        full_url=full_url,
    )


@app.post("/manage/<slug>")
def manage_post(slug: str):
    key = request.args.get("key")
    rec = db.get(slug)
    if not rec:
        return render_template("notfound.html", title="Not found"), 404
    if key != rec.get("secret"):
        abort(403)

    action = (request.form.get("action") or "update").strip().lower()
    if action == "delete":
        with _lock:
            db.delete(slug)
        flash("Link deleted.")
        return redirect(url_for("index"))

    # Update
    target = (request.form.get("target") or rec["target"]).strip()

    never_expires = request.form.get("never_expires")
    expires_date = request.form.get("expires_date") or ""
    expires_time = request.form.get("expires_time") or ("00:00" if expires_date else "")
    expires_raw = (expires_date + ("T" + expires_time if expires_time else "")).strip()
    expires_at = None if never_expires else (dt_from_str(expires_raw) if expires_raw else None)

    if (expires_raw and not never_expires) and not expires_at:
        flash("Couldn't parse expiration date/time.")
        return redirect(url_for("manage", slug=slug, key=key))

    if not is_valid_url(target):
        flash("Please provide a target that starts with http:// or https://")
        return redirect(url_for("manage", slug=slug, key=key))

    with _lock:
        rec["target"] = target
        rec["expires_at"] = dt_to_str(expires_at)
        db.upsert(slug, rec)

    flash("Changes saved.")
    return redirect(url_for("manage", slug=slug, key=key))


@app.get("/<slug>")
def go(slug: str):
    rec = db.get(slug)
    if not rec:
        return render_template("notfound.html", title="Not found"), 404

    # Check expiration
    if rec.get("expires_at"):
        try:
            exp = datetime.fromisoformat(rec["expires_at"]).astimezone(timezone.utc)
            if now_utc() >= exp:
                return render_template("gone.html", title="Expired"), 410
        except Exception:
            # On parse error, treat as expired to be safe.
            return render_template("gone.html", title="Expired"), 410

    # Increment stats first
    with _lock:
        rec["clicks"] = int(rec.get("clicks", 0)) + 1
        rec["last_access"] = dt_to_str(now_utc())
        db.upsert(slug, rec)

    # If GTAG_ID is configured, render a lightweight page that fires GA and then redirects
    if GTAG_ID:
        return render_template(
            "track_and_redirect.html",
            title="Redirecting…",
            gtag_id=GTAG_ID,
            slug=slug,
            target=rec["target"],
        )

    # Otherwise, redirect immediately
    return redirect(rec["target"], code=302)


# --- Admin routes ---

def _require_admin():
    if not ADMIN_TOKEN:
        abort(403)
    if session.get("is_admin"):
        return
    # Allow token via form or querystring once; then persist in session
    token = request.values.get("token")
    if token and secrets.compare_digest(token, ADMIN_TOKEN):
        session["is_admin"] = True
        return
    abort(403)


@app.get("/admin")
def admin_index():
    _require_admin()
    q = (request.args.get("q") or "").strip().lower()
    items = db.all()
    if q:
        def matches(r: dict) -> bool:
            return (
                q in r.get("slug", "").lower()
                or q in r.get("target", "").lower()
                or q in (r.get("created_at", "") or "").lower()
            )
        items = [r for r in items if matches(r)]

    # Simple counts
    total = len(db.data)
    active = sum(1 for r in db.data.values() if not r.get("expires_at") or now_utc() < datetime.fromisoformat(r["expires_at"]))
    expired = total - active

    return render_template(
        "admin.html",
        title=f"Admin • {APP_TITLE}",
        items=items,
        total=total,
        active=active,
        expired=expired,
        q=q,
    )


@app.post("/admin/delete/<slug>")
def admin_delete(slug: str):
    _require_admin()
    if not db.get(slug):
        flash("No such slug.")
        return redirect(url_for("admin_index"))
    with _lock:
        db.delete(slug)
    flash(f"Deleted {slug}.")
    return redirect(url_for("admin_index"))


@app.get("/admin/impersonate/<slug>")
def admin_impersonate(slug: str):
    """Jump to manage view for a slug using its secret key."""
    _require_admin()
    rec = db.get(slug)
    if not rec:
        flash("No such slug.")
        return redirect(url_for("admin_index"))
    return redirect(url_for("manage", slug=slug, key=rec.get("secret")))


# Optional: simple health check
@app.get("/healthz")
def healthz():
    return {"ok": True, "count": len(db.data)}


if __name__ == "__main__":
    # Ensure DB exists
    if not DB_PATH.exists():
        DB_PATH.write_text("{}", "utf-8")
    app.run(debug=True)