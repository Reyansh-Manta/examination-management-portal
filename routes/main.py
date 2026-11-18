from datetime import datetime
from flask import render_template, request, redirect, url_for, flash, session, abort
from sqlalchemy import or_

from database import db
from models import (
    User, Examination, ExaminationSlot, Booking,
    Evaluation, Notification, Announcement
)
from helpers import role_required, create_notification


def register_main_routes(app):

    @app.route("/")
    def index():
        if "user_id" in session:
            user = User.query.get(session["user_id"])
            if user and user.is_active:
                if user.role == "Admin":
                    return redirect(url_for("admin_dashboard"))
                elif user.role == "Examiner":
                    if user.is_approved:
                        return redirect(url_for("examiner_dashboard"))
                    else:
                        session.clear()
                        flash("Your account is waiting for Admin approval.", "info")
                        return redirect(url_for("login"))
                elif user.role == "Student":
                    return redirect(url_for("student_dashboard"))
            else:
                session.clear()
                return redirect(url_for("login"))

        return redirect(url_for("login"))

    @app.route("/notifications")
    def notifications_view():
        if "user_id" not in session:
            return redirect(url_for("login"))

        user_id = session["user_id"]
        notifications = Notification.query.filter_by(user_id=user_id).order_by(Notification.id.desc()).all()

        for n in notifications:
            n.is_read = True
        db.session.commit()

        return render_template(
            "notifications.html",
            notifications=notifications
        )

    @app.route("/announcements", methods=["GET", "POST"])
    def announcements_view():
        if "user_id" not in session:
            return redirect(url_for("login"))

        role = session.get("role")

        if request.method == "POST":
            if role != "Admin":
                abort(403)

            title = request.form.get("title")
            content = request.form.get("content")
            target_role = request.form.get("target_role", "All")

            if not title or not content:
                flash("Announcement title and content are required.", "danger")
                return redirect(url_for("announcements_view"))

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            announcement = Announcement(
                title=title.strip(),
                content=content.strip(),
                target_role=target_role,
                created_by=session["user_id"],
                created_at=now_str
            )
            db.session.add(announcement)
            db.session.commit()

            target_users = []
            if target_role == "All":
                target_users = User.query.filter(User.role != "Admin").all()
            else:
                target_users = User.query.filter_by(role=target_role).all()

            for u in target_users:
                create_notification(
                    user_id=u.id,
                    title=f"Announcement: {title.strip()}",
                    message=content.strip()[:180] + "...",
                    category="info"
                )
            db.session.commit()

            flash("Announcement published.", "success")
            return redirect(url_for("announcements_view"))

        if role == "Admin":
            announcements = Announcement.query.order_by(Announcement.id.desc()).all()
        else:
            announcements = Announcement.query.filter(
                or_(Announcement.target_role == "All", Announcement.target_role == role)
            ).order_by(Announcement.id.desc()).all()

        return render_template(
            "announcements.html",
            announcements=announcements
        )

    @app.route("/announcement/delete/<int:announcement_id>", methods=["POST"])
    @role_required("Admin")
    def delete_announcement(announcement_id):
        announcement = Announcement.query.get_or_404(announcement_id)
        db.session.delete(announcement)
        db.session.commit()
        flash("Announcement deleted.", "info")
        return redirect(url_for("announcements_view"))

    @app.route("/analytics")
    def performance_analytics():
        if "user_id" not in session:
            return redirect(url_for("login"))

        role = session.get("role")
        evaluations = Evaluation.query.filter_by(status="Completed").all()

        scores = [e.marks for e in evaluations if e.marks is not None]
        avg_marks = round(sum(scores) / len(scores), 1) if scores else 0
        highest_marks = max(scores) if scores else 0
        lowest_marks = min(scores) if scores else 0
        total_evaluations = len(scores)

        exam_stats = []
        examinations = Examination.query.all()
        for exam in examinations:
            exam_evals = Evaluation.query.join(
                Booking, Evaluation.booking_id == Booking.id
            ).join(
                ExaminationSlot, Booking.slot_id == ExaminationSlot.id
            ).filter(
                ExaminationSlot.examination_id == exam.id,
                Evaluation.status == "Completed"
            ).all()

            exam_scores = [ev.marks for ev in exam_evals if ev.marks is not None]
            exam_avg = round(sum(exam_scores) / len(exam_scores), 1) if exam_scores else 0
            exam_high = max(exam_scores) if exam_scores else 0
            exam_low = min(exam_scores) if exam_scores else 0

            grades = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
            for s in exam_scores:
                if s >= 85:
                    grades["A"] += 1
                elif s >= 70:
                    grades["B"] += 1
                elif s >= 50:
                    grades["C"] += 1
                elif s >= 40:
                    grades["D"] += 1
                else:
                    grades["F"] += 1

            exam_stats.append({
                "examination": exam,
                "attempts": len(exam_scores),
                "avg": exam_avg,
                "high": exam_high,
                "low": exam_low,
                "grades": grades
            })

        return render_template(
            "analytics.html",
            avg_marks=avg_marks,
            highest_marks=highest_marks,
            lowest_marks=lowest_marks,
            total_evaluations=total_evaluations,
            exam_stats=exam_stats,
            role=role
        )
