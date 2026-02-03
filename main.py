from fastapi import FastAPI, UploadFile, File, HTTPException, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
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
        
        # Cleanup
        background_tasks.add_task(cleanup_files, [input_path, output_path])
        
        filename = "split_pages.zip" if mode == 'all' else "extracted_pages.pdf"
        
        return FileResponse(
            output_path,
            media_type=mime_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception as e:
        if input_path: cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/compress")
async def compress_pdf_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    target_size_mb: Optional[float] = Form(None)
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
        pdf_utils.compress_pdf(input_path, output_path, target_size_mb)
        
        # Cleanup
        background_tasks.add_task(cleanup_files, [input_path, output_path])
        
        return FileResponse(
            output_path,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=compressed.pdf"}
        )
    except Exception as e:
        if input_path: cleanup_file(input_path)
        if output_path: cleanup_file(output_path)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/img2pdf")
async def img2pdf_endpoint(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    temp_files = []
    output_path = None
    
    try:
        # Save uploads
        for file in files:
            # Determine extension
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
        
        # Cleanup
        background_tasks.add_task(cleanup_files, temp_files + [output_path])
        
        return FileResponse(
            output_path,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=converted_images.pdf"}
        )
    except Exception as e:
        cleanup_files(temp_files)
        if output_path: cleanup_file(output_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/extract-text")
async def extract_text_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    mode: str = Form("ocr") # ocr, text
):
    input_path = None
    
    try:
        # Save input
        fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Process - extract_text returns a string, so we don't need a file response for the output, 
        # but we DO need to clean up the input file.
        text = pdf_utils.extract_text(input_path, mode)
        
        # Cleanup
        background_tasks.add_task(cleanup_file, input_path)
        
        return Response(
            content=text,
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=extracted_text.txt"}
        )
    except Exception as e:
        if input_path: cleanup_file(input_path)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Host 0.0.0.0 is important for Android emulator to access via 10.0.2.2 or local IP
    uvicorn.run(app, host="0.0.0.0", port=8000)
