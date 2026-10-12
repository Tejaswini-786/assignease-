import os
from datetime import datetime, date
from flask import Flask, render_template, redirect, url_for, flash, request, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, SelectField, DateField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from config import Config

app = Flask(__name__, template_folder="Templates")
app.config.from_object(Config)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- DATABASE MODELS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    assignments = db.relationship('Assignment', backref='author', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    subject = db.Column(db.String(64), nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    priority = db.Column(db.String(20), default='Medium')
    status = db.Column(db.String(20), default='Pending')
    filename = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- FORMS ---
class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Create Account')

    def validate_username(self, username):
        if User.query.filter_by(username=username.data).first():
            raise ValidationError('This username is already taken.')

    def validate_email(self, email):
        if User.query.filter_by(email=email.data).first():
            raise ValidationError('This email is already registered.')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Sign In')

class AssignmentForm(FlaskForm):
    title = StringField('Assignment Title', validators=[DataRequired(), Length(max=120)])
    subject = StringField('Subject', validators=[DataRequired(), Length(max=64)])
    description = TextAreaField('Description')
    due_date = DateField('Due Date', format='%Y-%m-%d', validators=[DataRequired()])
    priority = SelectField('Priority', choices=[('Low', 'Low'), ('Medium', 'Medium'), ('High', 'High')])
    status = SelectField('Status', choices=[('Pending', 'Pending'), ('Submitted', 'Submitted'), ('Completed', 'Completed')])
    file = FileField('Attachment (Optional)', validators=[FileAllowed(['pdf', 'docx', 'zip', 'png', 'jpg'], 'Documents and images only!')])
    submit = SubmitField('Save Assignment')

# --- ROUTES ---
@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template("index.html", title="Welcome")

@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template("register.html", title="Register", form=form)

@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            flash('Welcome back to AssignEase!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template("login.html", title="Login", form=form)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('home'))

@app.route("/dashboard")
@login_required
def dashboard():
    assignments = Assignment.query.filter_by(user_id=current_user.id).all()
    total = len(assignments)
    pending = sum(1 for a in assignments if a.status == 'Pending')
    completed = sum(1 for a in assignments if a.status == 'Completed')
    submitted = sum(1 for a in assignments if a.status == 'Submitted')
    
    today = date.today()
    overdue = sum(1 for a in assignments if a.due_date < today and a.status != 'Completed')
    upcoming = sorted([a for a in assignments if a.status != 'Completed' and a.due_date >= today], key=lambda x: x.due_date)[:5]

    return render_template("dashboard.html", title="Dashboard", 
                           total=total, pending=pending, completed=completed, 
                           submitted=submitted, overdue=overdue, upcoming=upcoming)

@app.route("/assignments")
@login_required
def assignments():
    status_filter = request.args.get('status', 'All')
    search_query = request.args.get('q', '')
    
    query = Assignment.query.filter_by(user_id=current_user.id)
    if status_filter != 'All':
        query = query.filter_by(status=status_filter)
    if search_query:
        query = query.filter(Assignment.title.ilike(f'%{search_query}%') | Assignment.subject.ilike(f'%{search_query}%'))
        
    user_assignments = query.order_by(Assignment.due_date.asc()).all()
    return render_template("assignments.html", title="Assignments", assignments=user_assignments, status_filter=status_filter, search_query=search_query)

@app.route("/assignments/new", methods=['GET', 'POST'])
@login_required
def new_assignment():
    form = AssignmentForm()
    if form.validate_on_submit():
        filename = None
        if form.file.data:
            f = form.file.data
            filename = secure_filename(f.filename)
            filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        assignment = Assignment(
            title=form.title.data,
            subject=form.subject.data,
            description=form.description.data,
            due_date=form.due_date.data,
            priority=form.priority.data,
            status=form.status.data,
            filename=filename,
            author=current_user
        )
        db.session.add(assignment)
        db.session.commit()
        flash('Assignment created successfully!', 'success')
        return redirect(url_for('assignments'))
    return render_template("assignment_form.html", title="New Assignment", form=form, legend="New Assignment")

@app.route("/assignments/<int:assignment_id>/edit", methods=['GET', 'POST'])
@login_required
def edit_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    if assignment.author != current_user:
        abort(403)
    form = AssignmentForm()
    if form.validate_on_submit():
        assignment.title = form.title.data
        assignment.subject = form.subject.data
        assignment.description = form.description.data
        assignment.due_date = form.due_date.data
        assignment.priority = form.priority.data
        assignment.status = form.status.data
        
        if form.file.data:
            f = form.file.data
            filename = secure_filename(f.filename)
            filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            assignment.filename = filename

        db.session.commit()
        flash('Assignment updated successfully!', 'success')
        return redirect(url_for('assignments'))
    elif request.method == 'GET':
        form.title.data = assignment.title
        form.subject.data = assignment.subject
        form.description.data = assignment.description
        form.due_date.data = assignment.due_date
        form.priority.data = assignment.priority
        form.status.data = assignment.status
    return render_template("assignment_form.html", title="Edit Assignment", form=form, legend="Edit Assignment")

@app.route("/assignments/<int:assignment_id>/delete", methods=['POST'])
@login_required
def delete_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    if assignment.author != current_user:
        abort(403)
    db.session.delete(assignment)
    db.session.commit()
    flash('Assignment deleted successfully!', 'success')
    return redirect(url_for('assignments'))

@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=8000)