from functools import wraps
from datetime import date, datetime
from flask import redirect, url_for, session, abort
from database import db
from models import User, Notification


def role_required(required_role):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))

            user = User.query.get(session["user_id"])
            if not user or not user.is_active:
                session.clear()
                return redirect(url_for("login"))

            if user.role != required_role:
                abort(403)

            if user.role == "Examiner" and not user.is_approved:
                session.clear()
                return redirect(url_for("login"))

            return fn(*args, **kwargs)
        return wrapper
    return decorator


def create_notification(user_id, title, message, category="info"):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    notif = Notification(
        user_id=user_id,
        title=title,
        message=message,
        category=category,
        created_at=now_str
    )
    db.session.add(notif)


def update_examination_status(examination):
    today = date.today().isoformat()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")

    if examination.status == "Completed":
        return

    if examination.slot_creation_start and examination.slot_creation_end:
        if examination.slot_creation_start <= now <= examination.slot_creation_end:
            examination.slot_creation_open = True
            examination.status = "Slot Creation"
        elif now > examination.slot_creation_end:
            examination.slot_creation_open = False

    if examination.booking_start and examination.booking_end:
        if examination.booking_start <= now <= examination.booking_end:
            examination.booking_open = True
            examination.status = "Booking Open"
        elif now > examination.booking_end:
            examination.booking_open = False
            examination.status = "Closed"

    if examination.booking_open:
        examination.status = "Booking Open"
    elif examination.slot_creation_open:
        examination.status = "Slot Creation"

    if examination.slots:
        all_passed = True
        for slot in examination.slots:
            if slot.date >= today:
                all_passed = False
                break
            for booking in slot.bookings:
                if booking.status not in ["Completed", "Cancelled"]:
                    all_passed = False
                    break
        if all_passed:
            examination.status = "Completed"
            examination.booking_open = False
            examination.slot_creation_open = False

    db.session.commit()
