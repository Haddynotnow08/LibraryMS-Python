import os
import sqlite3
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, g
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'libraryms.db')
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv('ADMIN_EMAILS', '').split(',') if e.strip()}
if not ADMIN_EMAILS:
    ADMIN_EMAILS = {'admin@example.com'}

LOAN_DAYS = 14
MAX_BORROW = 3
FINE_PER_DAY = 2

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'change-this-secret-key-in-production')
app.config['DATABASE'] = DB_PATH


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'member',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT DEFAULT '',
        membership_id TEXT NOT NULL UNIQUE,
        borrowed_books INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        isbn TEXT DEFAULT '',
        category TEXT NOT NULL DEFAULT 'Other',
        total_copies INTEGER NOT NULL DEFAULT 1,
        available_copies INTEGER NOT NULL DEFAULT 1,
        rack_location TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL,
        member_name TEXT NOT NULL,
        membership_id TEXT NOT NULL,
        book_id INTEGER NOT NULL,
        book_title TEXT NOT NULL,
        book_author TEXT NOT NULL,
        issued_at TEXT NOT NULL,
        due_date TEXT NOT NULL,
        returned_at TEXT,
        fine INTEGER NOT NULL DEFAULT 0,
        fine_paid INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE,
        FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE RESTRICT
    );
    CREATE INDEX IF NOT EXISTS idx_transactions_member ON transactions(member_id);
    CREATE INDEX IF NOT EXISTS idx_transactions_issued ON transactions(issued_at);
    CREATE TABLE IF NOT EXISTS todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        task TEXT NOT NULL,
        priority TEXT NOT NULL DEFAULT 'Medium',
        due_date TEXT,
        completed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        completed_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_todos_user ON todos(user_id);
    CREATE INDEX IF NOT EXISTS idx_todos_completed ON todos(completed);
    ''')
    db.commit()


def now_iso():
    return datetime.now().isoformat(timespec='seconds')


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def fmt_date(value):
    d = parse_dt(value)
    return d.strftime('%d %b %Y') if d else '—'


def generate_membership_id():
    chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    while True:
        code = 'LIB-' + ''.join(secrets.choice(chars) for _ in range(6))
        if not get_db().execute('SELECT 1 FROM members WHERE membership_id=?', (code,)).fetchone():
            return code


def status_for(tx):
    if tx['returned_at']:
        return 'returned'
    due = parse_dt(tx['due_date'])
    return 'overdue' if due and datetime.now() > due else 'issued'


def fine_for(tx):
    due = parse_dt(tx['due_date'])
    end = parse_dt(tx['returned_at']) if tx['returned_at'] else datetime.now()
    if not due:
        return 0
    days_late = max(0, (end.date() - due.date()).days)
    return days_late * FINE_PER_DAY


def enrich_tx(tx):
    d = dict(tx)
    d['status'] = status_for(tx)
    d['calculated_fine'] = fine_for(tx)
    return d


def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return get_db().execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for('login'))
        if user['role'] != 'admin':
            flash('Admin access required.', 'error')
            return redirect(url_for('dashboard'))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_globals():
    return {
        'user': current_user(),
        'fmt_date': fmt_date,
        'fine_per_day': FINE_PER_DAY,
        'loan_days': LOAN_DAYS,
        'max_borrow': MAX_BORROW,
    }


@app.route('/')
def index():
    return redirect(url_for('dashboard')) if current_user() else redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user():
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = get_db().execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        if not user or not check_password_hash(user['password_hash'], password):
            flash('Invalid email or password.', 'error')
            return render_template('login.html', signup=False, email=email)
        session.clear()
        session['user_id'] = user['id']
        return redirect(url_for('dashboard'))
    return render_template('login.html', signup=request.args.get('signup') == '1', email='')


@app.route('/signup', methods=['POST'])
def signup():
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    name = request.form.get('name', '').strip() or email.split('@')[0]
    if len(password) < 6:
        flash('Password must be at least 6 characters.', 'error')
        return render_template('login.html', signup=True, email=email, name=name)
    if '@' not in email or '.' not in email.split('@')[-1]:
        flash('Enter a valid email address.', 'error')
        return render_template('login.html', signup=True, email=email, name=name)
    db = get_db()
    if db.execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone():
        flash('Email already in use.', 'error')
        return render_template('login.html', signup=True, email=email, name=name)
    role = 'admin' if email in ADMIN_EMAILS else 'member'
    cur = db.execute('INSERT INTO users(email,password_hash,name,role,created_at) VALUES(?,?,?,?,?)',
                     (email, generate_password_hash(password), name, role, now_iso()))
    if role == 'member':
        db.execute('INSERT INTO members(name,email,phone,membership_id,borrowed_books,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                   (name, email, '', generate_membership_id(), 0, now_iso(), now_iso()))
    db.commit()
    session.clear(); session['user_id'] = cur.lastrowid
    flash('Account created successfully.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    db = get_db()
    stats = {'books': 0, 'members': 0, 'available': 0, 'borrowed': 0}
    if user['role'] == 'admin':
        stats['books'] = db.execute('SELECT COUNT(*) c FROM books').fetchone()['c']
        stats['members'] = db.execute('SELECT COUNT(*) c FROM members').fetchone()['c']
        stats['available'] = db.execute('SELECT COALESCE(SUM(available_copies),0) c FROM books').fetchone()['c']
        stats['borrowed'] = db.execute('SELECT COALESCE(SUM(total_copies-available_copies),0) c FROM books').fetchone()['c']
    return render_template('dashboard.html', stats=stats)


@app.route('/books')
@login_required
def books():
    q = request.args.get('q', '').strip().lower()
    category = request.args.get('category', 'All')
    db = get_db()
    rows = db.execute('SELECT * FROM books ORDER BY created_at DESC').fetchall()
    books = [dict(r) for r in rows if (not q or q in r['title'].lower() or q in r['author'].lower() or q in (r['isbn'] or '').lower()) and (category == 'All' or r['category'] == category)]
    categories = [r['category'] for r in db.execute('SELECT DISTINCT category FROM books ORDER BY category').fetchall()]
    return render_template('books.html', books=books, categories=categories, q=q, category=category)


@app.route('/books/add', methods=['POST'])
@admin_required
def add_book():
    title = request.form.get('title', '').strip(); author = request.form.get('author', '').strip()
    isbn = request.form.get('isbn', '').strip(); category = request.form.get('category', 'Other') or 'Other'
    rack = request.form.get('rack_location', '').strip()
    try: copies = int(request.form.get('total_copies', '0'))
    except ValueError: copies = 0
    if not title or not author or copies < 1:
        flash('Title, author and at least 1 copy are required.', 'error'); return redirect(url_for('books'))
    db = get_db(); t = now_iso()
    db.execute('INSERT INTO books(title,author,isbn,category,total_copies,available_copies,rack_location,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
               (title,author,isbn,category,copies,copies,rack,t,t)); db.commit()
    flash('Book added!', 'success'); return redirect(url_for('books'))


@app.route('/books/<int:book_id>/edit', methods=['POST'])
@admin_required
def edit_book(book_id):
    title=request.form.get('title','').strip(); author=request.form.get('author','').strip(); isbn=request.form.get('isbn','').strip(); category=request.form.get('category','Other') or 'Other'; rack=request.form.get('rack_location','').strip()
    try: total=int(request.form.get('total_copies','0')); available=int(request.form.get('available_copies','0'))
    except ValueError: total=available=-1
    if not title or not author or total < 1 or available < 0 or available > total:
        flash('Invalid book values.', 'error'); return redirect(url_for('books'))
    db=get_db(); active=db.execute('SELECT COUNT(*) c FROM transactions WHERE book_id=? AND returned_at IS NULL',(book_id,)).fetchone()['c']
    if available != total - active:
        flash(f'Available copies must equal total copies minus active loans ({total-active}).', 'error'); return redirect(url_for('books'))
    db.execute('UPDATE books SET title=?,author=?,isbn=?,category=?,total_copies=?,available_copies=?,rack_location=?,updated_at=? WHERE id=?',(title,author,isbn,category,total,available,rack,now_iso(),book_id)); db.commit(); flash('Book updated!','success'); return redirect(url_for('books'))


@app.route('/books/<int:book_id>/delete', methods=['POST'])
@admin_required
def delete_book(book_id):
    db=get_db()
    if db.execute('SELECT COUNT(*) c FROM transactions WHERE book_id=?',(book_id,)).fetchone()['c']:
        flash('This book has transaction history and cannot be deleted.', 'error')
    else:
        db.execute('DELETE FROM books WHERE id=?',(book_id,)); db.commit(); flash('Book deleted.','success')
    return redirect(url_for('books'))


@app.route('/members')
@admin_required
def members():
    q=request.args.get('q','').strip().lower(); db=get_db(); rows=db.execute('SELECT * FROM members ORDER BY created_at DESC').fetchall()
    ms=[dict(r) for r in rows if not q or q in r['name'].lower() or q in r['email'].lower() or q in r['membership_id'].lower()]
    return render_template('members.html', members=ms, q=q)


@app.route('/members/add', methods=['POST'])
@admin_required
def add_member():
    name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); phone=request.form.get('phone','').strip()
    if not name or '@' not in email: flash('Name and valid email are required.','error'); return redirect(url_for('members'))
    db=get_db(); t=now_iso(); db.execute('INSERT INTO members(name,email,phone,membership_id,borrowed_books,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(name,email,phone,generate_membership_id(),0,t,t)); db.commit(); flash('Member added!','success'); return redirect(url_for('members'))


@app.route('/members/<int:member_id>/edit', methods=['POST'])
@admin_required
def edit_member(member_id):
    name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); phone=request.form.get('phone','').strip()
    if not name or '@' not in email: flash('Name and valid email are required.','error'); return redirect(url_for('members'))
    db=get_db(); db.execute('UPDATE members SET name=?,email=?,phone=?,updated_at=? WHERE id=?',(name,email,phone,now_iso(),member_id)); db.commit(); flash('Member updated!','success'); return redirect(url_for('member_profile',member_id=member_id))


@app.route('/members/<int:member_id>/delete', methods=['POST'])
@admin_required
def delete_member(member_id):
    db=get_db(); active=db.execute('SELECT COUNT(*) c FROM transactions WHERE member_id=? AND returned_at IS NULL',(member_id,)).fetchone()['c']
    if active: flash('Member has active borrowed books and cannot be deleted.','error')
    else: db.execute('DELETE FROM members WHERE id=?',(member_id,)); db.commit(); flash('Member deleted.','success')
    return redirect(url_for('members'))


@app.route('/members/<int:member_id>')
@admin_required
def member_profile(member_id):
    db=get_db(); member=db.execute('SELECT * FROM members WHERE id=?',(member_id,)).fetchone()
    if not member: abort(404)
    txs=[enrich_tx(r) for r in db.execute('SELECT * FROM transactions WHERE member_id=? ORDER BY issued_at DESC',(member_id,)).fetchall()]
    return render_template('member_profile.html', member=member, transactions=txs)


@app.route('/transactions')
@admin_required
def transactions():
    filter_name=request.args.get('filter','All'); q=request.args.get('q','').strip().lower(); db=get_db(); rows=db.execute('SELECT * FROM transactions ORDER BY issued_at DESC').fetchall(); txs=[]
    for r in rows:
        d=enrich_tx(r)
        if filter_name != 'All' and d['status'] != filter_name.lower(): continue
        if q and not any(q in str(d.get(k,'')).lower() for k in ('member_name','book_title','membership_id')): continue
        txs.append(d)
    members=db.execute('SELECT * FROM members ORDER BY name').fetchall(); books=db.execute('SELECT * FROM books ORDER BY title').fetchall()
    return render_template('transactions.html', transactions=txs, filter_name=filter_name, q=q, members=members, books=books)


@app.route('/transactions/issue', methods=['POST'])
@admin_required
def issue_book():
    member_id=int(request.form.get('member_id')); book_id=int(request.form.get('book_id')); db=get_db()
    member=db.execute('SELECT * FROM members WHERE id=?',(member_id,)).fetchone(); book=db.execute('SELECT * FROM books WHERE id=?',(book_id,)).fetchone()
    if not member or not book: flash('Member or book not found.','error'); return redirect(url_for('transactions'))
    if book['available_copies'] < 1: flash('No copies available for this book right now.','error'); return redirect(url_for('transactions'))
    if member['borrowed_books'] >= MAX_BORROW: flash(f'Borrow limit reached — this member already has {MAX_BORROW} books.','error'); return redirect(url_for('transactions'))
    now=datetime.now(); due=now+timedelta(days=LOAN_DAYS)
    try:
        db.execute('BEGIN')
        db.execute('UPDATE members SET borrowed_books=borrowed_books+1,updated_at=? WHERE id=?',(now_iso(),member_id))
        db.execute('UPDATE books SET available_copies=available_copies-1,updated_at=? WHERE id=?',(now_iso(),book_id))
        db.execute('INSERT INTO transactions(member_id,member_name,membership_id,book_id,book_title,book_author,issued_at,due_date,fine,fine_paid) VALUES(?,?,?,?,?,?,?,?,0,0)',(member_id,member['name'],member['membership_id'],book_id,book['title'],book['author'],now.isoformat(timespec='seconds'),due.isoformat(timespec='seconds')))
        db.commit()
    except Exception:
        db.rollback(); raise
    flash('Book issued successfully!','success'); return redirect(url_for('transactions'))


@app.route('/transactions/<int:tx_id>/return', methods=['POST'])
@admin_required
def return_book(tx_id):
    db=get_db(); tx=db.execute('SELECT * FROM transactions WHERE id=?',(tx_id,)).fetchone()
    if not tx: abort(404)
    if tx['returned_at']: flash('This book has already been returned.','error'); return redirect(url_for('transactions'))
    now=datetime.now(); due=parse_dt(tx['due_date']); days_late=max(0,(now.date()-due.date()).days) if due else 0; fine=days_late*FINE_PER_DAY
    try:
        db.execute('BEGIN')
        db.execute('UPDATE transactions SET returned_at=?,fine=? WHERE id=?',(now.isoformat(timespec='seconds'),fine,tx_id))
        db.execute('UPDATE members SET borrowed_books=MAX(0,borrowed_books-1),updated_at=? WHERE id=?',(now_iso(),tx['member_id']))
        db.execute('UPDATE books SET available_copies=available_copies+1,updated_at=? WHERE id=?',(now_iso(),tx['book_id']))
        db.commit()
    except Exception:
        db.rollback(); raise
    flash(f'Book returned. Fine: ₹{fine}','success'); return redirect(url_for('transactions'))


@app.route('/my-borrows')
@login_required
def my_borrows():
    user=current_user(); db=get_db(); member=db.execute('SELECT * FROM members WHERE lower(email)=lower(?)',(user['email'],)).fetchone()
    txs=[]
    if member:
        txs=[enrich_tx(r) for r in db.execute('SELECT * FROM transactions WHERE member_id=? ORDER BY issued_at DESC',(member['id'],)).fetchall()]
    return render_template('my_borrows.html', member=member, transactions=txs)


@app.route('/calculator')
@login_required
def calculator():
    return render_template('calculator.html')


@app.route('/todo')
@login_required
def todo():
    user=current_user(); db=get_db()
    rows=db.execute(
        "SELECT * FROM todos WHERE user_id=? ORDER BY completed ASC, CASE priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, CASE WHEN due_date IS NULL OR due_date='' THEN 1 ELSE 0 END, due_date ASC, id DESC",
        (user['id'],)
    ).fetchall()
    today=datetime.now().date().isoformat()
    tasks=[]
    for r in rows:
        d=dict(r)
        if d['completed']:
            d['due_state']='completed'
        elif not d['due_date']:
            d['due_state']='none'
        elif d['due_date'] < today:
            d['due_state']='overdue'
        elif d['due_date'] == today:
            d['due_state']='today'
        else:
            d['due_state']='upcoming'
        tasks.append(d)
    total=len(tasks); completed=sum(1 for t in tasks if t['completed']); pending=total-completed; high=sum(1 for t in tasks if not t['completed'] and t['priority']=='High')
    return render_template('todo.html', tasks=tasks, total=total, completed=completed, pending=pending, high=high, today=today)


@app.route('/todo/add', methods=['POST'])
@login_required
def add_todo():
    task=request.form.get('task','').strip()
    priority=request.form.get('priority','Medium').title()
    due_date=request.form.get('due_date','').strip() or None
    if priority not in {'Low','Medium','High'}:
        priority='Medium'
    if not task:
        flash('Task cannot be empty.','error')
        return redirect(url_for('todo'))
    if due_date:
        try:
            datetime.strptime(due_date,'%Y-%m-%d')
        except ValueError:
            flash('Enter a valid due date.','error')
            return redirect(url_for('todo'))
    user=current_user(); db=get_db()
    db.execute('INSERT INTO todos(user_id,task,priority,due_date,completed,created_at) VALUES(?,?,?,?,0,?)',(user['id'],task,priority,due_date,now_iso()))
    db.commit()
    flash('Task added!','success')
    return redirect(url_for('todo'))


@app.route('/todo/<int:todo_id>/toggle', methods=['POST'])
@login_required
def toggle_todo(todo_id):
    user=current_user(); db=get_db()
    task=db.execute('SELECT * FROM todos WHERE id=? AND user_id=?',(todo_id,user['id'])).fetchone()
    if not task:
        abort(404)
    if task['completed']:
        db.execute('UPDATE todos SET completed=0, completed_at=NULL WHERE id=? AND user_id=?',(todo_id,user['id']))
        flash('Task marked as pending.','success')
    else:
        db.execute('UPDATE todos SET completed=1, completed_at=? WHERE id=? AND user_id=?',(now_iso(),todo_id,user['id']))
        flash('Task completed!','success')
    db.commit()
    return redirect(url_for('todo'))


@app.route('/todo/<int:todo_id>/delete', methods=['POST'])
@login_required
def delete_todo(todo_id):
    user=current_user(); db=get_db()
    db.execute('DELETE FROM todos WHERE id=? AND user_id=?',(todo_id,user['id']))
    db.commit()
    flash('Task deleted.','success')
    return redirect(url_for('todo'))


@app.route('/todo/clear-completed', methods=['POST'])
@login_required
def clear_completed_todos():
    user=current_user(); db=get_db()
    db.execute('DELETE FROM todos WHERE user_id=? AND completed=1',(user['id'],))
    db.commit()
    flash('Completed tasks cleared.','success')
    return redirect(url_for('todo'))


with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
