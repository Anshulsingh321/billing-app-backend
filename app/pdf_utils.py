import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from datetime import datetime


def generate_bill_pdf(bill, customer, items, subtotal, gst_amount, grand_total):
    # Ensure directory exists
    os.makedirs("generated", exist_ok=True)

    file_path = f"generated/bill_{bill.id}.pdf"

    c = canvas.Canvas(file_path, pagesize=A4)
    width, height = A4

    y = height - 60

    # -------------------------
    # HEADER
    # -------------------------
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "TAX INVOICE")
    y -= 30

    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Bill ID: {bill.id}")
    y -= 15
    c.drawString(50, y, f"Invoice Date: {datetime.now().strftime('%d-%m-%Y')}")
    y -= 20
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Seller:")
    y -= 15
    c.setFont("Helvetica", 10)
    c.drawString(50, y, "ABC Hardware Store")
    y -= 15
    c.drawString(50, y, "Main Market, Sector 12")
    y -= 15
    c.drawString(50, y, "GSTIN: 07ABCDE1234F1Z5")
    y -= 25

    if customer:
        c.drawString(50, y, f"Customer: {customer.name}")
        y -= 15
        if customer.phone:
            c.drawString(50, y, f"Phone: {customer.phone}")
            y -= 15

    c.drawString(50, y, f"Bill Type: {bill.bill_type}")
    y -= 25

    # -------------------------
    # TABLE HEADER
    # -------------------------
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Item")
    c.drawString(250, y, "Qty")
    c.drawString(300, y, "Rate")
    c.drawString(380, y, "Total")
    y -= 10

    c.line(50, y, 500, y)
    y -= 15

    # -------------------------
    # ITEMS
    # -------------------------
    c.setFont("Helvetica", 10)

    for item in items:
        c.drawString(50, y, item.item_name)
        c.drawRightString(280, y, str(item.quantity))
        c.drawRightString(350, y, f"{item.rate:.2f}")
        c.drawRightString(450, y, f"{item.subtotal:.2f}")

        y -= 15

        if y < 100:
            c.showPage()
            y = height - 60
            c.setFont("Helvetica", 10)

    # -------------------------
    # TOTALS
    # -------------------------
    y -= 10
    c.setFont("Helvetica", 10)

    c.drawRightString(380, y, "Subtotal:")
    c.drawRightString(450, y, f"{subtotal:.2f}")
    y -= 15

    if bill.bill_type == "GST":
        c.drawRightString(380, y, "GST @ 18%:")
        c.drawRightString(450, y, f"{gst_amount:.2f}")
        y -= 15

    c.setFont("Helvetica-Bold", 11)
    c.line(300, y, 500, y)
    y -= 15
    c.drawRightString(380, y, "Grand Total:")
    c.drawRightString(450, y, f"{grand_total:.2f}")

    c.save()
    return file_path


def generate_customer_ledger_pdf(customer, ledger):
    os.makedirs("generated", exist_ok=True)

    file_path = f"generated/ledger_customer_{customer.id}.pdf"
    c = canvas.Canvas(file_path, pagesize=A4)
    width, height = A4

    y = height - 60

    # -------------------------
    # HEADER
    # -------------------------
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "Customer Ledger Statement")
    y -= 30

    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Customer: {customer.name}")
    y -= 15
    c.drawString(50, y, f"Phone: {customer.phone or '-'}")
    y -= 15
    c.drawString(
        50,
        y,
        f"Generated on: {datetime.now().strftime('%d-%m-%Y')}"
    )
    y -= 25

    # -------------------------
    # TABLE HEADER
    # -------------------------
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Date")
    c.drawString(140, y, "Type")
    c.drawString(230, y, "Debit")
    c.drawString(310, y, "Credit")
    c.drawString(400, y, "Balance")
    y -= 10

    c.line(50, y, 520, y)
    y -= 15

    # -------------------------
    # LEDGER ROWS
    # -------------------------
    c.setFont("Helvetica", 10)

    for row in ledger:
        c.drawString(
            50,
            y,
            row["date"].strftime("%d-%m-%Y")
        )
        c.drawString(140, y, row["type"])
        c.drawRightString(270, y, f'{row["debit"]:.2f}')
        c.drawRightString(350, y, f'{row["credit"]:.2f}')
        c.drawRightString(450, y, f'{row["balance"]:.2f}')

        y -= 15

        if y < 80:
            c.showPage()
            y = height - 60
            c.setFont("Helvetica", 10)

    c.save()
    return file_path