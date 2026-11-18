from datetime import datetime
from flask import render_template, request, redirect, url_for, flash

from database import db
from models import (
    User, Course, Examination, ExaminationSlot, Booking,
    ExaminationRubric, Evaluation, Resource,
    ExaminerUnavailability, Announcement
)
from helpers import role_required, create_notification, update_examination_status


def register_admin_routes(app):
    @app.route("/admin_dashboard")
    @role_required("Admin")
    def admin_dashboard():

        total_courses = Course.query.count()
        total_examinations = Examination.query.count()
        total_examiners = User.query.filter_by(role="Examiner").count()
        total_students = User.query.filter_by(role="Student").count()
        total_slots = ExaminationSlot.query.count()
        total_bookings = Booking.query.count()

        pending_examiners = User.query.filter_by(
            role="Examiner",
            is_approved=False
        ).all()

        approved_examiners = User.query.filter_by(
            role="Examiner",
            is_approved=True,
            is_active=True
        ).all()

        inactive_examiners = User.query.filter_by(
            role="Examiner",
            is_active=False
        ).all()

        examiner_stats = []
        for ex in approved_examiners:
            evals = Evaluation.query.filter_by(examiner_id=ex.id, status="Completed").all()
            scores = [e.marks for e in evals if e.marks is not None]
            avg_grade = round(sum(scores) / len(scores), 1) if scores else None
            total_evals = len(scores)
            total_slots_created = ExaminationSlot.query.filter_by(examiner_id=ex.id).count()
            examiner_stats.append({
                "examiner": ex,
                "avg_grade": avg_grade,
                "total_evals": total_evals,
                "total_slots": total_slots_created
            })

        announcements = Announcement.query.order_by(Announcement.id.desc()).limit(5).all()

        return render_template(
            "admin_dashboard.html",
            total_courses=total_courses,
            total_examinations=total_examinations,
            total_examiners=total_examiners,
            total_students=total_students,
            total_slots=total_slots,
            total_bookings=total_bookings,
            pending_examiners=pending_examiners,
            approved_examiners=approved_examiners,
            inactive_examiners=inactive_examiners,
            examiner_stats=examiner_stats,
            announcements=announcements
        )


    @app.route("/approve_examiner/<int:user_id>", methods=["POST"])
    @role_required("Admin")
    def approve_examiner(user_id):

        examiner = User.query.filter_by(
            id=user_id,
            role="Examiner"
        ).first_or_404()

        examiner.is_approved = True
        db.session.commit()

        flash("Examiner approved.")

        return redirect(url_for("admin_dashboard"))


    @app.route("/deactivate_examiner/<int:user_id>", methods=["POST"])
    @role_required("Admin")
    def deactivate_examiner(user_id):

        examiner = User.query.filter_by(
            id=user_id,
            role="Examiner"
        ).first_or_404()

        examiner.is_active = False
        db.session.commit()

        flash("Examiner deactivated.")

        return redirect(url_for("admin_dashboard"))


    @app.route("/reactivate_examiner/<int:user_id>", methods=["POST"])
    @role_required("Admin")
    def reactivate_examiner(user_id):

        examiner = User.query.filter_by(
            id=user_id,
            role="Examiner"
        ).first_or_404()

        examiner.is_active = True
        db.session.commit()

        flash("Examiner reactivated.")

        return redirect(url_for("admin_dashboard"))


    @app.route("/courses")
    @role_required("Admin")
    def courses():
        all_courses = Course.query.all()

        return render_template("courses.html", courses=all_courses)


    @app.route("/course/add", methods=["GET", "POST"])
    @role_required("Admin")
    def add_course():

        if request.method == "POST":
            name = request.form.get("name")
            description = request.form.get("description")

            if not name or not name.strip():
                flash("Course name is required.")
                return redirect(url_for("add_course"))

            new_course = Course(
                name=name.strip(),
                description=description
            )

            db.session.add(new_course)
            db.session.flush()

            resource_title = request.form.get("resource_title")
            resource_url = request.form.get("resource_url")
            if resource_title and resource_url:
                res = Resource(
                    title=resource_title.strip(),
                    url=resource_url.strip(),
                    description=f"Course Material for {new_course.name}",
                    course_id=new_course.id,
                    created_at=datetime.now().strftime("%Y-%m-%d %H:%M")
                )
                db.session.add(res)

            db.session.commit()

            flash("Course added.")
            return redirect(url_for("courses"))

        return render_template("add_course.html")


    @app.route("/course/edit/<int:course_id>", methods=["GET", "POST"])
    @role_required("Admin")
    def edit_course(course_id):

        course = Course.query.get_or_404(course_id)

        if request.method == "POST":
            name = request.form.get("name")
            description = request.form.get("description")

            if not name or not name.strip():
                flash("Course name is required.")
                return redirect(url_for("edit_course", course_id=course.id))

            course.name = name.strip()
            course.description = description

            db.session.commit()

            flash("Course updated.")
            return redirect(url_for("courses"))

        return render_template("edit_course.html", course=course)


    @app.route("/course/delete/<int:course_id>", methods=["POST"])
    @role_required("Admin")
    def delete_course(course_id):

        course = Course.query.get_or_404(course_id)

        if course.examinations:
            flash("Cannot delete this course because examinations are linked to it.")
            return redirect(url_for("courses"))

        db.session.delete(course)
        db.session.commit()

        flash("Course removed.")
        return redirect(url_for("courses"))


    @app.route("/examinations")
    @role_required("Admin")
    def examinations():

        search = request.args.get("search", "").strip().lower()

        all_examinations = Examination.query.all()
        for examination in all_examinations:
            update_examination_status(examination)

        if search:
            all_examinations = [
                examination for examination in all_examinations
                if search in str(examination.id)
                or search in examination.name.lower()
                or search in examination.course.name.lower()
            ]

        return render_template(
            "examinations.html",
            examinations=all_examinations,
            search=search
        )


    @app.route("/examination/add", methods=["GET", "POST"])
    @role_required("Admin")
    def add_examination():

        all_courses = Course.query.all()

        if request.method == "POST":

            name = request.form.get("name")
            course_id = request.form.get("course_id", type=int)

            if not name or not name.strip():
                flash("Examination name is required.")
                return redirect(url_for("add_examination"))

            course = Course.query.get(course_id)

            if course is None:
                flash("Please select a valid course.")
                return redirect(url_for("add_examination"))

            new_examination = Examination(
                name=name.strip(),
                course_id=course_id
            )

            db.session.add(new_examination)
            db.session.flush()

            resource_title = request.form.get("resource_title")
            resource_url = request.form.get("resource_url")
            if resource_title and resource_url:
                res = Resource(
                    title=resource_title.strip(),
                    url=resource_url.strip(),
                    description=f"Study Resource for {new_examination.name}",
                    course_id=course_id,
                    examination_id=new_examination.id,
                    created_at=datetime.now().strftime("%Y-%m-%d %H:%M")
                )
                db.session.add(res)

            db.session.commit()

            flash("Exam created.")
            return redirect(url_for("examinations"))

        return render_template(
            "add_examination.html",
            courses=all_courses
        )


    @app.route("/examination/edit/<int:examination_id>", methods=["GET", "POST"])
    @role_required("Admin")
    def edit_examination(examination_id):

        examination = Examination.query.get_or_404(examination_id)
        all_courses = Course.query.all()

        if request.method == "POST":

            name = request.form.get("name")
            course_id = request.form.get("course_id", type=int)

            if not name or not name.strip():
                flash("Examination name is required.")
                return redirect(
                    url_for("edit_examination", examination_id=examination.id)
                )

            course = Course.query.get(course_id)

            if course is None:
                flash("Please select a valid course.")
                return redirect(
                    url_for("edit_examination", examination_id=examination.id)
                )

            examination.name = name.strip()
            examination.course_id = course_id

            db.session.commit()

            flash("Exam updated.")
            return redirect(url_for("examinations"))

        return render_template(
            "edit_examination.html",
            examination=examination,
            courses=all_courses
        )


    @app.route("/examination/delete/<int:examination_id>", methods=["POST"])
    @role_required("Admin")
    def delete_examination(examination_id):

        examination = Examination.query.get_or_404(examination_id)

        if examination.slots or examination.rubrics:
            flash("Cannot delete an examination with linked slots or rubrics.")
            return redirect(url_for("examinations"))

        db.session.delete(examination)
        db.session.commit()

        flash("Exam removed.")
        return redirect(url_for("examinations"))


    @app.route("/examination/<int:examination_id>/rubrics")
    @role_required("Admin")
    def manage_rubrics(examination_id):

        examination = Examination.query.get_or_404(examination_id)

        rubrics = ExaminationRubric.query.filter_by(
            examination_id=examination_id
        ).all()

        total_marks = sum(rubric.marks for rubric in rubrics)

        return render_template(
            "rubrics.html",
            examination=examination,
            rubrics=rubrics,
            total_marks=total_marks
        )


    @app.route("/rubric/add/<int:examination_id>", methods=["GET", "POST"])
    @role_required("Admin")
    def add_rubric(examination_id):

        examination = Examination.query.get_or_404(examination_id)

        if request.method == "POST":

            criterion = request.form.get("criterion")
            marks = request.form.get("marks", type=int)

            if not criterion or not criterion.strip():
                flash("Criterion name is required.")
                return redirect(url_for("add_rubric", examination_id=examination_id))

            if marks is None or marks <= 0:
                flash("Marks must be a positive number.")
                return redirect(url_for("add_rubric", examination_id=examination_id))

            new_rubric = ExaminationRubric(
                examination_id=examination_id,
                criterion=criterion.strip(),
                marks=marks
            )

            db.session.add(new_rubric)
            db.session.commit()

            flash("Rubric saved.")
            return redirect(url_for("manage_rubrics", examination_id=examination_id))

        return render_template(
            "add_rubric.html",
            examination=examination
        )


    @app.route("/rubric/edit/<int:rubric_id>", methods=["GET", "POST"])
    @role_required("Admin")
    def edit_rubric(rubric_id):

        rubric = ExaminationRubric.query.get_or_404(rubric_id)

        if request.method == "POST":

            criterion = request.form.get("criterion")
            marks = request.form.get("marks", type=int)

            if not criterion or not criterion.strip():
                flash("Criterion name is required.")
                return redirect(url_for("edit_rubric", rubric_id=rubric.id))

            if marks is None or marks <= 0:
                flash("Marks must be a positive number.")
                return redirect(url_for("edit_rubric", rubric_id=rubric.id))

            rubric.criterion = criterion.strip()
            rubric.marks = marks

            db.session.commit()

            flash("Rubric updated.")

            return redirect(
                url_for("manage_rubrics", examination_id=rubric.examination_id)
            )

        return render_template("edit_rubric.html", rubric=rubric)


    @app.route("/rubric/delete/<int:rubric_id>", methods=["POST"])
    @role_required("Admin")
    def delete_rubric(rubric_id):

        rubric = ExaminationRubric.query.get_or_404(rubric_id)

        examination_id = rubric.examination_id

        db.session.delete(rubric)
        db.session.commit()

        flash("Rubric removed.")

        return redirect(
            url_for("manage_rubrics", examination_id=examination_id)
        )


    @app.route("/examination/<int:examination_id>/settings", methods=["GET", "POST"])
    @role_required("Admin")
    def examination_settings(examination_id):

        examination = Examination.query.get_or_404(examination_id)

        if request.method == "POST":

            slot_start = request.form.get("slot_creation_start")
            slot_end = request.form.get("slot_creation_end")
            booking_start = request.form.get("booking_start")
            booking_end = request.form.get("booking_end")

            if bool(slot_start) != bool(slot_end):
                flash("Enter both slot creation dates.")
                return redirect(url_for(
                    "examination_settings",
                    examination_id=examination.id
                ))

            if slot_start and slot_start > slot_end:
                flash("Slot creation end must be after its start.")
                return redirect(url_for(
                    "examination_settings",
                    examination_id=examination.id
                ))

            if bool(booking_start) != bool(booking_end):
                flash("Enter both booking dates.")
                return redirect(url_for(
                    "examination_settings",
                    examination_id=examination.id
                ))

            if booking_start and booking_start > booking_end:
                flash("Booking end must be after its start.")
                return redirect(url_for(
                    "examination_settings",
                    examination_id=examination.id
                ))

            if slot_end and booking_start and booking_start < slot_end:
                flash("Booking can only start AFTER slot creation period ends.", "danger")
                return redirect(url_for(
                    "examination_settings",
                    examination_id=examination.id
                ))

            examination.slot_creation_start = slot_start or None
            examination.slot_creation_end = slot_end or None
            examination.booking_start = booking_start or None
            examination.booking_end = booking_end or None

            db.session.commit()

            flash("Timelines saved.")
            return redirect(url_for(
                "examination_settings",
                examination_id=examination.id
            ))

        return render_template(
            "examination_settings.html",
            examination=examination
        )


    @app.route("/examination/<int:examination_id>/toggle-slots", methods=["POST"])
    @role_required("Admin")
    def toggle_slot_creation(examination_id):

        examination = Examination.query.get_or_404(examination_id)

        if not examination.slot_creation_open:
            if not examination.slot_creation_start or not examination.slot_creation_end:
                flash("Configure slot creation dates before opening it.")
                return redirect(url_for(
                    "examination_settings",
                    examination_id=examination.id
                ))

        examination.slot_creation_open = not examination.slot_creation_open

        if examination.slot_creation_open:
            examination.status = "Slot Creation"

        elif examination.booking_open:
            examination.status = "Booking Open"

        else:
            examination.status = "Draft"

        db.session.commit()

        flash("Slot creation setting updated.")

        return redirect(url_for(
            "examination_settings",
            examination_id=examination.id
        ))


    @app.route("/examination/<int:examination_id>/toggle-booking", methods=["POST"])
    @role_required("Admin")
    def toggle_booking(examination_id):

        examination = Examination.query.get_or_404(examination_id)

        if not examination.booking_open:
            if not examination.booking_start or not examination.booking_end:
                flash("Configure booking dates before opening booking.")
                return redirect(url_for(
                    "examination_settings",
                    examination_id=examination.id
                ))

        examination.booking_open = not examination.booking_open

        if examination.booking_open:
            examination.status = "Booking Open"

        else:
            examination.status = "Closed"

        db.session.commit()

        flash("Booking setting updated.")

        return redirect(url_for(
            "examination_settings",
            examination_id=examination.id
        ))


    @app.route("/admin/slots")
    @role_required("Admin")
    def admin_slots():

        search = request.args.get("search", "").strip()

        all_slots = ExaminationSlot.query.all()

        if search:
            all_slots = [
                slot for slot in all_slots
                if search.lower() in str(slot.id).lower()
                or search.lower() in slot.examination.name.lower()
                or search.lower() in slot.examiner.name.lower()
            ]

        approved_examiners = User.query.filter_by(
            role="Examiner",
            is_approved=True,
            is_active=True
        ).all()

        unavailabilities = ExaminerUnavailability.query.all()
        unavail_map = {f"{u.examiner_id}_{u.date}": u.reason or "Unavailable" for u in unavailabilities}

        return render_template(
            "admin_slots.html",
            slots=all_slots,
            examiners=approved_examiners,
            unavail_map=unavail_map,
            search=search
        )


    @app.route("/admin/slot/<int:slot_id>/change-examiner", methods=["POST"])
    @role_required("Admin")
    def change_slot_examiner(slot_id):

        slot = ExaminationSlot.query.get_or_404(slot_id)

        examiner_id = request.form.get("examiner_id", type=int)

        examiner = User.query.filter_by(
            id=examiner_id,
            role="Examiner",
            is_approved=True,
            is_active=True
        ).first()

        if examiner is None:
            flash("Please select a valid active examiner.")
            return redirect(url_for("admin_slots"))

        slot.examiner_id = examiner.id

        db.session.commit()

        flash("Examiner updated.")

        return redirect(url_for("admin_slots"))


    @app.route("/admin/bookings")
    @role_required("Admin")
    def admin_bookings():

        search = request.args.get("search", "").strip()

        all_bookings = Booking.query.all()

        if search:
            all_bookings = [
                booking for booking in all_bookings
                if search.lower() in str(booking.id).lower()
                or search.lower() in booking.student.name.lower()
                or search.lower() in booking.student.email.lower()
                or search.lower() in booking.slot.examination.name.lower()
            ]

        return render_template(
            "admin_bookings.html",
            bookings=all_bookings,
            search=search
        )


    @app.route("/admin/booking/<int:booking_id>/reschedule", methods=["GET", "POST"])
    @role_required("Admin")
    def reschedule_booking(booking_id):

        booking = Booking.query.get_or_404(booking_id)

        available_slots = ExaminationSlot.query.filter_by(
            examination_id=booking.slot.examination_id
        ).all()

        if request.method == "POST":

            new_slot_id = request.form.get("slot_id", type=int)

            new_slot = ExaminationSlot.query.filter_by(
                id=new_slot_id,
                examination_id=booking.slot.examination_id
            ).first()

            if new_slot is None:
                flash("Please select a valid slot.")
                return redirect(
                    url_for("reschedule_booking", booking_id=booking.id)
                )

            if new_slot.id == booking.slot_id:
                flash("This student is already booked in that slot.")
                return redirect(
                    url_for("reschedule_booking", booking_id=booking.id)
                )

            if booking.status != "Booked":
                flash("Only active bookings can be rescheduled.")
                return redirect(url_for("admin_bookings"))

            existing_booking = Booking.query.join(
                ExaminationSlot,
                Booking.slot_id == ExaminationSlot.id
            ).filter(
                Booking.student_id == booking.student_id,
                Booking.status == "Booked",
                ExaminationSlot.examination_id == booking.slot.examination_id,
                Booking.id != booking.id
            ).first()

            if existing_booking:
                flash("Student already has a booking for this examination.")
                return redirect(url_for("reschedule_booking", booking_id=booking.id))

            booked_count = Booking.query.filter_by(
                slot_id=new_slot.id,
                status="Booked"
            ).count()

            if booked_count >= new_slot.capacity:
                flash("The selected slot is already full.")
                return redirect(url_for("reschedule_booking", booking_id=booking.id))


            booking.slot_id = new_slot.id

            create_notification(
                user_id=booking.student_id,
                title="Booking Rescheduled",
                message=f"Your booking for {booking.slot.examination.name} was rescheduled to {new_slot.date} at {new_slot.time} (Examiner: {new_slot.examiner.name}).",
                category="info"
            )

            db.session.commit()

            flash("Booking rescheduled.")

            return redirect(url_for("admin_bookings"))

        return render_template(
            "reschedule_booking.html",
            booking=booking,
            slots=available_slots
        )


    @app.route("/admin/users")
    @role_required("Admin")
    def admin_users():

        search = request.args.get("search", "").strip().lower()

        students = User.query.filter_by(role="Student").all()
        examiners = User.query.filter_by(role="Examiner").all()

        if search:
            students = [
                student for student in students
                if search in str(student.id)
                or search in student.name.lower()
                or search in student.email.lower()
            ]

            examiners = [
                examiner for examiner in examiners
                if search in str(examiner.id)
                or search in examiner.name.lower()
                or search in examiner.email.lower()
            ]

        return render_template(
            "admin_users.html",
            students=students,
            examiners=examiners,
            search=search
        )


    @app.route("/admin/resources", methods=["GET", "POST"])
    @role_required("Admin")
    def admin_resources():
        if request.method == "POST":
            title = request.form.get("title")
            description = request.form.get("description")
            url = request.form.get("url")
            course_id = request.form.get("course_id", type=int) or None
            examination_id = request.form.get("examination_id", type=int) or None

            if not title or not url:
                flash("Resource title and URL are required.", "danger")
                return redirect(url_for("admin_resources"))

            res = Resource(
                title=title.strip(),
                url=url.strip(),
                description=description.strip() if description else None,
                course_id=course_id,
                examination_id=examination_id,
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M")
            )
            db.session.add(res)
            db.session.commit()
            flash("Resource uploaded.", "success")
            return redirect(url_for("admin_resources"))

        resources = Resource.query.order_by(Resource.id.desc()).all()
        courses = Course.query.all()
        examinations = Examination.query.all()

        return render_template(
            "admin_resources.html",
            resources=resources,
            courses=courses,
            examinations=examinations
        )


    @app.route("/admin/resource/delete/<int:resource_id>", methods=["POST"])
    @role_required("Admin")
    def delete_resource(resource_id):
        res = Resource.query.get_or_404(resource_id)
        db.session.delete(res)
        db.session.commit()
        flash("Resource deleted.", "info")
        return redirect(url_for("admin_resources"))


    @app.route("/admin/examination/<int:examination_id>/grades")
    @role_required("Admin")
    def examination_grade_analysis(examination_id):
        examination = Examination.query.get_or_404(examination_id)

        evals = Evaluation.query.join(
            Booking, Evaluation.booking_id == Booking.id
        ).join(
            ExaminationSlot, Booking.slot_id == ExaminationSlot.id
        ).filter(
            ExaminationSlot.examination_id == examination.id,
            Evaluation.status == "Completed"
        ).all()

        scores = [ev.marks for ev in evals if ev.marks is not None]
        avg_marks = round(sum(scores) / len(scores), 1) if scores else 0
        highest_marks = max(scores) if scores else 0
        lowest_marks = min(scores) if scores else 0

        grades = {"A (85+)": 0, "B (70-84)": 0, "C (50-69)": 0, "D (40-49)": 0, "F (<40)": 0}
        for s in scores:
            if s >= 85:
                grades["A (85+)"] += 1
            elif s >= 70:
                grades["B (70-84)"] += 1
            elif s >= 50:
                grades["C (50-69)"] += 1
            elif s >= 40:
                grades["D (40-49)"] += 1
            else:
                grades["F (<40)"] += 1

        return render_template(
            "grade_distribution.html",
            examination=examination,
            evaluations=evals,
            total_students=len(scores),
            avg_marks=avg_marks,
            highest_marks=highest_marks,
            lowest_marks=lowest_marks,
            grades=grades
        )
