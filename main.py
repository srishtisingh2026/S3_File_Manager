import os
import re
from typing import List
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from supabase import create_client, Client
from dotenv import load_dotenv

# Load env vars
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Please set SUPABASE_URL and SUPABASE_KEY in environment or .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

# Static + templates
templates = Jinja2Templates(directory="templates")

# ------------ Helpers ------------
def list_bucket_objects(bucket_name: str) -> List[dict]:
    try:
        res = supabase.storage.from_(bucket_name).list()
        return res or []
    except Exception:
        return []

def remove_all_in_bucket(bucket_name: str) -> None:
    files = list_bucket_objects(bucket_name)
    names = [f["name"] for f in files if "name" in f]
    if names:
        supabase.storage.from_(bucket_name).remove(names)

def copy_or_move_files(src_bucket: str, files: List[str], dest_bucket: str, move: bool) -> str:
    if not dest_bucket:
        return "Destination bucket is required"

    for f in files:
        existing = supabase.storage.from_(dest_bucket).list()
        if any(obj["name"] == f for obj in existing):
            return f"File '{f}' already exists in destination bucket '{dest_bucket}'"

        data = supabase.storage.from_(src_bucket).download(f)
        if not data:
            return f"File '{f}' not found in source bucket '{src_bucket}'"

        supabase.storage.from_(dest_bucket).upload(f, data)
        if move:
            supabase.storage.from_(src_bucket).remove([f])

    return "Files moved successfully" if move else "Files copied successfully"

def valid_filename(filename: str) -> bool:
    return re.match(r'^[a-zA-Z0-9._-]+$', filename) is not None

def valid_bucket_name(name: str) -> bool:
    return re.match(r'^[a-z0-9-]+$', name) is not None

# ------------ Routes ------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request, success: str = None, error: str = None):
    buckets = supabase.storage.list_buckets()
    return templates.TemplateResponse(
        "index.html", {"request": request, "buckets": buckets, "success": success, "error": error}
    )

@app.get("/bucket/{bucket_name}", response_class=HTMLResponse)
def view_bucket(request: Request, bucket_name: str, success: str = None, error: str = None):
    files = list_bucket_objects(bucket_name)
    buckets = supabase.storage.list_buckets()
    return templates.TemplateResponse(
        "bucket.html",
        {"request": request, "bucket": bucket_name, "files": files, "buckets": buckets, "success": success, "error": error},
    )

@app.post("/create-bucket")
def create_bucket(bucket_name: str = Form(...)):
    if not valid_bucket_name(bucket_name):
        return RedirectResponse(
            "/?error=Invalid bucket name. Use only lowercase letters, numbers, and hyphens.",
            status_code=303,
        )

    try:
        supabase.storage.create_bucket(bucket_name)
        return RedirectResponse(
            f"/?success=Bucket '{bucket_name}' created successfully",
            status_code=303,
        )
    except Exception as e:
        error_msg = str(e)
        if "already exists" in error_msg.lower():
            return RedirectResponse(
                f"/?error=Bucket '{bucket_name}' already exists",
                status_code=303,
            )
        return RedirectResponse(
            f"/?error=Failed to create bucket: {error_msg}",
            status_code=303,
        )


@app.post("/delete-bucket")
def delete_bucket(bucket_name: str = Form(...), force: bool = Form(False)):
    files = list_bucket_objects(bucket_name)

    if files and not force:
        return HTMLResponse(
    f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Delete Bucket</title>
        <style>
            body {{
                font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
                background: #f4f7f9;
                margin: 0;
                padding: 40px;
                color: #333;
            }}
            .container {{
                max-width: 600px;
                margin: auto;
                background: #fff;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                text-align: center;
            }}
            h2 {{
                color: #e74c3c;
                margin-bottom: 20px;
            }}
            p {{
                margin: 20px 0;
            }}
            form {{
                display: inline-block;
                margin-top: 10px;
            }}
            button {{
                background: #e74c3c;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                cursor: pointer;
                font-size: 15px;
                transition: background 0.3s ease;
            }}
            button:hover {{
                background: #c0392b;
            }}
            .cancel {{
                display: inline-block;
                margin-left: 15px;
                padding: 10px 20px;
                border-radius: 6px;
                background: #bdc3c7;
                color: #2c3e50;
                text-decoration: none;
                transition: background 0.3s ease;
            }}
            .cancel:hover {{
                background: #95a5a6;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>⚠️ Bucket '{bucket_name}' is not empty</h2>
            <p>If you proceed, all files inside this bucket will be permanently deleted.</p>
            
            <form method="post" action="/delete-bucket">
                <input type="hidden" name="bucket_name" value="{bucket_name}">
                <input type="hidden" name="force" value="true">
                <button type="submit">Yes, Delete All</button>
            </form>
            <a href="/" class="cancel">Cancel</a>
        </div>
    </body>
    </html>
    """,
    status_code=200,
)


    if files:
        remove_all_in_bucket(bucket_name)

    try:
        supabase.storage.delete_bucket(bucket_name)
        return RedirectResponse(f"/?success=Bucket '{bucket_name}' deleted successfully", status_code=303)
    except Exception:
        return RedirectResponse(f"/?error=Failed to delete bucket '{bucket_name}'", status_code=303)

@app.post("/upload-file")
async def upload_file(bucket_name: str = Form(...), file: UploadFile = File(...)):
    content = await file.read()
    try:
        supabase.storage.from_(bucket_name).upload(file.filename, content)
        return RedirectResponse(f"/bucket/{bucket_name}?success=File '{file.filename}' uploaded successfully", status_code=303)
    except Exception:
        return RedirectResponse(f"/bucket/{bucket_name}?error=Failed to upload file '{file.filename}'", status_code=303)

@app.post("/delete-file")
def delete_file(bucket_name: str = Form(...), filename: str = Form(...)):
    try:
        supabase.storage.from_(bucket_name).remove([filename])
        return RedirectResponse(f"/bucket/{bucket_name}?success=File '{filename}' deleted successfully", status_code=303)
    except Exception:
        return RedirectResponse(f"/bucket/{bucket_name}?error=Failed to delete file '{filename}'", status_code=303)

@app.post("/file-action")
def file_action(
    src_bucket: str = Form(...),
    filename: str = Form(...),
    action: str = Form(...),
    dest_bucket: str = Form(None),
):
    if action == "delete":
        try:
            supabase.storage.from_(src_bucket).remove([filename])
            return RedirectResponse(f"/bucket/{src_bucket}?success=File '{filename}' deleted successfully", status_code=303)
        except Exception:
            return RedirectResponse(f"/bucket/{src_bucket}?error=Failed to delete file '{filename}'", status_code=303)

    elif action in ("copy", "move"):
        msg = copy_or_move_files(src_bucket, [filename], dest_bucket, move=(action == "move"))
        if "already exists" in msg or "required" in msg or "not found" in msg:
            return RedirectResponse(f"/bucket/{src_bucket}?error={msg}", status_code=303)
        return RedirectResponse(f"/bucket/{src_bucket}?success={msg}", status_code=303)

    return RedirectResponse(f"/bucket/{src_bucket}?error=Invalid action", status_code=303)
