import secrets
from uuid import uuid4
from flask import Flask, Response, jsonify, render_template, request, redirect, send_file
from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
import json
from datetime import datetime, date
import calendar
from collections import defaultdict
from flask_wtf.csrf import CSRFProtect
import pytz
import requests

app = Flask(__name__)
secret_key = os.urandom(24)
app.secret_key = secret_key
csrf = CSRFProtect(app)


if os.getenv("VERCEL") is None:
    from dotenv import load_dotenv
    load_dotenv()  # Load environment variables from .env file

# Spreadsheet ID dan range untuk menyimpan data
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
PDFSHIFT_API_KEY = os.getenv("PDFSHIFT_API_KEY")
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Load credentials
if os.getenv("VERCEL"):
    # Di Vercel: dari environment variable GOOGLE_CREDENTIALS
    service_account_info = json.loads(os.getenv("GOOGLE_CREDENTIALS", "{}"))
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info, scopes=SCOPES
    )
else:
    # Lokal: dari file credentials.json
    credentials = service_account.Credentials.from_service_account_file(
        'credentials.json', scopes=SCOPES
    )

sheets_service = build('sheets', 'v4', credentials=credentials)


## OTHERS
#--- Format rupiah --- 
@app.template_filter('format_rupiah')
def format_rupiah(amount):
    try:
        amount = float(amount)
        return f"Rp {amount:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return amount 

#--- Format tanggal ---
@app.template_filter("format_date")
def format_date(value):
    from datetime import datetime
    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except:
        return value

@app.template_filter('format_date_2')
def format_date_2(value):
    # Pastikan timezone ke Asia/Jakarta
    jakarta = pytz.timezone("Asia/Jakarta")
    if value.tzinfo is None:
        value = jakarta.localize(value)
    else:
        value = value.astimezone(jakarta)

    return value.strftime("%a, %d %b %Y %H.%M")

#--- Format bulan ---
@app.template_filter()
def format_month(value):
    try:
        dt = datetime.strptime(value, "%Y-%m")
        return dt.strftime("%B %Y")  # e.g. July 2025
    except:
        return value
    
@app.template_filter('monthname')
def monthname_filter(m):
    return calendar.month_name[int(m)]

@app.context_processor
def inject_now():
    return {'now': datetime.now}
 
# Ambil category di sheet Category
def get_categories(column):
    range_map= {
        "income" : "Category!A2:A",
        "expenses" : "Category!B2:B"
    }

    range_name = range_map.get(column)

    result = sheets_service.spreadsheets().values().get(spreadsheetId = SPREADSHEET_ID, range = range_name).execute()

    values = result.get('values', [])
    return [row[0] for row in values if row]

#ambil data untuk ditampilkan dalam tabel
def get_data(sheet_name):
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{sheet_name}!A2:E"
    ).execute()

    values = result.get('values', [])
    return values

# PDFSHIFT Configuration
def pdf_with_pdfshift(html_content, filename="report.pdf"):
    if not PDFSHIFT_API_KEY:
        print("PDFSHIFT_API_KEY not found in environment variables.")
        return False

    response = requests.post(
        "https://api.pdfshift.io/v3/convert/pdf",
        headers={
            "X-API-Key": PDFSHIFT_API_KEY
        },
        json={
            "source": html_content,
            "landscape": False,
            "use_print": False
        }
    )

    if response.status_code == 200:
        with open(filename, "wb") as f:
            f.write(response.content)
        return True
    else:
        print("PDFShift Error:", response.text)
        return False

    
@app.route("/")
def index():
    return redirect('dashboard')

# hitung growth
def get_growth(data):
    # Ambil dua bulan terakhir yang tidak nol
    nonzero = [v for v in reversed(data) if v != 0]
    if len(nonzero) >= 2 and nonzero[1] != 0:
        growth = ((nonzero[0] - nonzero[1]) / nonzero[1]) * 100
        return round(growth, 1)
    
def get_growth_series(values):
    growth_list = []
    for i in range(len(values)):
        if i == 0 or values[i - 1] == 0:
            growth_list.append(0)
        else:
            growth = ((values[i] - values[i - 1]) / abs(values[i - 1])) * 100
            growth_list.append(round(growth, 1))
    return growth_list
    
# Dashboard page
@app.route("/dashboard")
def dashboard():
    selected_year = request.args.get("year", datetime.now().year, type=int)
    
    # Ambil data dari Google Sheets
    income_data = get_data("Income")
    expenses_data = get_data("Expenses")

    # Buat struktur penampung total per bulan
    monthly_summary = defaultdict(lambda: {"income": 0, "expenses": 0})

    def process_data(data, tipe):
        for row in data:
            try:
                date_obj = datetime.strptime(row[1], "%Y-%m-%d")
                if date_obj.year == selected_year:
                    month_key = date_obj.strftime("%Y-%m")
                    amount = int(row[4].replace(".", "").replace(",", ""))
                    monthly_summary[month_key][tipe] += amount
            except (IndexError, ValueError):
                continue  # Lewati baris rusak

    process_data(income_data, "income")
    process_data(expenses_data, "expenses")

    # Tambahkan saldo
    for key in monthly_summary:
        summary = monthly_summary[key]
        summary["balance"] = summary["income"] - summary["expenses"]

    # Urutkan berdasarkan bulan
    sorted_months = sorted(monthly_summary.keys())
    summary_data = [(month, monthly_summary[month]) for month in sorted_months]

    chart_labels = [calendar.month_name[m] for m in range(1, 13)]
    chart_income = []
    chart_expenses = []
    chart_balance = []

    for m in range(1, 13):
        key = f"{selected_year}-{m:02d}"
        data = monthly_summary.get(key, {"income": 0, "expenses": 0, "balance": 0})
        chart_income.append(data["income"])
        chart_expenses.append(data["expenses"])
        chart_balance.append(data["balance"])

    # growth bulan ini
    net_balance = [i - e for i, e in zip(chart_income, chart_expenses)]
    income_growth = get_growth(chart_income)
    expenses_growth = get_growth(chart_expenses)
    net_growth = get_growth(net_balance)

    # growth series satu tahun
    income_growth_series = get_growth_series(chart_income)
    expenses_growth_series = get_growth_series(chart_expenses)
    net_growth_series = get_growth_series(net_balance)

    return render_template("dashboard.html", summary_data=summary_data, selected_year=str(selected_year),
                           chart_labels=chart_labels,
                           chart_income=chart_income,
                           chart_expenses=chart_expenses,
                           chart_balance=chart_balance,
                           income_growth=income_growth,
                           expenses_growth=expenses_growth,
                           net_growth=net_growth,
                           income_growth_series=income_growth_series,
                           expenses_growth_series=expenses_growth_series,
                           net_growth_series=net_growth_series)

# Income page
@app.route("/income", methods=["GET", "POST"])
def income():
    if request.method == "POST":
        try:
            income_id = secrets.token_hex(6)
            date_income = request.form["date"]
            item = request.form["item"]
            category = request.form["category"]
            amount = request.form["amount"]

            values = [[income_id, date_income, item, category, amount]]

            sheets_service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range="Income!A2:E",
                valueInputOption="USER_ENTERED",
                body={"values": values}
            ).execute()

            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
    
    income_categories = get_categories("income")
    income_data = get_data("Income")

    # Ambil bulan & tahun dari query param, default: bulan sekarang
    selected_month = request.args.get("month", default=str(datetime.now().month))
    selected_year = request.args.get("year", default=str(datetime.now().year))

    # Filter data berdasarkan bulan & tahun
    filtered_data = []
    for row in income_data:
        try:
            row_date = datetime.strptime(row[1], "%Y-%m-%d")
            if (str(row_date.month) == selected_month and str(row_date.year) == selected_year):
                filtered_data.append(row)
        except Exception:
            continue

    month_name = calendar.month_name[int(selected_month)]

    # hitung total per kategoru
    category_totals = defaultdict(float)
    for row in filtered_data:
        try:
            category = row[3]
            amount = float(row[4].replace(",", "").replace(".", ""))
            category_totals[category] += amount
        except:
            continue

    return render_template("form.html", tipe="income", today=date.today(),
                           categories=income_categories,
                           records = filtered_data,
                           selected_month=selected_month,
                           selected_year=selected_year,
                           month_name=month_name,
                           chart_labels=list(category_totals.keys()),
                           chart_data=list(category_totals.values()))

# Expenses page
@app.route("/expenses", methods=["GET", "POST"])
def expenses():
    if request.method == "POST":
        try:
            expenses_id = secrets.token_hex(6)
            date_expenses = request.form["date"]
            item = request.form["item"]
            category = request.form["category"]
            amount = request.form["amount"]

            values = [[expenses_id, date_expenses, item, category, amount]]

            sheets_service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range="Expenses!A2:E",
                valueInputOption="USER_ENTERED",
                body={"values": values}
            ).execute()

            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})

    expenses_categories = get_categories("expenses")
    expenses_data = get_data("Expenses")

    # Ambil bulan & tahun dari query param, default: bulan sekarang
    selected_month = request.args.get("month", default=str(datetime.now().month))
    selected_year = request.args.get("year", default=str(datetime.now().year))

    # Filter data berdasarkan bulan & tahun
    filtered_data = []
    for row in expenses_data:
        try:
            row_date = datetime.strptime(row[1], "%Y-%m-%d")
            if (str(row_date.month) == selected_month and str(row_date.year) == selected_year):
                filtered_data.append(row)
        except Exception:
            continue

    month_name = calendar.month_name[int(selected_month)]

    category_totals = defaultdict(float)
    for row in filtered_data:
        try:
            category = row[3]
            amount = float(row[4].replace(",", "").replace(".", ""))
            category_totals[category] += amount
        except:
            continue

    return render_template("form.html", tipe="expenses", today=date.today(),
                           categories = expenses_categories,
                           records = filtered_data,
                           selected_month=selected_month,
                           selected_year=selected_year,
                           month_name=month_name,
                           chart_labels=list(category_totals.keys()),
                           chart_data=list(category_totals.values()))


# Edit record
@app.route("/edit/<sheet>/<record_id>", methods=["POST"])
def edit_record(sheet, record_id):
    item = request.form.get("item")
    category = request.form.get("category")
    date_record = request.form.get("date")
    amount = request.form.get("amount")

    # Ambil semua data dulu
    data = sheets_service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{sheet.capitalize()}!A2:E"
    ).execute().get('values', [])

    # Cari baris berdasarkan ID
    for index, row in enumerate(data, start=2):  # mulai dari baris 2 (A2)
        if row[0] == record_id:
            values = [[record_id, date_record, item, category, amount]]
            sheets_service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{sheet.capitalize()}!A{index}:E{index}",
                valueInputOption="USER_ENTERED",
                body={"values": values}
            ).execute()
            return jsonify({"status": "success"})

    return jsonify({"status": "error", "message": "Record not found"})


def get_sheet_data_with_index(sheet_name):
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{sheet_name}!A2:E"  # Sesuaikan dengan kolom A-E (ID, Date, Item, Category, Amount)
    ).execute()

    values = result.get('values', [])
    data_with_index = []

    for i, row in enumerate(values, start=2):  # start=2 karena A1 adalah header
        data_with_index.append({
            "index": i,   # Baris aktual di Google Sheets
            "data": row   # Data pada baris tersebut
        })

    return data_with_index

def get_sheet_id_by_name(sheet_name):
    """
    Mengambil sheetId dari nama sheet/tab.
    """
    metadata = sheets_service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    for sheet in metadata["sheets"]:
        if sheet["properties"]["title"].lower() == sheet_name.lower():
            return sheet["properties"]["sheetId"]
    raise ValueError(f"Sheet '{sheet_name}' not found.")

# Delete record
@app.route("/delete/<sheet>/<record_id>", methods=["POST"])
def delete_record(sheet, record_id):
    try:
        # Ambil semua data beserta baris
        all_data = get_sheet_data_with_index(sheet.capitalize())

        # Cari baris yang memiliki ID tersebut
        for row in all_data:
            if row["data"][0] == record_id:
                row_index = row["index"] - 1  # Google Sheets 0-based index
                break
        else:
            return jsonify({"status": "error", "message": "Record ID not found."})

        sheet_id = get_sheet_id_by_name(sheet.capitalize())

        # Hapus baris tersebut secara penuh
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={
                "requests": [
                    {
                        "deleteDimension": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": row_index,
                                "endIndex": row_index + 1
                            }
                        }
                    }
                ]
            }
        ).execute()

        return jsonify({"status": "success", "message": "Record successfully deleted."})
    except Exception as e:
       return jsonify({"status": "error", "message": f"Failed to delete record: {e}"})

# Unduh annual report pdf
@app.route('/annual_report')
def annual_report():
    selected_year = request.args.get("year", datetime.now().year, type=int)
    # Ambil data dari Google Sheets
    income_data = get_data("Income")
    expenses_data = get_data("Expenses")

    # Buat struktur penampung total per bulan
    monthly_summary = defaultdict(lambda: {"income": 0, "expenses": 0})

    def process_data(data, tipe):
        for row in data:
            try:
                date_obj = datetime.strptime(row[1], "%Y-%m-%d")
                if date_obj.year == selected_year:
                    month_key = date_obj.strftime("%Y-%m")
                    amount = int(row[4].replace(".", "").replace(",", ""))
                    monthly_summary[month_key][tipe] += amount
            except (IndexError, ValueError):
                continue  # Lewati baris rusak

    process_data(income_data, "income")
    process_data(expenses_data, "expenses")

    # Tambahkan saldo
    for key in monthly_summary:
        summary = monthly_summary[key]
        summary["balance"] = summary["income"] - summary["expenses"]

    # Urutkan berdasarkan bulan
    sorted_months = sorted(monthly_summary.keys())
    summary_data = [(month, monthly_summary[month]) for month in sorted_months]

    chart_labels = [calendar.month_name[m] for m in range(1, 13)]
    chart_income = []
    chart_expenses = []
    chart_balance = []

    for m in range(1, 13):
        key = f"{selected_year}-{m:02d}"
        data = monthly_summary.get(key, {"income": 0, "expenses": 0, "balance": 0})
        chart_income.append(data["income"])
        chart_expenses.append(data["expenses"])
        chart_balance.append(data["balance"])
    
    total_income = sum(chart_income)
    total_expenses = sum(chart_expenses)
    total_balance = sum(chart_balance)

    # growth bulan ini
    net_balance = [i - e for i, e in zip(chart_income, chart_expenses)]
    income_growth = get_growth(chart_income)
    expenses_growth = get_growth(chart_expenses)
    net_growth = get_growth(net_balance)

    # growth series satu tahun
    income_growth_series = get_growth_series(chart_income)
    expenses_growth_series = get_growth_series(chart_expenses)
    net_growth_series = get_growth_series(net_balance)

    now = datetime.now()

    html = render_template("report.html",
                           now=now,
                           summary_data=summary_data,
                           selected_year=str(selected_year),
                           chart_labels=chart_labels,
                           chart_income=chart_income,
                           chart_expenses=chart_expenses,
                           chart_balance=chart_balance,
                           total_income=total_income,
                           total_expenses=total_expenses,
                           total_balance=total_balance,
                           income_growth=income_growth,
                           expenses_growth=expenses_growth,
                           net_growth=net_growth,
                           income_growth_series=income_growth_series,
                           expenses_growth_series=expenses_growth_series,
                           net_growth_series=net_growth_series)  # render HTML dengan Jinja
    
    response = requests.post(
        "https://api.pdfshift.io/v3/convert/pdf",
        headers={ "X-API-Key": PDFSHIFT_API_KEY },
        json={ "source": html }
    )

    if response.status_code == 200:
        return Response(
            response.content,
            mimetype='application/pdf',
            headers={
                "Content-Disposition": "inline; filename=report.pdf"
            }
        )
    else:
        return f"PDFShift Error: {response.text}", 500

# Unduh report pdf (testing)
@app.route('/annual-report-test')
def annual_report_test():
    selected_year = request.args.get("year", datetime.now().year, type=int)
    
    # Ambil data dari Google Sheets
    income_data = get_data("Income")
    expenses_data = get_data("Expenses")

    # Buat struktur penampung total per bulan
    monthly_summary = defaultdict(lambda: {"income": 0, "expenses": 0})

    def process_data(data, tipe):
        for row in data:
            try:
                date_obj = datetime.strptime(row[1], "%Y-%m-%d")
                if date_obj.year == selected_year:
                    month_key = date_obj.strftime("%Y-%m")
                    amount = int(row[4].replace(".", "").replace(",", ""))
                    monthly_summary[month_key][tipe] += amount
            except (IndexError, ValueError):
                continue  # Lewati baris rusak

    process_data(income_data, "income")
    process_data(expenses_data, "expenses")

    # Tambahkan saldo
    for key in monthly_summary:
        summary = monthly_summary[key]
        summary["balance"] = summary["income"] - summary["expenses"]

    # Urutkan berdasarkan bulan
    sorted_months = sorted(monthly_summary.keys())
    summary_data = [(month, monthly_summary[month]) for month in sorted_months]

    chart_labels = [calendar.month_name[m] for m in range(1, 13)]
    chart_income = []
    chart_expenses = []
    chart_balance = []

    for m in range(1, 13):
        key = f"{selected_year}-{m:02d}"
        data = monthly_summary.get(key, {"income": 0, "expenses": 0, "balance": 0})
        chart_income.append(data["income"])
        chart_expenses.append(data["expenses"])
        chart_balance.append(data["balance"])

    total_income = sum(chart_income)
    total_expenses = sum(chart_expenses)
    total_balance = sum(chart_balance)

    # growth bulan ini
    net_balance = [i - e for i, e in zip(chart_income, chart_expenses)]
    income_growth = get_growth(chart_income)
    expenses_growth = get_growth(chart_expenses)
    net_growth = get_growth(net_balance)

    # growth series satu tahun
    income_growth_series = get_growth_series(chart_income)
    expenses_growth_series = get_growth_series(chart_expenses)
    net_growth_series = get_growth_series(net_balance)

    now = datetime.now()

    return render_template("report.html", 
                           now = now,
                           summary_data=summary_data,
                           selected_year=str(selected_year),
                           chart_labels=chart_labels,
                           chart_income=chart_income,
                           chart_expenses=chart_expenses,
                           chart_balance=chart_balance,
                           total_income=total_income,
                           total_expenses=total_expenses,
                           total_balance=total_balance,
                           income_growth=income_growth,
                           expenses_growth=expenses_growth,
                           net_growth=net_growth,
                           income_growth_series=income_growth_series,
                           expenses_growth_series=expenses_growth_series,
                           net_growth_series=net_growth_series)

@app.route("/monthly_report/<month>")
def monthly_report(month):
    # Ambil data dari Google Sheets
    income_data = get_data("Income")
    expense_data = get_data("Expenses")

    try:
        year, mon = map(int, month.split('-'))
    except ValueError:
        return "Invalid month format. Use YYYY-MM.", 400

    def filter_by_month(data, y, m):
        filtered = []
        for row in data:
            try:
                row_date = datetime.strptime(row[1], "%Y-%m-%d")
                if row_date.month == m and row_date.year == y:
                    filtered.append(row)
            except:
                continue
        return filtered

    def get_total(data):
        total = 0
        for row in data:
            try:
                amount = float(row[4].replace(",", "").replace(".", ""))
                total += amount
            except:
                continue
        return total

    # Data bulan ini
    income_filtered = filter_by_month(income_data, year, mon)
    expense_filtered = filter_by_month(expense_data, year, mon)

    income_totals = defaultdict(float)
    for row in income_filtered:
        try:
            category = row[3]
            amount = float(row[4].replace(",", "").replace(".", ""))
            income_totals[category] += amount
        except:
            continue

    expense_totals = defaultdict(float)
    for row in expense_filtered:
        try:
            category = row[3]
            amount = float(row[4].replace(",", "").replace(".", ""))
            expense_totals[category] += amount
        except:
            continue

    total_income = sum(income_totals.values())
    total_expense = sum(expense_totals.values())
    balance = total_income - total_expense

    # Data bulan sebelumnya
    prev_year = year if mon > 1 else year - 1
    prev_month = mon - 1 if mon > 1 else 12

    prev_income_filtered = filter_by_month(income_data, prev_year, prev_month)
    prev_expense_filtered = filter_by_month(expense_data, prev_year, prev_month)

    prev_total_income = get_total(prev_income_filtered)
    prev_total_expense = get_total(prev_expense_filtered)
    prev_balance = prev_total_income - prev_total_expense

    # Growth perbandingan bulan ini vs sebelumnya
    income_growth = get_growth([prev_total_income, total_income])
    expenses_growth = get_growth([prev_total_expense, total_expense])
    net_growth = get_growth([prev_balance, balance])

    # Nama bulan
    month_name = calendar.month_name[mon]
    now = datetime.now()

    html = render_template("monthly-report.html",
                           now=now,
                           month=month,
                           selected_year=year,
                           month_name=month_name,
                           income_labels=list(income_totals.keys()),
                           income_data=list(income_totals.values()),
                           expense_labels=list(expense_totals.keys()),
                           expense_data=list(expense_totals.values()),
                           total_income=total_income,
                           total_expenses=total_expense,
                           balance=balance,
                           income_growth=income_growth,
                           expenses_growth=expenses_growth,
                           net_growth=net_growth,
                           summary_data_income=income_filtered,
                           summary_data_expenses=expense_filtered
    )

    response = requests.post(
        "https://api.pdfshift.io/v3/convert/pdf",
        headers={ "X-API-Key": PDFSHIFT_API_KEY },
        json={ "source": html }
    )

    if response.status_code == 200:
        return Response(
            response.content,
            mimetype='application/pdf',
            headers={
                "Content-Disposition": "inline; filename=report.pdf"
            }
        )
    else:
        return f"PDFShift Error: {response.text}", 500

# Unduh report perbulan pdf (testing)
@app.route("/monthly-report-tes/<month>")
def monthly_report_test(month):
    # Ambil data dari Google Sheets
    income_data = get_data("Income")
    expense_data = get_data("Expenses")

    try:
        year, mon = map(int, month.split('-'))
    except ValueError:
        return "Invalid month format. Use YYYY-MM.", 400

    def filter_by_month(data, y, m):
        filtered = []
        for row in data:
            try:
                row_date = datetime.strptime(row[1], "%Y-%m-%d")
                if row_date.month == m and row_date.year == y:
                    filtered.append(row)
            except:
                continue
        return filtered

    def get_total(data):
        total = 0
        for row in data:
            try:
                amount = float(row[4].replace(",", "").replace(".", ""))
                total += amount
            except:
                continue
        return total

    # Data bulan ini
    income_filtered = filter_by_month(income_data, year, mon)
    expense_filtered = filter_by_month(expense_data, year, mon)

    income_totals = defaultdict(float)
    for row in income_filtered:
        try:
            category = row[3]
            amount = float(row[4].replace(",", "").replace(".", ""))
            income_totals[category] += amount
        except:
            continue

    expense_totals = defaultdict(float)
    for row in expense_filtered:
        try:
            category = row[3]
            amount = float(row[4].replace(",", "").replace(".", ""))
            expense_totals[category] += amount
        except:
            continue

    total_income = sum(income_totals.values())
    total_expense = sum(expense_totals.values())
    balance = total_income - total_expense

    # Data bulan sebelumnya
    prev_year = year if mon > 1 else year - 1
    prev_month = mon - 1 if mon > 1 else 12

    prev_income_filtered = filter_by_month(income_data, prev_year, prev_month)
    prev_expense_filtered = filter_by_month(expense_data, prev_year, prev_month)

    prev_total_income = get_total(prev_income_filtered)
    prev_total_expense = get_total(prev_expense_filtered)
    prev_balance = prev_total_income - prev_total_expense

    # Growth perbandingan bulan ini vs sebelumnya
    income_growth = get_growth([prev_total_income, total_income])
    expenses_growth = get_growth([prev_total_expense, total_expense])
    net_growth = get_growth([prev_balance, balance])

    # Nama bulan
    month_name = calendar.month_name[mon]
    now = datetime.now()

    return render_template("monthly-report.html",
                           now=now,
                           month=month,
                           selected_year=year,
                           month_name=month_name,
                           income_labels=list(income_totals.keys()),
                           income_data=list(income_totals.values()),
                           expense_labels=list(expense_totals.keys()),
                           expense_data=list(expense_totals.values()),
                           total_income=total_income,
                           total_expenses=total_expense,
                           balance=balance,
                           income_growth=income_growth,
                           expenses_growth=expenses_growth,
                           net_growth=net_growth,
                           summary_data_income=income_filtered,
                           summary_data_expenses=expense_filtered
    )



if __name__ == '__main__':
    app.run(debug=True)
