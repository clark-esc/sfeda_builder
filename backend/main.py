from fastapi import FastAPI, UploadFile, File, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import shutil
import uuid
import zipfile
import json
from pathlib import Path
import re
from PIL import Image, ImageDraw, ImageFont
from typing import List, Dict, Any

# Importers
# Removed top-level fitz import to prevent startup crashes. It is now imported on-demand inside functions.
from bs4 import BeautifulSoup

app = FastAPI(title="Detailing Aid Converter API")

app.add_middleware(
    CORSMiddleware,
    # Most permissive configuration to avoid CORS issues on error responses
    allow_origins=["*"],
    allow_credentials=False, 
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback
    error_msg = f"Unhandled error: {str(exc)}\n{traceback.format_exc()}"
    print(error_msg)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "error": str(exc)},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*"
        }
    )

STORAGE_DIR = Path("/app/storage") if os.path.exists("/app") else Path("storage")
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = STORAGE_DIR / "projects.json"
TEMPLATES_DIR = Path(__file__).parent / "templates"

# Load SFE Templates
def load_template(path, default=""):
    t_path = TEMPLATES_DIR / path
    if t_path.exists():
        with open(t_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
            print(f"DEBUG: Loaded template {path} ({len(content)} bytes)")
            return content
    print(f"WARNING: Template {path} not found at {t_path}")
    return default

# Load SFE Templates with safety
try:
    SFE_STYLE = load_template("css/style.css")
    SFE_CONTROL = load_template("js/control.js")
    SFE_JQUERY = load_template("js/jquery.min.js")
    SFE_TRACKING = load_template("js/tracking.js")
except Exception as e:
    print(f"CRITICAL: Failed to load core SFE templates: {e}")
    SFE_STYLE = SFE_CONTROL = SFE_JQUERY = SFE_TRACKING = ""

# Mount the storage directory so we can serve generated images
app.mount("/storage", StaticFiles(directory=STORAGE_DIR), name="storage")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    # Return 204 No Content to satisfy the browser without a file
    return Response(status_code=204)

@app.get("/")
def read_root():
    return {"status": "ok", "message": "DA Converter API is online on Port 8000."}

# DB Persistence
projects_db = {}

def save_db():
    try:
        # Convert Path objects to strings for JSON serialization
        serializable_db = {}
        for pid, data in projects_db.items():
            serializable_db[pid] = data.copy()
            if 'pages' in serializable_db[pid]:
                # Deep copy to avoid mutating the original
                serializable_db[pid]['pages'] = json.loads(json.dumps(data['pages']))
        
        with open(DB_FILE, "w") as f:
            json.dump(serializable_db, f, indent=4)
    except Exception as e:
        print(f"Error saving DB: {e}")

def load_db():
    global projects_db
    if DB_FILE.exists() and DB_FILE.stat().st_size > 0:
        try:
            with open(DB_FILE, "r") as f:
                content = f.read().strip()
                if not content:
                    projects_db = {}
                    return
                projects_db = json.loads(content)
                # Sanitize: Ensure hotspots and required fields exist for all pages
                for pid, data in projects_db.items():
                    if 'pages' in data:
                        for page in data['pages']:
                            if 'hotspots' not in page:
                                page['hotspots'] = []
                            # ... defaults
                            for key in ['video_top', 'video_left', 'video_width', 'video_height']:
                                if key not in page:
                                    page[key] = 0
        except Exception as e:
            print(f"Critical error loading DB: {e}")
            projects_db = {}
    else:
        projects_db = {}

# Initialize DB on start
load_db()

@app.get("/projects")
async def list_projects():
    summary = []
    for pid, data in projects_db.items():
        summary.append({
            "id": pid,
            "original_file": data.get("original_file"),
            "type": data.get("type"),
            "page_count": len(data.get("pages", [])),
            "timestamp": data.get("timestamp")
        })
    # Sort by timestamp descending
    summary.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return summary

@app.get("/project/{project_id}")
async def get_project(project_id: str):
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    return projects_db[project_id]

@app.put("/project/{project_id}")
async def update_project(project_id: str, payload: Dict[str, Any]):
    print(f"DEBUG: Update requested for {project_id}")
    if project_id not in projects_db:
        # Check if it's in the persisted file
        if DB_FILE.exists():
            with open(DB_FILE, "r") as f:
                temp_db = json.load(f)
                if project_id in temp_db:
                    projects_db[project_id] = temp_db[project_id]
        
        if project_id not in projects_db:
            raise HTTPException(status_code=404, detail="Project not found")
    
    # Merge payload defensively
    project = projects_db[project_id]
    for key, value in payload.items():
        project[key] = value
        
    save_db()
    return {"status": "ok", "project": project}

@app.delete("/project/{project_id}")
async def delete_project(project_id: str):
    if project_id in projects_db:
        # Optionally delete files too
        project_dir = STORAGE_DIR / project_id
        if project_dir.exists():
            shutil.rmtree(project_dir)
        del projects_db[project_id]
        save_db()
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Project not found")

def generate_filename(text: str, default: str, used_names: set) -> str:
    if not text:
        return default
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # Filter out common footers/headers
    valid_lines = [line for line in lines if len(line) > 3 and not any(skip in line.lower() for skip in ['www.', '.com', 'confidential', '©', 'http'])]
    
    if not valid_lines:
        return default
        
    first_line = valid_lines[0]
    cleaned = re.sub(r'[^A-Za-z0-9 ]+', '', first_line).title().replace(' ', '')
    if len(cleaned) < 3:
        return default
        
    base_name = cleaned[:25]
    final_name = f"{base_name}.html"
    counter = 2
    while final_name in used_names:
        final_name = f"{base_name}_{counter}.html"
        counter += 1
        
    used_names.add(final_name)
    return final_name

def create_dummy_slide(title: str, text: str, dest_path: str):
    img = Image.new('RGB', (1024, 768), color=(240, 240, 240))
    d = ImageDraw.Draw(img)
    try:
        # Try generic Linux/Mac paths or fallback to default
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", # Common on Linux
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",   # Mac
        ]
        font_large = None
        for path in font_paths:
            if os.path.exists(path):
                font_large = ImageFont.truetype(path, 40)
                font_small = ImageFont.truetype(path, 20)
                break
        
        if not font_large:
            font_large = ImageFont.load_default()
            font_small = font_large
    except IOError:
        font_large = ImageFont.load_default()
        font_small = font_large
        
    d.text((100, 100), title[:50] + ("..." if len(title) > 50 else ""), fill=(10,10,10), font=font_large)
    
    y = 180
    for line in text.split('\n')[:15]:
        d.text((100, y), line[:80] + ("..." if len(line) > 80 else ""), fill=(50,50,50), font=font_small)
        y += 30
        
    img.save(dest_path)

def get_base_html(image_filename, prev_filename="", next_filename="", video_filename="", v_top=10, v_left=10, v_width=80, v_height=80, hotspots=None, home_position='none', home_v="", arrow_v="", aspect_ratio=1.333, output_format='v9'):
    video_embed = ""
    if video_filename:
        # Put id directly on video for control.js play() call
        video_embed = f"""
            <video id="slideVid" src="./media/{video_filename}" autoplay loop playsinline muted style="position: absolute; top: {v_top}%; left: {v_left}%; width: {v_width}%; height: {v_height}%; z-index: 50; display: block;"></video>
        """
        
    def make_link(target, class_str="", style_str="", onclick_str="", text=""):
        c_attr = f' class="{class_str}"' if class_str else ""
        s_attr = f' style="{style_str}"' if style_str else ""
        o_attr = f' onclick="{onclick_str}"' if onclick_str else ""
        
        if target == "javascript:void(0)":
            return f'<a href="{target}"{c_attr}{s_attr}{o_attr}>{text}</a>'
            
        if output_format == 'sfe+':
            if onclick_str.startswith("location.href"):
                o_attr = f' onclick="event.stopPropagation();"'
            return f'<a data-next-file="{target}"{c_attr}{s_attr}{o_attr}>{text}</a>'
        else:
            if onclick_str.startswith("location.href"):
                return f'<a href="javascript:void(0)"{c_attr}{s_attr}{o_attr}>{text}</a>'
            return f'<a href="{target}"{c_attr}{s_attr}{o_attr}>{text}</a>'
    
    hotspot_html = ""
    menu_overlays = ""
    home_btn_html = ""
    
    if home_position != 'none':
        home_btn_html = make_link("index.html", class_str="global-home-btn", style_str=home_v)

    # SFE COMPLIANCE: Inject visual arrows if position is not 'none'
    arrow_html = ""
    # We use the same 'none' check as the nav-zone opacity rule
    # But here we are injecting the actual visual button elements
    if arrow_v and "top: 0; height: 100%" not in arrow_v: # If not the purely invisible tap-zone config
        if prev_filename and prev_filename != "javascript:void(0)":
            arrow_html += make_link(prev_filename, class_str="global-nav-arrow global-nav-prev", style_str=arrow_v)
        if next_filename and next_filename != "javascript:void(0)":
            arrow_html += make_link(next_filename, class_str="global-nav-arrow global-nav-next", style_str=arrow_v)

    if hotspots:
        for idx, h in enumerate(hotspots):
            h_top, h_left, h_width, h_height = h.get('top', 0), h.get('left', 0), h.get('width', 0), h.get('height', 0)
            h_type = str(h.get('type', '')).lower()
            # z-index 1000 to ensure it's above ALL other layers including safe-zone
            common_style = f"position: absolute; top: {h_top}%; left: {h_left}%; width: {h_width}%; height: {h_height}%; z-index: 1000;"
            
            if h_type == 'home':
                hotspot_html += make_link("index.html", style_str=common_style)
            elif h_type == 'nav':
                target = h.get('target', '#')
                if not target.endswith('.html') and target != '#': target = f"{target}.html"
                hotspot_html += make_link(target, style_str=common_style)
            elif 'menu' in h_type or 'popup' in h_type:
                menu_id = f"custom-menu-{idx}"
                hotspot_html += f'<a href="javascript:void(0)" onclick="toggleMenu(\'{menu_id}\')" style="{common_style}"></a>'
                items_html = ""
                for item in h.get('menuItems', []):
                    target = item.get("target", "#")
                    if not target.endswith('.html') and target != '#': target = f"{target}.html"
                    # SFE COMPLIANCE: Use location.href redirection for absolute reliability in SFE webviews
                    onclick_val = f"location.href='{target}'; event.stopPropagation();"
                    items_html += f'<li>{make_link(target, onclick_str=onclick_val, text=item.get("label", "Link"))}</li>'
                menu_overlays += f"""
                <div id="{menu_id}" class="popup-menu-overlay" onclick="toggleMenu('{menu_id}')">
                    <div class="popup-menu-content" onclick="event.stopPropagation()">
                        <ul>{items_html}</ul>
                        <button class="close-menu" onclick="toggleMenu('{menu_id}')">Close</button>
                    </div>
                </div>
                """

    html_template = """<!DOCTYPE html>
<html>
    <head>
        <title>Detailing Aid Slide</title>
        <style>
[[STYLE]]
            #aspect-ratio-container {
                aspect-ratio: [[RATIO]];
                width: 100%;
                /* Total Visibility: 94vh + 5px padding ensures no edge clipping EVER */
                max-width: calc(94vh * [[RATIO]]);
                max-height: 94vh;
                margin: auto;
                position: relative;
                overflow: visible;
                padding: 5px; /* Safety buffer inside the container */
                background: #000;
            }
        </style>
        <script type="text/javascript">
[[JQUERY]]
        </script>
        <script type="text/javascript">
[[TRACKING_SCRIPT]]
        </script>
    </head>
    <body>
        <div id="gameContainer">
            <div id="aspect-ratio-container">
                <div id="slideCover">
                    <img src="./images/[[IMAGE]]" data-next-file="[[NEXT]]" data-previous-file="[[PREV]]"/>
                    [[NAV_ZONE_LEFT]]
                    [[NAV_ZONE_RIGHT]]
                    [[VIDEO_EMBED]]
                    [[HOTSPOT_HTML]]
                    [[HOME_BTN_HTML]]
                    [[ARROW_HTML]]
                </div>
                <div class="sfe-safe-zone"></div>
            </div>
            [[MENU_OVERLAYS]]
        </div>
        <script type="text/javascript">
[[CONTROL]]
        </script>
    </body>
</html>"""

    html = html_template.replace("[[STYLE]]", SFE_STYLE)
    html = html.replace("[[JQUERY]]", SFE_JQUERY)
    html = html.replace("[[TRACKING_SCRIPT]]", SFE_TRACKING)
    html = html.replace("[[CONTROL]]", SFE_CONTROL)
    html = html.replace("[[IMAGE]]", image_filename)
    html = html.replace("[[NEXT]]", next_filename if next_filename else "javascript:void(0)")
    html = html.replace("[[PREV]]", prev_filename if prev_filename else "javascript:void(0)")
    html = html.replace("[[VIDEO_EMBED]]", video_embed)
    html = html.replace("[[HOTSPOT_HTML]]", hotspot_html)
    html = html.replace("[[HOME_BTN_HTML]]", home_btn_html)
    html = html.replace("[[ARROW_HTML]]", arrow_html)
    html = html.replace("[[MENU_OVERLAYS]]", menu_overlays)
    html = html.replace("[[RATIO]]", str(aspect_ratio))
    
    if output_format == 'sfe+':
        html = html.replace('src="./images/', 'src="images/')
        html = html.replace('src="./media/', 'src="media/')
        
    return html

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    import fitz # Lazy import to prevent startup crash
    print(f"DEBUG: Starting upload for file: {file.filename}")
    try:
        project_id = str(uuid.uuid4())
        project_dir = STORAGE_DIR / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        print(f"DEBUG: Created project directory: {project_dir}")
        
        file_path = project_dir / file.filename
        print(f"DEBUG: Saving file to: {file_path}")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        print(f"DEBUG: File saved successfully")
        
        pages = []
        used_names = {"index.html"}  # Reserve index.html so it's never auto-suggested
        
        if file.filename.lower().endswith(".pdf"):
            # Convert PDF to images
            doc = fitz.open(str(file_path))
            images_dir = project_dir / "images"
            images_dir.mkdir(exist_ok=True)
            html_dir = project_dir / "slides"
            html_dir.mkdir(exist_ok=True)
            
            for i in range(len(doc)):
                page = doc.load_page(i)
                # SFE COMPLIANCE: Force use of MediaBox to prevent cropping of footer buttons
                # This ensures that buttons at the very bottom edge are captured.
                page.set_cropbox(page.mediabox)
                
                # Default PDF width may be small, increase resolution for sharp buttons
                zoom = 3 # Increased to 3 (300dpi approx) for better small text clarity
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                image_name = f"slide_{i+1}.png"
                pix.save(str(images_dir / image_name))
                
                # Extract text to generate a smart name
                text = page.get_text()
                suggested_name = generate_filename(text, f"slide_{i+1}.html", used_names)
                
                pages.append({"id": f"slide_{i+1}", "html_name": suggested_name, "image_name": image_name})
                
        elif file.filename.lower().endswith(".pptx"):
            raise HTTPException(
                status_code=400,
                detail="PPTX files are not supported. Please convert your PPTX to PDF first, then upload the PDF."
            )

        elif file.filename.lower().endswith(".zip"):
            # Sanitize HTML logic
            with zipfile.ZipFile(file_path, "r") as zip_ref:
                zip_ref.extractall(project_dir / "extracted")
            
            # Traverse and sanitize
            extracted_dir = project_dir / "extracted"
            for root, dirs, files in os.walk(extracted_dir):
                for name in files:
                    if name.endswith(".html"):
                        html_file = os.path.join(root, name)
                        with open(html_file, 'r', encoding='utf-8', errors='replace') as f:
                            soup = BeautifulSoup(f, 'html.parser')
                            
                        # Sanitize Links and try to extract title for suggestion
                        title_text = ""
                        if soup.title and soup.title.string:
                            title_text = soup.title.string
                        elif soup.h1 and soup.h1.string:
                            title_text = soup.h1.string

                        for a in soup.find_all('a'):
                            href = a.get('href', '')
                            if href.startswith('http://') or href.startswith('https://'):
                                a['href'] = '#' # Or remove the link entirely
                                
                        # Remove body onload
                        if soup.body and soup.body.has_attr('onload'):
                            del soup.body['onload']
                            
                        # Remove <script> with src pointing to external
                        for script in soup.find_all('script'):
                            if script.get('src', '').startswith(('http://', 'https://')):
                                script.decompose()
                                
                        with open(html_file, 'w', encoding='utf-8', errors='replace') as f:
                            f.write(str(soup))
                            
                        suggested_name = generate_filename(title_text, name, used_names)
                        pages.append({"id": name, "html_name": suggested_name, "image_name": ""})
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format.")
        
    except Exception as e:
        import traceback
        print(f"ERROR in upload_file: {str(e)}")
        print(traceback.format_exc())
        raise e
        
    import datetime
    projects_db[project_id] = {
        "id": project_id,
        "pages": pages, 
        "original_file": file.filename, 
        "type": file.filename.split('.')[-1].lower(),
        "timestamp": datetime.datetime.now().isoformat()
    }
    save_db()
    
    return {"project_id": project_id, "pages": pages}

@app.post("/project/{project_id}/media/{slide_id}")
async def upload_slide_media(project_id: str, slide_id: str, file: UploadFile = File(...)):
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
        
    project = projects_db[project_id]
    media_dir = STORAGE_DIR / project_id / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = media_dir / file.filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    for page in project['pages']:
        if page['id'] == slide_id:
            page['video_name'] = file.filename
            break
    save_db()
            
    return {"status": "success", "video_name": file.filename}

@app.post("/generate/{project_id}")
async def generate_project(project_id: str, body: Dict[str, Any]):
    new_pages = body.get('pages', [])
    nav_arrows_position = body.get('nav_arrows_position', 'bottom')
    home_position = body.get('home_position', 'top')
    output_format = body.get('output_format', 'v9')
    # User provides renamed pages: [{"id": "slide_1", "new_html_name": "ProductBenefits.html"}]
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
        
    project = projects_db[project_id]
    project_dir = STORAGE_DIR / project_id
    output_zip = project_dir / "output.zip"
    
    try:
        # We will zip files in a particular folder structure.
        # First create a build dir.
        build_dir = project_dir / "build"
        # Clear old build if exists
        if build_dir.exists():
            shutil.rmtree(build_dir)
            
        build_dir.mkdir(exist_ok=True)
        images_build_dir = build_dir / "images"
        images_build_dir.mkdir(exist_ok=True)
        media_build_dir = build_dir / "media"
        media_build_dir.mkdir(exist_ok=True)
            # Build nav arrow CSS (vertical position)
        # Parse home position
        home_pos_str = str(home_position or 'top-right').lower()
        home_side = 'right' if 'right' in home_pos_str else 'left'
        
        if 'top' in home_pos_str:
            home_y_val = "top: 2%;"
            home_transform = "none"
        elif 'middle' in home_pos_str:
            home_y_val = "top: 50%;"
            home_transform = "translateY(-50%)"
        elif 'bottom' in home_pos_str:
            home_y_val = "bottom: 2%;"
            home_transform = "none"
        else: # none
            home_y_val = "display: none;"
            home_transform = "none"
        
        home_v = f"{home_y_val} {home_side}: 2%; transform: {home_transform};"
        
        _arrow_v_map = {
            'top':    'top: 2%; transform: none;',
            'middle': 'top: 50%; transform: translateY(-50%);',
            'bottom': 'bottom: 2%; transform: none;',
            'none':   'top: 0; height: 100%; width: 15%; opacity: 0; transition: none;',
        }
        arrow_v = _arrow_v_map.get(nav_arrows_position, _arrow_v_map['bottom'])

        # Added CamelCase naming enforcement and removed separate JS/CSS folder creation
            
        project_type = project.get('type', '').lower()
        if project_type in ['pdf']:
            # Rename logic and building HTML
            # Convert new_pages list to a map dict
            rename_map = {p['id']: p.get('new_html_name', p.get('html_name')) for p in new_pages}
            frontend_state_map = {p['id']: p for p in new_pages}
            
            # CONTEXT: Selective build logic. 
            # We iterate over new_pages (the selection) instead of all project pages.
            for i, page_config in enumerate(new_pages):
                page_id = page_config['id']
                # find the original page data
                page = next((p for p in project['pages'] if p['id'] == page_id), None)
                if not page: continue

                new_html_name = rename_map.get(page_id, page.get('html_name'))
                image_name = page['image_name']
                
                # Copy assets only for selected slides
                src_image = project_dir / "images" / image_name
                if src_image.exists():
                    shutil.copy(src_image, images_build_dir / image_name)
                
                # Dynamic next/prev naming within the selection subset
                prev_html_name = "javascript:void(0)"
                if i > 0:
                    prev_id = new_pages[i-1]['id']
                    prev_html_name = rename_map.get(prev_id, "")
                    
                next_html_name = "javascript:void(0)"
                if i < len(new_pages) - 1:
                    next_id = new_pages[i+1]['id']
                    next_html_name = rename_map.get(next_id, "")
                    
                # Grab interaction hotspots from the payload config
                frontend_page = page_config
                v_top = frontend_page.get('video_top', 10)
                v_left = frontend_page.get('video_left', 10)
                v_width = frontend_page.get('video_width', 80)
                v_height = frontend_page.get('video_height', 80)
                video_name = page.get('video_name', '')
                if video_name:
                    src_video = project_dir / "media" / video_name
                    if src_video.exists():
                        shutil.copy(src_video, media_build_dir / video_name)
                        
                # SFE COMPLIANCE: Rewrite hotspot targets using the rename_map
                processed_hotspots = []
                first_slide_id = project['pages'][0]['id'] if project['pages'] else None
                
                # Check for hotspots in the payload
                raw_hotspots = frontend_page.get('hotspots', [])
                for h in raw_hotspots:
                    h_copy = h.copy()
                    t_type = str(h_copy.get('type', '')).lower()
                    target = h_copy.get('target', '')
                    
                    # Resolve Target
                    if t_type == 'home' or target == first_slide_id:
                        h_copy['target'] = "index.html"
                    elif target in rename_map:
                        h_copy['target'] = rename_map[target]
                    else:
                        if not target.endswith('.html') and target and target != '#':
                            h_copy['target'] = f"{target}.html"
                    
                    # Handle Menu Items - Defensive check for multiple naming conventions
                    menu_items = h_copy.get('menuItems', h_copy.get('items', []))
                    if menu_items:
                        h_copy['menuItems'] = [] # Normalize
                        for item in menu_items:
                            i_copy = item.copy()
                            i_target = i_copy.get('target', '')
                            if i_target == first_slide_id:
                                i_copy['target'] = "index.html"
                            elif i_target in rename_map:
                                i_copy['target'] = rename_map[i_target]
                            h_copy['menuItems'].append(i_copy)
                    
                    processed_hotspots.append(h_copy)
                
                print(f"DEBUG: Generating {new_html_name} with {len(processed_hotspots)} hotspots")
                
                # SFE COMPLIANCE: Calculate aspect ratio for precision lock
                aspect_ratio = 1.333 # Fallback
                try:
                    with Image.open(src_image) as img_ref:
                        w, h = img_ref.size
                        aspect_ratio = round(w / h, 4)
                except Exception as e:
                    print(f"WARNING: Could not read image size for {image_name}: {e}")

                html_content = get_base_html(image_filename=image_name, 
                                            prev_filename=prev_html_name, 
                                            next_filename=next_html_name, 
                                            video_filename=video_name, 
                                            v_top=v_top, v_left=v_left, v_width=v_width, v_height=v_height, 
                                            hotspots=processed_hotspots, 
                                            home_position=home_position,
                                            home_v=home_v,
                                            arrow_v=arrow_v,
                                            aspect_ratio=aspect_ratio,
                                            output_format=output_format)
                
                with open(build_dir / new_html_name, "w") as f:
                    f.write(html_content)
                    
        elif project_type in ['zip']:
            # For ZIP, rename files in the extracted directory
            # This is a bit more complex (refs need rewriting).
            # We will just copy the extracted items and rename the requested files.
            extracted_dir = project_dir / "extracted"
            shutil.copytree(extracted_dir, build_dir, dirs_exist_ok=True)
            rename_map = {p['id']: p.get('new_html_name', p.get('html_name')) for p in new_pages}
            
            for root, dirs, files in os.walk(build_dir):
                for name in files:
                    if name in rename_map and rename_map[name] != name:
                        os.rename(os.path.join(root, name), os.path.join(root, rename_map[name]))
                        
            # Update references in all HTML using BS4. This is a naive implementation but works for simple simulation.
            for root, dirs, files in os.walk(build_dir):
                for name in files:
                    if name.endswith(".html"):
                        html_file = os.path.join(root, name)
                        with open(html_file, 'r', encoding='utf-8', errors='replace') as f:
                            soup = BeautifulSoup(f, 'html.parser')
                        for a in soup.find_all('a'):
                            href = a.get('href', '')
                            if href in rename_map:
                                a['href'] = rename_map[href]
                        with open(html_file, 'w', encoding='utf-8', errors='replace') as f:
                            f.write(str(soup))

        # ZIP it up (Handles both PDF and ZIP source types)
        shutil.make_archive(str(project_dir / "output"), 'zip', build_dir)
        
        # Persist the updated hotspots/state
        projects_db[project_id]['pages'] = new_pages
        projects_db[project_id]['nav_arrows_position'] = nav_arrows_position
        projects_db[project_id]['home_position'] = home_position
        projects_db[project_id]['output_format'] = output_format
        save_db()

        return {"download_url": f"/download/{project_id}"}

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


@app.get("/download/{project_id}")
async def download_project(project_id: str):
    project_dir = STORAGE_DIR / project_id
    output_zip = project_dir / "output.zip"
    if not output_zip.exists():
        raise HTTPException(status_code=404, detail="Archive not found.")
        
    project = projects_db.get(project_id)
    if project and project.get('original_file'):
        # Strip extension, add .zip, and replace spaces with underscores
        base_name = project['original_file'].rsplit('.', 1)[0]
        base_name = base_name.replace(' ', '_')
        download_name = f"{base_name}.zip"
    else:
        download_name = f"conversion_{project_id}.zip"
        
    return FileResponse(output_zip, media_type="application/zip", filename=download_name)

if __name__ == "__main__":
    import uvicorn
    # Use the port assigned by Railway
    port = int(os.environ.get("PORT", 8080))
    # Disable reload for production stability
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
