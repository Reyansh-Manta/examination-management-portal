from flask import render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from database import db
from models import User


def register_auth_routes(app):

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            name = request.form.get("name")
            email = request.form.get("email")
            password = request.form.get("password")

            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash("Email already registered!")
                return redirect(url_for("register"))

            hashed_password = generate_password_hash(password, method="pbkdf2:sha256")
            new_user = User(
                name=name,
                email=email,
                password_hash=hashed_password,
                role="Student"
            )
            new_user.is_approved = True

            db.session.add(new_user)
            db.session.commit()

            flash("Account created. Please sign in.")
            return redirect(url_for("login"))

        return render_template("register.html")

    @app.route("/examiner_register", methods=["GET", "POST"])
    def examiner_register():
        if request.method == "POST":
            name = request.form.get("name")
            email = request.form.get("email")
            password = request.form.get("password")

            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash("Email already registered!")
                return redirect(url_for("examiner_register"))

            hashed_password = generate_password_hash(password, method="pbkdf2:sha256")
            new_examiner = User(
                name=name,
                email=email,
                password_hash=hashed_password,
                role="Examiner"
            )
            new_examiner.is_approved = False

            db.session.add(new_examiner)
            db.session.commit()

            flash("Registration submitted. Awaiting admin approval.")
            return redirect(url_for("examiner_register"))

        return render_template("examiner_register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email")
            password = request.form.get("password")

            user = User.query.filter_by(email=email).first()

            if user and check_password_hash(user.password_hash, password):
                if not user.is_active:
                    flash("Your account has been deactivated.")
                    return redirect(url_for("login"))

                if user.role == "Examiner" and not user.is_approved:
                    flash("Your account is waiting for Admin approval.")
                    return redirect(url_for("login"))

                session["user_id"] = user.id
                session["role"] = user.role
                session["user_role"] = user.role
                session["user_name"] = user.name

                flash("Welcome back!")

                if user.role == "Admin":
                    return redirect(url_for("admin_dashboard"))
                elif user.role == "Examiner":
                    return redirect(url_for("examiner_dashboard"))
                elif user.role == "Student":
                    return redirect(url_for("student_dashboard"))
            else:
                flash("Invalid email or password!")

        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("Signed out.")
        return redirect(url_for("login"))
