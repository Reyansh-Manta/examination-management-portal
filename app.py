import os
from flask import Flask, session, redirect, url_for, flash
from database import db
from models import Notification

from routes.main import register_main_routes
from routes.auth import register_auth_routes
from routes.admin import register_admin_routes
from routes.examiner import register_examiner_routes
from routes.student import register_student_routes

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///examination.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "tfcviyhcv97tufv976ft76g768g86guyvu"

db.init_app(app)

with app.app_context():
    db.create_all()

register_main_routes(app)
register_auth_routes(app)
register_admin_routes(app)
register_examiner_routes(app)
register_student_routes(app)


@app.context_processor
def inject_global_data():
    unread_count = 0
    if "user_id" in session:
        unread_count = Notification.query.filter_by(
            user_id=session["user_id"],
            is_read=False,
        ).count()
    return {"unread_notifications_count": unread_count}


@app.errorhandler(403)
def handle_forbidden(e):
    flash("You do not have permission to access that page.", "warning")
    if "user_id" in session:
        role = session.get("role")
        if role == "Admin":
            return redirect(url_for("admin_dashboard"))
        elif role == "Examiner":
            return redirect(url_for("examiner_dashboard"))
        elif role == "Student":
            return redirect(url_for("student_dashboard"))
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, host="127.0.0.1", port=port)
