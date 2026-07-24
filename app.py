from flask import Flask, render_template, redirect, url_for, flash, session, request
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from dotenv import load_dotenv
import bcrypt
import os
import uuid

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-this-secret')
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Supabase Client setup
SUPABASE_URL = os.getenv('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '').strip()

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY and 'your-supabase-project-id' not in SUPABASE_URL:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print("Supabase connection warning:", e)

# Allowed media upload types
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'avi', 'webm'}

try:
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
except Exception as fs_err:
    print("Serverless filesystem notice:", fs_err)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.template_filter('media_url')
def media_url_filter(filename):
    if not filename:
        return ''
    if filename.startswith('http://') or filename.startswith('https://'):
        return filename
    return f'/static/uploads/{filename}'


# ─────────────────── FORMS ───────────────────

class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=20)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[DataRequired(), EqualTo('password', message='Passwords must match')]
    )
    submit = SubmitField('Register')


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


# ─────────────────── ROUTES ───────────────────

@app.route('/')
def index():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('dashboard'))
        return redirect(url_for('client_news'))
    return render_template('index.html')


# ── REGISTER ──
@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()

    if form.validate_on_submit():
        username = form.username.data.strip()
        email = form.email.data.strip().lower()
        password_hash = bcrypt.hashpw(
            form.password.data.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')

        if not supabase:
            flash("Database not configured. Please set SUPABASE_URL and SUPABASE_KEY in .env.")
            return redirect(url_for('register'))

        try:
            # Check existing username or email
            res = supabase.table('users').select('id').or_(f"username.eq.{username},email.eq.{email}").execute()
            if res.data and len(res.data) > 0:
                flash("Username or Email already exists.")
                return redirect(url_for('register'))

            # Insert user
            supabase.table('users').insert({
                'username': username,
                'email': email,
                'password': password_hash,
                'role': 'client'
            }).execute()

            flash("Registration successful! Please login.")
            return redirect(url_for('login'))
        except Exception as e:
            print("Supabase Register Error:", e)
            flash(f"Error during registration: {e}")
            return redirect(url_for('register'))

    return render_template('register.html', form=form)


# ── LOGIN ──
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()

    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        password = form.password.data

        if not supabase:
            flash("Database not configured. Please set SUPABASE_URL and SUPABASE_KEY in .env.")
            return redirect(url_for('login'))

        try:
            res = supabase.table('users').select('*').eq('email', email).execute()
            user = res.data[0] if (res.data and len(res.data) > 0) else None

            if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']

                if user['role'] == 'admin':
                    return redirect(url_for('dashboard'))
                return redirect(url_for('client_news'))

            flash("Invalid Email or Password")
            return redirect(url_for('login'))
        except Exception as e:
            print("Supabase Login Error:", e)
            flash(f"Login error: {e}")
            return redirect(url_for('login'))

    return render_template('login.html', form=form)


# ── ADMIN DASHBOARD ──
@app.route('/dashboard')
def dashboard():
    if session.get('role') != 'admin':
        flash("Access denied.")
        return redirect(url_for('login'))

    news_list = []
    if supabase:
        try:
            res = supabase.table('news').select('*').order('created_at', desc=True).execute()
            news_list = res.data or []
        except Exception as e:
            print("Dashboard Fetch Error:", e)
            flash(f"Error fetching news: {e}")

    return render_template('dashboard.html', news=news_list, username=session.get('username'))


# ── ADD NEWS ──
@app.route('/add_news', methods=['POST'])
def add_news():
    if session.get('role') != 'admin':
        flash("Access denied.")
        return redirect(url_for('login'))

    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    hours = int(request.form.get('expires_in', 24))

    media_filename = None
    media_type = 'none'

    file = request.files.get('media')
    if file and file.filename != '' and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        unique_name = str(uuid.uuid4()) + '.' + ext
        file_bytes = file.read()

        uploaded_to_supabase = False
        if supabase:
            try:
                # Attempt upload to Supabase Storage bucket 'news-media'
                content_type = file.content_type or ('image/' + ext if ext in {'png', 'jpg', 'jpeg', 'gif'} else 'video/' + ext)
                supabase.storage.from_('news-media').upload(
                    path=unique_name,
                    file=file_bytes,
                    file_options={"content-type": content_type}
                )
                media_filename = supabase.storage.from_('news-media').get_public_url(unique_name)
                uploaded_to_supabase = True
            except Exception as st_err:
                print("Supabase Storage upload warning (falling back to local):", st_err)

        if not uploaded_to_supabase:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
            with open(file_path, 'wb') as f:
                f.write(file_bytes)
            media_filename = unique_name

        if ext in {'png', 'jpg', 'jpeg', 'gif'}:
            media_type = 'image'
        elif ext in {'mp4', 'mov', 'avi', 'webm'}:
            media_type = 'video'

    expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()

    if not supabase:
        flash("Database connection missing.")
        return redirect(url_for('dashboard'))

    try:
        supabase.table('news').insert({
            'title': title,
            'content': content,
            'expires_at': expires_at,
            'media_filename': media_filename,
            'media_type': media_type
        }).execute()
        flash("News added successfully.")
    except Exception as e:
        print("Add News DB Error:", e)
        flash(f"Error adding news: {e}")

    return redirect(url_for('dashboard'))


# ── DELETE NEWS ──
@app.route('/delete_news/<int:news_id>')
def delete_news(news_id):
    if session.get('role') != 'admin':
        flash("Access denied.")
        return redirect(url_for('login'))

    if not supabase:
        flash("Database connection missing.")
        return redirect(url_for('dashboard'))

    try:
        res = supabase.table('news').select('media_filename').eq('id', news_id).execute()
        if res.data and len(res.data) > 0:
            media = res.data[0].get('media_filename')
            if media and not media.startswith('http'):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], media)
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass

        supabase.table('news').delete().eq('id', news_id).execute()
        flash("News deleted.")
    except Exception as e:
        print("Delete News Error:", e)
        flash(f"Error deleting news: {e}")

    return redirect(url_for('dashboard'))


# ── EDIT NEWS ──
@app.route('/edit_news/<int:news_id>', methods=['GET', 'POST'])
def edit_news(news_id):
    if session.get('role') != 'admin':
        flash("Access denied.")
        return redirect(url_for('login'))

    if not supabase:
        flash("Database connection missing.")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        try:
            supabase.table('news').update({
                'title': title,
                'content': content
            }).eq('id', news_id).execute()
            flash("News updated.")
            return redirect(url_for('dashboard'))
        except Exception as e:
            print("Update News Error:", e)
            flash(f"Error updating news: {e}")
            return redirect(url_for('dashboard'))

    try:
        res = supabase.table('news').select('*').eq('id', news_id).execute()
        news = res.data[0] if (res.data and len(res.data) > 0) else None
        if not news:
            flash("News article not found.")
            return redirect(url_for('dashboard'))
        return render_template('edit_news.html', news=news)
    except Exception as e:
        print("Edit News Fetch Error:", e)
        flash(f"Error fetching news item: {e}")
        return redirect(url_for('dashboard'))


# ── CLIENT NEWS ──
@app.route('/news')
def client_news():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'client':
        return redirect(url_for('dashboard'))

    news_list = []
    if supabase:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            res = supabase.table('news').select('*').or_(f"expires_at.is.null,expires_at.gt.{now_iso}").order('created_at', desc=True).execute()
            news_list = res.data or []
        except Exception as e:
            print("Client News Fetch Error:", e)
            flash(f"Error loading news feed: {e}")

    return render_template('news.html', news=news_list, username=session.get('username'))


# ── LOGOUT ──
@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for('login'))


if __name__ == "__main__":
    app.run(debug=True)