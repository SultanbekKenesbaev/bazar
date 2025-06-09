from flask import Flask, render_template, request, redirect, url_for, session, send_file
import sqlite3
from datetime import datetime
import pandas as pd
import io
import pytz
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'
DATABASE = 'database.db'
LOCAL_TZ = pytz.timezone('Asia/Tashkent') 


def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db


def convert_to_local_time(utc_time_str):
    try:
        utc_time = datetime.strptime(utc_time_str, '%Y-%m-%d %H:%M:%S')
        utc_time = pytz.utc.localize(utc_time)
        local_time = utc_time.astimezone(LOCAL_TZ)
        return local_time.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError) as e:
        print(f"Ошибка преобразования времени: {utc_time_str}, ошибка: {e}")
        return utc_time_str


def create_tables():
    db = get_db()
    db.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('operator', 'admin'))
                  )''')
    db.execute('''CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL
                  )''')
    db.execute('''CREATE TABLE IF NOT EXISTS assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL,
                    operator_id INTEGER NOT NULL,
                    assignee_name TEXT NOT NULL,
                    assignee_surname TEXT NOT NULL,
                    amount REAL NOT NULL,
                    stall_number TEXT NOT NULL,
                    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (category_id) REFERENCES categories (id),
                    FOREIGN KEY (operator_id) REFERENCES users (id)
                  )''')
    db.commit()


    if db.execute('SELECT COUNT(*) FROM categories').fetchone()[0] == 0:
        db.execute('INSERT INTO categories (name) VALUES (?)', ('Продукты',))
        db.execute('INSERT INTO categories (name) VALUES (?)', ('Скот',))
        db.execute('INSERT INTO categories (name) VALUES (?)', ('Одежда',))
    if db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0:
        db.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)', ('admin1', 'adminpass', 'admin'))
        db.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)', ('operator1', 'oppass1', 'operator'))
        db.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)', ('operator2', 'oppass2', 'operator'))
    if db.execute('SELECT COUNT(*) FROM assignments').fetchone()[0] == 0:
        current_time = datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        db.execute('INSERT INTO assignments (category_id, operator_id, assignee_name, assignee_surname, amount, stall_number, assigned_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (1, 2, 'Иван', 'Иванов', 10000, 'STALL-1', current_time))
        db.execute('INSERT INTO assignments (category_id, operator_id, assignee_name, assignee_surname, amount, stall_number, assigned_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (2, 3, 'Петр', 'Петров', 20000, 'STALL-2', current_time))
    db.commit()

# Маршрут для входа
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password)).fetchone()
        if user:
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['username'] = user['username']
            if user['role'] == 'operator':
                return redirect(url_for('operator_dashboard'))
            else:
                return redirect(url_for('admin_reports'))
        else:
            return render_template('login.html', error='Неверные учетные данные')
    return render_template('login.html')

# Маршрут для выхода
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('role', None)
    session.pop('username', None)
    return redirect(url_for('login'))

# Панель оператора
@app.route('/operator_dashboard', methods=['GET', 'POST'])
def operator_dashboard():
    if 'user_id' not in session or session['role'] != 'operator':
        return redirect(url_for('login'))
    db = get_db()
    operator_id = session['user_id']
    selected_date = request.form.get('selected_date', datetime.now(LOCAL_TZ).date().strftime('%Y-%m-%d'))
    
    if request.method == 'POST' and 'selected_date' in request.form:
        selected_date = request.form['selected_date']
    
    assignments = db.execute('''
        SELECT a.*, c.name as category_name
        FROM assignments a
        JOIN categories c ON a.category_id = c.id
        WHERE DATE(a.assigned_at) = ? AND a.operator_id = ?
    ''', (selected_date, operator_id)).fetchall()
    print("Assignments for operator", operator_id, "on", selected_date, ":", [(a['id'], a['assigned_at']) for a in assignments])
    assignments = [dict(assignment, assigned_at=convert_to_local_time(assignment['assigned_at'])) for assignment in assignments]
    total_assignments = len(assignments)
    total_amount = sum(assignment['amount'] for assignment in assignments)
    return render_template('operator_dashboard.html', assignments=assignments, total_assignments=total_assignments, total_amount=total_amount, selected_date=selected_date)

# Форма для назначения места
@app.route('/assign_place', methods=['GET'])
def assign_place():
    if 'user_id' not in session or session['role'] != 'operator':
        return redirect(url_for('login'))
    db = get_db()
    categories = db.execute('SELECT * FROM categories').fetchall()
    return render_template('assign_place.html', categories=categories)

# Обработка назначения места
@app.route('/assign', methods=['POST'])
def assign():
    if 'user_id' not in session or session['role'] != 'operator':
        return redirect(url_for('login'))
    category_id = request.form['category_id']
    assignee_name = request.form['assignee_name']
    assignee_surname = request.form['assignee_surname']
    amount = request.form['amount']
    operator_id = session['user_id']
    
    # Генерация уникального номера стенда
    db = get_db()
    last_assignment = db.execute('SELECT MAX(id) FROM assignments').fetchone()[0]
    stall_number = f'STALL-{last_assignment + 1 if last_assignment else 1}'
    
    db.execute('INSERT INTO assignments (category_id, operator_id, assignee_name, assignee_surname, amount, stall_number) VALUES (?, ?, ?, ?, ?, ?)',
               (category_id, operator_id, assignee_name, assignee_surname, amount, stall_number))
    db.commit()
    assignment_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    return redirect(url_for('receipt', assignment_id=assignment_id))

# Печать чека
@app.route('/receipt/<int:assignment_id>')
def receipt(assignment_id):
    db = get_db()
    assignment = db.execute('''
        SELECT a.*, c.name as category_name, u.username as operator_name
        FROM assignments a
        JOIN categories c ON a.category_id = c.id
        JOIN users u ON a.operator_id = u.id
        WHERE a.id = ?
    ''', (assignment_id,)).fetchone()
    if not assignment:
        return render_template('error.html', message='Назначение не найдено'), 404
    assignment = dict(assignment)
    assignment['assigned_at'] = convert_to_local_time(assignment['assigned_at'])
    return render_template('receipt.html', assignment=assignment)

# Отчеты администратора
@app.route('/admin_reports', methods=['GET', 'POST'])
def admin_reports():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    db = get_db()
    operators = db.execute('SELECT id, username FROM users WHERE role = ?', ('operator',)).fetchall()
    categories = db.execute('SELECT * FROM categories').fetchall()
    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        selected_category = request.form.get('category_id', '')
        selected_operator = request.form.get('operator_id', '')
        
        query = '''
            SELECT a.*, c.name as category_name, u.username as operator_name
            FROM assignments a
            JOIN categories c ON a.category_id = c.id
            JOIN users u ON a.operator_id = u.id
            WHERE a.assigned_at BETWEEN ? AND ?
        '''
        params = [start_date, end_date]
        
        if selected_category:
            query += ' AND a.category_id = ?'
            params.append(selected_category)
        if selected_operator:
            query += ' AND a.operator_id = ?'
            params.append(selected_operator)
        
        assignments = db.execute(query, params).fetchall()
        assignments = [dict(assignment, assigned_at=convert_to_local_time(assignment['assigned_at'])) for assignment in assignments]
        total_assignments = len(assignments)
        total_amount = sum(assignment['amount'] for assignment in assignments)
        
        selected_operator_name = None
        if selected_operator:
            for operator in operators:
                if str(operator['id']) == selected_operator:
                    selected_operator_name = operator['username']
                    break
        
        selected_category_name = None
        if selected_category:
            for category in categories:
                if str(category['id']) == selected_category:
                    selected_category_name = category['name']
                    break
        
        return render_template('admin_reports.html', assignments=assignments, start_date=start_date, end_date=end_date, 
                              total_assignments=total_assignments, total_amount=total_amount, operators=operators, 
                              categories=categories, selected_category=selected_category, selected_operator=selected_operator,
                              selected_operator_name=selected_operator_name, selected_category_name=selected_category_name)
    return render_template('admin_reports.html', operators=operators, categories=categories)

# Экспорт отчетов администратора в Excel
@app.route('/export_excel', methods=['POST'])
def export_excel():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    start_date = request.form['start_date']
    end_date = request.form['end_date']
    selected_category = request.form.get('category_id', '')
    selected_operator = request.form.get('operator_id', '')
    
    db = get_db()
    query = '''
        SELECT a.assigned_at, c.name as category_name, 
               a.assignee_name, a.assignee_surname, a.amount, u.username as operator_name
        FROM assignments a
        JOIN categories c ON a.category_id = c.id
        JOIN users u ON a.operator_id = u.id
        WHERE a.assigned_at BETWEEN ? AND ?
    '''
    params = [start_date, end_date]
    
    if selected_category:
        query += ' AND a.category_id = ?'
        params.append(selected_category)
    if selected_operator:
        query += ' AND a.operator_id = ?'
        params.append(selected_operator)
    
    assignments = db.execute(query, params).fetchall()
    assignments = [dict(assignment, assigned_at=convert_to_local_time(assignment['assigned_at'])) for assignment in assignments]
    
    data = [{
        'Дата': assignment['assigned_at'],
        'Категория': assignment['category_name'],
        'Имя арендатора': assignment['assignee_name'],
        'Фамилия арендатора': assignment['assignee_surname'],
        'Сумма': assignment['amount'],
        'Оператор': assignment['operator_name']
    } for assignment in assignments]
    df = pd.DataFrame(data)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Отчет')
    output.seek(0)
    
    return send_file(output, download_name=f'report_{start_date}_to_{end_date}.xlsx', as_attachment=True)

# Экспорт отчетов оператора в Excel
@app.route('/export_operator_excel', methods=['POST'])
def export_operator_excel():
    if 'user_id' not in session or session['role'] != 'operator':
        return redirect(url_for('login'))
    selected_date = request.form['selected_date']
    operator_id = session['user_id']
    
    db = get_db()
    assignments = db.execute('''
        SELECT a.assigned_at, c.name as category_name, 
               a.assignee_name, a.assignee_surname, a.amount, u.username as operator_name
        FROM assignments a
        JOIN categories c ON a.category_id = c.id
        JOIN users u ON a.operator_id = u.id
        WHERE DATE(a.assigned_at) = ? AND a.operator_id = ?
    ''', (selected_date, operator_id)).fetchall()
    assignments = [dict(assignment, assigned_at=convert_to_local_time(assignment['assigned_at'])) for assignment in assignments]
    
    data = [{
        'Дата': assignment['assigned_at'],
        'Категория': assignment['category_name'],
        'Имя арендатора': assignment['assignee_name'],
        'Фамилия арендатора': assignment['assignee_surname'],
        'Сумма': assignment['amount'],
        'Оператор': assignment['operator_name']
    } for assignment in assignments]
    df = pd.DataFrame(data)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Отчет')
    output.seek(0)
    
    return send_file(output, download_name=f'report_{selected_date}.xlsx', as_attachment=True)

@app.route('/')
def index():
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
