"""Tests for the filter module."""

from pathlib import Path
from unittest.mock import patch, MagicMock

from bookstuff.filter import FilterResult, filter_file, filter_files


class TestFilterResult:
    def test_attributes(self):
        r = FilterResult(path=Path("/tmp/book.pdf"), is_book=True, reason="looks like a book")
        assert r.path == Path("/tmp/book.pdf")
        assert r.is_book is True
        assert r.reason == "looks like a book"


class TestFilterFile:
    def test_accepts_normal_book_filename(self):
        result = filter_file(Path("/books/Python Programming.pdf"))
        assert result.is_book is True

    def test_rejects_invoice(self):
        result = filter_file(Path("/docs/invoice_2024.pdf"))
        assert result.is_book is False
        assert "invoice" in result.reason.lower()

    def test_rejects_receipt(self):
        result = filter_file(Path("/docs/receipt-amazon.pdf"))
        assert result.is_book is False

    def test_rejects_cv(self):
        result = filter_file(Path("/docs/my_cv.pdf"))
        assert result.is_book is False

    def test_rejects_personal_resume(self):
        result = filter_file(Path("/docs/John_Resume_2024.pdf"))
        assert result.is_book is False

    def test_rejects_my_resume(self):
        result = filter_file(Path("/docs/my_resume.pdf"))
        assert result.is_book is False

    def test_accepts_book_about_resumes(self):
        result = filter_file(Path("/books/The Tech Resume Inside Out v1.0.pdf"))
        assert result.is_book is True

    def test_rejects_tax_document(self):
        result = filter_file(Path("/docs/tax_return_2023.pdf"))
        assert result.is_book is False

    def test_rejects_bank_statement(self):
        result = filter_file(Path("/docs/bank_statement_jan.pdf"))
        assert result.is_book is False

    def test_rejects_cover_letter(self):
        result = filter_file(Path("/docs/cover_letter_google.pdf"))
        assert result.is_book is False

    def test_rejects_electricity_bill(self):
        result = filter_file(Path("/docs/electricity_bill_feb.pdf"))
        assert result.is_book is False

    def test_accepts_author_named_bill(self):
        result = filter_file(Path("/books/Disciplined Entrepreneurship (Bill Aulet).epub"))
        assert result.is_book is True

    def test_accepts_financial_statements_book(self):
        result = filter_file(Path("/books/The Interpretation of Financial Statements.pdf"))
        assert result.is_book is True

    def test_rejects_ticket(self):
        result = filter_file(Path("/docs/BIG TASTY Event Ticket.pdf"))
        assert result.is_book is False

    def test_rejects_booking_confirmation(self):
        result = filter_file(Path("/docs/Booking Confirmation - Gelmerbahn.pdf"))
        assert result.is_book is False

    def test_rejects_coupon(self):
        result = filter_file(Path("/docs/Coupon-xch4j.pdf"))
        assert result.is_book is False

    def test_rejects_camscanner(self):
        result = filter_file(Path("/docs/CamScanner 2024-09-18 23.55.pdf"))
        assert result.is_book is False

    def test_rejects_voucher(self):
        result = filter_file(Path("/docs/Gift Voucher.pdf"))
        assert result.is_book is False

    def test_rejects_user_manual(self):
        result = filter_file(Path("/docs/Gaming Monitor User Manual C49RG9.pdf"))
        assert result.is_book is False

    def test_accepts_epub(self):
        result = filter_file(Path("/books/Great Expectations.epub"))
        assert result.is_book is True

    def test_accepts_mobi(self):
        result = filter_file(Path("/books/Dune.mobi"))
        assert result.is_book is True

    def test_case_insensitive_rejection(self):
        result = filter_file(Path("/docs/INVOICE_123.pdf"))
        assert result.is_book is False

    def test_accepts_book_with_numbers(self):
        result = filter_file(Path("/books/1984.pdf"))
        assert result.is_book is True

    def test_rejects_payslip(self):
        result = filter_file(Path("/docs/payslip_march.pdf"))
        assert result.is_book is False


class TestFilterFiles:
    def test_filters_multiple_files(self):
        files = [
            Path("/books/Python.pdf"),
            Path("/docs/invoice.pdf"),
            Path("/books/Dune.epub"),
            Path("/docs/my_resume.pdf"),
        ]
        results = filter_files(files)
        books = [r for r in results if r.is_book]
        non_books = [r for r in results if not r.is_book]
        assert len(books) == 2
        assert len(non_books) == 2

    def test_empty_list(self):
        results = filter_files([])
        assert results == []
