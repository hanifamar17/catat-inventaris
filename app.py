from flask import Flask, render_template, request, redirect
from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
import json
from datetime import date

app = Flask(__name__)
secret_key = os.urandom(24)
app.secret_key = secret_key


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
        return f"IDR {amount:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
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


@app.route("/income", methods=["GET", "POST"])
def income():
    if request.method == "POST":
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

        return redirect("/income")
    
    income_categories = get_categories("income")
    income_data = get_data("Income")
    return render_template("form.html", tipe="income", today=date.today(),
                           categories=income_categories,
                           records = income_data)

@app.route("/expenses", methods=["GET", "POST"])
def expenses():
    if request.method == "POST":
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

        return redirect("/expenses")

    expenses_categories = get_categories("expenses")
    expenses_data = get_data("Expenses")
    return render_template("form.html", tipe="expenses", today=date.today(),
                           categories = expenses_categories,
                           records = expenses_data)


if __name__ == '__main__':
    app.run(debug=True)
