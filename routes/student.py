from datetime import date, datetime
from flask import render_template, request, redirect, url_for, flash, session, abort
from sqlalchemy import or_

from database import db
from models import (
    User, Course, Examination, ExaminationSlot, Booking,
    Evaluation, EvaluationMark, StudentProfile, Resource, Announcement
)
from helpers import role_required, create_notification


def register_student_routes(app):
    @app.route("/student_dashboard")
    @role_required("Student")
    def student_dashboard():

        student_id = session["user_id"]

        bookings = Booking.query.filter_by(
            student_id=student_id,
            status="Booked"
        ).all()

        total_bookings = len(bookings)
        upcoming_examinations = len([b for b in bookings if b.slot.date >= date.today().isoformat()])
        completed_examinations = Booking.query.filter_by(
            student_id=student_id,
            status="Completed"
        ).count()

        evaluations = Evaluation.query.join(
            Booking,
            Evaluation.booking_id == Booking.id
        ).filter(
            Booking.student_id == student_id,
            Evaluation.status == "Completed"
        ).all()

        announcements = Announcement.query.filter(
            or_(Announcement.target_role == "All", Announcement.target_role == "Student")
        ).order_by(Announcement.id.desc()).limit(5).all()

        scores = [e.marks for e in evaluations if e.marks is not None]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0
        highest_score = max(scores) if scores else 0

        return render_template(
            "student_dashboard.html",
            total_bookings=total_bookings,
            upcoming_examinations=upcoming_examinations,
            completed_examinations=completed_examinations,
            evaluations=evaluations,
            announcements=announcements,
            avg_score=avg_score,
            highest_score=highest_score
        )


    @app.route("/student/profile", methods=["GET", "POST"])
    @role_required("Student")
    def student_profile():

        student_id = session["user_id"]

        student = User.query.get_or_404(student_id)
        profile = StudentProfile.query.filter_by(user_id=student_id).first()
        if profile is None:
            profile = StudentProfile(user_id=student_id)
            db.session.add(profile)
            db.session.commit()

        if request.method == "POST":

            name = request.form.get("name")
            email = request.form.get("email")
            roll_number = request.form.get("roll_number")
            department = request.form.get("department")
            year = request.form.get("year")
            phone = request.form.get("phone")

            if not name or not name.strip():
                flash("Name is required.")
                return redirect(url_for("student_profile"))

            if not email or not email.strip():
                flash("Email is required.")
                return redirect(url_for("student_profile"))

            existing_user = User.query.filter(
                User.email == email,
                User.id != student_id
            ).first()

            if existing_user:
                flash("This email is already registered.")
                return redirect(url_for("student_profile"))

            student.name = name.strip()
            student.email = email.strip()
            profile.roll_number = roll_number.strip() if roll_number else None
            profile.department = department.strip() if department else None
            profile.year = year.strip() if year else None
            profile.phone = phone.strip() if phone else None

            db.session.commit()

            session["user_name"] = student.name

            flash("Profile saved.")

            return redirect(url_for("student_profile"))

        return render_template(
            "student_profile.html",
            student=student,
            profile=profile
        )


    @app.route("/student/examinations")
    @role_required("Student")
    def student_examinations():
        search = request.args.get("search", "").strip()

        query = Examination.query.filter_by(booking_open=True)

        if search:
            if search.isdigit():
                query = query.filter(
                    or_(
                        Examination.name.ilike("%" + search + "%"),
                        Examination.id == int(search)
                    )
                )
            else:
                query = query.filter(
                    Examination.name.ilike("%" + search + "%")
                )

        examinations = query.all()

        return render_template(
            "student_examinations.html",
            examinations=examinations,
            search=search
        )


    @app.route("/student/examinations/<int:examination_id>")
    @role_required("Student")
    def student_examination_slots(examination_id):
        examination = Examination.query.get_or_404(examination_id)

        slots = ExaminationSlot.query.filter_by(
            examination_id=examination_id
        ).filter(
            ExaminationSlot.date >= date.today().isoformat()
        ).all()

        available_slots = []

        for slot in slots:
            booked_count = Booking.query.filter_by(
                slot_id=slot.id,
                status="Booked"
            ).count()

            remaining_seats = slot.capacity - booked_count

            if remaining_seats > 0:
                available_slots.append({
                    "slot": slot,
                    "remaining_seats": remaining_seats
                })

        return render_template(
            "student_slots.html",
            examination=examination,
            available_slots=available_slots
        )


    @app.route("/student/book-slot/<int:slot_id>", methods=["POST"])
    @role_required("Student")
    def student_book_slot(slot_id):
        student_id = session["user_id"]

        slot = ExaminationSlot.query.get_or_404(slot_id)
        examination = Examination.query.get_or_404(slot.examination_id)

        if not examination.booking_open:
            flash("Booking for this examination is closed.", "danger")
            return redirect(url_for(
                "student_examination_slots",
                examination_id=examination.id
            ))

        if slot.date < date.today().isoformat():
            flash("You cannot book a slot in the past.", "danger")
            return redirect(url_for(
                "student_examination_slots",
                examination_id=examination.id
            ))

        existing_booking = Booking.query.join(
            ExaminationSlot,
            Booking.slot_id == ExaminationSlot.id
        ).filter(
            Booking.student_id == student_id,
            Booking.status == "Booked",
            ExaminationSlot.examination_id == examination.id
        ).first()

        if existing_booking:
            flash(
                "You have already booked a slot for this examination.",
                "warning"
            )
            return redirect(url_for(
                "student_examination_slots",
                examination_id=examination.id
            ))

        booked_count = Booking.query.filter_by(
            slot_id=slot.id,
            status="Booked"
        ).count()

        if booked_count >= slot.capacity:
            flash("This slot is already full.", "danger")
            return redirect(url_for(
                "student_examination_slots",
                examination_id=examination.id
            ))

        booking = Booking(
            student_id=student_id,
            slot_id=slot.id,
            status="Booked"
        )

        db.session.add(booking)
        db.session.commit()

        create_notification(
            user_id=student_id,
            title="Booking Confirmed",
            message=f"You booked {slot.examination.name} on {slot.date} at {slot.time} (Examiner: {slot.examiner.name}).",
            category="success"
        )
        db.session.commit()

        flash("Slot booked!", "success")

        return redirect(url_for("student_bookings"))


    @app.route("/student/bookings")
    @role_required("Student")
    def student_bookings():
        bookings = Booking.query.filter_by(
            student_id=session["user_id"],
            status="Booked"
        ).all()

        return render_template(
            "student_bookings.html",
            bookings=bookings
        )


    @app.route("/student/cancel-booking/<int:booking_id>", methods=["POST"])
    @role_required("Student")
    def student_cancel_booking(booking_id):

        booking = Booking.query.filter_by(
            id=booking_id,
            student_id=session["user_id"]
        ).first_or_404()

        if booking.status != "Booked":
            flash("This booking cannot be cancelled.", "danger")
            return redirect(url_for("student_bookings"))

        examination = booking.slot.examination

        if examination.booking_end:
            if date.today().isoformat() > examination.booking_end:
                flash(
                    "The cancellation deadline has passed.",
                    "danger"
                )
                return redirect(url_for("student_bookings"))

        booking.status = "Cancelled"
        create_notification(
            user_id=booking.student_id,
            title="Booking Cancelled",
            message=f"Your booking for {booking.slot.examination.name} on {booking.slot.date} has been cancelled.",
            category="warning"
        )
        db.session.commit()

        flash("Booking cancelled.", "success")

        return redirect(url_for("student_bookings"))


    @app.route("/student/upcoming")
    @role_required("Student")
    def student_upcoming():

        bookings = Booking.query.filter_by(
            student_id=session["user_id"],
            status="Booked"
        ).all()

        upcoming_bookings = []

        for booking in bookings:
            if booking.slot.date >= date.today().isoformat():
                upcoming_bookings.append(booking)

        return render_template(
            "student_upcoming.html",
            bookings=upcoming_bookings
        )


    @app.route("/student/history")
    @role_required("Student")
    def student_history():

        bookings = Booking.query.filter_by(
            student_id=session["user_id"]
        ).all()

        history_bookings = []

        for booking in bookings:
            if booking.status in ["Completed", "Cancelled"]:
                history_bookings.append(booking)

            elif booking.slot.date < date.today().isoformat():
                history_bookings.append(booking)

        return render_template(
            "student_history.html",
            bookings=history_bookings
        )


    @app.route("/student/results")
    @role_required("Student")
    def student_results():

        evaluations = Evaluation.query.join(
            Booking,
            Evaluation.booking_id == Booking.id
        ).filter(
            Booking.student_id == session["user_id"],
            Evaluation.status == "Completed"
        ).all()

        return render_template(
            "student_results.html",
            evaluations=evaluations
        )


    @app.route("/student/calendar")
    @role_required("Student")
    def student_calendar():
        student_id = session["user_id"]

        my_bookings = Booking.query.filter_by(
            student_id=student_id,
            status="Booked"
        ).all()

        upcoming_slots = ExaminationSlot.query.join(
            Examination
        ).filter(
            ExaminationSlot.date >= date.today().isoformat()
        ).all()

        calendar_events = []
        for b in my_bookings:
            calendar_events.append({
                "title": f"My Exam: {b.slot.examination.name}",
                "date": b.slot.date,
                "time": b.slot.time,
                "examiner": b.slot.examiner.name,
                "is_booked": True,
                "status": b.status
            })

        for s in upcoming_slots:
            if not any(b.slot_id == s.id for b in my_bookings):
                calendar_events.append({
                    "title": f"Slot: {s.examination.name}",
                    "date": s.date,
                    "time": s.time,
                    "examiner": s.examiner.name,
                    "is_booked": False,
                    "status": "Available"
                })

        return render_template(
            "student_calendar.html",
            calendar_events=calendar_events
        )


    @app.route("/student/result/<int:evaluation_id>/report")
    @role_required("Student")
    def download_result_report(evaluation_id):
        student_id = session["user_id"]
        evaluation = Evaluation.query.get_or_404(evaluation_id)

        if evaluation.booking.student_id != student_id:
            abort(403)

        student = evaluation.booking.student
        examination = evaluation.booking.slot.examination
        rubric_marks = EvaluationMark.query.filter_by(evaluation_id=evaluation.id).all()
        total_rubric_possible = sum(r.rubric.marks for r in rubric_marks if r.rubric)

        return render_template(
            "result_report.html",
            evaluation=evaluation,
            student=student,
            examination=examination,
            rubric_marks=rubric_marks,
            total_rubric_possible=total_rubric_possible,
            generated_at=datetime.now().strftime("%d %B %Y, %H:%M")
        )


    @app.route("/student/resources")
    @role_required("Student")
    def student_resources():
        resources = Resource.query.all()
        courses = Course.query.all()
        examinations = Examination.query.all()

        return render_template(
            "student_resources.html",
            resources=resources,
            courses=courses,
            examinations=examinations
        )
