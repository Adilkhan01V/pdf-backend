import io
import os
import subprocess
import tempfile
import shutil
from typing import List, Union, Optional
import pypdf
import pikepdf
import fitz  # PyMuPDF
import pytesseract
import zipfile
from PIL import Image

# Configure Tesseract Path if not in PATH
tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if shutil.which("tesseract") is None:
    if os.path.exists(tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
        print(f"INFO: Using Tesseract at {tesseract_path}")
    else:
        print("WARNING: Tesseract not found in PATH or default location. OCR will fail.")

def get_ghostscript_command() -> Optional[str]:
    """
    Check if Ghostscript is available and return the command name.
    """
    commands = ["gswin64c", "gswin32c", "gs"]
    for cmd in commands:
        if shutil.which(cmd):
            return cmd
    return None

def compress_pdf_ghostscript(input_path: str, output_path: str, target_size_mb: float) -> bool:
    """
    Attempt to compress PDF using Ghostscript with iterative DPI reduction.
    Returns True if successful, False otherwise.
    """
    gs_cmd = get_ghostscript_command()
    if not gs_cmd:
        print("WARNING: Ghostscript not found. Skipping GS compression.")
        return False

    target_bytes = target_size_mb * 1024 * 1024
    
    # Iterative compression strategy
    # Start at 200 DPI, step down by 25, until 72 DPI
    current_dpi = 200
    min_dpi = 72
    step_dpi = 25
    
    min_size_achieved = float('inf')
    # We will use a temp file for intermediate GS outputs to avoid overwriting the final output repeatedly
    # unless it's the best one. But to keep it simple, we can write to output_path and check size.
    
    # However, GS writes directly.
    
    while current_dpi >= min_dpi:
        args = [
            gs_cmd,
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            "-dDownsampleColorImages=true",
            f"-dColorImageResolution={current_dpi}",
            "-dDownsampleGrayImages=true",
            f"-dGrayImageResolution={current_dpi}",
            "-dDownsampleMonoImages=true",
            f"-dMonoImageResolution={current_dpi}",
            f"-sOutputFile={output_path}",
            input_path
        ]
        
        try:
            subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(output_path):
                size = os.path.getsize(output_path)
                
                # If we met the target, stop!
                if size <= target_bytes:
                    return True
                    
        except subprocess.CalledProcessError:
            pass
        except Exception:
            pass
            
        current_dpi -= step_dpi
        
    # If we finished the loop, the last output_path (72 DPI) is there.
    # It might not meet the target, but it's the best GS could do.
    return os.path.exists(output_path)

def images_to_pdf(image_paths: List[str], output_path: str) -> None:
    """
    Convert a list of images to a single PDF.
    """
    images = []
    # We load images. For very large images, this might still be memory intensive.
    # But Pillow handles lazy loading somewhat.
    # To truly minimize memory for HUGE images, we might need a different approach,
    # but for typical usage, opening file paths is better than loading bytes.
    
    valid_images = []
    for img_path in image_paths:
        try:
            img = Image.open(img_path)
            # Convert to RGB
            if img.mode == 'RGBA':
                img = img.convert('RGB')
            valid_images.append(img)
        except Exception as e:
            print(f"Error processing image {img_path}: {e}")
            continue

    if not valid_images:
        raise ValueError("No valid images provided")

    # Save to output path
    valid_images[0].save(
        output_path, 
        format='PDF', 
        save_all=True, 
        append_images=valid_images[1:]
    )

def merge_pdfs(pdf_paths: List[str], output_path: str) -> None:
    """Merge multiple PDF files into one."""
    merger = pypdf.PdfWriter()
    
    for path in pdf_paths:
        merger.append(path)
        
    merger.write(output_path)
    merger.close()

def split_pdf(input_path: str, output_path: str, mode: str = "all", pages: Optional[Union[str, List[int]]] = None) -> str:
    """
    Split a PDF file.
    Returns the mimetype of the output (application/zip or application/pdf).
    """
    reader = pypdf.PdfReader(input_path)
    total_pages = len(reader.pages)

    if mode == 'all':
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for i, page in enumerate(reader.pages):
                writer = pypdf.PdfWriter()
                writer.add_page(page)
                
                # Write page to a temp file then add to zip to avoid large in-memory buffers
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_page:
                    writer.write(tmp_page)
                    tmp_page_path = tmp_page.name
                
                writer.close()
                zip_file.write(tmp_page_path, f"page_{i+1}.pdf")
                os.unlink(tmp_page_path)
        return "application/zip"

    elif mode in ['range', 'selected']:
        writer = pypdf.PdfWriter()
        indices_to_extract = []

        if mode == 'range' and isinstance(pages, str):
            try:
                start, end = map(int, pages.split('-'))
                start = max(1, start)
                end = min(total_pages, end)
                indices_to_extract = list(range(start - 1, end))
            except ValueError:
                pass

        elif mode == 'selected' and isinstance(pages, str):
            try:
                parts = pages.split(',')
                for p in parts:
                    idx = int(p.strip())
                    if 1 <= idx <= total_pages:
                        indices_to_extract.append(idx - 1)
            except ValueError:
                pass

        if not indices_to_extract:
             indices_to_extract = list(range(total_pages))

        for idx in indices_to_extract:
            writer.add_page(reader.pages[idx])

        writer.write(output_path)
        writer.close()
        return "application/pdf"

    return "application/pdf"

def _downsample_images(pdf: pikepdf.Pdf, scale_factor: float, quality: int):
    """
    Iterates through all images in the PDF and resizes/compresses them.
    Handles shared resources to prevent file bloat.
    """
    count = 0
    seen_images = {} # Map objgen to new stream

    for page in pdf.pages:
        if "/Resources" not in page:
            continue
        resources = page.Resources
        if "/XObject" in resources:
            xobjects = resources.XObject
            keys = list(xobjects.keys())
            
            for name in keys:
                raw_image = xobjects[name]
                if raw_image.Subtype != "/Image":
                    continue
                
                # Check if we already processed this image (handle shared resources)
                # raw_image is a pikepdf object. We use its object ID (objgen) as key.
                if hasattr(raw_image, 'objgen') and raw_image.objgen in seen_images:
                    xobjects[name] = seen_images[raw_image.objgen]
                    continue
                    
                try:
                    pdf_image = pikepdf.PdfImage(raw_image)
                    pil_image = pdf_image.as_pil_image()
                    
                    new_width = int(pil_image.width * scale_factor)
                    new_height = int(pil_image.height * scale_factor)
                    
                    if new_width < 10 or new_height < 10:
                        continue
                        
                    if pil_image.mode == 'L':
                        color_space_name = "/DeviceGray"
                    else:
                        pil_image = pil_image.convert('RGB')
                        color_space_name = "/DeviceRGB"
                    
                    resized_pil = pil_image.resize((new_width, new_height), Image.LANCZOS)
                    
                    img_buffer = io.BytesIO()
                    resized_pil.save(img_buffer, format='JPEG', quality=quality)
                    img_buffer.seek(0)
                    
                    new_stream = pikepdf.Stream(
                        pdf, 
                        img_buffer.getvalue(),
                        Type=pikepdf.Name("/XObject"),
                        Subtype=pikepdf.Name("/Image"),
                        Width=new_width,
                        Height=new_height,
                        ColorSpace=pikepdf.Name(color_space_name),
                        BitsPerComponent=8,
                        Filter=pikepdf.Name("/DCTDecode")
                    )
                    
                    # Update cache if it's an indirect object
                    if hasattr(raw_image, 'objgen'):
                        seen_images[raw_image.objgen] = new_stream

                    xobjects[name] = new_stream
                    count += 1
                except Exception:
                    continue
    return count

def compress_pdf(input_path: str, output_path: str, target_size_mb: Optional[float] = None) -> None:
    """
    Compress a PDF file.
    Reads from input_path, writes to output_path.
    """
    get_mb = lambda p: os.path.getsize(p) / (1024 * 1024)
    
    original_size = get_mb(input_path)
    
    # If target not set, assume we want significant compression, say 50% or generic
    if target_size_mb is None:
        target_size_mb = original_size * 0.75 # Default target

    # 1. Try Ghostscript first
    # We use a temp file for GS output to not clobber output_path yet
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as gs_tmp:
        gs_tmp_path = gs_tmp.name
    
    gs_success = compress_pdf_ghostscript(input_path, gs_tmp_path, target_size_mb)
    
    current_working_path = input_path
    if gs_success and os.path.exists(gs_tmp_path):
        gs_size = get_mb(gs_tmp_path)
        if gs_size < original_size:
            current_working_path = gs_tmp_path
            
            if gs_size <= target_size_mb:
                # Success! Move GS result to output
                shutil.move(gs_tmp_path, output_path)
                return

    # 2. Pikepdf Iterative
    # We work on 'current_working_path' (either original or GS result)
    # We need to save to output_path.
    
    # If we are using the original file, we copy it to output_path first to work on it?
    # Actually pikepdf can open input and save to output.
    
    attempts = [
        (1.0, 95), (1.0, 90), (1.0, 85), (1.0, 80), 
        (1.0, 75), (1.0, 70), (0.9, 70), (0.85, 70),
        (0.8, 70), (0.8, 65), (0.8, 60), (0.75, 60),
        (0.7, 60), (0.65, 60), (0.6, 60), (0.55, 55),
        (0.5, 50), (0.45, 50), (0.4, 50), (0.35, 45),
        (0.3, 40), (0.25, 40)
    ]
    
    current_size = get_mb(current_working_path)
    start_index = 0
    ratio = current_size / target_size_mb
    if ratio > 5.0: start_index = 9
    elif ratio > 2.0: start_index = 3
    
    best_tmp_path = None
    min_size = current_size
    
    for i in range(start_index, len(attempts)):
        scale, quality = attempts[i]
        
        # Open the current best candidate
        # If we have a best_tmp_path, use that as base? 
        # No, we should always go back to the 'current_working_path' (GS result or Original) 
        # to avoid degradation unless we want cumulative?
        # Typically iterative from source is better to control artifacts.
        
        try:
            pdf = pikepdf.Pdf.open(current_working_path)
            
            _downsample_images(pdf, scale, quality)
            
            pdf.remove_unreferenced_resources()
            
            # Save to a new temp file
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as attempt_tmp:
                attempt_path = attempt_tmp.name
                
            pdf.save(attempt_path, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
            pdf.close()
            
            new_size = get_mb(attempt_path)
            
            if new_size < min_size:
                min_size = new_size
                if best_tmp_path and os.path.exists(best_tmp_path):
                    os.unlink(best_tmp_path)
                best_tmp_path = attempt_path
                
                if min_size <= target_size_mb:
                    break
            else:
                os.unlink(attempt_path)
                
        except Exception:
            pass

    # Finalize
    if best_tmp_path and os.path.exists(best_tmp_path):
        if os.path.exists(output_path):
            os.unlink(output_path)
        shutil.move(best_tmp_path, output_path)
    elif current_working_path != input_path:
        # We used GS and it was the best we got
        shutil.move(current_working_path, output_path)
    else:
        # We failed to compress further, just copy original
        shutil.copy(input_path, output_path)
        
    # Cleanup GS temp if it exists and wasn't moved
    if os.path.exists(gs_tmp_path):
        try:
            os.unlink(gs_tmp_path)
        except:
            pass

def extract_text(input_path: str, mode: str = "ocr") -> str:
    """
    Extract text from PDF.
    mode: 'text' (native extraction) or 'ocr' (optical character recognition).
    """
    extracted_text = []
    
    try:
        doc = fitz.open(input_path)
        
        for i, page in enumerate(doc):
            if mode == 'ocr':
                # Force RGB to avoid sample mismatch issues with CMYK/RGBA
                pix = page.get_pixmap(dpi=300, colorspace=fitz.csRGB)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                extracted_text.append(f"--- Page {i+1} ---")
                text = pytesseract.image_to_string(img)
                extracted_text.append(text)
            else:
                extracted_text.append(f"--- Page {i+1} ---")
                text = page.get_text()
                extracted_text.append(text)
                
        return "\n".join(extracted_text)
        
    except Exception as e:
        print(f"Error in extract_text: {e}")
        return f"Error extracting text: {str(e)}"

def compress_image(input_path: str, output_path: str, target_size_mb: Optional[float] = None) -> None:
    """
    Compress an image file (JPEG/PNG).
    Reads from input_path, writes to output_path.
    """
    try:
        img = Image.open(input_path)
        
        # Handle transparency for JPEG conversion
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            # Create white background
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
            
        # Initial quality
        quality = 85
        step = 5
        min_quality = 10
        
        # If target size is provided, iterate
        if target_size_mb:
            target_bytes = target_size_mb * 1024 * 1024
            
            while quality >= min_quality:
                img.save(output_path, "JPEG", optimize=True, quality=quality)
                if os.path.getsize(output_path) <= target_bytes:
                    return
                quality -= step
        
        # If no target size or loop finished, save with last quality
        img.save(output_path, "JPEG", optimize=True, quality=quality)
        
    except Exception as e:
        print(f"Error compressing image: {e}")
        # If compression fails, try to just copy original if possible, 
        # but original might not be JPEG. So we save as JPEG with default settings.
        try:
             img = Image.open(input_path)
             if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
             img.save(output_path, "JPEG")
        except:
             shutil.copy(input_path, output_path)

def organize_pdf(input_path: str, output_path: str, pages_config: List[dict]) -> None:
    """
    Organize PDF: reorder, rotate, delete, add blank pages.
    pages_config: List of dicts, e.g., 
    [
      {"type": "original", "page_index": 0, "rotation": 90}, 
      {"type": "blank"}
    ]
    """
    reader = pypdf.PdfReader(input_path)
    writer = pypdf.PdfWriter()
    
    total_pages = len(reader.pages)
    
    for page_cfg in pages_config:
        if page_cfg.get("type") == "blank":
            # Add a blank page (standard A4 size or match first page size?)
            # pypdf's add_blank_page adds a page with the size of the last added page
            # or we can specify width/height. Let's try default first.
            writer.add_blank_page()
        
        elif page_cfg.get("type") == "original":
            idx = page_cfg.get("page_index")
            if idx is not None and 0 <= idx < total_pages:
                page = reader.pages[idx]
                
                # Handle Rotation
                # pypdf rotation is clockwise. 
                # We expect the frontend to send the DESIRED rotation (0, 90, 180, 270).
                # We apply rotation to the page AFTER adding it to the writer to avoid 
                # modifying the source page object (which might be reused/duplicated).
                
                added_page = writer.add_page(page)
                
                user_rotation = page_cfg.get("rotation", 0)
                if user_rotation is not None:
                     current_rot = added_page.get('/Rotate', 0)
                     delta = (user_rotation - current_rot) % 360
                     if delta != 0:
                        added_page.rotate(delta)

    writer.write(output_path)
    writer.close()
def lock_pdf(input_path: str, output_path: str, password: str) -> None:
    """
    Lock PDF: add password protection.
    """
    reader = pypdf.PdfReader(input_path)
    writer = pypdf.PdfWriter()
    
    for page in reader.pages:
        writer.add_page(page)
    
    writer.encrypt(password)
    with open(output_path, 'wb') as f:
        writer.write(f)