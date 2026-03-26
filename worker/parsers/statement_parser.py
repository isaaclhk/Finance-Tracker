import io
import logging

import pdfplumber

logger = logging.getLogger(__name__)


def extract_transactions_from_pdf(pdf_bytes: bytes) -> list[str]:
    chunks: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    chunks.append(text)
    except Exception:
        logger.exception("Failed to extract text from PDF")
    return chunks
