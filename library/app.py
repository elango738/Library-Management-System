from flask import Flask, render_template, redirect, url_for, flash, request, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bootstrap import Bootstrap
from models import db, User, Book, Category, Issue
from forms import RegistrationForm, LoginForm, AddBookForm, EditBookForm, IssueBookForm, ReturnBookForm, SearchBookForm
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
Bootstrap(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()
    # Pre-create admin user
    admin = User.query.filter_by(email='admin@library.com').first()
    if not admin:
        admin = User(username='admin', email='admin@library.com', is_admin=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
    # Pre-populate categories and books
    if not Category.query.first():
        cat1 = Category(name='Fiction')
        cat2 = Category(name='Non-Fiction')
        cat3 = Category(name='Science')
        db.session.add_all([cat1, cat2, cat3])
        db.session.commit()
        book1 = Book(title='The Great Gatsby', author='F. Scott Fitzgerald', isbn='9780743273565', category_id=cat1.id, quantity=5, available=5)
        book2 = Book(title='Sapiens', author='Yuval Noah Harari', isbn='9780062316097', category_id=cat2.id, quantity=3, available=3)
        book3 = Book(title='A Brief History of Time', author='Stephen Hawking', isbn='9780553380169', category_id=cat3.id, quantity=2, available=2)
        db.session.add_all([book1, book2, book3])
        db.session.commit()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('dashboard'))
        else:
            flash('Login unsuccessful. Please check email and password.', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    else:
        return redirect(url_for('user_dashboard'))

@app.route('/user_dashboard')
@login_required
def user_dashboard():
    issues = Issue.query.filter_by(user_id=current_user.id, return_date=None).all()
    overdue = [i for i in issues if i.due_date < datetime.utcnow()]
    return render_template('user_dashboard.html', issues=issues, overdue=overdue)

@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    total_books = Book.query.count()
    total_users = User.query.filter_by(is_admin=False).count()
    total_issues = Issue.query.filter_by(return_date=None).count()
    overdue_issues = Issue.query.filter(Issue.return_date == None, Issue.due_date < datetime.utcnow()).all()
    books = Book.query.all()
    return render_template('admin_dashboard.html', total_books=total_books, total_users=total_users, total_issues=total_issues, overdue_issues=overdue_issues, books=books)

@app.route('/add_book', methods=['GET', 'POST'])
@login_required
def add_book():
    if not current_user.is_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    form = AddBookForm()
    form.category.choices = [(c.id, c.name) for c in Category.query.all()]
    if form.validate_on_submit():
        book = Book(title=form.title.data, author=form.author.data, isbn=form.isbn.data, category_id=form.category.data, quantity=form.quantity.data, available=form.quantity.data)
        db.session.add(book)
        db.session.commit()
        flash('Book added successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('add_book.html', form=form)

@app.route('/edit_book/<int:book_id>', methods=['GET', 'POST'])
@login_required
def edit_book(book_id):
    if not current_user.is_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    book = Book.query.get_or_404(book_id)
    form = EditBookForm()
    form.category.choices = [(c.id, c.name) for c in Category.query.all()]
    if form.validate_on_submit():
        issued = book.quantity - book.available
        book.title = form.title.data
        book.author = form.author.data
        book.isbn = form.isbn.data
        book.category_id = form.category.data
        book.quantity = form.quantity.data
        book.available = book.quantity - issued
        if book.available < 0:
            book.available = 0
        db.session.commit()
        flash('Book updated successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    elif request.method == 'GET':
        form.title.data = book.title
        form.author.data = book.author
        form.isbn.data = book.isbn
        form.category.data = book.category_id
        form.quantity.data = book.quantity
    return render_template('edit_book.html', form=form, book=book)

@app.route('/delete_book/<int:book_id>')
@login_required
def delete_book(book_id):
    if not current_user.is_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    book = Book.query.get_or_404(book_id)
    db.session.delete(book)
    db.session.commit()
    flash('Book deleted successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/issue_book', methods=['GET', 'POST'])
@login_required
def issue_book():
    form = IssueBookForm()
    available_books = Book.query.filter(Book.available > 0).all()
    form.book_id.choices = [(b.id, f'{b.title} by {b.author}') for b in available_books]
    if form.validate_on_submit():
        book = Book.query.get(form.book_id.data)
        if book.available > 0:
            issue = Issue(user_id=current_user.id, book_id=form.book_id.data)
            book.available -= 1
            db.session.add(issue)
            db.session.commit()
            flash('Book issued successfully!', 'success')
            return redirect(url_for('user_dashboard'))
        else:
            flash('Book not available.', 'danger')
    return render_template('issue_book.html', form=form)

@app.route('/return_book', methods=['GET', 'POST'])
@login_required
def return_book():
    form = ReturnBookForm()
    user_issues = Issue.query.filter_by(user_id=current_user.id, return_date=None).all()
    form.issue_id.choices = [(i.id, f'{i.book.title} by {i.book.author}') for i in user_issues]
    if form.validate_on_submit():
        issue = Issue.query.get(form.issue_id.data)
        if issue.user_id == current_user.id:
            issue.return_date = datetime.utcnow()
            if issue.return_date > issue.due_date:
                days_overdue = (issue.return_date - issue.due_date).days
                issue.fine = days_overdue * 0.5  # $0.50 per day
            issue.book.available += 1
            db.session.commit()
            flash('Book returned successfully!', 'success')
            return redirect(url_for('user_dashboard'))
        else:
            flash('Invalid issue.', 'danger')
    return render_template('return_book.html', form=form)

@app.route('/search_books', methods=['GET', 'POST'])
@login_required
def search_books():
    form = SearchBookForm()
    results = []
    if form.validate_on_submit():
        query = form.query.data.lower()
        results = Book.query.filter(
            (Book.title.ilike(f'%{query}%')) |
            (Book.author.ilike(f'%{query}%')) |
            (Book.category.has(Category.name.ilike(f'%{query}%')))
        ).all()
    return render_template('search_books.html', form=form, results=results)

if __name__ == '__main__':
    app.run(debug=True)