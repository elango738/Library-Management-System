from flask import Flask, render_template, request, redirect, url_for, flash, abort
from datetime import datetime, timedelta
from models import db, Book, Borrower, Loan, User
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash
import os
import re
from models import NotificationLog
import importlib
try:
    _apscheduler_sched = importlib.import_module('apscheduler.schedulers.background')
    BackgroundScheduler = getattr(_apscheduler_sched, 'BackgroundScheduler', None)
    _apscheduler_triggers = importlib.import_module('apscheduler.triggers.cron')
    CronTrigger = getattr(_apscheduler_triggers, 'CronTrigger', None)
except Exception:
    BackgroundScheduler = None
    CronTrigger = None


def create_app(config_overrides=None):
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'dev-secret-key'
    # fine per overdue day in currency units (Rs.) — configurable via instance/config.py
    app.config.setdefault('FINE_PER_DAY', 5)

    if config_overrides:
        app.config.update(config_overrides)

    db.init_app(app)

    with app.app_context():
        # Automate DB creation
        db.create_all()

    # Inject helpers into Jinja templates
    @app.context_processor
    def inject_now():
        from datetime import datetime
        # make now() available in templates so layout.html can call now().year
        return {'now': datetime.utcnow}

    # Setup LoginManager
    login_manager = LoginManager()
    login_manager.login_view = 'login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Auto-create a default admin if none exists (change credentials after first run)
    with app.app_context():
        try:
            admin = User.query.filter_by(role='admin').first()
            if not admin:
                default_admin = User(username='admin', role='admin')
                default_admin.set_password('admin')
                db.session.add(default_admin)
                db.session.commit()
                print('Created default admin: username=admin password=admin — please change this password immediately')
        except Exception:
            # if migrations or db issues occur, ignore here
            pass

    # --------------------- SMS helpers ---------------------
    # Only send to Indian mobile numbers (10-digit starting with 6-9) or numbers starting with +91
    INDIAN_RE = re.compile(r'^(?:\+91|91|0)?([6-9]\d{9})$')

    def normalize_indian_number(number: str):
        if not number:
            return None
        number = re.sub(r"[^0-9+]", "", number)
        m = INDIAN_RE.match(number)
        if not m:
            return None
        return '+91' + m.group(1)

    def send_sms_and_log(phone: str, message: str, event: str = None, loan: Loan = None):
        """Simulate sending SMS and record NotificationLog (no external provider).
        This implementation only accepts Indian numbers, prints the message to console
        and records a NotificationLog with status 'simulated'."""
        normalized = normalize_indian_number(phone)
        if not normalized:
            nl = NotificationLog(phone=phone or '', message=message, event=event, loan_id=getattr(loan, 'id', None), status='invalid-number', error='Not an Indian mobile number')
            db.session.add(nl)
            db.session.commit()
            return False

        to_number = normalized
        # simulated send
        print(f'[SMS-SIM] To: {to_number} Message: {message}')
        nl = NotificationLog(phone=to_number, message=message, event=event, loan_id=getattr(loan, 'id', None), status='simulated', error=None)
        db.session.add(nl)
        db.session.commit()
        return True
    # expose helpers on app for easier access from scripts/tests
    app.normalize_indian_number = normalize_indian_number
    app.send_sms_and_log = send_sms_and_log
    # ------------------- end SMS helpers -------------------

    def send_overdue_notifications():
        """Scan overdue loans and send SMS notifications. Returns (attempted, sent)."""
        with app.app_context():
            now = datetime.utcnow()
            overdue = Loan.query.filter(Loan.due_date < now, Loan.return_date == None).all()
            sent = 0
            for loan in overdue:
                borrower = Borrower.query.get(loan.borrower_id)
                book = Book.query.get(loan.book_id)
                if borrower and borrower.phone:
                    days = (now.date() - loan.due_date.date()).days if loan.due_date else 0
                    msg = f'Overdue: "{book.title}" was due on {loan.due_date.date()}. Overdue by {days} days. Please return and pay any fines.'
                    if send_sms_and_log(borrower.phone, msg, event='overdue', loan=loan):
                        sent += 1
            return len(overdue), sent

    # Scheduler: run send_overdue_notifications daily if enabled via app config (instance/config.py)
    enable_sched = app.config.get('ENABLE_SCHEDULER') or os.environ.get('ENABLE_SCHEDULER')
    if enable_sched and BackgroundScheduler and CronTrigger:
        try:
            sched_hour = app.config.get('SCHEDULE_HOUR') or os.environ.get('SCHEDULE_HOUR') or '9'
            # accept format 'HH' or 'HH:MM'
            hh, mm = (sched_hour.split(':') + ['0'])[:2]
            hh = int(hh) % 24
            mm = int(mm) % 60
            scheduler = BackgroundScheduler()
            trigger = CronTrigger(hour=hh, minute=mm)
            scheduler.add_job(send_overdue_notifications, trigger, id='overdue_notifications')
            scheduler.start()
            print(f'APScheduler started — overdue_notifications scheduled daily at {hh:02d}:{mm:02d}')
            app.scheduler = scheduler
        except Exception as e:
            print('Failed to start scheduler:', e)
    # expose for tests
    app.send_overdue_notifications = send_overdue_notifications

    # (SMS runs are simulated; no external provider checks performed)

    @app.route('/')
    def home():
        return redirect(url_for('list_books'))

    # Books
    @app.route('/books')
    def list_books():
        q = request.args.get('q', '').strip()
        if q:
            books = Book.query.filter(
                (Book.title.ilike(f'%{q}%')) |
                (Book.author.ilike(f'%{q}%')) |
                (Book.isbn.ilike(f'%{q}%'))
            ).all()
        else:
            books = Book.query.order_by(Book.title).all()
        return render_template('books.html', books=books, q=q)


    @app.route('/books/add', methods=['GET', 'POST'])
    def add_book():
        # only admins can add books
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)

        if request.method == 'POST':
            data = request.form
            book = Book(
                title=data.get('title','').strip(),
                author=data.get('author','').strip(),
                isbn=data.get('isbn','').strip(),
                publisher=data.get('publisher','').strip(),
                year=data.get('year') or None,
                copies_total=int(data.get('copies_total') or 1),
                copies_available=int(data.get('copies_total') or 1)
            )
            db.session.add(book)
            db.session.commit()
            flash('Book added', 'success')
            return redirect(url_for('list_books'))
        return render_template('add_book.html')

    @app.route('/books/<int:book_id>/delete', methods=['POST'])
    def delete_book(book_id):
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)

        book = Book.query.get_or_404(book_id)
        db.session.delete(book)
        db.session.commit()
        flash('Book deleted', 'info')
        return redirect(url_for('list_books'))

    # Borrowers
    @app.route('/borrowers')
    def list_borrowers():
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        borrowers = Borrower.query.order_by(Borrower.name).all()
        return render_template('borrowers.html', borrowers=borrowers)

    @app.route('/borrowers/add', methods=['GET', 'POST'])
    def add_borrower():
        # only admins can add borrowers via this route
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)

        if request.method == 'POST':
            data = request.form
            b = Borrower(
                name=data.get('name','').strip(),
                email=data.get('email','').strip(),
                phone=data.get('phone','').strip(),
                member_id=data.get('member_id','').strip()
            )
            db.session.add(b)
            db.session.commit()
            flash('Borrower added', 'success')
            return redirect(url_for('list_borrowers'))
        return render_template('add_borrower.html')

    # Issue and Return
    @app.route('/issue', methods=['GET','POST'])
    def issue_book():
        # only logged-in users can issue books
        if not current_user.is_authenticated:
            return redirect(url_for('login', next=request.path))

        if request.method == 'POST':
            book_id = int(request.form.get('book_id'))
            duration_days = int(request.form.get('duration_days') or 14)

            # determine borrower: admin may choose borrower, normal user uses own borrower record
            if current_user.role == 'admin':
                borrower_id = int(request.form.get('borrower_id'))
            else:
                if not current_user.borrower_id:
                    flash('No borrower profile attached to your account', 'danger')
                    return redirect(url_for('list_books'))
                borrower_id = current_user.borrower_id

            book = Book.query.get_or_404(book_id)
            if book.copies_available < 1:
                flash('No copies available', 'danger')
                return redirect(url_for('list_books'))
            loan = Loan(
                book_id=book_id,
                borrower_id=borrower_id,
                issue_date=datetime.utcnow(),
                due_date=datetime.utcnow() + timedelta(days=duration_days)
            )
            book.copies_available -= 1
            db.session.add(loan)
            db.session.commit()
            # send SMS notification to borrower if they have an Indian phone number
            try:
                borrower = Borrower.query.get(borrower_id)
                if borrower and borrower.phone:
                    msg = f'Book issued: "{book.title}". Due on {loan.due_date.date()}.'
                    send_sms_and_log(borrower.phone, msg, event='issued', loan=loan)
            except Exception:
                pass
            flash('Book issued', 'success')
            return redirect(url_for('list_books'))

        # allow preselecting a book via query param (books list links to ?book_id=)
        selected_book_id = request.args.get('book_id', type=int)
        books = Book.query.filter(Book.copies_available > 0).all()
        borrowers = []
        if current_user.role == 'admin':
            borrowers = Borrower.query.all()
        return render_template('issue_return.html', books=books, borrowers=borrowers, selected_book_id=selected_book_id)

    @app.route('/return/<int:loan_id>', methods=['GET', 'POST'])
    @login_required
    def return_book(loan_id):
        loan = Loan.query.get_or_404(loan_id)
        # only admin or owning borrower can return
        if current_user.role != 'admin' and loan.borrower_id != current_user.borrower_id:
            abort(403)

        # If GET: show confirmation page with fine calculation
        if request.method == 'GET':
            if loan.return_date:
                flash('Already returned', 'info')
                return redirect(url_for('view_loans'))

            now = datetime.utcnow()
            overdue_days = 0
            if loan.due_date and now.date() > loan.due_date.date():
                overdue_days = (now.date() - loan.due_date.date()).days
            fine_per_day = app.config.get('FINE_PER_DAY', 0) or 0
            fine_amount = overdue_days * fine_per_day
            return render_template('return_confirm.html', loan=loan, overdue_days=overdue_days, fine_amount=fine_amount)

        # POST: perform the return
        if loan.return_date:
            flash('Already returned', 'info')
            return redirect(url_for('view_loans'))

        loan.return_date = datetime.utcnow()
        book = Book.query.get(loan.book_id)
        if book:
            book.copies_available += 1

        # compute fine for informational purposes (not stored in DB for now)
        now = datetime.utcnow()
        overdue_days = 0
        if loan.due_date and now.date() > loan.due_date.date():
            overdue_days = (now.date() - loan.due_date.date()).days
        fine_per_day = app.config.get('FINE_PER_DAY', 0) or 0
        fine_amount = overdue_days * fine_per_day

        db.session.commit()

        # send SMS notification about return and any fine due
        try:
            borrower = Borrower.query.get(loan.borrower_id)
            if borrower and borrower.phone:
                if fine_amount > 0:
                    msg = f'Book returned: "{book.title}". Overdue by {overdue_days} days. Fine due: Rs. {fine_amount}. Please pay at the library.'
                else:
                    msg = f'Book returned: "{book.title}". Thank you.'
                send_sms_and_log(borrower.phone, msg, event='returned', loan=loan)
        except Exception:
            pass

        if fine_amount > 0:
            flash(f'Book returned. Fine due: Rs. {fine_amount}. Use the Pay Fine action on the loans page.', 'warning')
        else:
            flash('Book returned', 'success')
        return redirect(url_for('view_loans'))

    @app.route('/loans')
    def view_loans():
        if not current_user.is_authenticated:
            return redirect(url_for('login', next=request.path))

        if current_user.role == 'admin':
            loans = Loan.query.order_by(Loan.issue_date.desc()).all()
        else:
            loans = Loan.query.filter_by(borrower_id=current_user.borrower_id).order_by(Loan.issue_date.desc()).all()
        return render_template('loans.html', loans=loans)

    # Admin endpoint to run overdue notifications manually (or via cron)
    @app.route('/admin/notify/due')
    def admin_notify_due():
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        now = datetime.utcnow()
        overdue = Loan.query.filter(Loan.due_date < now, Loan.return_date == None).all()
        sent = 0
        for loan in overdue:
            borrower = Borrower.query.get(loan.borrower_id)
            book = Book.query.get(loan.book_id)
            if borrower and borrower.phone:
                days = (now.date() - loan.due_date.date()).days if loan.due_date else 0
                msg = f'Overdue: "{book.title}" was due on {loan.due_date.date()}. Overdue by {days} days. Please return and pay any fines.'
                if send_sms_and_log(borrower.phone, msg, event='overdue', loan=loan):
                    sent += 1
        flash(f'Overdue notifications processed, attempted: {len(overdue)}, sent: {sent}', 'info')
        return redirect(url_for('admin_csv'))

    # Endpoint to mark fine paid (simple placeholder): sends SMS to borrower
    @app.route('/loans/<int:loan_id>/pay_fine', methods=['POST'])
    @login_required
    def pay_fine(loan_id):
        loan = Loan.query.get_or_404(loan_id)
        # authorization: user must be admin or owning borrower
        if current_user.role != 'admin' and loan.borrower_id != current_user.borrower_id:
            abort(403)
        # For now, we don't track payments in DB; just send notification and log
        borrower = Borrower.query.get(loan.borrower_id)
        book = Book.query.get(loan.book_id)
        if borrower and borrower.phone:
            msg = f'Payment received for fines related to "{book.title}". Thank you.'
            send_sms_and_log(borrower.phone, msg, event='fine_paid', loan=loan)
        flash('Fine payment recorded (placeholder). SMS notification sent.', 'success')
        return redirect(url_for('view_loans'))

    # Authentication routes
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form.get('username','').strip()
            password = request.form.get('password','')
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                login_user(user)
                flash('Logged in', 'success')
                next_page = request.args.get('next') or url_for('list_books')
                return redirect(next_page)
            flash('Invalid credentials', 'danger')
        return render_template('login.html')

    @app.route('/logout')
    def logout():
        logout_user()
        flash('Logged out', 'info')
        return redirect(url_for('list_books'))

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        # allow new borrowers to self-register and create linked user
        if request.method == 'POST':
            username = request.form.get('username','').strip()
            password = request.form.get('password','')
            name = request.form.get('name','').strip()
            if User.query.filter_by(username=username).first():
                flash('Username taken', 'danger')
                return render_template('register.html')
            borrower = Borrower(name=name)
            db.session.add(borrower)
            db.session.flush()
            user = User(username=username, role='user', borrower_id=borrower.id)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash('Registered and logged in', 'success')
            return redirect(url_for('list_books'))
        return render_template('register.html')

    # --- CSV import/export admin pages ---
    from io import StringIO
    import csv
    from flask import Response

    @app.route('/admin/csv')
    def admin_csv():
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        return render_template('admin_csv.html')

    @app.route('/admin/notifications')
    def admin_notifications():
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        notifications = NotificationLog.query.order_by(NotificationLog.sent_at.desc()).limit(200).all()
        return render_template('admin_notifications.html', notifications=notifications)


    

    @app.route('/admin/notifications/<int:notif_id>/retry', methods=['POST'])
    def admin_retry_notification(notif_id):
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        n = NotificationLog.query.get_or_404(notif_id)
        # attempt to resend the original message to the stored phone
        success = send_sms_and_log(n.phone, n.message, event=(n.event or 'retry'), loan=Loan.query.get(n.loan_id) if n.loan_id else None)
        flash(f'Retry attempted: success={bool(success)}', 'info')
        return redirect(url_for('admin_notifications'))

    @app.route('/admin/import/books', methods=['POST'])
    def admin_import_books():
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        f = request.files.get('file')
        if not f:
            flash('No file uploaded', 'danger')
            return redirect(url_for('admin_csv'))

        stream = StringIO(f.stream.read().decode('utf-8'))
        reader = csv.DictReader(stream)
        created = 0
        updated = 0
        errors = []
        for i, row in enumerate(reader, start=1):
            try:
                title = (row.get('title') or '').strip()
                if not title:
                    raise ValueError('title is required')
                author = (row.get('author') or '').strip()
                isbn = (row.get('isbn') or '').strip()
                publisher = (row.get('publisher') or '').strip()
                year = row.get('year')
                year = int(year) if year else None
                copies = int(row.get('copies_total') or row.get('copies') or 1)

                # try to find by ISBN if present, else by title+author
                book = None
                if isbn:
                    book = Book.query.filter_by(isbn=isbn).first()
                if not book:
                    book = Book.query.filter_by(title=title, author=author).first()

                if book:
                    book.publisher = publisher
                    book.year = year
                    # update totals and available accordingly (simple strategy)
                    diff = copies - (book.copies_total or 0)
                    book.copies_total = copies
                    book.copies_available = max(0, (book.copies_available or 0) + diff)
                    updated += 1
                else:
                    book = Book(title=title, author=author, isbn=isbn, publisher=publisher, year=year, copies_total=copies, copies_available=copies)
                    db.session.add(book)
                    created += 1
            except Exception as e:
                errors.append(f'Row {i}: {e}')

        db.session.commit()
        flash(f'Import finished — created: {created}, updated: {updated}', 'success')
        if errors:
            flash('Errors: ' + '; '.join(errors[:5]), 'danger')
        return redirect(url_for('admin_csv'))

    @app.route('/admin/export/books')
    def admin_export_books():
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        si = StringIO()
        writer = csv.writer(si)
        writer.writerow(['id','title','author','isbn','publisher','year','copies_total','copies_available'])
        for b in Book.query.order_by(Book.title).all():
            writer.writerow([b.id, b.title, b.author, b.isbn, b.publisher, b.year or '', b.copies_total or 0, b.copies_available or 0])
        output = si.getvalue()
        return Response(output, mimetype='text/csv', headers={"Content-Disposition":"attachment;filename=books.csv"})

    @app.route('/admin/import/borrowers', methods=['POST'])
    def admin_import_borrowers():
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        f = request.files.get('file')
        if not f:
            flash('No file uploaded', 'danger')
            return redirect(url_for('admin_csv'))

        stream = StringIO(f.stream.read().decode('utf-8'))
        reader = csv.DictReader(stream)
        created = 0
        updated = 0
        errors = []
        for i, row in enumerate(reader, start=1):
            try:
                name = (row.get('name') or '').strip()
                if not name:
                    raise ValueError('name is required')
                email = (row.get('email') or '').strip()
                phone = (row.get('phone') or '').strip()
                member_id = (row.get('member_id') or '').strip()

                borrower = None
                if member_id:
                    borrower = Borrower.query.filter_by(member_id=member_id).first()
                if not borrower and phone:
                    borrower = Borrower.query.filter_by(phone=phone).first()
                if not borrower and email:
                    borrower = Borrower.query.filter_by(email=email).first()

                # if we found a borrower, but the phone conflicts with another borrower, raise error
                if borrower:
                    # check phone conflict
                    if phone:
                        other = Borrower.query.filter(Borrower.phone == phone, Borrower.id != borrower.id).first()
                        if other:
                            raise ValueError(f'phone {phone} already used by another borrower (id {other.id})')
                    borrower.name = name
                    borrower.email = email
                    borrower.phone = phone
                    borrower.member_id = member_id
                    updated += 1
                else:
                    # ensure no existing borrower uses the phone
                    if phone and Borrower.query.filter_by(phone=phone).first():
                        raise ValueError(f'phone {phone} already exists')
                    borrower = Borrower(name=name, email=email, phone=phone, member_id=member_id)
                    db.session.add(borrower)
                    created += 1
            except Exception as e:
                errors.append(f'Row {i}: {e}')

        db.session.commit()
        flash(f'Borrowers import finished — created: {created}, updated: {updated}', 'success')
        if errors:
            flash('Errors: ' + '; '.join(errors[:5]), 'danger')
        return redirect(url_for('admin_csv'))

    @app.route('/admin/export/borrowers')
    def admin_export_borrowers():
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        si = StringIO()
        writer = csv.writer(si)
        writer.writerow(['id','name','email','phone','member_id','created_at'])
        for b in Borrower.query.order_by(Borrower.name).all():
            writer.writerow([b.id, b.name, b.email or '', b.phone or '', b.member_id or '', b.created_at.isoformat() if b.created_at else ''])
        output = si.getvalue()
        return Response(output, mimetype='text/csv', headers={"Content-Disposition":"attachment;filename=borrowers.csv"})

    @app.route('/profile', methods=['GET', 'POST'])
    @login_required
    def profile():
        # allow user to view/edit their borrower profile
        borrower = None
        if current_user.borrower_id:
            borrower = Borrower.query.get(current_user.borrower_id)

        if request.method == 'POST':
            name = request.form.get('name','').strip()
            email = request.form.get('email','').strip()
            phone = request.form.get('phone','').strip()

            # ensure phone uniqueness among borrowers
            if phone:
                other = Borrower.query.filter(Borrower.phone == phone)
                if borrower:
                    other = other.filter(Borrower.id != borrower.id)
                other = other.first()
                if other:
                    flash('Phone number already used by another user', 'danger')
                    return render_template('profile.html', borrower=borrower)

            if not borrower:
                # create borrower profile and link to user
                borrower = Borrower(name=name, email=email, phone=phone)
                db.session.add(borrower)
                db.session.flush()
                current_user.borrower_id = borrower.id
                db.session.add(current_user)
            else:
                borrower.name = name
                borrower.email = email
                borrower.phone = phone

            db.session.commit()
            flash('Profile saved', 'success')
            return redirect(url_for('profile'))

        return render_template('profile.html', borrower=borrower)

    @app.route('/change_password', methods=['GET', 'POST'])
    @login_required
    def change_password():
        if request.method == 'POST':
            current_password = request.form.get('current_password','')
            new_password = request.form.get('new_password','')
            confirm_password = request.form.get('confirm_password','')

            if not current_user.check_password(current_password):
                flash('Current password is incorrect', 'danger')
                return render_template('change_password.html')
            if new_password != confirm_password:
                flash('New password and confirmation do not match', 'danger')
                return render_template('change_password.html')
            if len(new_password) < 6:
                flash('New password must be at least 6 characters', 'danger')
                return render_template('change_password.html')

            current_user.set_password(new_password)
            db.session.add(current_user)
            db.session.commit()
            flash('Password changed successfully', 'success')
            return redirect(url_for('list_books'))

        return render_template('change_password.html')

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
