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

def merge_pdfs(pdf_paths: List[str], output_path: str, passwords: Optional[List[Optional[str]]] = None) -> None:
    """Merge multiple PDF files into one."""
    merger = pypdf.PdfWriter()

    if not passwords:
        passwords = [None] * len(pdf_paths)

    for idx, path in enumerate(pdf_paths):
        password = passwords[idx]
        reader = pypdf.PdfReader(path)
        if reader.is_encrypted:
            if not password:
                raise ValueError(f"PDF at index {idx} is password-protected but no password was provided.")
            result = reader.decrypt(password)
            if result == pypdf.PasswordType.NOT_DECRYPTED:
                raise ValueError(f"Wrong password for PDF at index {idx}.")
        merger.append(reader)

    with open(output_path, "wb") as f:
        merger.write(f)
    merger.close()

def split_pdf(input_path: str, output_path: str, mode: str = "all", pages: Optional[Union[str, List[int]]] = None, password: Optional[str] = None) -> str:
    """
    Split a PDF file.
    Returns the mimetype of the output (application/zip or application/pdf).
    """
    reader = pypdf.PdfReader(input_path)
    if reader.is_encrypted:
        if not password:
            raise ValueError("PDF is password-protected but no password was provided.")
        result = reader.decrypt(password)
        if result == pypdf.PasswordType.NOT_DECRYPTED:
            raise ValueError("Wrong password for the PDF.")
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
    Preserves SMask (transparency), skips image masks and unsupported color spaces.
    """
    count = 0
    seen_images = {}  # Map objgen -> new stream (avoid reprocessing shared refs)

    for page in pdf.pages:
        if "/Resources" not in page:
            continue
        resources = page.Resources
        if "/XObject" not in resources:
            continue
        xobjects = resources.XObject
        keys = list(xobjects.keys())

        for name in keys:
            raw_image = xobjects[name]
            try:
                if raw_image.get("/Subtype") != pikepdf.Name("/Image"):
                    continue

                # Skip image masks (1-bit masks used for text/line art rendering)
                if raw_image.get("/ImageMask") == pikepdf.Boolean(True):
                    continue

                # Skip images that have an inline mask — replacing them would break rendering
                if "/Mask" in raw_image:
                    continue

                # Skip unsupported / non-trivial color spaces
                cs = raw_image.get("/ColorSpace")
                if cs is not None:
                    cs_name = str(cs) if isinstance(cs, pikepdf.Name) else ""
                    # CMYK, Indexed, ICCBased, Pattern, Separation → skip
                    if any(x in cs_name for x in ["/DeviceCMYK", "/Indexed", "/ICCBased", "/Pattern", "/Separation", "/CalRGB", "/CalGray", "/Lab"]):
                        continue

                # Check shared resource cache
                if hasattr(raw_image, 'objgen') and raw_image.objgen in seen_images:
                    xobjects[name] = seen_images[raw_image.objgen]
                    continue

                pdf_image = pikepdf.PdfImage(raw_image)
                pil_image = pdf_image.as_pil_image()

                new_width = int(pil_image.width * scale_factor)
                new_height = int(pil_image.height * scale_factor)

                if new_width < 10 or new_height < 10:
                    continue

                # Determine output color space
                if pil_image.mode == 'L':
                    color_space_name = "/DeviceGray"
                elif pil_image.mode == 'RGBA':
                    # Drop alpha — write RGB only (alpha was in SMask, handled separately)
                    pil_image = pil_image.convert('RGB')
                    color_space_name = "/DeviceRGB"
                elif pil_image.mode == 'RGB':
                    color_space_name = "/DeviceRGB"
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

                # Preserve SMask (soft transparency mask) from original image
                if "/SMask" in raw_image:
                    new_stream["/SMask"] = raw_image["/SMask"]

                if hasattr(raw_image, 'objgen'):
                    seen_images[raw_image.objgen] = new_stream

                xobjects[name] = new_stream
                count += 1

            except Exception:
                continue
    return count


def _validate_pdf_content(path: str, expected_pages: int) -> bool:
    """
    Returns True if the PDF at `path` appears to have non-blank content
    and the correct number of pages. Used to catch compression artifacts
    (e.g. Ghostscript producing blank pages for certain structured PDFs).
    """
    try:
        doc = fitz.open(path)
        if len(doc.pages) != expected_pages:
            doc.close()
            return False
        # Spot-check first and last pages for any renderable content
        pages_to_check = list({0, len(doc.pages) - 1})  # deduped
        for idx in pages_to_check:
            page = doc[idx]
            # Any of: text, vector drawings, or embedded images
            if page.get_text().strip():
                doc.close()
                return True
            if page.get_drawings():
                doc.close()
                return True
            if page.get_images():
                doc.close()
                return True
        doc.close()
        return False  # All checked pages were blank
    except Exception:
        return False  # Unreadable = not valid


def compress_pdf(input_path: str, output_path: str, target_size_mb: Optional[float] = None, password: Optional[str] = None) -> None:
    """
    Compress a PDF file.
    Reads from input_path, writes to output_path.
    Supports password-protected PDFs: decrypts first, then compresses.
    """
    get_mb = lambda p: os.path.getsize(p) / (1024 * 1024)

    # Fast encryption check: attempt a pikepdf open.
    # pikepdf is C-based — open/close on a non-encrypted PDF is nearly instant.
    # Only on PasswordError do we fall into the decrypt path.
    decrypted_input = input_path
    _decrypted_tmp = None
    try:
        probe = pikepdf.Pdf.open(input_path)
        probe.close()
        # Not encrypted — proceed directly
    except pikepdf.PasswordError:
        # PDF is encrypted
        if not password:
            raise ValueError("PDF is password-protected but no password was provided.")
        try:
            src = pikepdf.Pdf.open(input_path, password=password)
        except pikepdf.PasswordError:
            raise ValueError("Wrong password for the PDF.")
        # Write a decrypted copy for the compression pipeline
        fd, _decrypted_tmp = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        src.save(_decrypted_tmp)
        src.close()
        decrypted_input = _decrypted_tmp
    except Exception:
        raise


    original_size = get_mb(decrypted_input)

    # If target not set, assume we want significant compression
    if target_size_mb is None:
        target_size_mb = original_size * 0.75  # Default target

    gs_tmp_path = None
    try:
        # ── Stage 1: Ghostscript ──────────────────────────────────────────────
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as gs_tmp:
            gs_tmp_path = gs_tmp.name

        gs_success = compress_pdf_ghostscript(decrypted_input, gs_tmp_path, target_size_mb)

        # Count original pages for validation
        try:
            orig_doc = fitz.open(decrypted_input)
            original_page_count = len(orig_doc.pages)
            orig_doc.close()
        except Exception:
            original_page_count = 0

        current_working_path = decrypted_input
        if gs_success and os.path.exists(gs_tmp_path):
            gs_size = get_mb(gs_tmp_path)
            if gs_size < original_size:
                # Validate GS output has non-blank content before accepting it
                # (GS can produce blank pages for structured/government PDFs)
                if original_page_count == 0 or _validate_pdf_content(gs_tmp_path, original_page_count):
                    current_working_path = gs_tmp_path
                    if gs_size <= target_size_mb:
                        shutil.move(gs_tmp_path, output_path)
                        gs_tmp_path = None  # already moved, don't delete
                        return
                else:
                    print("WARNING: GS output failed content validation (blank pages). Falling back to pikepdf.")

        # ── Stage 2: Pikepdf iterative image downsampling ─────────────────────
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
        if ratio > 5.0:
            start_index = 9
        elif ratio > 2.0:
            start_index = 3

        best_tmp_path = None
        min_size = current_size

        for i in range(start_index, len(attempts)):
            scale, quality = attempts[i]
            try:
                pdf = pikepdf.Pdf.open(current_working_path)
                _downsample_images(pdf, scale, quality)
                pdf.remove_unreferenced_resources()
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

        # ── Finalize: pick best result ────────────────────────────────────────
        if best_tmp_path and os.path.exists(best_tmp_path):
            # Validate pikepdf output before accepting
            if original_page_count == 0 or _validate_pdf_content(best_tmp_path, original_page_count):
                if os.path.exists(output_path):
                    os.unlink(output_path)
                shutil.move(best_tmp_path, output_path)
            else:
                # pikepdf output is blank — fall back to GS result or original
                print("WARNING: pikepdf output failed content validation. Using fallback.")
                os.unlink(best_tmp_path)
                best_tmp_path = None
                if current_working_path != decrypted_input and os.path.exists(current_working_path):
                    shutil.copy(current_working_path, output_path)
                else:
                    shutil.copy(decrypted_input, output_path)
        elif current_working_path != decrypted_input and os.path.exists(current_working_path):
            shutil.move(current_working_path, output_path)
            gs_tmp_path = None  # already moved
        else:
            shutil.copy(decrypted_input, output_path)

    finally:
        # Cleanup GS temp if it wasn't moved to output
        if gs_tmp_path and os.path.exists(gs_tmp_path):
            try:
                os.unlink(gs_tmp_path)
            except Exception:
                pass
        # Cleanup decrypted temp
        if _decrypted_tmp and os.path.exists(_decrypted_tmp):
            try:
                os.unlink(_decrypted_tmp)
            except Exception:
                pass


def extract_text(input_path: str, mode: str = "ocr", password: Optional[str] = None) -> str:
    """
    Extract text from PDF.
    mode: 'text' (native extraction) or 'ocr' (optical character recognition).
    Supports password-protected PDFs.
    """
    extracted_text = []

    try:
        doc = fitz.open(input_path)
        if doc.needs_pass:
            if not password:
                raise ValueError("PDF is password-protected but no password was provided.")
            if not doc.authenticate(password):
                raise ValueError("Wrong password for the PDF.")
        
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
        except Exception:
             shutil.copy(input_path, output_path)

def organize_pdf(input_path: str, output_path: str, pages_config: List[dict], password: Optional[str] = None) -> None:
    """
    Organize PDF: reorder, rotate, delete, add blank pages.
    Supports password-protected PDFs.
    pages_config: List of dicts, e.g.,
    [
      {"type": "original", "page_index": 0, "rotation": 90},
      {"type": "blank"}
    ]
    """
    reader = pypdf.PdfReader(input_path)
    if reader.is_encrypted:
        if not password:
            raise ValueError("PDF is password-protected but no password was provided.")
        result = reader.decrypt(password)
        if result == pypdf.PasswordType.NOT_DECRYPTED:
            raise ValueError("Wrong password for the PDF.")
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

def unlock_pdf(input_path: str, output_path: str, password: str) -> None:
    """
    Unlock a password-protected PDF.
    Raises ValueError with a descriptive message on failure.
    """
    # First, check if the PDF is actually encrypted
    try:
        test_pdf = pikepdf.Pdf.open(input_path)
        # If we can open without password, it's not encrypted
        test_pdf.close()
        raise ValueError("This PDF is not password protected.")
    except pikepdf.PasswordError:
        # Good — the PDF is indeed encrypted, proceed to unlock
        pass
    except ValueError:
        # Re-raise our own ValueError
        raise

    # Now try to open with the provided password
    try:
        pdf = pikepdf.Pdf.open(input_path, password=password)
        pdf.save(output_path)
        pdf.close()
    except pikepdf.PasswordError:
        raise ValueError("Wrong password. Please try again.")


def crop_pdf(
    input_path: str,
    output_path: str,
    pages: List[int],
    crop_box: dict,
    password: Optional[str] = None,
) -> None:
    """
    Crop selected pages of a PDF by setting their CropBox.

    Args:
        input_path:  Path to the source PDF.
        output_path: Path for the output PDF.
        pages:       0-based page indices to crop. Pass [-1] to crop ALL pages.
        crop_box:    Dict with fractional values (0.0–1.0) of the MediaBox:
                     { "left": f, "top": f, "right": f, "bottom": f }
                     where left/top are the start, right/bottom are the end of
                     the kept area (not the margin sizes).
    """
    doc = fitz.open(input_path)
    if doc.needs_pass:
        if not password:
            raise ValueError("PDF is password-protected but no password was provided.")
        if not doc.authenticate(password):
            raise ValueError("Wrong password for the PDF.")

    all_pages = pages == [-1] or pages == []

    for page_num in range(len(doc)):
        if not all_pages and page_num not in pages:
            continue

        page = doc[page_num]
        mb = page.mediabox  # fitz.Rect(x0, y0, x1, y1)

        w = mb.width
        h = mb.height

        # Convert fractional values → absolute PDF points
        x0 = mb.x0 + crop_box.get("left", 0.0) * w
        y0 = mb.y0 + crop_box.get("top", 0.0) * h
        x1 = mb.x0 + crop_box.get("right", 1.0) * w
        y1 = mb.y0 + crop_box.get("bottom", 1.0) * h

        page.set_cropbox(fitz.Rect(x0, y0, x1, y1))

    doc.save(output_path)
    doc.close()


def resize_image(input_path: str, output_path: str, width: Optional[int] = None, height: Optional[int] = None, scale_factor: Optional[float] = None) -> None:
    """
    Resize an image. If scale_factor is provided, use that; else use width/height (preserve aspect ratio if only one is provided).
    """
    try:
        img = Image.open(input_path)
        
        if scale_factor:
            new_width = int(img.width * scale_factor)
            new_height = int(img.height * scale_factor)
        else:
            if width and height:
                new_width, new_height = width, height
            elif width:
                ratio = width / img.width
                new_height = int(img.height * ratio)
                new_width = width
            elif height:
                ratio = height / img.height
                new_width = int(img.width * ratio)
                new_height = height
            else:
                shutil.copy(input_path, output_path)
                return
        
        resized_img = img.resize((new_width, new_height), Image.LANCZOS)
        
        # Handle transparency for JPEG conversion
        if resized_img.mode in ('RGBA', 'LA') or (resized_img.mode == 'P' and 'transparency' in resized_img.info):
            background = Image.new('RGB', resized_img.size, (255, 255, 255))
            if resized_img.mode == 'P':
                resized_img = resized_img.convert('RGBA')
            background.paste(resized_img, mask=resized_img.split()[-1])
            resized_img = background
        elif resized_img.mode != 'RGB':
            resized_img = resized_img.convert('RGB')
            
        resized_img.save(output_path, "JPEG", optimize=True)
        
    except Exception as e:
        print(f"Error resizing image: {e}")
        try:
             img = Image.open(input_path)
             if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
             img.save(output_path, "JPEG")
        except Exception:
             shutil.copy(input_path, output_path)


def add_page_numbers(
    input_path: str,
    output_path: str,
    position: str = "bottom-center",
    font_size: int = 12,
    start_number: int = 1,
    prefix: str = "",
    suffix: str = "",
    password: Optional[str] = None,
) -> None:
    """
    Add page numbers to every page of a PDF using PyMuPDF.
    position: one of top-left, top-center, top-right,
                         bottom-left, bottom-center, bottom-right
    """
    doc = fitz.open(input_path)
    if doc.needs_pass:
        if not password:
            raise ValueError("PDF is password-protected but no password was provided.")
        if not doc.authenticate(password):
            raise ValueError("Wrong password for the PDF.")

    margin = 28  # points from edge

    for i, page in enumerate(doc):
        page_num = i + start_number
        label = f"{prefix}{page_num}{suffix}"
        rect = page.rect  # page bounding box

        # Determine x, y based on position
        pos_lower = position.lower()
        if "top" in pos_lower:
            y = rect.y0 + margin
        else:
            y = rect.y1 - margin

        if "left" in pos_lower:
            x = rect.x0 + margin
            align = fitz.TEXT_ALIGN_LEFT
        elif "right" in pos_lower:
            x = rect.x1 - margin
            align = fitz.TEXT_ALIGN_RIGHT
        else:
            x = rect.width / 2
            align = fitz.TEXT_ALIGN_CENTER

        # Insert text annotation
        page.insert_text(
            fitz.Point(x, y),
            label,
            fontsize=font_size,
            color=(0, 0, 0),
            fontname="helv",
        )

    doc.save(output_path)
    doc.close()


def repair_pdf(input_path: str, output_path: str, password: Optional[str] = None) -> dict:
    """
    Attempt a professional multi-stage repair of a damaged / malformed PDF.
    Returns a dict with 'method' and 'issues_found' for reporting.
    """
    issues = []
    method_used = "none"

    # ── Stage 1: try pikepdf (handles xref rebuilding, stream errors) ──────────
    try:
        open_kwargs = {}
        if password:
            open_kwargs["password"] = password
        pdf = pikepdf.Pdf.open(
            input_path,
            suppress_warnings=False,
            **open_kwargs
        )
        pdf.remove_unreferenced_resources()
        pdf.save(
            output_path,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            linearize=False,
        )
        pdf.close()
        issues.append("Rebuilt cross-reference table")
        issues.append("Removed unreferenced resources")
        method_used = "pikepdf"

        # Validate output is readable
        test = pikepdf.Pdf.open(output_path)
        page_count = len(test.pages)
        test.close()
        issues.append(f"Verified {page_count} pages readable")
        return {"method": method_used, "issues_found": issues}

    except Exception as pikepdf_err:
        issues.append(f"pikepdf partial: {str(pikepdf_err)[:120]}")

    # ── Stage 2: try Ghostscript (deep stream repair + re-distillation) ────────
    gs_cmd = get_ghostscript_command()
    if gs_cmd:
        try:
            args = [
                gs_cmd,
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                "-dNOPAUSE",
                "-dQUIET",
                "-dBATCH",
                "-dPDFSETTINGS=/default",
                f"-sOutputFile={output_path}",
                input_path,
            ]
            subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                issues.append("Repaired via Ghostscript re-distillation")
                method_used = "ghostscript"
                return {"method": method_used, "issues_found": issues}
        except Exception as gs_err:
            issues.append(f"Ghostscript failed: {str(gs_err)[:120]}")

    # ── Stage 3: PyMuPDF salvage (page-by-page extraction) ────────────────────
    try:
        src = fitz.open(input_path)
        if src.needs_pass:
            if not password:
                raise ValueError("PDF is password-protected but no password was provided.")
            if not src.authenticate(password):
                raise ValueError("Wrong password for the PDF.")

        dest = fitz.open()  # new empty PDF
        salvaged = 0
        for page_num in range(len(src)):
            try:
                dest.insert_pdf(src, from_page=page_num, to_page=page_num)
                salvaged += 1
            except Exception:
                issues.append(f"Skipped unreadable page {page_num + 1}")

        dest.save(output_path, garbage=4, deflate=True)
        dest.close()
        src.close()

        if salvaged == 0:
            raise ValueError("No pages could be salvaged from the PDF.")

        issues.append(f"Salvaged {salvaged} pages via PyMuPDF")
        method_used = "pymupdf_salvage"
        return {"method": method_used, "issues_found": issues}

    except Exception as mupdf_err:
        issues.append(f"PyMuPDF failed: {str(mupdf_err)[:120]}")

    raise ValueError(
        "Could not repair the PDF. It may be severely corrupted or encrypted with an unknown cipher.\n"
        + "\n".join(issues)
    )