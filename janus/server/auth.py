"""Authentication helpers: password hashing, JWT tokens, email verification.

Email sending uses ``smtplib``.  Configure via environment variables::

    JANUS_SMTP_HOST      – SMTP server   (default: smtp.gmail.com)
    JANUS_SMTP_PORT      – SMTP port     (default: 587)
    JANUS_SMTP_USER      – login user    (required for real sending)
    JANUS_SMTP_PASSWORD  – login password / app-password
    JANUS_SMTP_FROM      – From address  (defaults to SMTP_USER)

If ``JANUS_SMTP_USER`` is *not* set the mailer falls back to a console stub
so that tests and local dev work without an SMTP server.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import bcrypt
import jwt

# Load .env from the project root (two levels up from this file)
_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path)

# ── secrets ───────────────────────────────────────────────────────────────────
# In production, load these from env vars or a vault.

SECRET_KEY: str = os.environ.get("JANUS_SECRET_KEY", "change-me-in-production")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRY_SECONDS: int = 3600  # 1 hour
EMAIL_VERIFY_MAX_AGE: int = 3600  # 1 hour

_serializer = URLSafeTimedSerializer(SECRET_KEY)


# ── password hashing (bcrypt) ─────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Return a bcrypt hash of *password*."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, password_hash: str) -> bool:
    """Return True if *password* matches *password_hash*."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# ── email-verification tokens (itsdangerous) ─────────────────────────────────

def create_email_token(email: str) -> str:
    """Create a signed, time-limited token that encodes *email*."""
    return _serializer.dumps(email, salt="email-verify")


def verify_email_token(token: str) -> str:
    """Decode and validate the email-verification token.

    Returns the email address on success.

    Raises:
        ValueError – token is expired or tampered with.
    """
    try:
        email: str = _serializer.loads(
            token, salt="email-verify", max_age=EMAIL_VERIFY_MAX_AGE
        )
        return email
    except (BadSignature, SignatureExpired) as exc:
        raise ValueError(f"Invalid or expired verification token: {exc}")


# ── JWT bearer tokens ────────────────────────────────────────────────────────

def create_jwt(user_id: str, email: str) -> str:
    """Issue a JWT with the user's id and email as claims."""
    payload = {
        "sub": user_id,
        "email": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    """Decode and validate a JWT.

    Returns the payload dict on success.

    Raises:
        ValueError – token is invalid or expired.
    """
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidTokenError as exc:
        raise ValueError(f"Invalid token: {exc}")


# ── SMTP configuration ────────────────────────────────────────────────────────

SMTP_HOST: str = os.environ.get("JANUS_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.environ.get("JANUS_SMTP_PORT", "587"))
SMTP_USER: str | None = os.environ.get("JANUS_SMTP_USER")  # None → stub mode
SMTP_PASSWORD: str | None = os.environ.get("JANUS_SMTP_PASSWORD")
SMTP_FROM: str = os.environ.get("JANUS_SMTP_FROM", SMTP_USER or "noreply@example.com")


# ── email sending ─────────────────────────────────────────────────────────────

# Captured emails – always recorded so tests can inspect them regardless of
# whether real SMTP is enabled.
_sent_emails: list[dict] = []


def _build_verification_message(to: str, token: str) -> MIMEMultipart:
    """Build a MIME email with both plain-text and HTML bodies."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Verify your Janus email address"
    msg["From"] = SMTP_FROM
    msg["To"] = to

    text_body = (
        "Welcome to Janus!\n\n"
        "Please verify your email using the token below:\n\n"
        f"  {token}\n\n"
        "This token will expire in 1 hour.\n"
    )
    html_body = (
        "<html><body>"
        "<h2>Welcome to Janus!</h2>"
        "<p>Please verify your email using the token below:</p>"
        f"<p><code>{token}</code></p>"
        "<p>This token will expire in 1 hour.</p>"
        "</body></html>"
    )

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    return msg


def send_verification_email(email: str, token: str) -> None:
    """Send a verification email containing the verification token.

    * If ``JANUS_SMTP_USER`` is configured, the email is sent via SMTP
      (TLS on the configured host/port).
    * Otherwise the email is only logged to stdout (stub mode for local
      dev and tests).

    In **both** cases the email is recorded in ``_sent_emails`` so tests
    can assert on it.
    """
    record = {"to": email, "token": token}
    _sent_emails.append(record)

    if SMTP_USER:
        msg = _build_verification_message(email, token)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD or "")
            server.sendmail(SMTP_FROM, email, msg.as_string())
        print(f"[EMAIL] Sent verification email to {email} via {SMTP_HOST}:{SMTP_PORT}")
    else:
        # Stub mode – just log to console
        print(f"[EMAIL-STUB] To: {email}")
        print(f"[EMAIL-STUB] Verification token: {token}")


def get_sent_emails() -> list[dict]:
    """Return the list of emails sent (for testing)."""
    return _sent_emails


def clear_sent_emails() -> None:
    """Clear the captured email list (call between tests)."""
    _sent_emails.clear()
