import json
from fastapi import FastAPI, UploadFile, File, HTTPException, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import shutil
import os
import tempfile
import pdf_utils
import watermark_utils
import ai_utils

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def cleanup_file(path: str):
    """Function to remove temporary file."""
    try:
        if os.path.exists(path):
            os.unlink(path)
    except Exception as e:
        print(f"Error cleaning up file {path}: {e}")

def cleanup_files(paths: List[str]):
    """Function to remove multiple temporary files."""
    for path in paths:
        cleanup_file(path)

@app.get("/")
async def root():
    return {"message": "PDF Utility API is running"}

@app.post("/merge")
async def merge_pdfs_endpoint(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    passwords: Optional[str] = Form(None)
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    temp_files = []
    output_path = None
    
    try:
        # Parse passwords if provided
        password_list: Optional[List[Optional[str]]] = None
        if passwords:
            password_list = json.loads(passwords)
        
        # Save uploads to temp files
        for file in files:
            fd, path = tempfile.mkstemp(suffix=".pdf")
            os.close(fd)
            temp_files.append(path)
            
            with open(path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        
        # Prepare output file
        fd, output_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        
        # Process
        pdf_utils.merge_pdfs(temp_files, output_path, password_list)
        
        # Add cleanup tasks
        background_tasks.add_task(cleanup_files, temp_files + [output_path])
        
        return FileResponse(
            output_path,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=merged.pdf"}
        )
        
    except Exception as e:
        # Clean up immediately on error
        cleanup_files(temp_files)
        if output_path:
            cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/split")
async def split_pdf_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    mode: str = Form("all"),
    pages: str = Form(None),
    password: Optional[str] = Form(None)
):
    input_path = None
    output_path = None

    try:
        fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        suffix = ".zip" if mode == 'all' else ".pdf"
        fd, output_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)

        try:
            mime_type = pdf_utils.split_pdf(input_path, output_path, mode, pages, password)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        background_tasks.add_task(cleanup_files, [input_path, output_path])
        filename = "split_files.zip" if mime_type == "application/zip" else "split.pdf"

        return FileResponse(
            output_path,
            media_type=mime_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except HTTPException:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise
    except Exception as e:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/compress")
async def compress_pdf_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    target_size_mb: Optional[float] = Form(None),
    file_type: str = Form("pdf"),
    password: Optional[str] = Form(None)
):
    input_path = None
    output_path = None

    try:
        ext = os.path.splitext(file.filename)[1]
        if not ext:
            ext = ".pdf" if file_type == "pdf" else ".jpg"

        fd, input_path = tempfile.mkstemp(suffix=ext)
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        suffix = ".pdf" if file_type == "pdf" else ".jpg"
        fd, output_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)

        try:
            if file_type == "pdf":
                pdf_utils.compress_pdf(input_path, output_path, target_size_mb, password)
                media_type = "application/pdf"
                filename = "compressed.pdf"
            else:
                pdf_utils.compress_image(input_path, output_path, target_size_mb)
                media_type = "image/jpeg"
                filename = "compressed.jpg"
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        background_tasks.add_task(cleanup_files, [input_path, output_path])

        return FileResponse(
            output_path,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except HTTPException:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise
    except Exception as e:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/img2pdf")
async def img_to_pdf_endpoint(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...)
):
    temp_files = []
    output_path = None
    
    try:
        # Save inputs
        for file in files:
            # We need to preserve extensions for Pillow to detect format? 
            # Pillow can usually detect from bytes, but file extension helps.
            ext = os.path.splitext(file.filename)[1]
            if not ext: ext = ".jpg"
            
            fd, path = tempfile.mkstemp(suffix=ext)
            os.close(fd)
            temp_files.append(path)
            
            with open(path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
                
        # Prepare output
        fd, output_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        
        # Process
        pdf_utils.images_to_pdf(temp_files, output_path)
        
        # Add cleanup tasks
        background_tasks.add_task(cleanup_files, temp_files + [output_path])
        
        return FileResponse(
            output_path,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=images.pdf"}
        )
        
    except Exception as e:
        cleanup_files(temp_files)
        if output_path:
            cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/extract-text")
async def extract_text_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    mode: str = Form("ocr"),
    password: Optional[str] = Form(None)
):
    input_path = None
    output_path = None

    try:
        fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        try:
            text = pdf_utils.extract_text(input_path, mode, password)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        fd, output_path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)

        background_tasks.add_task(cleanup_files, [input_path, output_path])

        return FileResponse(
            output_path,
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=extracted.txt"}
        )

    except HTTPException:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise
    except Exception as e:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/organize")
async def organize_pdf_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    pages_config: str = Form(...),
    password: Optional[str] = Form(None)
):
    input_path = None
    output_path = None

    try:
        config = json.loads(pages_config)

        fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        fd, output_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)

        try:
            pdf_utils.organize_pdf(input_path, output_path, config, password)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        background_tasks.add_task(cleanup_files, [input_path, output_path])

        return FileResponse(
            output_path,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=organized.pdf"}
        )

    except HTTPException:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise
    except Exception as e:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/protect")
async def protect_pdf_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    password: str = Form(...)
):
    input_path = None
    output_path = None
    
    try:
        # Save input
        fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Prepare output
        fd, output_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        
        # Process
        pdf_utils.lock_pdf(input_path, output_path, password)
        
        # Add cleanup tasks
        background_tasks.add_task(cleanup_files, [input_path, output_path])
        
        return FileResponse(
            output_path,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=protected.pdf"}
        )
        
    except Exception as e:
        cleanup_file(input_path)
        if output_path:
            cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pdf/watermark/text")
async def add_watermark_text_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    text: str = Form(...),
    fontSize: int = Form(40),
    opacity: float = Form(0.5),
    rotation: int = Form(45),
    isBold: bool = Form(False),
    isItalic: bool = Form(False),
    isUnderline: bool = Form(False)
):
    input_path = None
    output_path = None
    
    try:
        # Save input
        fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Prepare output
        fd, output_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        
        # Process
        try:
            watermark_utils.apply_watermark(
                input_path, output_path,
                text, fontSize, opacity, rotation, isBold, isItalic, isUnderline
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        # Add cleanup tasks
        background_tasks.add_task(cleanup_files, [input_path, output_path])
        
        return FileResponse(
            output_path,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=watermarked.pdf"}
        )
        
    except HTTPException:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise
    except Exception as e:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/unlock")
async def unlock_pdf_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    password: str = Form(...)
):
    input_path = None
    output_path = None
    
    try:
        # Save input
        fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Prepare output
        fd, output_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        
        # Process
        try:
            pdf_utils.unlock_pdf(input_path, output_path, password)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        # Add cleanup tasks
        background_tasks.add_task(cleanup_files, [input_path, output_path])
        
        return FileResponse(
            output_path,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=unlocked.pdf"}
        )
        
    except HTTPException:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise
    except Exception as e:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/crop")
async def crop_pdf_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    pages: str = Form("[]"),
    crop_box: str = Form("{}"),
    password: Optional[str] = Form(None)
):
    input_path = None
    output_path = None

    try:
        pages_list: List[int] = json.loads(pages)
        crop_box_dict: dict = json.loads(crop_box)

        fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        fd, output_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)

        try:
            pdf_utils.crop_pdf(input_path, output_path, pages_list, crop_box_dict, password)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        background_tasks.add_task(cleanup_files, [input_path, output_path])

        return FileResponse(
            output_path,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=cropped.pdf"},
        )

    except HTTPException:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise
    except Exception as e:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/page-numbers")
async def add_page_numbers_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    position: str = Form("bottom-center"),
    font_size: int = Form(12),
    start_number: int = Form(1),
    prefix: str = Form(""),
    suffix: str = Form(""),
    password: Optional[str] = Form(None)
):
    input_path = None
    output_path = None

    try:
        fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        fd, output_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)

        try:
            pdf_utils.add_page_numbers(
                input_path, output_path,
                position, font_size, start_number, prefix, suffix, password
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        background_tasks.add_task(cleanup_files, [input_path, output_path])

        return FileResponse(
            output_path,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=numbered.pdf"}
        )

    except HTTPException:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise
    except Exception as e:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/repair")
async def repair_pdf_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    password: Optional[str] = Form(None)
):
    input_path = None
    output_path = None

    try:
        fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        fd, output_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)

        try:
            result = pdf_utils.repair_pdf(input_path, output_path, password)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        background_tasks.add_task(cleanup_files, [input_path, output_path])

        return FileResponse(
            output_path,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=repaired.pdf",
                "X-Repair-Method": result.get("method", "unknown"),
                "X-Repair-Issues": "; ".join(result.get("issues_found", []))
            }
        )

    except HTTPException:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise
    except Exception as e:
        cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))


# --- AI Features ---

class AssistantRequest(BaseModel):
    message: str

@app.post("/ai/assistant")
async def ai_assistant_endpoint(request: AssistantRequest):
    """
    AI Assistant for app guidance.
    """
    response = ai_utils.get_assistant_response(request.message)
    return {"reply": response}

@app.post("/ai/chat-pdf")
async def chat_with_pdf_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    question: str = Form(...)
):
    """
    Chat with an uploaded PDF.
    """
    input_path = None
    
    try:
        # Save input
        fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Process
        answer = ai_utils.chat_with_pdf(input_path, question)
        
        # Add cleanup tasks
        background_tasks.add_task(cleanup_file, input_path)
        
        return {"reply": answer}
        
    except Exception as e:
        cleanup_file(input_path)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ai/summarize")
async def summarize_pdf_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    """
    Summarize an uploaded PDF.
    """
    input_path = None
    
    try:
        # Save input
        fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Process
        summary = ai_utils.summarize_pdf(input_path)
        
        # Add cleanup tasks
        background_tasks.add_task(cleanup_file, input_path)
        
        return {"reply": summary}
        
    except Exception as e:
        cleanup_file(input_path)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/resize-image")
async def resize_image_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    width: Optional[int] = Form(None),
    height: Optional[int] = Form(None),
    scale_factor: Optional[float] = Form(None)
):
    input_path = None
    output_path = None
    
    try:
        # Save input
        ext = os.path.splitext(file.filename)[1]
        if not ext: ext = ".jpg"
        fd, input_path = tempfile.mkstemp(suffix=ext)
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Prepare output
        fd, output_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        
        # Process
        pdf_utils.resize_image(input_path, output_path, width, height, scale_factor)
        
        # Add cleanup tasks
        background_tasks.add_task(cleanup_files, [input_path, output_path])
        
        return FileResponse(
            output_path,
            media_type="image/jpeg",
            headers={"Content-Disposition": "attachment; filename=resized.jpg"}
        )
        
    except Exception as e:
        cleanup_file(input_path)
        if output_path:
            cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))
