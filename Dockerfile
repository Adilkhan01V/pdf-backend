# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Install Ghostscript (Crucial for PDF Compression)
RUN apt-get update && apt-get install -y \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Run app.py when the container launches
# Use shell form to allow variable expansion for $PORT (Render sets this dynamically)
CMD python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}