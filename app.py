from flask import Flask, render_template, redirect, url_for, flash, session, request
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo
from flask_mysqldb import MySQL
from werkzeug.utils import secure_filename
import bcrypt
import os
import uuid

app = Flask(__name__)

app.config['SECRET_KEY'] = 'change-this-secret'
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'jiit'
app.config['MYSQL_DB'] = 'news_app'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Image aur Video dono allowed
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'avi', 'webm'}

csrf = CSRFProtect(app)
mysql = MySQL(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


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

        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT id FROM users WHERE username = %s OR email = %s",
            (username, email)
        )
        existing = cur.fetchone()

        if existing:
            cur.close()
            flash("Username or Email already exists.")
            return redirect(url_for('register'))

        cur.execute(
            "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
            (username, email, password_hash)
        )
        mysql.connection.commit()
        cur.close()

        flash("Registration successful! Please login.")
        return redirect(url_for('login'))

    return render_template('register.html', form=form)


# ── LOGIN ──
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()

    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        password = form.password.data

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()

        if user and bcrypt.checkpw(
            password.encode('utf-8'),
            user['password'].encode('utf-8')
        ):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']

            if user['role'] == 'admin':
                return redirect(url_for('dashboard'))
            return redirect(url_for('client_news'))

        flash("Invalid Email or Password")
        return redirect(url_for('login'))

    return render_template('login.html', form=form)


# ── ADMIN DASHBOARD ──
@app.route('/dashboard')
def dashboard():
    if session.get('role') != 'admin':
        flash("Access denied.")
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM news ORDER BY created_at DESC")
    news_list = cur.fetchall()
    cur.close()

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

    # File upload handle karo
    file = request.files.get('media')
    if file and file.filename != '' and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        unique_name = str(uuid.uuid4()) + '.' + ext
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
        media_filename = unique_name

        # Image ya video detect karo
        if ext in {'png', 'jpg', 'jpeg', 'gif'}:
            media_type = 'image'
        elif ext in {'mp4', 'mov', 'avi', 'webm'}:
            media_type = 'video'

    try:
        cur = mysql.connection.cursor()
        cur.execute(
            """INSERT INTO news (title, content, expires_at, media_filename, media_type)
               VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL %s HOUR), %s, %s)""",
            (title, content, hours, media_filename, media_type)
        )
        mysql.connection.commit()
        cur.close()
        flash("News added successfully.")
    except Exception as e:
        print("DB ERROR:", e)
        flash(f"Error: {e}")

    return redirect(url_for('dashboard'))


# ── DELETE NEWS ──
@app.route('/delete_news/<int:news_id>')
def delete_news(news_id):
    if session.get('role') != 'admin':
        flash("Access denied.")
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()

    # Pehle file ka naam lo
    cur.execute("SELECT media_filename FROM news WHERE id = %s", (news_id,))
    news = cur.fetchone()

    # File disk se bhi delete karo
    if news and news['media_filename']:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], news['media_filename'])
        if os.path.exists(file_path):
            os.remove(file_path)

    cur.execute("DELETE FROM news WHERE id = %s", (news_id,))
    mysql.connection.commit()
    cur.close()

    flash("News deleted.")
    return redirect(url_for('dashboard'))


# ── EDIT NEWS ──
@app.route('/edit_news/<int:news_id>', methods=['GET', 'POST'])
def edit_news(news_id):
    if session.get('role') != 'admin':
        flash("Access denied.")
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        cur.execute(
            "UPDATE news SET title = %s, content = %s WHERE id = %s",
            (title, content, news_id)
        )
        mysql.connection.commit()
        cur.close()
        flash("News updated.")
        return redirect(url_for('dashboard'))

    cur.execute("SELECT * FROM news WHERE id = %s", (news_id,))
    news = cur.fetchone()
    cur.close()

    return render_template('edit_news.html', news=news)


# ── CLIENT NEWS ──
@app.route('/news')
def client_news():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'client':
        return redirect(url_for('dashboard'))

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT * FROM news
        WHERE expires_at IS NULL OR expires_at > NOW()
        ORDER BY created_at DESC
    """)
    news_list = cur.fetchall()
    cur.close()

    return render_template('news.html', news=news_list, username=session.get('username'))


# ── LOGOUT ──
@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for('login'))


if __name__ == "__main__":
    app.run(debug=True)