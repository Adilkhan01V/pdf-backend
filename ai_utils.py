import os
import google.generativeai as genai
import fitz  # PyMuPDF
import pdf_utils

# Configure Gemini
def configure_genai():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("WARNING: GEMINI_API_KEY not set.")
        return False
    genai.configure(api_key=api_key)
    return True

def get_assistant_response(message: str) -> str:
    """
    Get a response from the AI Assistant for app guidance.
    """
    if not configure_genai():
        return "Error: AI service not configured (Missing API Key)."

    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        
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
    if not configure_genai():
        return "Error: AI service not configured (Missing API Key)."

    # 1. Extract text from PDF
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        
        # If native text is empty or too short, try OCR
        if not text.strip() or len(text.strip()) < 50:
            print("INFO: Native text extraction yielded little/no text. Attempting OCR...")
            try:
                # Use the existing extract_text utility with OCR mode
                ocr_text = pdf_utils.extract_text(pdf_path, mode='ocr')
                if ocr_text.strip():
                    text = ocr_text
            except Exception as ocr_error:
                print(f"WARNING: OCR failed: {ocr_error}")

        if not text.strip():
            return "Error: This PDF seems to be empty or contains only images (no selectable text), and OCR could not extract any text."
            
        # Limit text length for free tier (approx 30k chars is safe for simple context)
        # Gemini 1.5 Flash has a large context window, but let's be safe.
        if len(text) > 100000:
            text = text[:100000] + "...(truncated)"
            
    except Exception as e:
        return f"Error reading PDF: {str(e)}"

    # 2. Ask Gemini
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        
        prompt = f"""
        You are a helpful assistant. Answer the user's question based ONLY on the following Context extracted from a PDF.
        
        CONTEXT:
        {text}
        
        USER QUESTION:
        {user_question}
        
        If the answer is not in the context, say "I cannot find the answer in this PDF."
        Reply in the same language as the question.
        Use clean Markdown formatting (bold for key terms, bullet points for lists) to make the answer easy to read.
        """
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI Error: {str(e)}"
