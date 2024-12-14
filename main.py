from flask import Flask, redirect, render_template, flash, request, url_for, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_required, logout_user, login_user, current_user
from flask_mail import Mail, Message
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import json
import os
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer
import pyotp

# App configuration
local_server = True
app = Flask(__name__)
app.secret_key = "qwerty"

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://root:@localhost/tradehubx'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # Added to suppress warning

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your-email@gmail.com'
app.config['MAIL_PASSWORD'] = 'your-email-password'
app.config['UPLOAD_FOLDER'] = 'static/uploads'  # Ensure the folder exists

# Initialize extensions
db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Updated database models to include necessary relationships
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_verified = db.Column(db.Boolean, default=False)
    account_type = db.Column(db.String(20), default='standard')
    bidding_points = db.Column(db.Integer, default=0)
    properties = db.relationship('Property', backref='seller', lazy=True)
    bids = db.relationship('Bid', backref='bidder', lazy=True)
    wishlist = db.relationship('WishlistItem', backref='user', lazy=True)

class Property(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    starting_price = db.Column(db.Float, nullable=False)
    current_price = db.Column(db.Float, nullable=False)
    images = db.Column(db.JSON)
    end_time = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, active, completed
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    bids = db.relationship('Bid', backref='property', lazy=True)

class Bid(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id'), nullable=False)

class WishlistItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id'), nullable=False)

class SellerRating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rater_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# Helper functions
def send_email(to, subject, template):
    msg = Message(
        subject,
        recipients=[to],
        html=template,
        sender=app.config['MAIL_USERNAME']
    )
    mail.send(msg)

def generate_otp():
    totp = pyotp.TOTP(pyotp.random_base32())
    return totp.now()

def generate_verification_token(email):
    serializer = URLSafeTimedSerializer(app.secret_key)
    return serializer.dumps(email, salt='email-confirm-salt')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route("/")
def home():
    return render_template("index.html")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if User.query.filter_by(email=email).first():
            flash('Email already registered')
            return redirect(url_for('register'))

        user = User(
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()

        token = generate_verification_token(email)
        verification_url = url_for('verify_email', token=token, _external=True)
        send_email(email, 'Verify your email', f'Click here to verify: {verification_url}')

        flash('Please check your email to verify your account')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            if not user.is_verified:
                flash('Please verify your email first')
                return redirect(url_for('login'))

            login_user(user)
            return redirect(url_for('dashboard'))

        flash('Invalid email or password')
    return render_template('login.html')

@app.route('/property/new', methods=['GET', 'POST'])
@login_required
def new_property():
    if request.method == 'POST':
        property = Property(
            title=request.form.get('title'),
            description=request.form.get('description'),
            starting_price=float(request.form.get('starting_price')),
            current_price=float(request.form.get('starting_price')),
            end_time=datetime.strptime(request.form.get('end_time'), '%Y-%m-%dT%H:%M'),
            seller=current_user
        )

        images = request.files.getlist('images')
        image_paths = []
        for image in images:
            if image:
                filename = secure_filename(image.filename)
                image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_paths.append(filename)
        property.images = json.dumps(image_paths)

        db.session.add(property)
        db.session.commit()

        flash('Property listed for auction pending admin approval')
        return redirect(url_for('dashboard'))

    return render_template('new_property.html')

@app.route('/verify_email/<token>')
def verify_email(token):
    serializer = URLSafeTimedSerializer(app.secret_key)
    try:
        email = serializer.loads(token, salt='email-confirm-salt', max_age=3600)
    except Exception:
        flash('The confirmation link is invalid or has expired.')
        return redirect(url_for('register'))

    user = User.query.filter_by(email=email).first()
    if user:
        user.is_verified = True
        db.session.commit()
        flash('Your email has been verified. You can now log in.')
    else:
        flash('Verification failed.')

    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(debug=True)
