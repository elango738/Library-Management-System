# Library Management System

A comprehensive Flask-based library management system with user authentication, book management, and issue/return functionality.

## Features

- User registration and login
- Admin login with full access
- Book management (add, edit, delete) for admins
- Issue and return books for users
- Search books by title, author, or category
- Book categories
- Overdue book tracking with fines
- Responsive Bootstrap UI

## Setup Instructions

1. **Clone or download the project files.**

2. **Install dependencies:**
   ```
   pip install -r requirements.txt
   ```

3. **Run the application:**
   ```
   python app.py
   ```

4. **Access the application:**
   Open your browser and go to `http://127.0.0.1:5000/`

## Pre-configured Accounts

- **Admin Account:**
  - Email: admin@library.com
  - Password: admin123

- **Sample Data:**
  The application comes with pre-populated sample books and categories.

## Usage

- Register as a new user or login with the admin account.
- Users can issue books, return books, and search for books.
- Admins can manage books (add, edit, delete) and view dashboard statistics.

## Technologies Used

- Flask
- SQLAlchemy
- Flask-WTF
- Flask-Login
- Bootstrap 5
- SQLite

## Database

The application uses SQLite for simplicity. The database file `library.db` will be created automatically when you run the app for the first time.