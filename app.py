import os, sqlite3, csv, io, re
from datetime import date, timedelta
from functools import wraps
from flask import Flask, g, render_template, request, redirect, url_for, session, flash, abort, Response
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("LIBRARY_DB", os.path.join(BASE, "library.db"))
LOAN_DAYS, MAX_BOOKS = 14, 3
FINE_PER_DAY = int(os.environ.get("FINE_PER_DAY", "10"))   # Rs per overdue day; set FINE_PER_DAY=2 to match the report text
CATEGORIES = ["Computer Science", "Information Technology", "Mathematics", "Commerce", "Management", "Literature", "Science", "Biography", "History", "Fiction", "Other"]
DEPARTMENTS = ["B.Sc. Computer Science", "B.Sc. Information Technology", "B.Com", "B.A.", "B.M.S.", "Other"]

app = Flask(__name__)
DEFAULT_SECRET = "local-development-key-change-before-deployment"
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", DEFAULT_SECRET)
if app.config["SECRET_KEY"] == DEFAULT_SECRET:
    app.logger.warning("SECRET_KEY is not set: using the development-only default. Set SECRET_KEY before deployment.")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# CSRF protection is applied to all POST forms.
csrf = CSRFProtect(app)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
 username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL,
 password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'student',
 phone TEXT DEFAULT '', department TEXT DEFAULT '', joined TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS books(
 id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, author TEXT NOT NULL,
 category TEXT NOT NULL, isbn TEXT UNIQUE NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity>=0), available INTEGER NOT NULL CHECK(available>=0));
CREATE TABLE IF NOT EXISTS transactions(
 id INTEGER PRIMARY KEY AUTOINCREMENT, book_id INTEGER NOT NULL REFERENCES books(id),
 user_id INTEGER NOT NULL REFERENCES users(id), issue_date TEXT NOT NULL,
 due_date TEXT NOT NULL, return_date TEXT, fine INTEGER DEFAULT 0, fine_paid INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS notifications(
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 message TEXT NOT NULL, created TEXT NOT NULL, is_read INTEGER DEFAULT 0);
"""

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()

def today():
    return date.today()

def init_db():
    os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    if not con.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        con.execute("INSERT INTO users(name,username,email,password_hash,role,joined) VALUES(?,?,?,?,?,?)",
                    ("Librarian", "admin", "admin@library.local", generate_password_hash("admin123"), "admin", str(today())))
    # Demo student account for local demonstration; password is hashed.
    if not con.execute("SELECT 1 FROM users WHERE role='student' LIMIT 1").fetchone():
        con.execute("INSERT INTO users(name,username,email,password_hash,role,department,joined) VALUES(?,?,?,?,?,?,?)",
                    ("Riya Sharma", "riya", "riya@student.edu", generate_password_hash("riya123"),
                     "student", "B.Sc. Computer Science", str(today())))
    # Seed a small catalogue only when the database is empty.
    if not con.execute("SELECT 1 FROM books LIMIT 1").fetchone():
        seed = [
            ("Wings of Fire", "A.P.J. Abdul Kalam", "Biography", "9788173711466", 3, 3),
            ("Introduction to Algorithms", "Cormen, Leiserson, Rivest, Stein", "Computer Science", "9780262046305", 2, 2),
            ("The Discovery of India", "Jawaharlal Nehru", "History", "9780143031031", 2, 2),
            ("Clean Code", "Robert C. Martin", "Computer Science", "9780132350884", 1, 1),
            ("Concepts of Physics", "H.C. Verma", "Science", "9788177091878", 4, 4),
            ("The White Tiger", "Aravind Adiga", "Fiction", "9781416562603", 2, 2),
            ("Database System Concepts", "Silberschatz, Korth", "Computer Science", "9780078022159", 2, 2),
        ]
        con.executemany("INSERT INTO books(title,author,category,isbn,quantity,available) VALUES(?,?,?,?,?,?)", seed)
    con.commit()
    con.close()

def tx(where="", args=None, order="ORDER BY t.id DESC"):
    sql = """SELECT t.*, b.title, b.isbn, u.name AS member, u.username,
      CASE WHEN t.return_date IS NULL
      THEN MAX(0, CAST(julianday(:today)-julianday(t.due_date) AS INTEGER))*:rate
      ELSE t.fine END AS fine_now,
      CASE WHEN t.return_date IS NULL AND t.due_date < :today THEN 1 ELSE 0 END AS overdue
      FROM transactions t JOIN books b ON b.id=t.book_id JOIN users u ON u.id=t.user_id """
    params = {"today": str(today()), "rate": FINE_PER_DAY}
    params.update(args or {})
    return db().execute(sql + " " + where + " " + order, params).fetchall()

def blocked(uid):
    n = db().execute("""SELECT COUNT(*) FROM transactions WHERE user_id=? AND
      ((return_date IS NULL AND due_date<?) OR (fine>0 AND fine_paid=0))""",
      (uid, str(today()))).fetchone()[0]
    return n > 0

@app.template_filter("availability")
def availability(b):
    if b["quantity"] == 0: return ("Out of stock", "bad")
    if b["available"] == 0: return ("Issued out", "warn")
    return ("Available", "ok")

@app.context_processor
def inject():
    unread = 0
    if session.get("user_id") and session.get("role") == "student":
        unread = db().execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                              (session["user_id"],)).fetchone()[0]
    return dict(unread=unread, LOAN_DAYS=LOAN_DAYS, FINE_PER_DAY=FINE_PER_DAY, MAX_BOOKS=MAX_BOOKS, today=str(today()),
                min_due=str(today() + timedelta(days=1)), max_due=str(today() + timedelta(days=LOAN_DAYS)))

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("user_id"):
            flash("Please log in to continue.", "bad")
            return redirect(url_for("login"))
        return f(*a, **k)
    return w

def admin_required(f):
    @wraps(f)
    @login_required
    def w(*a, **k):
        if session.get("role") != "admin": abort(403)
        return f(*a, **k)
    return w

def parse_due_date(raw, borrowed_on):
    """Strictly parse a planned return date (YYYY-MM-DD). Allowed: the day after borrowing up to LOAN_DAYS days later."""
    raw = (raw or "").strip()
    bad = "Select a valid return date from the calendar."
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
        return None, bad
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return None, bad
    latest = borrowed_on + timedelta(days=LOAN_DAYS)
    if d <= borrowed_on:
        return None, "The return date must be tomorrow or later."
    if d > latest:
        return None, f"The return date cannot be more than {LOAN_DAYS} days from today (latest allowed: {latest})."
    return d, None

def like_pattern(q):
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

def safe_back(default_endpoint):
    """Redirect back to the referring page only if it is on this site."""
    ref = request.referrer
    if ref:
        from urllib.parse import urlparse
        if urlparse(ref).netloc == request.host:
            return redirect(ref)
    return redirect(url_for(default_endpoint))

def create_loan(uid, bid, due, self_service=False):
    """Validate every borrowing rule and create the loan in ONE write transaction.
    Returns (ok, message, book_row, user_row)."""
    d = db()
    who = (lambda mine, other: mine if self_service else other)
    try:
        d.execute("BEGIN IMMEDIATE")   # take the write lock before reading stock
        u = d.execute("SELECT * FROM users WHERE id=? AND role='student'", (uid,)).fetchone()
        b = d.execute("SELECT * FROM books WHERE id=?", (bid,)).fetchone()
        held = d.execute("SELECT COUNT(*) FROM transactions WHERE user_id=? AND return_date IS NULL", (uid,)).fetchone()[0]
        msg = None
        if not u or not b:
            msg = "Member or book not found."
        elif b["available"] < 1:
            msg = who("No copy of this book is currently available.", "No copy of this book is available.")
        elif d.execute("SELECT 1 FROM transactions WHERE user_id=? AND book_id=? AND return_date IS NULL", (uid, bid)).fetchone():
            msg = who("You already have a copy of this book.", "This member already holds a copy of this book.")
        elif held >= MAX_BOOKS:
            msg = who(f"You can hold a maximum of {MAX_BOOKS} books at a time.", f"Limit reached: a member can hold {MAX_BOOKS} books at a time.")
        elif blocked(uid):
            msg = who("You have an overdue book or an unpaid fine. Clear it before borrowing.", "Member has an overdue book or an unpaid fine. Clear it first.")
        if msg:
            d.rollback()
            return False, msg, b, u
        cur = d.execute("UPDATE books SET available=available-1 WHERE id=? AND available>0", (bid,))
        if cur.rowcount != 1:          # stock vanished between check and update
            d.rollback()
            return False, "No copy of this book is available.", b, u
        d.execute("INSERT INTO transactions(book_id,user_id,issue_date,due_date) VALUES(?,?,?,?)",
                  (bid, uid, str(today()), str(due)))
        d.execute("INSERT INTO notifications(user_id,message,created) VALUES(?,?,?)",
                  (uid, f"'{b['title']}' was issued to you. Due date: {due}.", str(today())))
        d.commit()
        return True, "", b, u
    except Exception:
        d.rollback()
        raise

def clean_isbn(v):
    v = re.sub(r"[\s-]", "", v or "")
    return v if v.isdigit() and len(v) in (10, 13) else None

def check_user_form(f, creating=True):
    name, email = f.get("name", "").strip(), f.get("email", "").strip().lower()
    username, pw = f.get("username", "").strip().lower(), f.get("password", "")
    if not name or not email or (creating and not (username and pw)):
        return "Fill all required fields."
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return "Enter a valid email address."
    if creating and not re.fullmatch(r"[a-z0-9_-]+", username):
        return "Username can use letters, numbers, hyphen and underscore only."
    if pw and len(pw) < 6:
        return "Password needs at least 6 characters."
    return None

@app.route("/")
@app.route("/books")
def catalogue():
    q = request.args.get("q", "").strip()
    cat = request.args.get("category", "").strip()
    avail = request.args.get("avail", "").strip()
    sql, args = "SELECT * FROM books WHERE 1=1", []
    if q:
        sql += " AND (title LIKE ? ESCAPE '\\' OR author LIKE ? ESCAPE '\\' OR category LIKE ? ESCAPE '\\' OR isbn LIKE ? ESCAPE '\\')"
        args += [like_pattern(q)] * 4
    if cat:
        sql += " AND category=?"; args.append(cat)
    if avail == "yes": sql += " AND available>0"
    elif avail == "no": sql += " AND available=0"
    books = db().execute(sql + " ORDER BY title", args).fetchall()
    return render_template("catalogue.html", books=books, q=q, cat=cat, avail=avail, categories=CATEGORIES)

@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"): return redirect(url_for("dashboard"))
    if request.method == "POST":
        f = request.form
        err = check_user_form(f)
        if err: flash(err, "bad")
        else:
            try:
                db().execute("""INSERT INTO users(name,username,email,password_hash,phone,department,joined)
                    VALUES(?,?,?,?,?,?,?)""",
                    (f["name"].strip(), f["username"].strip().lower(), f["email"].strip().lower(),
                     generate_password_hash(f["password"]), f.get("phone","").strip(),
                     f.get("department","").strip(), str(today())))
                db().commit()
                flash("Account created. Please log in.", "ok")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That username or email is already registered.", "bad")
    return render_template("register.html", departments=DEPARTMENTS)

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"): return redirect(url_for("dashboard"))
    if request.method == "POST":
        ident = request.form.get("ident", "").strip().lower()
        pw = request.form.get("password", "")
        u = db().execute("SELECT * FROM users WHERE username=? OR email=?", (ident, ident)).fetchone()
        if u and check_password_hash(u["password_hash"], pw):
            session.clear()
            session.update(user_id=u["id"], name=u["name"], role=u["role"])
            return redirect(url_for("dashboard"))
        flash("Wrong username/email or password.", "bad")
    return render_template("login.html")

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("catalogue"))

@app.route("/dashboard")
@login_required
def dashboard():
    if session["role"] == "admin":
        c = lambda s: db().execute(s).fetchone()[0]
        allt = tx()
        stats = dict(titles=c("SELECT COUNT(*) FROM books"),
          copies=c("SELECT COALESCE(SUM(quantity),0) FROM books"),
          issued=c("SELECT COUNT(*) FROM transactions WHERE return_date IS NULL"),
          overdue=sum(r["overdue"] for r in allt),
          members=c("SELECT COUNT(*) FROM users WHERE role='student'"),
          fines=sum(r["fine_now"] for r in allt if not r["fine_paid"]))
        return render_template("dashboard_admin.html", s=stats, recent=allt[:6])
    return render_template("dashboard_student.html", **student_summary())

def student_summary():
    mine = tx("WHERE t.user_id=:u", {"u": session["user_id"]})
    return dict(mine=mine,
        holding=sum(1 for r in mine if r["return_date"] is None),
        overdue=sum(r["overdue"] for r in mine),
        owed=sum(r["fine_now"] for r in mine if not r["fine_paid"]),
        paid=sum(r["fine"] for r in mine if r["fine_paid"]))

@app.route("/my-books")
@login_required
def my_books():
    if session.get("role") == "admin":
        return redirect(url_for("transactions"))
    return render_template("my_books.html", **student_summary())

@app.route("/books/add", methods=["GET", "POST"])
@admin_required
def add_book():
    if request.method == "POST":
        data, err = read_book_form(request.form)
        if err: flash(err, "bad")
        else:
            try:
                db().execute("INSERT INTO books(title,author,category,isbn,quantity,available) VALUES(?,?,?,?,?,?)", (*data, data[4]))
                db().commit(); flash("Book added.", "ok")
                return redirect(url_for("catalogue"))
            except sqlite3.IntegrityError: flash("A book with this ISBN already exists.", "bad")
    return render_template("book_form.html", b=request.form, categories=CATEGORIES, edit=False)

def read_book_form(f):
    title, author = f.get("title","").strip(), f.get("author","").strip()
    category, isbn = f.get("category","").strip(), clean_isbn(f.get("isbn"))
    try: qty = int(f.get("quantity",""))
    except ValueError: qty = -1
    if not (title and author and category): return None, "Title, author and category are required."
    if not isbn: return None, "ISBN must have 10 or 13 digits."
    if qty < 0: return None, "Quantity must be zero or a positive whole number."
    return (title, author, category, isbn, qty), None

@app.route("/books/<int:bid>/edit", methods=["GET", "POST"])
@admin_required
def edit_book(bid):
    b = db().execute("SELECT * FROM books WHERE id=?", (bid,)).fetchone()
    if not b: abort(404)
    if request.method == "POST":
        data, err = read_book_form(request.form)
        issued = b["quantity"] - b["available"]
        if not err and data[4] < issued: err = f"Quantity cannot be less than the {issued} copies currently issued."
        if err: flash(err, "bad")
        else:
            try:
                db().execute("UPDATE books SET title=?,author=?,category=?,isbn=?,quantity=?,available=? WHERE id=?",
                             (*data[:4], data[4], data[4]-issued, bid))
                db().commit(); flash("Book updated.", "ok")
                return redirect(url_for("catalogue"))
            except sqlite3.IntegrityError: flash("A book with this ISBN already exists.", "bad")
    return render_template("book_form.html", b=b, categories=CATEGORIES, edit=True)

@app.route("/books/<int:bid>/delete", methods=["POST"])
@admin_required
def delete_book(bid):
    if not db().execute("SELECT 1 FROM books WHERE id=?",(bid,)).fetchone(): abort(404)
    if db().execute("SELECT 1 FROM transactions WHERE book_id=? AND return_date IS NULL",(bid,)).fetchone():
        flash("This book is currently issued and cannot be deleted.", "bad")
    elif db().execute("SELECT 1 FROM transactions WHERE book_id=? AND fine>0 AND fine_paid=0",(bid,)).fetchone():
        flash("This book has unpaid fines on record and cannot be deleted until they are collected.", "bad")
    else:
        db().execute("DELETE FROM transactions WHERE book_id=?",(bid,))
        db().execute("DELETE FROM books WHERE id=?",(bid,)); db().commit()
        flash("Book deleted.", "ok")
    return redirect(url_for("catalogue"))

@app.route("/members")
@admin_required
def members():
    q = request.args.get("q","").strip()
    rows = db().execute("""SELECT u.*, (SELECT COUNT(*) FROM transactions t WHERE t.user_id=u.id AND t.return_date IS NULL) AS holding
      FROM users u WHERE role='student' AND (name LIKE ? OR username LIKE ? OR email LIKE ?) ORDER BY id DESC""",
      (f"%{q}%",)*3).fetchall()
    return render_template("members.html", members=rows, q=q)

@app.route("/members/add", methods=["GET","POST"])
@admin_required
def add_member():
    if request.method == "POST":
        f=request.form; err=check_user_form(f)
        if err: flash(err,"bad")
        else:
            try:
                db().execute("""INSERT INTO users(name,username,email,password_hash,phone,department,joined)
                  VALUES(?,?,?,?,?,?,?)""",(f["name"].strip(),f["username"].strip().lower(),f["email"].strip().lower(),
                  generate_password_hash(f["password"]),f.get("phone","").strip(),f.get("department","").strip(),str(today())))
                db().commit(); flash("Member added.","ok"); return redirect(url_for("members"))
            except sqlite3.IntegrityError: flash("That username or email is already registered.","bad")
    return render_template("member_form.html", m=request.form, departments=DEPARTMENTS, edit=False)

@app.route("/members/<int:uid>/edit", methods=["GET","POST"])
@admin_required
def edit_member(uid):
    m=db().execute("SELECT * FROM users WHERE id=? AND role='student'",(uid,)).fetchone()
    if not m: abort(404)
    if request.method=="POST":
        f=request.form; err=check_user_form(f,creating=False)
        if err: flash(err,"bad")
        else:
            try:
                db().execute("UPDATE users SET name=?,email=?,phone=?,department=? WHERE id=?",
                  (f["name"].strip(),f["email"].strip().lower(),f.get("phone","").strip(),f.get("department","").strip(),uid))
                if f.get("password"): db().execute("UPDATE users SET password_hash=? WHERE id=?",(generate_password_hash(f["password"]),uid))
                db().commit(); flash("Member updated.","ok"); return redirect(url_for("members"))
            except sqlite3.IntegrityError: flash("That email is already registered.","bad")
    return render_template("member_form.html", m=m, departments=DEPARTMENTS, edit=True)

@app.route("/members/<int:uid>/delete", methods=["POST"])
@admin_required
def delete_member(uid):
    if db().execute("SELECT 1 FROM transactions WHERE user_id=? AND return_date IS NULL",(uid,)).fetchone():
        flash("This member still holds issued books and cannot be deleted.","bad")
    elif db().execute("SELECT 1 FROM transactions WHERE user_id=? AND fine>0 AND fine_paid=0",(uid,)).fetchone():
        flash("This member has unpaid fines on record and cannot be deleted until they are collected.","bad")
    else:
        db().execute("DELETE FROM transactions WHERE user_id=?",(uid,))
        db().execute("DELETE FROM notifications WHERE user_id=?",(uid,))
        db().execute("DELETE FROM users WHERE id=? AND role='student'",(uid,)); db().commit()
        flash("Member deleted.","ok")
    return redirect(url_for("members"))

@app.route("/borrow/<int:bid>", methods=["POST"])
@login_required
def borrow_book(bid):
    """A logged-in student borrows a catalogue book for their own account and picks the planned return date."""
    if session.get("role") != "student":
        abort(403)
    due, err = parse_due_date(request.form.get("due_date"), today())   # server-side date validation
    if err:
        flash(err, "bad")
        return redirect(url_for("catalogue"))
    ok, msg, b, _u = create_loan(session["user_id"], bid, due, self_service=True)
    if not ok:
        flash(msg, "bad")
        return redirect(url_for("catalogue"))
    flash(f"'{b['title']}' borrowed successfully. Return by {due}.", "ok")
    return redirect(url_for("dashboard"))


@app.route("/issue", methods=["GET","POST"])
@admin_required
def issue():
    if request.method=="POST":
        try: uid,bid=int(request.form["member_id"]),int(request.form["book_id"])
        except (KeyError,ValueError):
            flash("Select a member and a book.","bad"); return redirect(url_for("issue"))
        due=today()+timedelta(days=LOAN_DAYS)
        ok,msg,b,u=create_loan(uid,bid,due)
        if ok: flash(f"Issued '{b['title']}' to {u['name']}. Due date: {due}.","ok")
        else: flash(msg,"bad")
        return redirect(url_for("issue"))
    members_=db().execute("SELECT id,name,username FROM users WHERE role='student' ORDER BY name").fetchall()
    books_=db().execute("SELECT * FROM books WHERE available>0 ORDER BY title").fetchall()
    return render_template("issue.html", members=members_, books=books_, active=tx("WHERE t.return_date IS NULL",order="ORDER BY t.due_date"))

@app.route("/return/<int:tid>", methods=["POST"])
@admin_required
def return_book(tid):
    d=db()
    t=d.execute("SELECT * FROM transactions WHERE id=?",(tid,)).fetchone()
    if not t: abort(404)
    returned_on=today()
    late=max(0,(returned_on-date.fromisoformat(t["due_date"])).days); fine=late*FINE_PER_DAY
    try:
        d.execute("BEGIN IMMEDIATE")
        # Only the request that flips return_date from NULL may add the copy back (prevents double stock increase).
        cur=d.execute("UPDATE transactions SET return_date=?,fine=? WHERE id=? AND return_date IS NULL",(str(returned_on),fine,tid))
        if cur.rowcount==1:
            d.execute("UPDATE books SET available=available+1 WHERE id=? AND available<quantity",(t["book_id"],))
            d.commit()
            flash(f"Book returned. Fine: Rs {fine}." if fine else "Book returned. No fine.","ok")
        else:
            d.rollback(); flash("This book was already returned.","bad")
    except Exception:
        d.rollback(); raise
    return safe_back("issue")

@app.route("/transactions")
@admin_required
def transactions():
    st=request.args.get("status","")
    where={"active":"WHERE t.return_date IS NULL","returned":"WHERE t.return_date IS NOT NULL","overdue":"WHERE t.return_date IS NULL AND t.due_date < :today"}.get(st,"")
    return render_template("transactions.html",rows=tx(where),status=st)

@app.route("/fines")
@admin_required
def fines():
    rows=tx("WHERE (t.return_date IS NULL AND t.due_date < :today) OR t.fine>0",order="ORDER BY t.due_date")
    pending=sum(r["fine_now"] for r in rows if not r["fine_paid"])
    return render_template("fines.html",rows=rows,pending=pending)

@app.route("/fines/<int:tid>/pay",methods=["POST"])
@admin_required
def pay_fine(tid):
    t=db().execute("SELECT * FROM transactions WHERE id=?",(tid,)).fetchone()
    if not t: abort(404)
    if not t["return_date"] or t["fine"]<=0: flash("Only the fine of a returned book can be collected.","bad")
    else:
        db().execute("UPDATE transactions SET fine_paid=1 WHERE id=?",(tid,)); db().commit()
        flash(f"Fine of Rs {t['fine']} collected.","ok")
    return redirect(url_for("fines"))

@app.route("/remind",methods=["POST"])
@admin_required
def remind():
    soon=str(today()+timedelta(days=2)); sent=0
    for t in tx("WHERE t.return_date IS NULL AND t.due_date <= :soon",{"soon":soon}):
        msg=(f"Overdue: '{t['title']}' was due on {t['due_date']}. Fine so far: Rs {t['fine_now']}."
             if t["overdue"] else f"Reminder: '{t['title']}' is due on {t['due_date']}.")
        if not db().execute("SELECT 1 FROM notifications WHERE user_id=? AND message=? AND created=?",(t["user_id"],msg,str(today()))).fetchone():
            db().execute("INSERT INTO notifications(user_id,message,created) VALUES(?,?,?)",(t["user_id"],msg,str(today())))
            sent+=1
    db().commit(); flash(f"{sent} reminder(s) sent.","ok")
    return redirect(url_for("dashboard"))

@app.route("/notifications")
@login_required
def notifications():
    rows=db().execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC",(session["user_id"],)).fetchall()
    db().execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(session["user_id"],)); db().commit()
    return render_template("notifications.html",rows=rows)

def report_data(kind):
    d=db()
    if kind=="books":
        rows=d.execute("SELECT title,author,category,isbn,quantity,available FROM books ORDER BY title").fetchall()
        return "Books report",["Title","Author","Category","ISBN","Total","Available"],[list(r) for r in rows]
    if kind=="members":
        rows=d.execute("""SELECT name,username,email,department,joined,(SELECT COUNT(*) FROM transactions t
          WHERE t.user_id=u.id AND t.return_date IS NULL) FROM users u WHERE role='student' ORDER BY name""").fetchall()
        return "Members report",["Name","Username","Email","Department","Joined","Books held"],[list(r) for r in rows]
    if kind=="issued":
        rows=tx("WHERE t.return_date IS NULL",order="ORDER BY t.due_date")
        return "Issued books report",["Book","Member","Issued","Due","Status"],[[r["title"],r["member"],r["issue_date"],r["due_date"],"Overdue" if r["overdue"] else "On time"] for r in rows]
    if kind=="returned":
        rows=tx("WHERE t.return_date IS NOT NULL",order="ORDER BY t.return_date DESC")
        return "Returned books report",["Book","Member","Issued","Returned","Fine (Rs)"],[[r["title"],r["member"],r["issue_date"],r["return_date"],r["fine"]] for r in rows]
    if kind=="fines":
        rows=tx("WHERE (t.return_date IS NULL AND t.due_date < :today) OR t.fine>0",order="ORDER BY t.due_date")
        return "Fines report",["Book","Member","Due","Fine (Rs)","Status"],[[r["title"],r["member"],r["due_date"],r["fine_now"],"Paid" if r["fine_paid"] else ("Pending" if r["return_date"] else "Accruing")] for r in rows]
    abort(404)

@app.route("/reports")
@admin_required
def reports():
    kind=request.args.get("type","books")
    title,head,rows=report_data(kind)
    return render_template("reports.html",kind=kind,title=title,head=head,rows=rows)

@app.route("/reports/<kind>.csv")
@admin_required
def report_csv(kind):
    title,head,rows=report_data(kind); out=io.StringIO()
    w=csv.writer(out); w.writerow(head); w.writerows(rows)
    return Response(out.getvalue(),mimetype="text/csv",headers={"Content-Disposition":f"attachment; filename={kind}_report.csv"})

@app.errorhandler(403)
def e403(_): return render_template("error.html",code=403,msg="You do not have permission to open this page."),403
@app.errorhandler(404)
def e404(_): return render_template("error.html",code=404,msg="The page you asked for was not found."),404

init_db()
if __name__ == "__main__":
    # Debug mode is OFF unless you explicitly set FLASK_DEBUG=1 on your own machine.
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")),
            debug=os.environ.get("FLASK_DEBUG") == "1")
