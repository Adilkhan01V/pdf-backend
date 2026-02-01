from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from typing import List, Optional
import pdf_utils

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "PDF Utility API is running"}

@app.post("/merge")
async def merge_pdfs_endpoint(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    try:
        pdf_bytes_list = []
        for file in files:
            content = await file.read()
            pdf_bytes_list.append(content)
            
        merged_pdf = pdf_utils.merge_pdfs(pdf_bytes_list)
        
        return Response(
            content=merged_pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=merged.pdf"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/split")
async def split_pdf_endpoint(
    file: UploadFile = File(...),
    mode: str = Form("all"), # all, range, selected
    pages: str = Form(None)  # "2-5" or "1,3,5"
):
    try:
        content = await file.read()
        
        result = pdf_utils.split_pdf(content, mode, pages)
        
        if mode == 'all':
            return Response(
                content=result,
                media_type="application/zip",
                headers={"Content-Disposition": "attachment; filename=split_pages.zip"}
            )
        else:
             # Range or Selected returns a single PDF
            return Response(
                content=result,
                media_type="application/pdf",
                headers={"Content-Disposition": "attachment; filename=extracted_pages.pdf"}
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/compress")
async def compress_pdf_endpoint(
    file: UploadFile = File(...),
    target_size_mb: Optional[float] = Form(None)
):
    try:
        content = await file.read()
        compressed_pdf = pdf_utils.compress_pdf(content, target_size_mb)
        
        return Response(
            content=compressed_pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=compressed.pdf"}
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/img2pdf")
async def img2pdf_endpoint(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    try:
        image_bytes_list = []
        for file in files:
            content = await file.read()
            image_bytes_list.append(content)
            
        pdf_bytes = pdf_utils.images_to_pdf(image_bytes_list)
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=converted_images.pdf"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/extract-text")
async def extract_text_endpoint(
    file: UploadFile = File(...),
    mode: str = Form("ocr") # ocr, text
):
    try:
        content = await file.read()
        text = pdf_utils.extract_text(content, mode)
        
        return Response(
            content=text,
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=extracted_text.txt"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Host 0.0.0.0 is important for Android emulator to access via 10.0.2.2 or local IP
    uvicorn.run(app, host="0.0.0.0", port=8000)