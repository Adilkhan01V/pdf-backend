import os
import hashlib
from collections import OrderedDict
from typing import Optional

import google.generativeai as genai
import fitz  # PyMuPDF
import pdf_utils

_genai_configured = False
_gemini_model: Optional[genai.GenerativeModel] = None
_pdf_text_cache: "OrderedDict[str, str]" = OrderedDict()
_pdf_text_cache_max_entries = 8


def configure_genai() -> bool:
    global _genai_configured
    if _genai_configured:
        return True
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("WARNING: GEMINI_API_KEY not set.")
        return False
    genai.configure(api_key=api_key)
    _genai_configured = True
    return True


def _get_gemini_model() -> Optional[genai.GenerativeModel]:
    global _gemini_model
    if _gemini_model is not None:
        return _gemini_model
    if not configure_genai():
        return None
    _gemini_model = genai.GenerativeModel("gemini-flash-latest")
    return _gemini_model


def _hash_file(path: str) -> Optional[str]:
    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return None


def _get_cached_pdf_text(path: str) -> Optional[str]:
    key = _hash_file(path)
    if key is None:
        return None
    if key in _pdf_text_cache:
        text = _pdf_text_cache.pop(key)
        _pdf_text_cache[key] = text
        return text
    return None


def _set_cached_pdf_text(path: str, text: str) -> None:
    key = _hash_file(path)
    if key is None:
        return
    if key in _pdf_text_cache:
        _pdf_text_cache.pop(key)
    elif len(_pdf_text_cache) >= _pdf_text_cache_max_entries:
        _pdf_text_cache.popitem(last=False)
    _pdf_text_cache[key] = text


def get_assistant_response(message: str) -> str:
    """
    Get a response from the AI Assistant for app guidance.
    """
    model = _get_gemini_model()
    if model is None:
        return "Error: AI service not configured (Missing API Key)."

    try:
        system_prompt = """
    You are a helpful AI assistant for the 'GearPDF' application. 
    Your ONLY goal is to help users understand how to use the PDF tools in this app.
    
    The tools available are:
    1. Merge PDF: Combine multiple PDFs into one.
    2. Split PDF: Extract pages or split into individual files.
    3. Compress PDF: Reduce file size.
    4. Image to PDF: Convert images (JPG/PNG) to PDF.
    5. Extract Text: Get text from PDF (supports OCR).
    6. Organize PDF: Reorder, rotate, or delete pages.
    7. Security: Add password protection.
    8. Watermark: Add text watermarks.
    9. Chat with PDF: Upload a PDF and ask questions about it.

    If the user greets you (Hello, Hi, Namaste), greet them back politely in the same language.
    If the user asks how to use a tool, explain it simply.
    If the user asks about anything unrelated to PDF tools (e.g., "Who is the president?", "Write code"), 
    politely refuse and say you can only help with the PDF app.
    
    IMPORTANT: Reply in the SAME language as the user (English, Hindi, or Hinglish).
    """

        chat = model.start_chat(history=[
            {"role": "user", "parts": [system_prompt]},
            {"role": "model", "parts": ["Understood. I will guide users on using GearPDF tools in their preferred language."]}
        ])
        response = chat.send_message(message)
        return response.text
    except Exception as e:
        return f"AI Error: {str(e)}"


def chat_with_pdf(pdf_path: str, user_question: str) -> str:
    """
    Extract text from PDF and ask Gemini a question based on it.
    """
    model = _get_gemini_model()
    if model is None:
        return "Error: AI service not configured (Missing API Key)."

    try:
        cached_text = _get_cached_pdf_text(pdf_path)
        if cached_text is not None:
            text = cached_text
        else:
            doc = fitz.open(pdf_path)
            parts = []
            for page in doc:
                parts.append(page.get_text())
            text = "".join(parts)

            if not text.strip() or len(text.strip()) < 50:
                try:
                    ocr_text = pdf_utils.extract_text(pdf_path, mode="ocr")
                    if ocr_text.strip():
                        text = ocr_text
                except Exception as ocr_error:
                    print(f"WARNING: OCR failed: {ocr_error}")

            if not text.strip():
                return "Error: This PDF seems to be empty or contains only images (no selectable text), and OCR could not extract any text."

            if len(text) > 100000:
                text = text[:100000] + "...(truncated)"

            _set_cached_pdf_text(pdf_path, text)
    except Exception as e:
        return f"Error reading PDF: {str(e)}"

    try:
        prompt = f"""
        You are a helpful assistant for a PDF document.
        
        You are given CONTEXT text that was extracted from a PDF. Use it as your primary reference, but you may also use your own general knowledge to:
        - provide deeper explanations or background information
        - give brief or detailed summaries
        - suggest useful external links (official docs, websites, etc.) related to concepts in the PDF
        
        When the user asks for a link, answer with a direct https URL that best matches the topic, even if the exact URL is not written in the PDF, as long as it is relevant to the CONTEXT and question.
        
        When you add information that is not explicitly in the CONTEXT, present it clearly as explanation, background, or additional details, not as a quote from the PDF.
        
        CONTEXT:
        {text}
        
        USER QUESTION:
        {user_question}
        
        Reply in the same language as the question.
        Use clean Markdown formatting (bold for key terms, bullet points for lists) to make the answer easy to read.
        """

        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI Error: {str(e)}"
