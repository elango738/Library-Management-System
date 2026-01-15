# Library Pro — Flask Library Management System

This is a small library management system built with Flask and SQLite. It automates database creation on first run and includes a professional `style.css` theme.

Features
- Add/list/delete books
- Add/list borrowers
- Issue and return books (with due date)
- Search books by title, author, ISBN
- Automatic SQLite DB creation (`library.db`) on app startup

Quick start (Windows PowerShell)

1. Create a Python virtual environment and activate it:

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Run the app:

```powershell
python app.py
```

Open http://127.0.0.1:5000 in your browser. The `library.db` file will be created automatically.

Default admin
- On first run the app will create a default admin account if none exists:
	- username: admin
	- password: admin

	Change this password immediately after logging in (Admin -> change password not implemented in this minimal example).

Next steps
- Add authentication, role-based permissions
- Add CSV import/export, advanced reporting
- Add pagination and better validation
