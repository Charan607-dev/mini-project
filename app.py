from unittest import result

from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "super_secret_bank_project_key"

def get_db_connection():
    conn = sqlite3.connect('bank.db')
    conn.row_factory = sqlite3.Row
    return conn
from deepface import DeepFace
import cv2
import os

def verify_face(account):

    known_img = f"faces/{account}.jpg"

    if not os.path.exists(known_img):
        print("Known image not found")
        return False

    cam = cv2.VideoCapture(0)

    while True:
        ret, frame = cam.read()

        cv2.imshow("Face Verification - Press Q", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            cv2.imwrite("temp.jpg", frame)
            break

    cam.release()
    cv2.destroyAllWindows()

    try:
        result = DeepFace.verify(
            img1_path=known_img,
            img2_path="temp.jpg",
            enforce_detection=True,
            model_name="VGG-Face"
        )

        return result["verified"] and result["distance"] < 0.35

    except Exception as e:
        print("DeepFace Error:", e)
        return False
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()  # Kept strictly lowercase
    
    # Users table (Fixed: changed TEXT NOT EXISTS to TEXT NOT NULL)
    cur.execute('''
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        account TEXT UNIQUE,
        password TEXT,
        balance REAL
    )
    ''')
    
    # Transactions table (Fixed: cur lowercase)
    cur.execute('''
    CREATE TABLE IF NOT EXISTS transactions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account TEXT,
        type TEXT,
        amount REAL
    )
    ''')
    conn.commit()
    conn.close()

# Setup database tables
init_db()

# ----------------- ROUTES -----------------

@app.route('/')
def home():
    if 'account' in session:
        return redirect('/dashboard')
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():

    if request.method == 'POST':

        name = request.form['name']
        password = request.form['password']
        balance = float(request.form.get('balance', 0))

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT MAX(CAST(account AS INTEGER)) FROM users")
        result = cur.fetchone()

        if result[0] is None:
            account = "100"
        else:
            account = str(result[0] + 1)

        if balance < 0:
            flash("Initial deposit cannot be negative!", "error")
            conn.close()
            return redirect('/register')

        hashed_password = generate_password_hash(password)

        try:
            cur.execute(
                'INSERT INTO users(name, account, password, balance) VALUES(?,?,?,?)',
                (name, account, hashed_password, balance)
            )

            conn.commit()

            flash(
                f"Account Created Successfully! Your Account Number is {account}",
                "success"
            )

            return redirect('/')

        except sqlite3.IntegrityError:
            flash("Error creating account.", "error")
            return redirect('/register')

        finally:
            conn.close()

    return render_template('register.html')

@app.route('/login', methods=['POST'])
def login():
    account = request.form['account']
    password = request.form['password']

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE account=?', (account,))
    user = cur.fetchone()
    conn.close()

    if user and check_password_hash(user['password'], password):
        if verify_face(account):
            session['account'] = account
            session['name'] = user['name']
            return redirect('/dashboard')
        else:
            flash("Face Verification Failed!", "error")
            return redirect('/')
    flash("Invalid Account Number or Password.", "error")
    return redirect('/')

@app.route('/dashboard')
def dashboard():
    if 'account' not in session:
        flash("Please log in to access the dashboard.", "error")
        return redirect('/')

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE account=?', (session['account'],))
    user = cur.fetchone()
    conn.close()

    return render_template('dashboard.html', user=user)

@app.route('/deposit', methods=['POST'])
def deposit():
    if 'account' not in session:
        return redirect('/')

    amount = float(request.form['amount'])
    account = session['account']

    if amount <= 0:
        flash("Deposit amount must be greater than zero.", "error")
        return redirect('/dashboard')

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('UPDATE users SET balance = balance + ? WHERE account=?', (amount, account))
        cur.execute('INSERT INTO transactions(account, type, amount) VALUES(?,?,?)', (account, 'Deposit', amount))
        conn.commit()
        flash(f"Successfully deposited ${amount:.2f}", "success")
    except Exception:
        conn.rollback()
        flash("An error occurred during transaction processing.", "error")
    finally:
        conn.close()

    return redirect('/dashboard')

@app.route('/withdraw', methods=['POST'])
def withdraw():
    if 'account' not in session:
        return redirect('/')

    amount = float(request.form['amount'])
    account = session['account']

    if amount <= 0:
        flash("Withdrawal amount must be greater than zero.", "error")
        return redirect('/dashboard')

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT balance FROM users WHERE account=?', (account,))
    balance = cur.fetchone()['balance']

    if amount <= balance:
        try:
            cur.execute('UPDATE users SET balance = balance - ? WHERE account=?', (amount, account))
            cur.execute('INSERT INTO transactions(account, type, amount) VALUES(?,?,?)', (account, 'Withdrawal', amount))
            conn.commit()
            flash(f"Successfully withdrew ${amount:.2f}", "success")
        except Exception:
            conn.rollback()
            flash("An error occurred.", "error")
    else:
        flash("Insufficient funds available.", "error")
        
    conn.close()
    return redirect('/dashboard')

@app.route('/transfer', methods=['GET', 'POST'])
def transfer():
    if 'account' not in session:
        return redirect('/')

    if request.method == 'POST':
        receiver = request.form['receiver']
        amount = float(request.form['amount'])
        sender = session['account']

        if receiver == sender:
            flash("You cannot transfer money to yourself.", "error")
            return redirect('/transfer')
        if amount <= 0:
            flash("Transfer amount must be greater than zero.", "error")
            return redirect('/transfer')

        conn = get_db_connection()
        cur = conn.cursor()

        # Check receiver exists
        cur.execute('SELECT * FROM users WHERE account=?', (receiver,))
        receiver_user = cur.fetchone()
        
        if not receiver_user:
            flash("Receiver account number does not exist.", "error")
            conn.close()
            return redirect('/transfer')

        # Check sender funds
        cur.execute('SELECT balance FROM users WHERE account=?', (sender,))
        balance = cur.fetchone()['balance']

        if amount <= balance:
            try:
                cur.execute('UPDATE users SET balance = balance - ? WHERE account=?', (amount, sender))
                cur.execute('UPDATE users SET balance = balance + ? WHERE account=?', (amount, receiver))
                cur.execute('INSERT INTO transactions(account, type, amount) VALUES(?,?,?)', (sender, f"Sent to {receiver}", amount))
                cur.execute('INSERT INTO transactions(account, type, amount) VALUES(?,?,?)', (receiver, f"Received from {sender}", amount))
                conn.commit()
                flash(f"Successfully transferred ${amount:.2f} to Account {receiver}", "success")
                conn.close()
                return redirect('/dashboard')
            except Exception:
                conn.rollback()
                flash("Transfer failed during transaction commit.", "error")
        else:
            flash("Insufficient funds for this transfer.", "error")
        
        conn.close()
        return redirect('/transfer')

    return render_template('transfer.html')

@app.route('/transactions')
def transactions():
    if 'account' not in session:
        return redirect('/')

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM transactions WHERE account=? ORDER BY id DESC', (session['account'],))
    data = cur.fetchall()
    conn.close()

    return render_template('transactions.html', data=data)

@app.route('/delete')
def delete_account():
    if 'account' not in session:
        return redirect('/')

    account = session['account']
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('DELETE FROM users WHERE account=?', (account,))
        cur.execute('DELETE FROM transactions WHERE account=?', (account,))
        conn.commit()
        session.clear()
        return "<html><body><script>alert('Account permanently closed.'); window.location.href='/';</script></body></html>"
    except Exception:
        conn.rollback()
        flash("Could not delete account. Try again later.", "error")
        return redirect('/dashboard')
    finally:
        conn.close()

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')
@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'account' not in session:
        return redirect('/')

    if request.method == 'POST':
        old_password = request.form['old_password']
        new_password = request.form['new_password']

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            'SELECT password FROM users WHERE account=?',
            (session['account'],)
        )

        user = cur.fetchone()

        if check_password_hash(user['password'], old_password):
            hashed = generate_password_hash(new_password)

            cur.execute(
                'UPDATE users SET password=? WHERE account=?',
                (hashed, session['account'])
            )

            conn.commit()
            flash("Password changed successfully!", "success")
        else:
            flash("Old password is incorrect!", "error")

        conn.close()
        return redirect('/dashboard')

    return render_template('change_password.html')
@app.route('/loan_checker', methods=['GET', 'POST'])
def loan_checker():

    result = None

    if request.method == 'POST':

        income = float(request.form['income'])
        existing_loan = float(request.form['existing_loan'])

        if income >= 30000 and existing_loan < 50000:
            result = "Eligible for Loan"
        else:
            result = "Not Eligible"

    return render_template(
        'loan_checker.html',
        result=result
    )
@app.route('/admin')
def admin():

    if 'account' not in session:
        return redirect('/')

    admins = ['100']

    if session['account'] not in admins:
        flash("Access Denied!", "error")
        return redirect('/dashboard')

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users")
    users = cur.fetchall()

    cur.execute("SELECT COUNT(*) FROM users")
    total_accounts = cur.fetchone()[0]

    cur.execute("SELECT SUM(balance) FROM users")
    total_balance = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM transactions")
    total_transactions = cur.fetchone()[0]

    conn.close()

    return render_template(
        'admin.html',
        users=users,
        total_accounts=total_accounts,
        total_balance=total_balance,
        total_transactions=total_transactions
    )
@app.route('/fd_calculator', methods=['GET', 'POST'])
def fd_calculator():

    maturity = None

    if request.method == 'POST':

        principal = float(request.form['principal'])
        rate = float(request.form['rate'])
        years = float(request.form['years'])

        maturity = principal * ((1 + rate/100) ** years)

    return render_template(
        'fd_calculator.html',
        maturity=maturity
    )
@app.route('/expense_report')
def expense_report():

    if 'account' not in session:
        return redirect('/')

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute('''
        SELECT SUM(amount) as total
        FROM transactions
        WHERE account=?
        AND (
            type='Withdrawal'
            OR type LIKE 'Sent%'
        )
    ''', (session['account'],))

    total = cur.fetchone()['total']

    conn.close()

    return render_template(
        'expense_report.html',
        total=total or 0
    )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)