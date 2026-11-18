from datetime import datetime
from flask import render_template, request, redirect, url_for, flash, session, abort
from sqlalchemy import or_

from database import db
from models import (
    User, Examination, ExaminationSlot, Booking,
    ExaminationRubric, Evaluation, ExaminerProfile, EvaluationMark,
    ExaminerUnavailability, Announcement
)
from helpers import role_required, create_notification


def register_examiner_routes(app):
    @app.route("/examiner_dashboard")
    @role_required("Examiner")
    def examiner_dashboard():

        examiner_id = session["user_id"]

        slots = ExaminationSlot.query.filter_by(
            examiner_id=examiner_id
        ).all()

        examinations = set()

        for slot in slots:
            examinations.add(slot.examination_id)

        total_examinations = len(examinations)

        total_slots = len(slots)

        total_bookings = 0

        for slot in slots:
            total_bookings += Booking.query.filter_by(
                slot_id=slot.id,
                status="Booked"
            ).count()

        pending_evaluations = 0

        for slot in slots:

            bookings = Booking.query.filter_by(
                slot_id=slot.id,
                status="Booked"
            ).all()

            for booking in bookings:

                evaluation = Evaluation.query.filter_by(
                    booking_id=booking.id
                ).first()

                if evaluation is None or evaluation.status == "Pending":
                    pending_evaluations += 1

        evaluations = Evaluation.query.filter_by(
            examiner_id=examiner_id,
            status="Completed"
        ).all()

        scores = [e.marks for e in evaluations if e.marks is not None]
        avg_grading = round(sum(scores) / len(scores), 1) if scores else 0
        total_evaluated = len(scores)

        announcements = Announcement.query.filter(
            or_(Announcement.target_role == "All", Announcement.target_role == "Examiner")
        ).order_by(Announcement.id.desc()).limit(5).all()

        return render_template(
            "examiner_dashboard.html",
            examiner=User.query.get(examiner_id),
            total_examinations=total_examinations,
            total_slots=total_slots,
            total_bookings=total_bookings,
            pending_evaluations=pending_evaluations,
            avg_grading=avg_grading,
            total_evaluated=total_evaluated,
            announcements=announcements
        )


    @app.route("/examiner/evaluate/<int:booking_id>", methods=["GET", "POST"])
    @role_required("Examiner")
    def evaluate_student(booking_id):

        examiner_id = session["user_id"]

        booking = Booking.query.get_or_404(booking_id)

        if booking.status != "Booked":
            flash("This booking cannot be evaluated.")
            return redirect(url_for("examiner_bookings"))

        if booking.slot.examiner_id != examiner_id:
            abort(403)

        rubrics = ExaminationRubric.query.filter_by(
            examination_id=booking.slot.examination_id
        ).all()

        if not rubrics:
            flash("No examination rubrics have been created.")
            return redirect(url_for("examiner_bookings"))

        evaluation = Evaluation.query.filter_by(
            booking_id=booking.id
        ).first()

        if request.method == "POST":

            total_marks = 0
            marks_list = []

            for rubric in rubrics:

                marks = request.form.get(
                    "rubric_" + str(rubric.id),
                    type=int
                )

                if marks is None or marks < 0 or marks > rubric.marks:
                    flash("Please enter valid marks for every criterion.")
                    return redirect(
                        url_for("evaluate_student", booking_id=booking.id)
                    )

                total_marks += marks

                marks_list.append((rubric, marks))

            remarks = request.form.get("remarks")

            if evaluation is None:

                evaluation = Evaluation(
                    booking_id=booking.id,
                    examiner_id=examiner_id
                )

                db.session.add(evaluation)
                db.session.flush()

            evaluation.marks = total_marks
            evaluation.remarks = remarks
            evaluation.status = "Completed"
            booking.status = "Completed"

            for rubric, marks in marks_list:

                rubric_mark = EvaluationMark.query.filter_by(
                    evaluation_id=evaluation.id,
                    rubric_id=rubric.id
                ).first()

                if rubric_mark is None:

                    rubric_mark = EvaluationMark(
                        evaluation_id=evaluation.id,
                        rubric_id=rubric.id,
                        marks=marks
                    )

                    db.session.add(rubric_mark)

                else:

                    rubric_mark.marks = marks

            create_notification(
                user_id=booking.student_id,
                title="Result Published",
                message=f"Your evaluation for {booking.slot.examination.name} is complete. Total Score: {total_marks}. Check your Results section for detailed rubric scores.",
                category="success"
            )

            db.session.commit()

            flash("Evaluation recorded.")

            return redirect(url_for("examiner_bookings"))

        marks_by_rubric = {}

        if evaluation:

            saved_marks = EvaluationMark.query.filter_by(
                evaluation_id=evaluation.id
            ).all()

            for saved_mark in saved_marks:
                marks_by_rubric[saved_mark.rubric_id] = saved_mark.marks

        return render_template(
            "evaluate_student.html",
            booking=booking,
            rubrics=rubrics,
            evaluation=evaluation,
            marks_by_rubric=marks_by_rubric
        )


    @app.route("/examiner/bookings")
    @role_required("Examiner")
    def examiner_bookings():

        examiner_id = session["user_id"]

        slots = ExaminationSlot.query.filter_by(
            examiner_id=examiner_id
        ).all()

        bookings = []

        for slot in slots:
            slot_bookings = Booking.query.filter_by(
                slot_id=slot.id,
                status="Booked"
            ).all()

            bookings.extend(slot_bookings)

        return render_template(
            "examiner_bookings.html",
            bookings=bookings
        )


    @app.route("/examiner/slots", methods=["GET", "POST"])
    @role_required("Examiner")
    def examiner_slots():

        examiner_id = session["user_id"]

        if request.method == "POST":

            examination_id = request.form.get("examination_id", type=int)
            slot_date = request.form.get("date")
            time = request.form.get("time")

            examination = Examination.query.get(examination_id)

            if examination is None:
                flash("Please select a valid examination.")
                return redirect(url_for("examiner_slots"))


            if not examination.slot_creation_open:
                flash("Slot creation is currently closed.")
                return redirect(url_for("examiner_slots"))

            now = datetime.now().strftime("%Y-%m-%dT%H:%M")

            if not examination.slot_creation_start or not examination.slot_creation_end:
                flash("Slot creation dates are not configured.")
                return redirect(url_for("examiner_slots"))

            if now < examination.slot_creation_start or now > examination.slot_creation_end:
                flash("You can create slots only during the allowed period.")
                return redirect(url_for("examiner_slots"))


            if not slot_date or not time:
                flash("Please enter both date and time.")
                return redirect(url_for("examiner_slots"))

            slot_datetime = f"{slot_date}T{time}"
            if slot_datetime < now:
                flash("You cannot create a slot in the past.")
                return redirect(url_for("examiner_slots"))

            new_slot = ExaminationSlot(
                examination_id=examination_id,
                examiner_id=examiner_id,
                date=slot_date,
                time=time
            )

            db.session.add(new_slot)
            db.session.commit()

            flash("Slot created.")

            return redirect(url_for("examiner_slots"))

        examinations = Examination.query.filter_by(
            slot_creation_open=True
        ).all()

        slots = ExaminationSlot.query.filter_by(
            examiner_id=examiner_id
        ).all()

        return render_template(
            "examiner_slots.html",
            examinations=examinations,
            slots=slots
        )


    @app.route("/examiner/slots/edit/<int:slot_id>", methods=["GET", "POST"])
    @role_required("Examiner")
    def edit_examiner_slot(slot_id):

        examiner_id = session["user_id"]

        slot = ExaminationSlot.query.get_or_404(slot_id)

        if slot.examiner_id != examiner_id:
            abort(403)

        if slot.examination.booking_open:
            flash("You cannot edit slots after booking has started.")
            return redirect(url_for("examiner_slots"))

        if Booking.query.filter_by(slot_id=slot.id).count() > 0:
            flash("This slot already has bookings and cannot be edited.")
            return redirect(url_for("examiner_slots"))

        if request.method == "POST":

            slot_date = request.form.get("date")
            time = request.form.get("time")

            if not slot_date or not time:
                flash("Please enter both date and time.")
                return redirect(url_for("edit_examiner_slot", slot_id=slot.id))

            now = datetime.now().strftime("%Y-%m-%dT%H:%M")
            slot_datetime = f"{slot_date}T{time}"
            if slot_datetime < now:
                flash("You cannot set a slot date and time in the past.")
                return redirect(url_for("edit_examiner_slot", slot_id=slot.id))

            slot.date = slot_date
            slot.time = time

            db.session.commit()

            flash("Slot time updated.")

            return redirect(url_for("examiner_slots"))

        return render_template(
            "edit_examiner_slot.html",
            slot=slot
        )


    @app.route("/examiner/slots/delete/<int:slot_id>", methods=["POST"])
    @role_required("Examiner")
    def delete_examiner_slot(slot_id):

        examiner_id = session["user_id"]

        slot = ExaminationSlot.query.get_or_404(slot_id)

        if slot.examiner_id != examiner_id:
            abort(403)

        if slot.examination.booking_open:
            flash("You cannot delete slots after booking has started.")
            return redirect(url_for("examiner_slots"))

        if Booking.query.filter_by(slot_id=slot.id).count() > 0:
            flash("You cannot delete a slot that has bookings.")
            return redirect(url_for("examiner_slots"))

        db.session.delete(slot)
        db.session.commit()

        flash("Slot removed.")

        return redirect(url_for("examiner_slots"))


    @app.route("/examiner/profile", methods=["GET", "POST"])
    @role_required("Examiner")
    def examiner_profile():

        examiner_id = session["user_id"]

        examiner = User.query.get_or_404(examiner_id)

        profile = ExaminerProfile.query.filter_by(
            user_id=examiner_id
        ).first()

        if profile is None:
            profile = ExaminerProfile(user_id=examiner_id)
            db.session.add(profile)
            db.session.commit()

        if request.method == "POST":

            examiner.name = request.form.get("name")
            profile.qualification = request.form.get("qualification")
            profile.specialization = request.form.get("specialization")

            db.session.commit()

            flash("Profile saved.")

            return redirect(url_for("examiner_profile"))

        return render_template(
            "examiner_profile.html",
            examiner=examiner,
            profile=profile
        )


    @app.route("/examiner/examinations")
    @role_required("Examiner")
    def examiner_examinations():

        examiner_id = session["user_id"]

        examinations = Examination.query.join(
            ExaminationSlot
        ).filter(
            ExaminationSlot.examiner_id == examiner_id
        ).distinct().all()

        return render_template(
            "examiner_examinations.html",
            examinations=examinations
        )


    @app.route("/examiner/history")
    @role_required("Examiner")
    def examiner_history():
        examiner_id = session["user_id"]

        evaluations = Evaluation.query.filter_by(
            examiner_id=examiner_id,
            status="Completed"
        ).all()

        scores = [e.marks for e in evaluations if e.marks is not None]
        avg_marks = round(sum(scores) / len(scores), 1) if scores else 0
        highest_marks = max(scores) if scores else 0
        lowest_marks = min(scores) if scores else 0

        slots_created = ExaminationSlot.query.filter_by(examiner_id=examiner_id).all()

        return render_template(
            "examiner_history.html",
            evaluations=evaluations,
            total_evaluated=len(scores),
            avg_marks=avg_marks,
            highest_marks=highest_marks,
            lowest_marks=lowest_marks,
            slots=slots_created
        )


    @app.route("/examiner/availability", methods=["GET", "POST"])
    @role_required("Examiner")
    def examiner_availability():
        examiner_id = session["user_id"]

        if request.method == "POST":
            unavail_date = request.form.get("date")
            reason = request.form.get("reason")

            if not unavail_date:
                flash("Please specify a date.", "danger")
                return redirect(url_for("examiner_availability"))

            exists = ExaminerUnavailability.query.filter_by(
                examiner_id=examiner_id,
                date=unavail_date
            ).first()

            if exists:
                flash("You have already marked this date as unavailable.", "warning")
                return redirect(url_for("examiner_availability"))

            unavail = ExaminerUnavailability(
                examiner_id=examiner_id,
                date=unavail_date,
                reason=reason.strip() if reason else None
            )
            db.session.add(unavail)
            db.session.commit()

            flash("Unavailable date saved.", "success")
            return redirect(url_for("examiner_availability"))

        unavailabilities = ExaminerUnavailability.query.filter_by(
            examiner_id=examiner_id
        ).order_by(ExaminerUnavailability.date.asc()).all()

        return render_template(
            "examiner_availability.html",
            unavailabilities=unavailabilities
        )


    @app.route("/examiner/availability/delete/<int:unavail_id>", methods=["POST"])
    @role_required("Examiner")
    def delete_examiner_unavailability(unavail_id):
        examiner_id = session["user_id"]
        unavail = ExaminerUnavailability.query.filter_by(
            id=unavail_id,
            examiner_id=examiner_id
        ).first_or_404()

        db.session.delete(unavail)
        db.session.commit()
        flash("Unavailability entry removed.", "info")
        return redirect(url_for("examiner_availability"))
