
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

db = SQLAlchemy()


class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    author = db.Column(db.String(255), nullable=True)
    isbn = db.Column(db.String(50), nullable=True, unique=False)
    publisher = db.Column(db.String(255), nullable=True)
    year = db.Column(db.Integer, nullable=True)
    copies_total = db.Column(db.Integer, default=1)
    copies_available = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Book {self.title} by {self.author}>'


class Borrower(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(50), nullable=True, unique=True)
    member_id = db.Column(db.String(100), nullable=True, unique=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Borrower {self.name}>'


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user')  # 'admin' or 'user'
    borrower_id = db.Column(db.Integer, db.ForeignKey('borrower.id'), nullable=True)

    borrower = db.relationship('Borrower', backref=db.backref('user', uselist=False))

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    borrower_id = db.Column(db.Integer, db.ForeignKey('borrower.id'), nullable=False)
    issue_date = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=True)
    return_date = db.Column(db.DateTime, nullable=True)

    book = db.relationship('Book', backref=db.backref('loans', lazy=True))
    borrower = db.relationship('Borrower', backref=db.backref('loans', lazy=True))

    def is_overdue(self):
        if self.return_date:
            return False
        if self.due_date and datetime.utcnow() > self.due_date:
            return True
        return False

    def __repr__(self):
        return f'<Loan book:{self.book_id} borrower:{self.borrower_id}>'


class NotificationLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(50), nullable=False)
    message = db.Column(db.String(1024), nullable=False)
    event = db.Column(db.String(50), nullable=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loan.id'), nullable=True)
    status = db.Column(db.String(50), nullable=True)
    error = db.Column(db.Text, nullable=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

    loan = db.relationship('Loan', backref=db.backref('notifications', lazy=True))

    def __repr__(self):
        return f'<Notification {self.phone} {self.event} {self.status}>'
