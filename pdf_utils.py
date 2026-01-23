import io
import os
import subprocess
import tempfile
import shutil
import platform
from typing import List, Union, Optional
import pypdf
import pikepdf
import zipfile
from PIL import Image

def get_ghostscript_command() -> Optional[str]:
    """
    Check if Ghostscript is available and return the command name.
    """
    commands = ["gswin64c", "gswin32c", "gs"]
    for cmd in commands:
        if shutil.which(cmd):
            return cmd
    return None

def compress_pdf_ghostscript(pdf_bytes: bytes, target_size_mb: float) -> Optional[bytes]:
    """
    Attempt to compress PDF using Ghostscript with iterative DPI reduction.
    Returns compressed bytes if successful, or None if GS is missing/fails.
    """
    gs_cmd = get_ghostscript_command()
    if not gs_cmd:
        print("WARNING: Ghostscript not found. Skipping GS compression.")
        return None

    target_bytes = target_size_mb * 1024 * 1024
    
    # Create temp directory
    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = os.path.join(temp_dir, "input.pdf")
        output_path = os.path.join(temp_dir, "output.pdf")
        
        # Write input file
        with open(input_path, "wb") as f:
            f.write(pdf_bytes)
            
        # Iterative compression strategy
        # Start at 200 DPI, step down by 25, until 72 DPI
        current_dpi = 200
        min_dpi = 72
        step_dpi = 25
        
        best_output_bytes = None
        min_size_achieved = float('inf')
        
        while current_dpi >= min_dpi:
            # Ghostscript command
            # We use /default to allow custom resolution overrides
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
                    
                    with open(output_path, "rb") as f:
                        output_bytes = f.read()
                        
                    # Keep track of the smallest file achieved so far
                    if size < min_size_achieved:
                        min_size_achieved = size
                        best_output_bytes = output_bytes
                    
                    # If we met the target, stop!
                    if size <= target_bytes:
                        return output_bytes
                        
            except subprocess.CalledProcessError:
                pass
            except Exception:
                pass
                
            current_dpi -= step_dpi
            
        # If we finished the loop and didn't meet target, return the best we got
        # (This fulfills "Return smallest version with warning metadata" - though we just return bytes here)
        return best_output_bytes

def merge_pdfs(pdf_files: List[bytes]) -> bytes:
    """Merge multiple PDF files into one."""
    merger = pypdf.PdfWriter()
    
    for pdf_bytes in pdf_files:
        pdf_stream = io.BytesIO(pdf_bytes)
        merger.append(pdf_stream)
        
    output_stream = io.BytesIO()
    merger.write(output_stream)
    merger.close()
    
    output_stream.seek(0)
    return output_stream.getvalue()

def split_pdf(pdf_file: bytes) -> bytes:
    """
    Split a PDF file. 
    For simplicity, this splits all pages into separate PDFs and returns a ZIP file.
    """
    input_stream = io.BytesIO(pdf_file)
    reader = pypdf.PdfReader(input_stream)
    
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for i, page in enumerate(reader.pages):
            writer = pypdf.PdfWriter()
            writer.add_page(page)
            
            page_stream = io.BytesIO()
            writer.write(page_stream)
            writer.close()
            
            page_stream.seek(0)
            zip_file.writestr(f"page_{i+1}.pdf", page_stream.getvalue())
            
    zip_buffer.seek(0)
    return zip_buffer.getvalue()

def _downsample_images(pdf: pikepdf.Pdf, scale_factor: float, quality: int):
    """
    Iterates through all images in the PDF and resizes/compresses them.
    """
    count = 0
    for page in pdf.pages:
        # Access XObject resources directly
        if "/XObject" in page.Resources:
            xobjects = page.Resources.XObject
            # We need to list keys first because we are modifying the dictionary
            keys = list(xobjects.keys())
            
            for name in keys:
                raw_image = xobjects[name]
                # Check if it is an image
                if raw_image.Subtype != "/Image":
                    continue
                    
                try:
                    # Wrap raw object in PdfImage helper
                    pdf_image = pikepdf.PdfImage(raw_image)
                    
                    # Convert pikepdf image to PIL
                    pil_image = pdf_image.as_pil_image()
                    
                    # Calculate new size
                    new_width = int(pil_image.width * scale_factor)
                    new_height = int(pil_image.height * scale_factor)
                    
                    # Don't resize if too small already
                    if new_width < 10 or new_height < 10:
                        continue
                        
                    # Resize
                    # Handle Grayscale vs RGB for JPEG
                    if pil_image.mode == 'L':
                        color_space_name = "/DeviceGray"
                    else:
                        pil_image = pil_image.convert('RGB')
                        color_space_name = "/DeviceRGB"
                    
                    resized_pil = pil_image.resize((new_width, new_height), Image.LANCZOS)
                    
                    # Manual JPEG compression to control quality
                    img_buffer = io.BytesIO()
                    resized_pil.save(img_buffer, format='JPEG', quality=quality)
                    img_buffer.seek(0)
                    
                    # Create a new pikepdf Stream from raw JPEG data
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
                    
                    # Replace image in PDF
                    xobjects[name] = new_stream
                    count += 1
                except Exception:
                    # If image processing fails, skip it
                    continue
    return count

def compress_pdf(pdf_file: bytes, target_size_mb: Optional[float] = None) -> bytes:
    """
    Compress a PDF file.
    If target_size_mb is provided, it attempts to reduce file size below that target
    by iteratively downsampling images and reducing quality.
    """
    # Helper to get size in MB
    get_mb = lambda b: len(b) / (1024 * 1024)
    
    current_pdf_bytes = pdf_file
    original_size = get_mb(current_pdf_bytes)
    
    # 1. Initial Structural Compression
    input_stream = io.BytesIO(current_pdf_bytes)
    pdf = pikepdf.Pdf.open(input_stream)
    pdf.remove_unreferenced_resources()
    
    output_stream = io.BytesIO()
    # Enable object stream generation for better compression of PDF structure
    pdf.save(output_stream, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    pdf.close()
    
    current_pdf_bytes = output_stream.getvalue()
    current_size = get_mb(current_pdf_bytes)
    
    # If no target provided, or already satisfied, return
    if target_size_mb is None or current_size <= target_size_mb:
        return current_pdf_bytes

    # PRIORITY: Try Ghostscript Compression first (as requested)
    # This uses iterative DPI reduction (200 -> 72)
    gs_result = compress_pdf_ghostscript(current_pdf_bytes, target_size_mb)
    if gs_result is not None:
        # Check if GS result is actually smaller or meets target
        gs_size = len(gs_result) / (1024 * 1024)
        if gs_size <= target_size_mb or gs_size < current_size:
            return gs_result
        # If GS didn't help (unlikely but possible), fall through to Pikepdf
        
    # FALLBACK: Pikepdf Iterative Compression (Downsampling & Quality Reduction)
    # List of (scale_factor, jpeg_quality) tuples
    # More granular steps for better precision (to meet target size without over-compressing)
    attempts = [
        (1.0, 95),   # Minimal compression
        (1.0, 90),
        (1.0, 85),
        (1.0, 80),   # Standard
        (1.0, 75),
        (1.0, 70),
        (0.9, 70),   # Slight resize
        (0.85, 70),
        (0.8, 70),
        (0.8, 65),
        (0.8, 60),
        (0.75, 60),  # Gradual resize
        (0.7, 60),
        (0.65, 60),
        (0.6, 60),   # Moderate reduction
        (0.55, 55),
        (0.5, 50),
        (0.45, 50),
        (0.4, 50),   # Aggressive reduction
        (0.35, 45),
        (0.3, 40),
        (0.25, 40)   # Very aggressive
    ]
    
    # Heuristic: Skip high-quality attempts if the file is WAY larger than target
    # If current size > 2x target, start from index 3 (Q80)
    # If current size > 5x target, start from index 9 (0.6/60)
    start_index = 0
    ratio = current_size / target_size_mb
    if ratio > 5.0:
        start_index = 9
    elif ratio > 2.0:
        start_index = 3
        
    for i in range(start_index, len(attempts)):
        scale, quality = attempts[i]
        
        if current_size <= target_size_mb:
            break
            
        # Re-open the current best PDF
        input_stream = io.BytesIO(current_pdf_bytes)
        pdf = pikepdf.Pdf.open(input_stream)
        
        # Downsample images
        _downsample_images(pdf, scale, quality)
        
        # Save again
        pdf.remove_unreferenced_resources()
        output_stream = io.BytesIO()
        pdf.save(output_stream, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
        pdf.close()
        
        # Check result
        new_bytes = output_stream.getvalue()
        new_size = get_mb(new_bytes)
        
        # If we made progress, update current
        if new_size < current_size:
            current_pdf_bytes = new_bytes
            current_size = new_size
        else:
            # If this attempt didn't help (e.g. file size increased due to re-encoding or didn't drop), 
            # we might want to continue to the next more aggressive attempt instead of breaking.
            # Sometimes 1.0/80 increases size if original was highly compressed, but 0.8/70 might decrease it.
            pass
            
    return current_pdf_bytes
