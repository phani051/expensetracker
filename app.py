from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import os
from openpyxl import Workbook
from io import BytesIO
from datetime import timedelta, datetime

# ---------------- CATEGORY ICONS ----------------
CATEGORY_ICONS = {
    "Food & Dining": ("bi bi-egg-fried", "🍔"),
    "Transportation": ("bi bi-truck", "🚗"),
    "Housing & Utilities": ("bi bi-house", "🏠"),
    "Health & Fitness": ("bi bi-heart-pulse", "💪"),
    "Entertainment": ("bi bi-controller", "🎮"),
    "Shopping": ("bi bi-bag", "🛍️"),
    "Education": ("bi bi-book", "📚"),
    "Travel": ("bi bi-airplane", "✈️"),
    "Bills & EMI": ("bi bi-credit-card", "💳"),
    "Miscellaneous": ("bi bi-three-dots", "🌀"),
    "Investment": ("bi bi-graph-up-arrow", "📈")  # NEW CATEGORY
}

app = Flask(__name__)
app.secret_key = "supersecretkey"
DB_NAME = "expenses.db"


# ---------------- DATABASE INIT ----------------
def init_db():
    first_time = not os.path.exists(DB_NAME)
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()

        # Users
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      username TEXT UNIQUE,
                      password TEXT,
                      is_admin INTEGER DEFAULT 0)''')

        # Expenses
        c.execute('''CREATE TABLE IF NOT EXISTS expenses
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      amount REAL,
                      category TEXT,
                      note TEXT,
                      date TEXT,
                      FOREIGN KEY(user_id) REFERENCES users(id))''')

        # Income
        c.execute('''CREATE TABLE IF NOT EXISTS income
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      amount REAL,
                      source TEXT,
                      note TEXT,
                      date TEXT,
                      FOREIGN KEY(user_id) REFERENCES users(id))''')

        # Recurring Expenses
        c.execute('''CREATE TABLE IF NOT EXISTS recurring_expenses
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      amount REAL,
                      category TEXT,
                      note TEXT,
                      frequency TEXT,
                      next_due_date TEXT,
                      FOREIGN KEY(user_id) REFERENCES users(id))''')

        # Default Admin
        default_admin_user = "phani"
        default_admin_pass = generate_password_hash("admin123")
        c.execute("SELECT id FROM users WHERE username=?", (default_admin_user,))
        user = c.fetchone()
        if not user:
            c.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, 1)",
                      (default_admin_user, default_admin_pass))
            print("Default admin user 'phani' created with password 'admin123'")
        else:
            c.execute("UPDATE users SET is_admin=1 WHERE username=?", (default_admin_user,))
        conn.commit()


# ---------------- HELPERS ----------------
def get_user_id():
    return session.get("user_id")


def is_admin():
    if not get_user_id():
        return False
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT is_admin FROM users WHERE id=?", (get_user_id(),))
        result = c.fetchone()
        return result and result[0] == 1
    
def get_next_due_date(current_date, frequency):
    """Calculate next due date based on frequency"""
    if frequency == "daily":
        return current_date + timedelta(days=1)
    elif frequency == "weekly":
        return current_date + timedelta(weeks=1)
    elif frequency == "monthly":
        # Approx: add 30 days (can refine later)
        return current_date + timedelta(days=30)
    return current_date


# ---------------- ROUTES ----------------


@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    # ---------- Auto-add recurring expenses ----------
    today = datetime.now().date()
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        # Get due recurring
        c.execute("""
            SELECT id, amount, category, note, frequency, next_due_date
            FROM recurring_expenses
            WHERE user_id=? AND date(next_due_date) <= date(?)
        """, (user_id, today))
        due_recurring = c.fetchall()

        # Insert due into expenses and update next_due_date
        for rec in due_recurring:
            rec_id, amount, category, note, frequency, next_due_date = rec

            # Insert into expenses
            c.execute("""
                INSERT INTO expenses (user_id, amount, category, note, date)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, amount, category, note, today.strftime('%Y-%m-%d %H:%M:%S')))

            # Update next due date
            next_dt = get_next_due_date(today, frequency)
            c.execute("""
                UPDATE recurring_expenses
                SET next_due_date=?
                WHERE id=?
            """, (next_dt.strftime('%Y-%m-%d'), rec_id))

        conn.commit()

    # ---------- Rest of your existing index logic ----------
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    category = request.args.get('category')
    search = request.args.get('search')

    filters_expense = "user_id=?"
    params_expense = [user_id]

    if from_date:
        filters_expense += " AND date(date) >= date(?)"
        params_expense.append(from_date)
    if to_date:
        filters_expense += " AND date(date) <= date(?)"
        params_expense.append(to_date)
    if category:
        filters_expense += " AND category=?"
        params_expense.append(category)
    if search:
        filters_expense += " AND note LIKE ?"
        params_expense.append(f"%{search}%")

    filters_income = "user_id=?"
    params_income = [user_id]

    if from_date:
        filters_income += " AND date(date) >= date(?)"
        params_income.append(from_date)
    if to_date:
        filters_income += " AND date(date) <= date(?)"
        params_income.append(to_date)
    if search:
        filters_income += " AND note LIKE ?"
        params_income.append(f"%{search}%")

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()

        # Expenses
        c.execute(f"SELECT id, amount, category, note, date FROM expenses WHERE {filters_expense} ORDER BY date DESC", params_expense)
        expenses = c.fetchall()

        # Income
        c.execute(f"SELECT id, amount, source, note, date FROM income WHERE {filters_income} ORDER BY date DESC", params_income)
        income = c.fetchall()

        # Totals
        c.execute("SELECT SUM(amount) FROM expenses WHERE user_id=?", (user_id,))
        total_expenses = c.fetchone()[0] or 0
        c.execute("SELECT SUM(amount) FROM income WHERE user_id=?", (user_id,))
        total_income = c.fetchone()[0] or 0
        balance = total_income - total_expenses

        # Pie chart data
        c.execute(f"""
            SELECT category, SUM(amount)
            FROM expenses
            WHERE {filters_expense}
            GROUP BY category
        """, params_expense)
        expense_data = c.fetchall()
        expense_labels = [row[0] for row in expense_data]
        expense_values = [row[1] for row in expense_data]

        # Monthly bar chart data
        c.execute(f"""
            SELECT strftime('%Y-%m', date), SUM(amount)
            FROM income
            WHERE {filters_income}
            GROUP BY strftime('%Y-%m', date)
            ORDER BY strftime('%Y-%m', date)
        """, params_income)
        income_data = dict(c.fetchall())

        c.execute(f"""
            SELECT strftime('%Y-%m', date), SUM(amount)
            FROM expenses
            WHERE {filters_expense}
            GROUP BY strftime('%Y-%m', date)
            ORDER BY strftime('%Y-%m', date)
        """, params_expense)
        expense_month_data = dict(c.fetchall())

        months = sorted(set(list(income_data.keys()) + list(expense_month_data.keys())))
        income_per_month = [income_data.get(m, 0) for m in months]
        expenses_per_month = [expense_month_data.get(m, 0) for m in months]

    return render_template(
        'index.html',
        expenses=expenses,
        income=income,
        total_income=total_income,
        total_expenses=total_expenses,
        balance=balance,
        category_icons=CATEGORY_ICONS,
        expense_labels=expense_labels,
        expense_values=expense_values,
        months=months,
        income_per_month=income_per_month,
        expenses_per_month=expenses_per_month
    )



@app.route('/recurring', methods=['GET', 'POST'])
def recurring():
    if not get_user_id():
        return redirect(url_for('login'))

    if request.method == 'POST':
        amount = request.form['amount']
        category = request.form['category']
        note = request.form['note']
        frequency = request.form['frequency']

        next_due_date = datetime.now().strftime('%Y-%m-%d')

        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO recurring_expenses (user_id, amount, category, note, frequency, next_due_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (get_user_id(), amount, category, note, frequency, next_due_date))
            conn.commit()

        flash('Recurring expense added!')
        return redirect(url_for('recurring'))

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT id, amount, category, note, frequency, next_due_date FROM recurring_expenses WHERE user_id=?", (get_user_id(),))
        recurring_items = c.fetchall()

    return render_template('recurring.html', recurring_items=recurring_items, category_icons=CATEGORY_ICONS)


@app.route('/delete_recurring/<int:id>', methods=['POST'])
def delete_recurring(id):
    if not get_user_id():
        return redirect(url_for('login'))

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM recurring_expenses WHERE id=? AND user_id=?", (id, get_user_id()))
        conn.commit()

    flash('Recurring expense deleted!')
    return redirect(url_for('recurring'))

@app.route('/export_excel')
def export_excel():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    category = request.args.get('category')
    search = request.args.get('search')

    # Build filters for expenses
    filters_expense = "user_id=?"
    params_expense = [user_id]

    if from_date:
        filters_expense += " AND date(date) >= date(?)"
        params_expense.append(from_date)
    if to_date:
        filters_expense += " AND date(date) <= date(?)"
        params_expense.append(to_date)
    if category:
        filters_expense += " AND category=?"
        params_expense.append(category)
    if search:
        filters_expense += " AND note LIKE ?"
        params_expense.append(f"%{search}%")

    # Query expenses
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute(f"SELECT amount, category, note, date FROM expenses WHERE {filters_expense} ORDER BY date DESC", params_expense)
        expenses = c.fetchall()

        # Query income (apply only date/search filters if you want symmetry)
        c.execute("SELECT amount, source, note, date FROM income WHERE user_id=? ORDER BY date DESC", (user_id,))
        income = c.fetchall()

    # Create workbook
    wb = Workbook()

    # Expenses Sheet
    ws_exp = wb.active
    ws_exp.title = "Expenses"
    ws_exp.append(["Amount", "Category", "Note", "Date"])
    for row in expenses:
        ws_exp.append(row)

    # Income Sheet
    ws_inc = wb.create_sheet(title="Income")
    ws_inc.append(["Amount", "Source", "Note", "Date"])
    for row in income:
        ws_inc.append(row)

    # Save to memory
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="expenses_income.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route('/add', methods=['GET', 'POST'])
def add_expense():
    if not get_user_id():
        return redirect(url_for('login'))

    if request.method == 'POST':
        amount = request.form['amount']
        category = request.form['category']
        note = request.form['note']
        date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            c.execute("INSERT INTO expenses (user_id, amount, category, note, date) VALUES (?, ?, ?, ?, ?)",
                      (get_user_id(), amount, category, note, date))
            conn.commit()

        flash("Expense added successfully!")
        return redirect(url_for('index'))

    return render_template('add_expense.html', category_icons=CATEGORY_ICONS)

# -------- USER AUTH --------
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        try:
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
                conn.commit()
            flash("Signup successful! Please login.")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Username already exists!")
            return redirect(url_for('signup'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            c.execute("SELECT id, password, is_admin FROM users WHERE username=?", (username,))
            user = c.fetchone()

        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            session['username'] = username
            session['is_admin'] = user[2]
            return redirect(url_for('index'))
        else:
            flash("Invalid username or password!")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# -------- USER PASSWORD CHANGE --------
@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if not get_user_id():
        return redirect(url_for('login'))

    if request.method == 'POST':
        old_password = request.form['old_password']
        new_password = request.form['new_password']

        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            c.execute("SELECT password FROM users WHERE id=?", (get_user_id(),))
            user = c.fetchone()

        if user and check_password_hash(user[0], old_password):
            with sqlite3.connect(DB_NAME) as conn:
                c = conn.cursor()
                c.execute("UPDATE users SET password=? WHERE id=?",
                          (generate_password_hash(new_password), get_user_id()))
                conn.commit()
            flash("Password changed successfully!")
            return redirect(url_for('index'))
        else:
            flash("Old password incorrect!")
            return redirect(url_for('change_password'))

    return render_template('change_password.html')

@app.route('/add_income', methods=['GET', 'POST'])
def add_income():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        amount = request.form['amount']
        source = request.form['source']
        note = request.form['note']
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            c.execute("INSERT INTO income (user_id, amount, source, note, date) VALUES (?, ?, ?, ?, ?)",
                      (session['user_id'], amount, source, note, date))
            conn.commit()

        flash('Income added successfully!')
        return redirect(url_for('index'))

    return render_template('add_income.html')

@app.route('/view_income')
def view_income():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT id, amount, source, note, date FROM income WHERE user_id=? ORDER BY date DESC", (session['user_id'],))
        income_data = c.fetchall()

    return render_template('view_income.html', income=income_data)

@app.route('/delete_expense/<int:id>')
def delete_expense(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        # Delete only if belongs to current user
        c.execute("DELETE FROM expenses WHERE id=? AND user_id=?", (id, session['user_id']))
        conn.commit()

    flash('Expense deleted!')
    return redirect(url_for('index'))

@app.route('/delete_income/<int:id>')
def delete_income(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        # Delete only if belongs to current user
        c.execute("DELETE FROM income WHERE id=? AND user_id=?", (id, session['user_id']))
        conn.commit()

    flash('Income deleted!')
    return redirect(url_for('index'))



# -------- ADMIN PANEL --------
@app.route('/admin')
def admin_panel():
    if not is_admin():
        flash("Access denied.")
        return redirect(url_for('index'))

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT id, username FROM users")
        users = c.fetchall()

    return render_template('admin.html', users=users)

@app.route('/admin/reset/<int:user_id>', methods=['POST'])
def admin_reset_password(user_id):
    if not is_admin():
        flash("Access denied.")
        return redirect(url_for('index'))

    new_password = generate_password_hash("default123")  # temporary password
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET password=? WHERE id=?", (new_password, user_id))
        conn.commit()

    flash("Password reset to 'default123'. Ask user to change it.")
    return redirect(url_for('admin_panel'))

# ---------------- MAIN ----------------
if __name__ == '__main__':
    init_db()
    app.run(host="192.168.0.100", port=5000, debug=True)
