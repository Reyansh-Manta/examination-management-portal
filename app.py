from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, jsonify
from database import db
from models import (
    User, Course, Examination, ExaminationSlot, Booking,
    ExaminationRubric, Evaluation, ExaminerProfile, EvaluationMark,
    StudentProfile, Resource, ExaminerUnavailability, Notification, Announcement
)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import date, datetime
from sqlalchemy import or_, func
import csv
import io

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///examination.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "tfcviyhcv97tufv976ft76g768g86guyvu"

db.init_app(app)

with app.app_context():
    db.create_all()

# Function to check user role
def role_required(required_role):
    
    def decorator(function):

        @wraps(function)
        def wrapper(*args, **kwargs):

            # Check whether user is logged in
            if "user_id" not in session:
                return redirect(url_for("login"))

            # Get current user from database
            user = User.query.get(session["user_id"])
            if not user.is_active:
                session.clear()
                return redirect(url_for("login"))
            if user is None:
                session.clear()
                return redirect(url_for("login"))

            # Check whether user has the required role
            if user.role != required_role:
                abort(403)

            # Check examiner approval
            if user.role == "Examiner" and not user.is_approved:
                session.clear()
                return redirect(url_for("login"))

            return function(*args, **kwargs)

        return wrapper

    return decorator


# Helper to send in-app notification
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


# Context processor to inject unread notification count
@app.context_processor
def inject_global_data():
    unread_count = 0
    if "user_id" in session:
        unread_count = Notification.query.filter_by(
            user_id=session["user_id"],
            is_read=False
        ).count()
    return {"unread_notifications_count": unread_count}


def update_examination_status(examination):
    today = date.today().isoformat()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")

    if examination.status == "Completed":
        return

    # Automatic start & progression based on timelines:
    # 1. Slot creation automatic start / progression
    if examination.slot_creation_start and examination.slot_creation_end:
        if examination.slot_creation_start <= now <= examination.slot_creation_end:
            examination.slot_creation_open = True
            examination.status = "Slot Creation"
        elif now > examination.slot_creation_end:
            examination.slot_creation_open = False

    # 2. Student booking automatic start / progression (only after slot creation ends)
    if examination.booking_start and examination.booking_end:
        if examination.booking_start <= now <= examination.booking_end:
            examination.booking_open = True
            examination.status = "Booking Open"
        elif now > examination.booking_end:
            examination.booking_open = False
            examination.status = "Closed"

    # Fallback to manual flag statuses if set
    if examination.booking_open:
        examination.status = "Booking Open"
    elif examination.slot_creation_open:
        examination.status = "Slot Creation"

    # Check whether examination has slots and all slots/bookings have completed
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

# Root Route (redirects to the appropriate dashboard if logged in, or login if not)
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
            elif user.role == "Student":
                return redirect(url_for("student_dashboard"))

    return redirect(url_for("login"))

# Student Registration
@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")

        # Check whether email already exists
        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            flash("Email already registered!")
            return redirect(url_for("register"))

        # Hash the password
        hashed_password = generate_password_hash(password, method="pbkdf2:sha256")

        # Create new student
        new_user = User(
            name=name,
            email=email,
            password_hash=hashed_password,
            role="Student"
        )

        new_user.is_approved = True

        # Save student in database
        db.session.add(new_user)
        db.session.commit()

        flash("Registration successful! Please login.")

        return redirect(url_for("login"))

    return render_template("register.html")


# Examiner Registration
@app.route("/examiner_register", methods=["GET", "POST"])
def examiner_register():

    if request.method == "POST":

        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")

        # Check whether email already exists
        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            flash("Email already registered!")
            return redirect(url_for("examiner_register"))

        # Hash the password
        hashed_password = generate_password_hash(password, method="pbkdf2:sha256")

        # Create new examiner
        new_examiner = User(
            name=name,
            email=email,
            password_hash=hashed_password,
            role="Examiner"
        )

        # Examiner needs Admin approval
        new_examiner.is_approved = False

        # Save examiner in database
        db.session.add(new_examiner)
        db.session.commit()

        flash("Registration successful! Wait for Admin approval.")

        return redirect(url_for("examiner_register"))

    return render_template("examiner_register.html")


# Login
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email")
        password = request.form.get("password")

        # Find user using email
        user = User.query.filter_by(email=email).first()

        # Check whether user exists and password is correct
        if user and check_password_hash(user.password_hash, password):
            if not user.is_active:
                flash("Your account has been deactivated.")
                return redirect(url_for("login"))

            # Check whether examiner is approved
            if user.role == "Examiner" and not user.is_approved:
                flash("Your account is waiting for Admin approval.")
                return redirect(url_for("login"))

            # Store user information in session
            session["user_id"] = user.id
            session["role"] = user.role
            session["user_role"] = user.role
            session["user_name"] = user.name

            flash("Login successful!")

            # Redirect according to role
            if user.role == "Admin":
                return redirect(url_for("admin_dashboard"))

            elif user.role == "Examiner":
                return redirect(url_for("examiner_dashboard"))

            elif user.role == "Student":
                return redirect(url_for("student_dashboard"))

        else:
            flash("Invalid email or password!")

    return render_template("login.html")




# Admin Dashboard
@app.route("/admin_dashboard")
@role_required("Admin")
def admin_dashboard():

    # Dashboard statistics
    total_courses = Course.query.count()
    total_examinations = Examination.query.count()
    total_examiners = User.query.filter_by(role="Examiner").count()
    total_students = User.query.filter_by(role="Student").count()
    total_slots = ExaminationSlot.query.count()
    total_bookings = Booking.query.count()

    # Get pending examiners
    pending_examiners = User.query.filter_by(
        role="Examiner",
        is_approved=False
    ).all()

    # Get approved and active examiners
    approved_examiners = User.query.filter_by(
        role="Examiner",
        is_approved=True,
        is_active=True
    ).all()

    # Get deactivated examiners
    inactive_examiners = User.query.filter_by(
        role="Examiner",
        is_active=False
    ).all()

    # Examiner progress and average grading tracking
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

    # Recent announcements
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




# Examiner Dashboard

@app.route("/examiner_dashboard")
@role_required("Examiner")
def examiner_dashboard():

    examiner_id = session["user_id"]

    # Get all slots created by this examiner
    slots = ExaminationSlot.query.filter_by(
        examiner_id=examiner_id
    ).all()

    # Get assigned examinations
    examinations = set()

    for slot in slots:
        examinations.add(slot.examination_id)

    total_examinations = len(examinations)

    # Count created slots
    total_slots = len(slots)

    # Count students booked
    total_bookings = 0

    for slot in slots:
        total_bookings += Booking.query.filter_by(
            slot_id=slot.id,
            status="Booked"
        ).count()

    # Count pending evaluations
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

    # Evaluations done by this examiner
    evaluations = Evaluation.query.filter_by(
        examiner_id=examiner_id,
        status="Completed"
    ).all()

    scores = [e.marks for e in evaluations if e.marks is not None]
    avg_grading = round(sum(scores) / len(scores), 1) if scores else 0
    total_evaluated = len(scores)

    # Announcements for examiner
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



# Student Dashboard

@app.route("/student_dashboard")
@role_required("Student")
def student_dashboard():

    student_id = session["user_id"]

    # Get all active bookings of this student
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

    # Current & previous evaluations for this student
    evaluations = Evaluation.query.join(
        Booking,
        Evaluation.booking_id == Booking.id
    ).filter(
        Booking.student_id == student_id,
        Evaluation.status == "Completed"
    ).all()

    # Announcements for students
    announcements = Announcement.query.filter(
        or_(Announcement.target_role == "All", Announcement.target_role == "Student")
    ).order_by(Announcement.id.desc()).limit(5).all()

    # Performance stats
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



# Logout
@app.route("/logout")
def logout():

    # Clear all session information
    session.clear()

    flash("You have been logged out successfully.")

    # Redirect to login page
    return redirect(url_for("login"))


# Approve Examiner
@app.route("/approve_examiner/<int:user_id>", methods=["POST"])
@role_required("Admin")
def approve_examiner(user_id):

    examiner = User.query.filter_by(
        id=user_id,
        role="Examiner"
    ).first_or_404()

    examiner.is_approved = True
    db.session.commit()

    flash("Examiner approved successfully!")

    return redirect(url_for("admin_dashboard"))


# Deactivate Examiner
@app.route("/deactivate_examiner/<int:user_id>", methods=["POST"])
@role_required("Admin")
def deactivate_examiner(user_id):

    examiner = User.query.filter_by(
        id=user_id,
        role="Examiner"
    ).first_or_404()

    examiner.is_active = False
    db.session.commit()

    flash("Examiner deactivated successfully!")

    return redirect(url_for("admin_dashboard"))


# Reactivate Examiner
@app.route("/reactivate_examiner/<int:user_id>", methods=["POST"])
@role_required("Admin")
def reactivate_examiner(user_id):

    examiner = User.query.filter_by(
        id=user_id,
        role="Examiner"
    ).first_or_404()

    examiner.is_active = True
    db.session.commit()

    flash("Examiner reactivated successfully!")

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

        # Optional resource added during course creation
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

        flash("Course added successfully.")
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

        flash("Course updated successfully.")
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

    flash("Course deleted successfully.")
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

        # Optional study resource added during exam creation
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

        flash("Examination added successfully.")
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

        flash("Examination updated successfully.")
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

    flash("Examination deleted successfully.")
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

        flash("Rubric added successfully.")
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

        flash("Rubric updated successfully.")

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

    flash("Rubric deleted successfully.")

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

        # Check slot creation dates
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

        # Check booking dates
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

        # Enforce that slot booking can only start AFTER slot creation ends
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

        flash("Examination timelines saved successfully.")
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

    # Do not open slot creation without configured dates
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

    # Do not open booking without configured dates
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

    # Load unavailabilities to warn admin if an examiner is unavailable on this slot's date
    unavailabilities = ExaminerUnavailability.query.all()
    # Map (examiner_id, date) -> reason
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

    flash("Examiner changed successfully.")

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

    # Show only slots belonging to the same examination
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

        # Only active bookings can be rescheduled
        if booking.status != "Booked":
            flash("Only active bookings can be rescheduled.")
            return redirect(url_for("admin_bookings"))

        # Prevent duplicate bookings for the same examination
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

        # Check destination slot capacity
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

        flash("Booking rescheduled successfully.")

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


@app.route("/examiner/evaluate/<int:booking_id>", methods=["GET", "POST"])
@role_required("Examiner")
def evaluate_student(booking_id):

    examiner_id = session["user_id"]

    booking = Booking.query.get_or_404(booking_id)

    # Only booked students can be evaluated
    if booking.status != "Booked":
        flash("This booking cannot be evaluated.")
        return redirect(url_for("examiner_bookings"))

    # Check whether this examiner owns the slot
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

        # Read marks for each rubric
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

        # Create evaluation if it does not exist
        if evaluation is None:

            evaluation = Evaluation(
                booking_id=booking.id,
                examiner_id=examiner_id
            )

            db.session.add(evaluation)
            db.session.flush()

        # Save total marks and remarks
        evaluation.marks = total_marks
        evaluation.remarks = remarks
        evaluation.status = "Completed"
        # Mark booking as completed
        booking.status = "Completed"

        # Save individual rubric marks
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

        # Notify student about published result
        create_notification(
            user_id=booking.student_id,
            title="Result Published",
            message=f"Your evaluation for {booking.slot.examination.name} is complete. Total Score: {total_marks}. Check your Results section for detailed rubric scores.",
            category="success"
        )

        db.session.commit()

        flash("Evaluation submitted successfully.")

        return redirect(url_for("examiner_bookings"))

    # Get previously submitted marks
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

        # Prevent creating slots in the past
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

        flash("Examination slot created successfully.")

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

    # Check slot ownership
    if slot.examiner_id != examiner_id:
        abort(403)

    # Check whether booking has started
    if slot.examination.booking_open:
        flash("You cannot edit slots after booking has started.")
        return redirect(url_for("examiner_slots"))

    # Do not change slots that already have bookings
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

        flash("Slot updated successfully.")

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

    # Check slot ownership
    if slot.examiner_id != examiner_id:
        abort(403)

    # Check whether booking has started
    if slot.examination.booking_open:
        flash("You cannot delete slots after booking has started.")
        return redirect(url_for("examiner_slots"))

    # Check whether students have already booked this slot
    if Booking.query.filter_by(slot_id=slot.id).count() > 0:
        flash("You cannot delete a slot that has bookings.")
        return redirect(url_for("examiner_slots"))

    db.session.delete(slot)
    db.session.commit()

    flash("Slot deleted successfully.")

    return redirect(url_for("examiner_slots"))

@app.route("/examiner/profile", methods=["GET", "POST"])
@role_required("Examiner")
def examiner_profile():

    examiner_id = session["user_id"]

    examiner = User.query.get_or_404(examiner_id)

    profile = ExaminerProfile.query.filter_by(
        user_id=examiner_id
    ).first()

    # Create profile if it does not exist
    if profile is None:
        profile = ExaminerProfile(user_id=examiner_id)
        db.session.add(profile)
        db.session.commit()

    if request.method == "POST":

        examiner.name = request.form.get("name")
        profile.qualification = request.form.get("qualification")
        profile.specialization = request.form.get("specialization")

        db.session.commit()

        flash("Profile updated successfully.")

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

        # Check whether email is already used
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

        # Update session name
        session["user_name"] = student.name

        flash("Profile updated successfully.")

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

    # Show examinations for which booking is open
    query = Examination.query.filter_by(booking_open=True)

    # Search by examination name or examination ID
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

    # Get slots belonging to this examination
    slots = ExaminationSlot.query.filter_by(
        examination_id=examination_id
    ).filter(
        ExaminationSlot.date >= date.today().isoformat()
    ).all()

    # Calculate remaining seats in each slot
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

    # Check whether booking is open
    if not examination.booking_open:
        flash("Booking for this examination is closed.", "danger")
        return redirect(url_for(
            "student_examination_slots",
            examination_id=examination.id
        ))

    # Check whether the slot date has passed
    if slot.date < date.today().isoformat():
        flash("You cannot book a slot in the past.", "danger")
        return redirect(url_for(
            "student_examination_slots",
            examination_id=examination.id
        ))

    # Prevent the student from booking the same examination twice
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

    # Check how many students have already booked this slot
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

    # Create the booking
    booking = Booking(
        student_id=student_id,
        slot_id=slot.id,
        status="Booked"
    )

    db.session.add(booking)
    db.session.commit()

    # Create confirmation notification for the student
    create_notification(
        user_id=student_id,
        title="Booking Confirmed",
        message=f"You successfully booked {slot.examination.name} on {slot.date} at {slot.time} (Examiner: {slot.examiner.name}).",
        category="success"
    )
    db.session.commit()

    flash("Your examination slot has been booked successfully.", "success")

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

    # Only active bookings can be cancelled
    if booking.status != "Booked":
        flash("This booking cannot be cancelled.", "danger")
        return redirect(url_for("student_bookings"))

    examination = booking.slot.examination

    # Check the cancellation deadline
    if examination.booking_end:
        if date.today().isoformat() > examination.booking_end:
            flash(
                "The cancellation deadline has passed.",
                "danger"
            )
            return redirect(url_for("student_bookings"))

    # Cancel the booking
    booking.status = "Cancelled"
    create_notification(
        user_id=booking.student_id,
        title="Booking Cancelled",
        message=f"Your booking for {booking.slot.examination.name} on {booking.slot.date} has been cancelled.",
        category="warning"
    )
    db.session.commit()

    flash("Your booking has been cancelled successfully.", "success")

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


# -------------------------------------------------------------
# New Feature Routes: Calendar, Resources, Analytics, Announcements,
# Notifications, CSV Import, Examiner Availability & Report
# -------------------------------------------------------------

# Student Monthly Calendar View
@app.route("/student/calendar")
@role_required("Student")
def student_calendar():
    student_id = session["user_id"]

    # Student's active bookings
    my_bookings = Booking.query.filter_by(
        student_id=student_id,
        status="Booked"
    ).all()

    # All upcoming examinations with available slots
    upcoming_slots = ExaminationSlot.query.join(
        Examination
    ).filter(
        ExaminationSlot.date >= date.today().isoformat()
    ).all()

    # Build calendar event payloads
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
        # Avoid duplicate labels if user booked this slot
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


# Downloadable / Printable Result Report
@app.route("/student/result/<int:evaluation_id>/report")
@role_required("Student")
def download_result_report(evaluation_id):
    student_id = session["user_id"]
    evaluation = Evaluation.query.get_or_404(evaluation_id)

    # Validate that this evaluation belongs to the requesting student
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


# Notification Center for All Roles
@app.route("/notifications")
def notifications_view():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    notifications = Notification.query.filter_by(user_id=user_id).order_by(Notification.id.desc()).all()

    # Mark all as read
    for n in notifications:
        n.is_read = True
    db.session.commit()

    return render_template(
        "notifications.html",
        notifications=notifications
    )


# Announcement Management (Admin can publish, delete; viewable by all)
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

        # Notify relevant users
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

        flash("Announcement published successfully.", "success")
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


# Student Study Resources (added by admin during course/exam creation or management)
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


# Admin Resource Management
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
        flash("Study resource uploaded successfully.", "success")
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


# Overall Student Performance Analytics (Accessible by Admin, Examiner, Student)
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

    # Per-examination breakdown
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

        # Grade distribution for this exam
        # A: >= 85, B: 70-84, C: 50-69, D: 40-49, F: < 40
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


# Grade Distribution Analysis specifically for an Examination (Admin)
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


# Examiner History & Personal Analytics
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


# Examiner Availability Calendar / Marking Unavailability
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

        # Check if already added
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

        flash("Unavailable date recorded successfully.", "success")
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


# CSV Import for Students from Admin Side
@app.route("/admin/students/import-csv", methods=["POST"])
@role_required("Admin")
def import_students_csv():
    if "csv_file" not in request.files:
        flash("No file part in the request.", "danger")
        return redirect(url_for("admin_users"))

    file = request.files["csv_file"]
    if file.filename == "":
        flash("No file selected.", "danger")
        return redirect(url_for("admin_users"))

    if not file.filename.endswith(".csv"):
        flash("Please upload a valid .csv file.", "danger")
        return redirect(url_for("admin_users"))

    try:
        stream = io.StringIO(file.stream.read().decode("UTF-8"), newline=None)
        csv_reader = csv.DictReader(stream)

        imported_count = 0
        updated_count = 0

        for row in csv_reader:
            # Expected headers: name, email, password, roll_number, department, year, phone
            name = row.get("name", "").strip()
            email = row.get("email", "").strip()
            password = row.get("password", "").strip()
            roll_number = row.get("roll_number", "").strip()
            department = row.get("department", "").strip()
            year = row.get("year", "").strip()
            phone = row.get("phone", "").strip()

            if not name or not email or not password:
                continue

            user = User.query.filter_by(email=email).first()
            if user is None:
                hashed = generate_password_hash(password, method="pbkdf2:sha256")
                user = User(
                    name=name,
                    email=email,
                    password_hash=hashed,
                    role="Student"
                )
                user.is_approved = True
                user.is_active = True
                db.session.add(user)
                db.session.flush()

                profile = StudentProfile(
                    user_id=user.id,
                    roll_number=roll_number or None,
                    department=department or None,
                    year=year or None,
                    phone=phone or None
                )
                db.session.add(profile)
                imported_count += 1
            else:
                # Update existing student's info & profile
                user.name = name
                profile = StudentProfile.query.filter_by(user_id=user.id).first()
                if profile is None:
                    profile = StudentProfile(
                        user_id=user.id,
                        roll_number=roll_number or None,
                        department=department or None,
                        year=year or None,
                        phone=phone or None
                    )
                    db.session.add(profile)
                else:
                    if roll_number:
                        profile.roll_number = roll_number
                    if department:
                        profile.department = department
                    if year:
                        profile.year = year
                    if phone:
                        profile.phone = phone
                updated_count += 1

        db.session.commit()
        flash(f"CSV Import Complete: {imported_count} new student(s) added, {updated_count} updated.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error reading CSV file: {str(e)}", "danger")

    return redirect(url_for("admin_users"))


if __name__ == "__main__":
    app.run(debug=True)
