import json
from fastapi import FastAPI, UploadFile, File, HTTPException, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from typing import List, Optional
import shutil
import os
import tempfile
import pdf_utils

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
async def merge_pdfs_endpoint(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    temp_files = []
    output_path = None
    
    try:
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
        pdf_utils.merge_pdfs(temp_files, output_path)
        
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
    mode: str = Form("all"), # all, range, selected
    pages: str = Form(None)  # "2-5" or "1,3,5"
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
        suffix = ".zip" if mode == 'all' else ".pdf"
        fd, output_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        
        # Process
        mime_type = pdf_utils.split_pdf(input_path, output_path, mode, pages)
        
        # Add cleanup tasks
        background_tasks.add_task(cleanup_files, [input_path, output_path])
        
        filename = "split_files.zip" if mime_type == "application/zip" else "split.pdf"
        
        return FileResponse(
            output_path,
            media_type=mime_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        cleanup_file(input_path)
        if output_path:
            cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/compress")
async def compress_pdf_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    target_size_mb: Optional[float] = Form(None),
    file_type: str = Form("pdf")
):
    input_path = None
    output_path = None
    
    try:
        # Save input
        ext = os.path.splitext(file.filename)[1]
        if not ext:
             ext = ".pdf" if file_type == "pdf" else ".jpg"
        
        fd, input_path = tempfile.mkstemp(suffix=ext)
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Prepare output
        fd, output_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        
        # Process
        if file_type == "pdf":
            pdf_utils.compress_pdf(input_path, output_path, target_size_mb)
            media_type = "application/pdf"
            filename = "compressed.pdf"
        else:
            pdf_utils.compress_image(input_path, output_path, target_size_mb)
            media_type = "image/jpeg"
            filename = "compressed.jpg"
        
        # Add cleanup tasks
        background_tasks.add_task(cleanup_files, [input_path, output_path])
        
        return FileResponse(
            output_path,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        cleanup_file(input_path)
        if output_path:
            cleanup_file(output_path)
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
    mode: str = Form("ocr")
):
    input_path = None
    output_path = None
    
    try:
        # Save input
        fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Process (returns text, not file path, but we want to return a file/blob)
        text = pdf_utils.extract_text(input_path, mode)
        
        # Write text to temp file
        fd, output_path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
            
        # Add cleanup tasks
        background_tasks.add_task(cleanup_files, [input_path, output_path])
        
        return FileResponse(
            output_path,
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=extracted.txt"}
        )
        
    except Exception as e:
        cleanup_file(input_path)
        if output_path:
            cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/organize")
async def organize_pdf_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    pages_config: str = Form(...) # JSON string
):
    input_path = None
    output_path = None
    
    try:
        # Parse config
        config = json.loads(pages_config)
        
        # Save input
        fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Prepare output
        fd, output_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        
        # Process
        pdf_utils.organize_pdf(input_path, output_path, config)
        
        # Add cleanup tasks
        background_tasks.add_task(cleanup_files, [input_path, output_path])
        
        return FileResponse(
            output_path,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=organized.pdf"}
        )
        
    except Exception as e:
        cleanup_file(input_path)
        if output_path:
            cleanup_file(output_path)
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
