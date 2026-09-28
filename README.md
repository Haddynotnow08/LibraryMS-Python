# LibraryMS — Python/Flask Edition

This is a Python conversion of the React/Vite/Firebase LibraryMS project.

## Stack
- Python 3.10+
- Flask
- SQLite (no Firebase required)
- Jinja templates
- HTML/CSS

## Features
- Email/password signup and login
- Admin/member roles
- Dashboard statistics
- Book CRUD
- Member CRUD
- Issue and return books
- 14-day loan period
- Maximum 3 active books/member
- ₹2/day overdue fine calculation
- Transactions/history
- Member profile
- My Borrows page
- Search and filters
- Personal To-Do list with priorities, due dates and completed-task management
- Built-in Calculator with keyboard support and browser-saved calculation history

## Run on Windows
```powershell
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env .env.local
# edit .env (or set environment variables) and set ADMIN_EMAILS to your email
python app.py
```

Open http://127.0.0.1:5000


 

 