import io
import unittest
from unittest.mock import MagicMock, patch

import pdf_parser


class OcrPrivacyTests(unittest.TestCase):
    def test_pdf_is_opened_in_memory_and_closed(self):
        source = io.BytesIO(b"synthetic pdf bytes")
        document = MagicMock()
        document.__len__.return_value = 0
        diagnostics = {}

        with patch.object(pdf_parser, "pdfium") as pdfium, \
             patch.object(pdf_parser, "RapidOCR"), \
             patch.object(pdf_parser, "np"):
            pdfium.PdfDocument.return_value = document
            self.assertEqual(pdf_parser._extract_ocr_lines(source, diagnostics), [])
            pdfium.PdfDocument.assert_called_once_with(b"synthetic pdf bytes")

        document.close.assert_called_once_with()
        self.assertEqual(source.tell(), 0)
        self.assertIsNone(diagnostics["error"])

    def test_pdf_is_closed_when_ocr_initialization_fails(self):
        source = io.BytesIO(b"synthetic pdf bytes")
        document = MagicMock()
        document.__len__.return_value = 0
        diagnostics = {}

        with patch.object(pdf_parser, "pdfium") as pdfium, \
             patch.object(pdf_parser, "RapidOCR", side_effect=RuntimeError("test")), \
             patch.object(pdf_parser, "np"):
            pdfium.PdfDocument.return_value = document
            self.assertEqual(pdf_parser._extract_ocr_lines(source, diagnostics), [])

        document.close.assert_called_once_with()
        self.assertEqual(source.tell(), 0)
        self.assertEqual(diagnostics["error"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()