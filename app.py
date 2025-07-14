from flask import Flask, jsonify, render_template, request, redirect
from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
import json
from datetime import datetime, date
import calendar
from collections import defaultdict
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
secret_key = os.urandom(24)
app.secret_key = secret_key
csrf = CSRFProtect(app)


if os.getenv("VERCEL") is None:
    from dotenv import load_dotenv
    load_dotenv()  # Load environment variables from .env file

# Spreadsheet ID dan range untuk menyimpan data
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
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
        range=f"{sheet_name}!A2:D"
    ).execute()

    values = result.get('values', [])
    return values


@app.route("/")
def index():
    return redirect('dashboard')
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
                date_obj = datetime.strptime(row[0], "%Y-%m-%d")
                if date_obj.year == selected_year:
                    month_key = date_obj.strftime("%Y-%m")
                    amount = int(row[3].replace(".", "").replace(",", ""))
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

    return render_template("dashboard.html", summary_data=summary_data, selected_year=str(selected_year),
                           chart_labels=chart_labels,
                           chart_income=chart_income,
                           chart_expenses=chart_expenses,
                           chart_balance=chart_balance)

# Income page
@app.route("/income", methods=["GET", "POST"])
def income():
    if request.method == "POST":
        try:
            date_income = request.form["date"]
            item = request.form["item"]
            category = request.form["category"]
            amount = request.form["amount"]

            values = [[date_income, item, category, amount]]

            sheets_service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range="Income!A2:D",
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
            row_date = datetime.strptime(row[0], "%Y-%m-%d")
            if (str(row_date.month) == selected_month and str(row_date.year) == selected_year):
                filtered_data.append(row)
        except Exception:
            continue

    month_name = calendar.month_name[int(selected_month)]

    # hitung total per kategoru
    category_totals = defaultdict(float)
    for row in filtered_data:
        try:
            category = row[2]
            amount = float(row[3].replace(",", "").replace(".", ""))
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
            date_expenses = request.form["date"]
            item = request.form["item"]
            category = request.form["category"]
            amount = request.form["amount"]

            values = [[date_expenses, item, category, amount]]

            sheets_service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range="Expenses!A2:D",
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
            row_date = datetime.strptime(row[0], "%Y-%m-%d")
            if (str(row_date.month) == selected_month and str(row_date.year) == selected_year):
                filtered_data.append(row)
        except Exception:
            continue

    month_name = calendar.month_name[int(selected_month)]

    category_totals = defaultdict(float)
    for row in filtered_data:
        try:
            category = row[2]
            amount = float(row[3].replace(",", "").replace(".", ""))
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


def get_sheet_data_with_index(sheet_name):
    """
    Mengembalikan list data beserta index baris aslinya di Google Sheets.
    Misalnya row 2 berarti index=2 (karena header di A1).
    """
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{sheet_name}!A2:D"
    ).execute()

    values = result.get('values', [])
    data_with_index = []

    for i, row in enumerate(values, start=2):  # mulai dari baris 2 karena A1 header
        data_with_index.append({
            "index": i,
            "data": row
        })

    return data_with_index

# Edit record
@app.route("/edit/<sheet>/<int:row_index>", methods=["POST"])
def edit_record(sheet, row_index):
    item = request.form.get("item")
    category = request.form.get("category")
    date_val = request.form.get("date")
    amount = request.form.get("amount")

    sheet_row = row_index + 2
    values = [[date_val, item, category, amount]]

    try:
        sheets_service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{sheet.capitalize()}!A{sheet_row}:D{sheet_row}",
            valueInputOption="USER_ENTERED",
            body={"values": values}
        ).execute()

        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# Delete record
@app.route("/delete/<sheet>/<int:row_index>", methods=["POST"])
def delete_record(sheet, row_index):
    try:
        # Google Sheets baris data dimulai dari baris ke-2 (karena baris ke-1 adalah header)
        sheet_row = row_index + 2

        # Hapus data dari kolom A sampai D pada baris tersebut
        sheets_service.spreadsheets().values().clear(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{sheet.capitalize()}!A{sheet_row}:D{sheet_row}",
            body={}
        ).execute()

        return jsonify({"status": "success", "message": "Record successfully deleted."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to delete record: {e}"})



if __name__ == '__main__':
    app.run(debug=True)
