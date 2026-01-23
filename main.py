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
async def split_pdf_endpoint(file: UploadFile = File(...)):
    try:
        content = await file.read()
        zipped_pages = pdf_utils.split_pdf(content)
        
        return Response(
            content=zipped_pages,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=split_pages.zip"}
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

if __name__ == "__main__":
    import uvicorn
    # Host 0.0.0.0 is important for Android emulator to access via 10.0.2.2 or local IP
    uvicorn.run(app, host="0.0.0.0", port=8000)
