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


## installation
"💻 Installation
1️⃣ Clone the repository
git clone https://github.com/Haddynotnow08/LibraryMS-Python.git
cd LibraryMS-Python
2️⃣ Create a virtual environment
py -m venv venv
3️⃣ Activate the environment
Windows
venv\Scripts\activate
4️⃣ Install dependencies
pip install -r requirements.txt
5️⃣ Configure environment variables

Create or edit your .env file:

ADMIN_EMAILS=your-email@example.com

Replace the email with the account that should have Admin/Librarian access.

6️⃣ Run the application
python app.py
7️⃣ Open in browser
http://127.0.0.1:5000 "


 
# LibraryMS-Python
