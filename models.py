from database import db


# 1. User Model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    is_approved = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)

    def __init__(self, name: str, email: str, password_hash: str, role: str):
        self.name = name
        self.email = email
        self.password_hash = password_hash
        self.role = role


# Student Profile Extension
class StudentProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False
    )
    roll_number = db.Column(db.String(50), unique=True)
    department = db.Column(db.String(100))
    year = db.Column(db.String(20))
    phone = db.Column(db.String(30))

    user = db.relationship("User", backref=db.backref("student_profile", uselist=False))

    def __init__(self, user_id: int, roll_number: str = None, department: str = None, year: str = None, phone: str = None):
        self.user_id = user_id
        self.roll_number = roll_number
        self.department = department
        self.year = year
        self.phone = phone


# 2. Course Model
class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))

    def __init__(self, name: str, description: str = None):
        self.name = name
        self.description = description


# 3. Examination Model
class Examination(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

    course_id = db.Column(
        db.Integer, db.ForeignKey("course.id"), nullable=False
    )

    # Examination status
    status = db.Column(db.String(30), default="Draft")

    # Examiner slot creation period
    slot_creation_start = db.Column(db.String(30))
    slot_creation_end = db.Column(db.String(30))

    # Student booking period
    booking_start = db.Column(db.String(30))
    booking_end = db.Column(db.String(30))

    slot_creation_open = db.Column(db.Boolean, default=False)
    booking_open = db.Column(db.Boolean, default=False)

    course = db.relationship("Course", backref="examinations")

    def __init__(self, name: str, course_id: int = None):
        self.name = name
        self.course_id = course_id


# Course and Examination Resource
class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500))
    url = db.Column(db.String(500), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=True)
    examination_id = db.Column(db.Integer, db.ForeignKey("examination.id"), nullable=True)
    created_at = db.Column(db.String(30))

    course = db.relationship("Course", backref="resources")
    examination = db.relationship("Examination", backref="resources")

    def __init__(self, title: str, url: str, description: str = None, course_id: int = None, examination_id: int = None, created_at: str = None):
        self.title = title
        self.url = url
        self.description = description
        self.course_id = course_id
        self.examination_id = examination_id
        self.created_at = created_at


# 4. Examination Rubric Model
class ExaminationRubric(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    examination_id = db.Column(
        db.Integer, db.ForeignKey("examination.id"), nullable=False
    )

    criterion = db.Column(db.String(200), nullable=False)
    marks = db.Column(db.Integer, nullable=False)

    examination = db.relationship("Examination", backref="rubrics")

    def __init__(self, examination_id: int, criterion: str = None, marks: int = None):
        self.examination_id = examination_id
        self.criterion = criterion
        self.marks = marks


# 5. Examination Slot Model
class ExaminationSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    examination_id = db.Column(
        db.Integer, db.ForeignKey("examination.id"), nullable=False
    )

    examiner_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )

    date = db.Column(db.String(20), nullable=False)
    time = db.Column(db.String(20), nullable=False)

    examination = db.relationship("Examination", backref="slots")

    examiner = db.relationship("User", backref="assigned_slots")
    capacity = db.Column(db.Integer, default=1)

    def __init__(
        self,
        examination_id: int,
        examiner_id: int,
        date: str,
        time: str,
        capacity: int = 1
    ):
        self.examination_id = examination_id
        self.examiner_id = examiner_id
        self.date = date
        self.time = time
        self.capacity = capacity


# 6. Booking Model
class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    student_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )

    slot_id = db.Column(
        db.Integer, db.ForeignKey("examination_slot.id"), nullable=False
    )

    status = db.Column(db.String(20), default="Booked")

    student = db.relationship("User", backref="bookings")

    slot = db.relationship("ExaminationSlot", backref="bookings")

    def __init__(self, student_id: int, slot_id: int, status: str = "Booked"):
        self.student_id = student_id
        self.slot_id = slot_id
        self.status = status


# 7. Examiner Profile Model
class ExaminerProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"),
        unique=True, nullable=False
    )

    qualification = db.Column(db.String(200))
    specialization = db.Column(db.String(200))

    user = db.relationship(
        "User",
        backref=db.backref("examiner_profile", uselist=False)
    )

    def __init__(
        self,
        user_id: int,
        qualification: str = None,
        specialization: str = None
    ):
        self.user_id = user_id
        self.qualification = qualification
        self.specialization = specialization


# Examiner Unavailability
class ExaminerUnavailability(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    examiner_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )
    date = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(300))

    examiner = db.relationship("User", backref="unavailabilities")

    def __init__(self, examiner_id: int, date: str, reason: str = None):
        self.examiner_id = examiner_id
        self.date = date
        self.reason = reason


# Evaluation Model
class Evaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    booking_id = db.Column(
        db.Integer,
        db.ForeignKey("booking.id"),
        unique=True,
        nullable=False
    )

    examiner_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    marks = db.Column(db.Integer)
    remarks = db.Column(db.String(500))
    status = db.Column(db.String(20), default="Pending")

    booking = db.relationship("Booking", backref="evaluation")
    examiner = db.relationship("User")

    def __init__(self, booking_id: int, examiner_id: int = None):
        self.booking_id = booking_id
        self.examiner_id = examiner_id


class EvaluationMark(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    evaluation_id = db.Column(
        db.Integer,
        db.ForeignKey("evaluation.id"),
        nullable=False
    )

    rubric_id = db.Column(
        db.Integer,
        db.ForeignKey("examination_rubric.id"),
        nullable=False
    )

    marks = db.Column(db.Integer, nullable=False)

    rubric = db.relationship("ExaminationRubric")

    evaluation = db.relationship(
        "Evaluation",
        backref="rubric_marks"
    )

    def __init__(
        self,
        evaluation_id: int,
        rubric_id: int,
        marks: int
    ):
        self.evaluation_id = evaluation_id
        self.rubric_id = rubric_id
        self.marks = marks


# Notification Model
class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.String(1000), nullable=False)
    category = db.Column(db.String(50), default="info")  # success, warning, info, danger
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.String(30), nullable=False)

    user = db.relationship("User", backref="notifications")

    def __init__(self, user_id: int, title: str, message: str, category: str = "info", created_at: str = None):
        self.user_id = user_id
        self.title = title
        self.message = message
        self.category = category
        self.created_at = created_at


# Announcement Model
class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    target_role = db.Column(db.String(30), default="All")  # All, Student, Examiner
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.String(30), nullable=False)

    author = db.relationship("User", backref="announcements")

    def __init__(self, title: str, content: str, created_by: int, target_role: str = "All", created_at: str = None):
        self.title = title
        self.content = content
        self.created_by = created_by
        self.target_role = target_role
        self.created_at = created_at
