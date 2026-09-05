from flask import Flask, render_template, request, redirect, url_for, send_from_directory, abort, session, jsonify, make_response, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import os
import re
import io
import zipfile
import shutil
import mimetypes
import markdown
import yaml
from datetime import datetime

app = Flask(__name__, template_folder='.')
app.secret_key = os.environ.get('SECRET_KEY', 'automind_secret_key_1298471298')

# Database URI configuration (SQLite locally, PostgreSQL in production)
database_url = os.environ.get('DATABASE_URL')
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///docs.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# File uploads directory configuration
UPLOAD_FOLDER = os.path.join(app.root_path, 'uploads')
SOFTWARE_FOLDER = os.path.join(UPLOAD_FOLDER, 'software')
DOCS_UPLOAD_FOLDER = os.path.join(UPLOAD_FOLDER, 'docs')
os.makedirs(SOFTWARE_FOLDER, exist_ok=True)
os.makedirs(DOCS_UPLOAD_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB max for software releases

db = SQLAlchemy(app)

# ============================================
#     DATABASE MODELS
# ============================================

class Rover(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    pages = db.relationship('DocPage', backref='rover', lazy=True, cascade="all, delete-orphan")

class DocPage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rover_id = db.Column(db.Integer, db.ForeignKey('rover.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), nullable=False)  # e.g. 'introduction' or 'getting-started/hardware-setup'
    content = db.Column(db.Text, nullable=False, default="")  # markdown content
    parent_id = db.Column(db.Integer, db.ForeignKey('doc_page.id', ondelete='SET NULL'), nullable=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    children = db.relationship('DocPage', backref=db.backref('parent', remote_side=[id]), lazy=True)

class DocImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class QuoteRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product = db.Column(db.String(150), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    company = db.Column(db.String(150), nullable=True)
    use_case = db.Column(db.String(100), nullable=True)
    quantity = db.Column(db.String(50), default="1 Unit")
    timeframe = db.Column(db.String(100), nullable=True)
    requirements = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default="Pending")  # Pending, Contacted, Completed, Archived
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Software(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(150), unique=True, nullable=False)
    version = db.Column(db.String(50), nullable=False, default="v1.0.0")
    category = db.Column(db.String(100), nullable=False, default="Ground Station & UI")
    platform = db.Column(db.String(100), nullable=False, default="Windows / Linux")
    description = db.Column(db.Text, nullable=True)
    changelog = db.Column(db.Text, nullable=True)
    system_requirements = db.Column(db.Text, nullable=True)
    file_filename = db.Column(db.String(255), nullable=True)
    file_display_name = db.Column(db.String(255), nullable=True)
    file_size_bytes = db.Column(db.BigInteger, default=0)
    file_type = db.Column(db.String(50), nullable=True)
    download_count = db.Column(db.Integer, default=0)
    is_published = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Ensure database tables are created
with app.app_context():
    db.create_all()

# ============================================
#     TEMPLATE FILTERS & HELPER FUNCTIONS
# ============================================

@app.template_filter('filesize')
def format_file_size(size_in_bytes):
    """Formats raw bytes into human readable KB, MB, GB."""
    if not size_in_bytes:
        return "0 B"
    try:
        size = float(size_in_bytes)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}" if unit != 'B' else f"{int(size)} B"
            size /= 1024.0
        return f"{size:.1f} TB"
    except Exception:
        return "0 B"

def is_docs_subdomain():
    """Detects if the request is targeting the docs subdomain."""
    host = request.host.lower()
    return host.startswith('docs.')

def get_base_url():
    """Builds correct base url depending on subdomain or subdirectory usage."""
    host = request.host
    if is_docs_subdomain():
        return f"http://{host}"
    else:
        return f"http://{host}/docs"

def build_nav_tree(pages):
    """Builds a recursive nested tree for the documentation sidebar."""
    pages_by_id = {p.id: {'page': p, 'children': []} for p in pages}
    roots = []
    
    for p in pages:
        p_dict = pages_by_id[p.id]
        if p.parent_id and p.parent_id in pages_by_id:
            pages_by_id[p.parent_id]['children'].append(p_dict)
        else:
            roots.append(p_dict)
            
    def sort_tree(nodes):
        nodes.sort(key=lambda x: (x['page'].order if x['page'].order is not None else 0, x['page'].title.lower()))
        for node in nodes:
            sort_tree(node['children'])
            
    sort_tree(roots)
    return roots

def render_markdown(text):
    """Converts Markdown text into beautiful HTML supporting MkDocs and standard extensions."""
    if not text:
        return ""
    
    extensions = [
        'fenced_code',
        'tables',
        'toc',
        'nl2br',
        'admonition',
        'attr_list',
        'def_list'
    ]
    
    extension_configs = {}
    
    try:
        import pymdownx
        extensions.extend([
            'pymdownx.superfences',
            'pymdownx.details',
            'pymdownx.tabbed',
            'pymdownx.highlight',
            'pymdownx.inlinehilite',
            'pymdownx.tasklist',
            'pymdownx.magiclink'
        ])
        extension_configs['pymdownx.superfences'] = {
            'custom_fences': [
                {
                    'name': 'mermaid',
                    'class': 'mermaid',
                    'format': lambda source, language, css_class, options, md, **kwargs: f'<div class="{css_class}">{source}</div>'
                }
            ]
        }
    except ImportError:
        pass
    
    md = markdown.Markdown(extensions=extensions, extension_configs=extension_configs)
    return md.convert(text)

# ============================================
#     MKDOCS SAFE PARSER & BULK IMPORTER
# ============================================

class SafeMkDocsLoader(yaml.SafeLoader):
    """Custom YAML loader that ignores Python custom tags found in standard MkDocs configs."""
    pass

SafeMkDocsLoader.add_multi_constructor('tag:yaml.org,2002:python/', lambda loader, suffix, node: None)
SafeMkDocsLoader.add_multi_constructor('!python/', lambda loader, suffix, node: None)
SafeMkDocsLoader.add_constructor(None, lambda loader, node: None)

def slugify(text):
    """Converts string into clean URL-friendly slug."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\/_-]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')

def extract_title_from_markdown(content, default_title="Untitled Page"):
    """Finds the first H1 header in markdown content or falls back to default title."""
    if not content:
        return default_title
    for line in content.splitlines():
        line = line.strip()
        if line.startswith('# '):
            return line[2:].strip()
    return default_title

def import_mkdocs_dataset(files_dict, target_rover_id=None, custom_name=None, custom_slug=None, custom_desc=None, overwrite=False):
    """
    Imports an MkDocs structure from a dictionary of relative_path -> content (str or bytes).
    Handles YAML parsing, hierarchy, parent-child links, ordering, images, and slug routing.
    """
    # 1. Normalize paths
    norm_files = {}
    for k, v in files_dict.items():
        clean_k = k.replace('\\', '/').lstrip('/')
        norm_files[clean_k] = v

    # 2. Find mkdocs.yml
    yaml_key = None
    for k in norm_files.keys():
        if k.endswith('mkdocs.yml') or k.endswith('mkdocs.yaml'):
            yaml_key = k
            break

    config = {}
    if yaml_key:
        raw_yaml = norm_files[yaml_key]
        if isinstance(raw_yaml, bytes):
            raw_yaml = raw_yaml.decode('utf-8', errors='ignore')
        try:
            config = yaml.load(raw_yaml, Loader=SafeMkDocsLoader) or {}
        except Exception as e:
            print(f"Warning: Failed to parse mkdocs.yml: {e}")
            config = {}

    site_name = custom_name or config.get('site_name') or "Automind Documentation"
    site_description = custom_desc or config.get('site_description') or ""
    nav_tree = config.get('nav', [])
    docs_dir = config.get('docs_dir', 'docs').strip('/')

    # 3. Determine or create Rover
    if target_rover_id:
        rover = db.session.get(Rover, target_rover_id)
        if not rover:
            raise ValueError("Target rover not found")
        if overwrite:
            DocPage.query.filter_by(rover_id=rover.id).delete()
    else:
        slug = custom_slug or slugify(site_name)
        if not slug:
            slug = "imported-docs"
        base_slug = slug
        counter = 1
        while Rover.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{counter}"
            counter += 1
        rover = Rover(name=site_name, slug=slug, description=site_description)
        db.session.add(rover)
        db.session.flush()

    # 4. Import images
    image_url_map = {}
    image_exts = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico')
    for k, v in norm_files.items():
        if any(k.lower().endswith(ext) for ext in image_exts):
            img_bytes = v if isinstance(v, bytes) else v.encode('utf-8')
            mime_type, _ = mimetypes.guess_type(k)
            mime_type = mime_type or 'image/png'
            filename = os.path.basename(k)
            
            doc_img = DocImage(filename=filename, mime_type=mime_type, data=img_bytes)
            db.session.add(doc_img)
            db.session.flush()
            
            img_url = url_for('serve_doc_image', image_id=doc_img.id)
            image_url_map[k] = img_url
            image_url_map[filename] = img_url
            if docs_dir and k.startswith(docs_dir + '/'):
                rel_to_docs = k[len(docs_dir)+1:]
                image_url_map[rel_to_docs] = img_url

    def read_file_content(path_in_docs):
        candidates = [
            path_in_docs,
            f"{docs_dir}/{path_in_docs}" if docs_dir else path_in_docs,
            f"docs/{path_in_docs}",
            path_in_docs.lstrip('/')
        ]
        for c in candidates:
            if c in norm_files:
                data = norm_files[c]
                if isinstance(data, bytes):
                    return data.decode('utf-8', errors='ignore')
                return data
        for k, v in norm_files.items():
            if k.endswith(path_in_docs):
                if isinstance(v, bytes):
                    return v.decode('utf-8', errors='ignore')
                return v
        return ""

    def replace_image_links(text):
        if not text or not image_url_map:
            return text
        for raw_path, new_url in image_url_map.items():
            text = re.sub(r'(!\[.*?\]\()(?:\.?\.?/)*' + re.escape(raw_path) + r'(\))', r'\1' + new_url + r'\2', text)
            text = re.sub(r'(<img.*?src=["\'])(?:\.?\.?/)*' + re.escape(raw_path) + r'(["\'])', r'\1' + new_url + r'\2', text)
        return text

    created_pages = []
    order_counter = [10]

    # 5. Process Nav Hierarchy
    if nav_tree:
        def process_nav_list(nav_items, parent_page=None):
            for item in nav_items:
                order_counter[0] += 10
                curr_order = order_counter[0]
                if isinstance(item, str):
                    raw_content = read_file_content(item)
                    title = extract_title_from_markdown(raw_content, os.path.splitext(os.path.basename(item))[0].replace('-', ' ').replace('_', ' ').title())
                    slug = slugify(item.replace('.md', ''))
                    content = replace_image_links(raw_content)
                    page = DocPage(
                        rover_id=rover.id,
                        title=title,
                        slug=slug,
                        content=content,
                        parent_id=parent_page.id if parent_page else None,
                        order=curr_order
                    )
                    db.session.add(page)
                    db.session.flush()
                    created_pages.append(page)
                elif isinstance(item, dict):
                    for k, v in item.items():
                        if isinstance(v, str):
                            raw_content = read_file_content(v)
                            title = k
                            slug = slugify(v.replace('.md', ''))
                            if not slug or slug == 'index':
                                slug = 'index' if not parent_page else slugify(f"{parent_page.slug}/{k}")
                            content = replace_image_links(raw_content)
                            page = DocPage(
                                rover_id=rover.id,
                                title=title,
                                slug=slug,
                                content=content,
                                parent_id=parent_page.id if parent_page else None,
                                order=curr_order
                            )
                            db.session.add(page)
                            db.session.flush()
                            created_pages.append(page)
                        elif isinstance(v, list):
                            sec_title = k
                            sec_slug = slugify(sec_title) if not parent_page else slugify(f"{parent_page.slug}/{sec_title}")
                            sec_content = read_file_content(f"{sec_slug}/index.md") or read_file_content(f"{sec_slug}.md") or f"# {sec_title}\n\nDocumentation overview for {sec_title}."
                            sec_content = replace_image_links(sec_content)
                            sec_page = DocPage(
                                rover_id=rover.id,
                                title=sec_title,
                                slug=sec_slug,
                                content=sec_content,
                                parent_id=parent_page.id if parent_page else None,
                                order=curr_order
                            )
                            db.session.add(sec_page)
                            db.session.flush()
                            created_pages.append(sec_page)
                            process_nav_list(v, parent_page=sec_page)

        process_nav_list(nav_tree)
    else:
        # Fallback: scan all .md files in the repository
        md_files = [k for k in sorted(norm_files.keys()) if k.endswith('.md')]
        parent_map = {}
        for mf in md_files:
            order_counter[0] += 10
            rel_path = mf[len(docs_dir)+1:] if docs_dir and mf.startswith(docs_dir + '/') else mf
            parts = rel_path.split('/')
            raw_content = read_file_content(mf)
            content = replace_image_links(raw_content)
            
            if len(parts) == 1:
                slug = slugify(parts[0].replace('.md', ''))
                title = extract_title_from_markdown(content, parts[0].replace('.md', '').replace('-', ' ').title())
                page = DocPage(rover_id=rover.id, title=title, slug=slug, content=content, parent_id=None, order=order_counter[0])
                db.session.add(page)
                db.session.flush()
                created_pages.append(page)
            else:
                dir_name = parts[0]
                if dir_name not in parent_map:
                    dir_title = dir_name.replace('-', ' ').replace('_', ' ').title()
                    dir_slug = slugify(dir_name)
                    dir_page = DocPage(rover_id=rover.id, title=dir_title, slug=dir_slug, content=f"# {dir_title}\n\nSection overview for {dir_title}.", parent_id=None, order=order_counter[0])
                    db.session.add(dir_page)
                    db.session.flush()
                    parent_map[dir_name] = dir_page
                    created_pages.append(dir_page)
                
                parent_page = parent_map[dir_name]
                slug = slugify(rel_path.replace('.md', ''))
                title = extract_title_from_markdown(content, parts[-1].replace('.md', '').replace('-', ' ').title())
                page = DocPage(rover_id=rover.id, title=title, slug=slug, content=content, parent_id=parent_page.id, order=order_counter[0])
                db.session.add(page)
                db.session.flush()
                created_pages.append(page)

    db.session.commit()
    return rover, len(created_pages)

# ============================================
#     MAIN WEBSITE ROUTING & CLEAN URLS
# ============================================

@app.route('/')
def home():
    if is_docs_subdomain():
        return render_docs_home()
    return render_template('index.html')

@app.route('/index.html')
def index_html():
    return redirect(url_for('home'), code=301)

# Clean & Extensionless URL Routes
@app.route('/products')
def products_page():
    return render_template('products/index.html')

@app.route('/services')
def services_page():
    return render_template('services/index.html')

@app.route('/news')
def news_page():
    return render_template('news/index.html')

@app.route('/about')
def about_page():
    return render_template('about/index.html')

@app.route('/quote')
@app.route('/quote.html')
@app.route('/request-quote')
def quote_page():
    product = request.args.get('product', '')
    return render_template('templates/quote.html', selected_product=product)

# ============================================
#     PUBLIC SOFTWARE PORTAL & DOWNLOADS
# ============================================

@app.route('/software')
@app.route('/softwares')
@app.route('/downloads')
@app.route('/software.html')
@app.route('/softwares.html')
def software_portal():
    category = request.args.get('category', '').strip()
    platform = request.args.get('platform', '').strip()
    search_q = request.args.get('q', '').strip()
    
    query = Software.query.filter_by(is_published=True)
    if category and category != 'All':
        query = query.filter(Software.category == category)
    if platform and platform != 'All':
        query = query.filter(Software.platform.ilike(f'%{platform}%'))
    if search_q:
        query = query.filter(
            (Software.name.ilike(f'%{search_q}%')) |
            (Software.description.ilike(f'%{search_q}%')) |
            (Software.category.ilike(f'%{search_q}%')) |
            (Software.platform.ilike(f'%{search_q}%'))
        )
    softwares = query.order_by(Software.created_at.desc()).all()
    
    # Get categories & platforms for filter buttons
    all_categories = [c[0] for c in db.session.query(Software.category).filter_by(is_published=True).distinct().all() if c[0]]
    if not all_categories:
        all_categories = ["Ground Station & UI", "Autonomous Navigation", "Mesh Radio & Telemetry", "ROS 2 & Drivers", "Firmware & SDKs"]
        
    return render_template('templates/software.html', 
                           softwares=softwares, 
                           selected_category=category or 'All',
                           selected_platform=platform or 'All',
                           search_query=search_q,
                           categories=all_categories)

@app.route('/download/software/<int:software_id>')
@app.route('/api/software/<int:software_id>/download')
def download_software(software_id):
    software = Software.query.get_or_404(software_id)
    if not software.file_filename:
        abort(404)
    file_path = os.path.join(SOFTWARE_FOLDER, software.file_filename)
    if not os.path.exists(file_path):
        abort(404)
    
    # Increment download count
    software.download_count = (software.download_count or 0) + 1
    db.session.commit()
    
    return send_from_directory(
        SOFTWARE_FOLDER,
        software.file_filename,
        as_attachment=True,
        download_name=software.file_display_name or software.file_filename
    )

@app.route('/api/request-quote', methods=['POST'])
def api_request_quote():
    try:
        if request.is_json:
            data = request.get_json() or {}
        else:
            data = request.form

        # 1. Honeypot check: silently accept but discard if hidden bot field is filled
        honeypot = data.get('b_website') or data.get('hp_company_field')
        if honeypot:
            return jsonify({'status': 'success', 'message': 'Your quote request has been submitted successfully!'}), 200

        product = data.get('product') or 'General Product Inquiry'
        full_name = (data.get('full_name') or '').strip()
        email = (data.get('email') or '').strip()
        phone = (data.get('phone') or '').strip()
        company = (data.get('company') or '').strip()
        use_case = (data.get('use_case') or '').strip()
        quantity = data.get('quantity', '1 Unit')
        timeframe = (data.get('timeframe') or '').strip()
        requirements = (data.get('requirements') or '').strip()

        if not full_name or not email or not product:
            return jsonify({'status': 'error', 'message': 'Full name, email, and product selection are required.'}), 400

        # 2. Input validation: legitimate names do not contain URLs, links, or bot markers
        spam_link_pattern = re.compile(r'https?://|www\.|\.org|\.net|\.com|graph\.org|linkspree|bitcoin|coinbase|>>|=>|№', re.IGNORECASE)
        if spam_link_pattern.search(full_name):
            return jsonify({'status': 'error', 'message': 'Invalid character sequence in name.'}), 400

        quote = QuoteRequest(
            product=product,
            full_name=full_name,
            email=email,
            phone=phone,
            company=company,
            use_case=use_case,
            quantity=quantity,
            timeframe=timeframe,
            requirements=requirements
        )
        db.session.add(quote)
        db.session.commit()

        if request.is_json:
            return jsonify({'status': 'success', 'message': 'Your quote request has been submitted successfully!'}), 200
        else:
            return render_template('templates/quote.html', success=True, quote=quote)

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Redirect legacy .html endpoints to clean extensionless endpoints
@app.route('/products.html')
def redirect_products():
    return redirect(url_for('products_page'), code=301)

@app.route('/services.html')
def redirect_services():
    return redirect(url_for('services_page'), code=301)

@app.route('/news.html')
def redirect_news():
    return redirect(url_for('news_page'), code=301)

@app.route('/about.html')
def redirect_about():
    return redirect(url_for('about_page'), code=301)

@app.route('/Templates/<path:filename>')
@app.route('/templates/<path:filename>')
def serve_templates(filename):
    clean_name = filename.replace('.html', '').lower()
    if clean_name in ['products', 'services', 'news', 'about', 'software']:
        return redirect(f'/{clean_name}', code=301)
    template_path = f'templates/{filename}'
    if not os.path.exists(template_path):
        if os.path.exists(filename):
            return render_template(filename)
        abort(404)
    return render_template(template_path)

@app.route('/mappingui.html')
@app.route('/mappingui')
def mapping_ui():
    return render_template('mappingui.html')

@app.route('/sensorfusionui.html')
@app.route('/sensorfusionui')
def sensor_fusion_ui():
    return render_template('sensorfusionui.html')

@app.route('/software_stack.html')
@app.route('/software_stack')
def software_stack():
    return render_template('software_stack.html')

# Favicon & SEO File Routers
@app.route('/favicon.ico')
def favicon():
    return send_from_directory('Assets/Images', 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/apple-touch-icon.png')
def apple_touch_icon():
    return send_from_directory('Assets/Images', 'apple-touch-icon.png', mimetype='image/png')

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('.', 'sitemap.xml', mimetype='application/xml')

@app.route('/robots.txt')
def robots():
    return send_from_directory('.', 'robots.txt', mimetype='text/plain')

# Static Asset Routers
@app.route('/Static/<path:filename>')
def serve_static(filename):
    return send_from_directory('Static', filename)

@app.route('/Assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory('Assets', filename)

@app.route('/components/<path:filename>')
def serve_components(filename):
    return send_from_directory('components', filename)

@app.route('/docs/image/<int:image_id>')
def serve_doc_image(image_id):
    img = DocImage.query.get_or_404(image_id)
    response = make_response(img.data)
    response.headers.set('Content-Type', img.mime_type)
    return response

# ============================================
#     ADMIN PANEL SECURITY & VIEWS
# ============================================

@app.before_request
def admin_auth_check():
    """Ensure routes under /admin require authentication (except login)."""
    if request.path.startswith('/admin') and request.path != '/admin/login':
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password')
        admin_pass = os.environ.get('ADMIN_PASSWORD', 'admin123')
        if password == admin_pass:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            error = "Invalid passcode"
    return render_template('templates/admin_login.html', error=error)

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('home'))

@app.route('/admin/')
def admin_dashboard():
    rovers = Rover.query.order_by(Rover.created_at.desc()).all()
    quotes = QuoteRequest.query.order_by(QuoteRequest.created_at.desc()).all()
    softwares = Software.query.order_by(Software.created_at.desc()).all()
    
    total_pages = DocPage.query.count()
    total_downloads = sum((s.download_count or 0) for s in softwares)
    pending_quotes = QuoteRequest.query.filter_by(status='Pending').count()
    
    # Analyze quotes for spam / phishing patterns
    spam_pattern = re.compile(r'https?://|www\.|\.org|\.net|\.com|graph\.org|linkspree|bitcoin|cloud-mining|coinbase|>>|=>|№', re.IGNORECASE)
    spam_quotes_count = 0
    for q in quotes:
        is_suspicious = False
        if (q.full_name and spam_pattern.search(q.full_name)) or \
           (q.company and spam_pattern.search(q.company)) or \
           (q.email and ('@uberip.com' in q.email or '@enalvpe.com' in q.email or '@enalype.com' in q.email)):
            is_suspicious = True
            spam_quotes_count += 1
        q.is_spam = is_suspicious
        
    rover_data = []
    for r in rovers:
        page_count = DocPage.query.filter_by(rover_id=r.id).count()
        rover_data.append({
            'rover': r,
            'page_count': page_count
        })
        
    stats = {
        'total_rovers': len(rovers),
        'total_pages': total_pages,
        'total_softwares': len(softwares),
        'total_downloads': total_downloads,
        'total_quotes': len(quotes),
        'pending_quotes': pending_quotes,
        'spam_quotes': spam_quotes_count
    }
    return render_template('templates/admin_dashboard.html', rovers=rover_data, quotes=quotes, softwares=softwares, stats=stats)

# ============================================
#     ADMIN SOFTWARE CRUD HANDLERS
# ============================================

@app.route('/admin/software/new', methods=['POST'])
def admin_software_new():
    name = request.form.get('name', '').strip()
    version = request.form.get('version', 'v1.0.0').strip()
    category = request.form.get('category', 'Ground Station & UI').strip()
    platform = request.form.get('platform', 'Windows / Linux').strip()
    description = request.form.get('description', '').strip()
    changelog = request.form.get('changelog', '').strip()
    system_requirements = request.form.get('system_requirements', '').strip()
    is_published = request.form.get('is_published') == '1' or request.form.get('is_published') == 'on' or 'is_published' not in request.form
    
    if not name:
        return "Software Name is required", 400
    
    slug = slugify(f"{name}-{version}")
    existing = Software.query.filter_by(slug=slug).first()
    if existing:
        slug = f"{slug}-{int(datetime.utcnow().timestamp())}"
        
    file_filename = None
    file_display_name = None
    file_size_bytes = 0
    file_type = None
    
    if 'software_file' in request.files:
        f = request.files['software_file']
        if f and f.filename:
            file_display_name = secure_filename(f.filename)
            file_type = os.path.splitext(file_display_name)[1].lower()
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            file_filename = f"{slug}_{timestamp}_{file_display_name}"
            saved_path = os.path.join(SOFTWARE_FOLDER, file_filename)
            f.save(saved_path)
            file_size_bytes = os.path.getsize(saved_path)
            
    software = Software(
        name=name,
        slug=slug,
        version=version,
        category=category,
        platform=platform,
        description=description,
        changelog=changelog,
        system_requirements=system_requirements,
        file_filename=file_filename,
        file_display_name=file_display_name or name,
        file_size_bytes=file_size_bytes,
        file_type=file_type,
        is_published=is_published
    )
    db.session.add(software)
    db.session.commit()
    return redirect(url_for('admin_dashboard') + '#softwares')

@app.route('/admin/software/<int:software_id>/edit', methods=['POST'])
def admin_software_edit(software_id):
    software = Software.query.get_or_404(software_id)
    software.name = request.form.get('name', software.name).strip()
    software.version = request.form.get('version', software.version).strip()
    software.category = request.form.get('category', software.category).strip()
    software.platform = request.form.get('platform', software.platform).strip()
    software.description = request.form.get('description', software.description).strip()
    software.changelog = request.form.get('changelog', software.changelog).strip()
    software.system_requirements = request.form.get('system_requirements', software.system_requirements).strip()
    software.is_published = request.form.get('is_published') == '1' or request.form.get('is_published') == 'on'
    
    if 'software_file' in request.files:
        f = request.files['software_file']
        if f and f.filename:
            if software.file_filename:
                old_path = os.path.join(SOFTWARE_FOLDER, software.file_filename)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass
            file_display_name = secure_filename(f.filename)
            software.file_type = os.path.splitext(file_display_name)[1].lower()
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            software.file_filename = f"{software.slug}_{timestamp}_{file_display_name}"
            software.file_display_name = file_display_name
            saved_path = os.path.join(SOFTWARE_FOLDER, software.file_filename)
            f.save(saved_path)
            software.file_size_bytes = os.path.getsize(saved_path)
            
    db.session.commit()
    return redirect(url_for('admin_dashboard') + '#softwares')

@app.route('/admin/software/<int:software_id>/delete', methods=['POST'])
def admin_software_delete(software_id):
    software = Software.query.get_or_404(software_id)
    if software.file_filename:
        file_path = os.path.join(SOFTWARE_FOLDER, software.file_filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
    db.session.delete(software)
    db.session.commit()
    return redirect(url_for('admin_dashboard') + '#softwares')

# ============================================
#     ADMIN ROVER & DOC BULK MKDOCS HANDLERS
# ============================================

@app.route('/admin/quote/<int:quote_id>/status', methods=['POST'])
def admin_quote_status(quote_id):
    quote = QuoteRequest.query.get_or_404(quote_id)
    new_status = request.form.get('status', 'Pending')
    quote.status = new_status
    db.session.commit()
    return redirect(url_for('admin_dashboard') + '#quotes')

@app.route('/admin/quote/<int:quote_id>/delete', methods=['POST'])
def admin_quote_delete(quote_id):
    quote = QuoteRequest.query.get_or_404(quote_id)
    db.session.delete(quote)
    db.session.commit()
    return redirect(url_for('admin_dashboard') + '#quotes')

@app.route('/admin/quotes/purge-spam', methods=['POST'])
def admin_quotes_purge_spam():
    spam_pattern = re.compile(r'https?://|www\.|\.org|\.net|\.com|graph\.org|linkspree|bitcoin|cloud-mining|coinbase|>>|=>|№', re.IGNORECASE)
    quotes = QuoteRequest.query.all()
    deleted_count = 0
    for q in quotes:
        if (q.full_name and spam_pattern.search(q.full_name)) or \
           (q.company and spam_pattern.search(q.company)) or \
           (q.email and ('@uberip.com' in q.email or '@enalvpe.com' in q.email or '@enalype.com' in q.email)):
            db.session.delete(q)
            deleted_count += 1
    db.session.commit()
    return redirect(url_for('admin_dashboard') + '#quotes')

@app.route('/admin/rover/new', methods=['POST'])
def admin_rover_new():
    name = request.form.get('name')
    slug = request.form.get('slug').strip().lower().replace(' ', '-')
    description = request.form.get('description')
    
    if not name or not slug:
        return "Name and slug are required", 400
        
    existing = Rover.query.filter_by(slug=slug).first()
    if existing:
        return "Rover with this slug already exists", 400
        
    rover = Rover(name=name, slug=slug, description=description)
    db.session.add(rover)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/rover/<int:rover_id>/edit', methods=['POST'])
def admin_rover_edit(rover_id):
    rover = Rover.query.get_or_404(rover_id)
    name = request.form.get('name')
    slug = request.form.get('slug').strip().lower().replace(' ', '-')
    description = request.form.get('description')
    
    if not name or not slug:
        return "Name and slug are required", 400
        
    existing = Rover.query.filter(Rover.slug == slug, Rover.id != rover_id).first()
    if existing:
        return "Rover with this slug already exists", 400
        
    rover.name = name
    rover.slug = slug
    rover.description = description
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/rover/<int:rover_id>/delete', methods=['POST'])
def admin_rover_delete(rover_id):
    rover = Rover.query.get_or_404(rover_id)
    db.session.delete(rover)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/rover/<int:rover_id>')
def admin_rover_view(rover_id):
    rover = Rover.query.get_or_404(rover_id)
    pages = DocPage.query.filter_by(rover_id=rover.id).order_by(DocPage.order, DocPage.title).all()
    nav_tree = build_nav_tree(pages)
    return render_template('templates/admin_rover.html', rover=rover, pages=pages, nav_tree=nav_tree)

# Single Page CRUD (Preserved)
@app.route('/admin/rover/<int:rover_id>/page/new', methods=['GET', 'POST'])
def admin_page_new(rover_id):
    rover = Rover.query.get_or_404(rover_id)
    if request.method == 'POST':
        title = request.form.get('title')
        slug = request.form.get('slug').strip().lower().replace(' ', '-')
        content = request.form.get('content', '')
        parent_id = request.form.get('parent_id')
        order = request.form.get('order', 0)
        
        parent_id = int(parent_id) if parent_id and parent_id.isdigit() else None
        order = int(order) if order and str(order).isdigit() else 0
        
        if not title or not slug:
            return "Title and slug are required", 400
            
        existing = DocPage.query.filter_by(rover_id=rover.id, slug=slug).first()
        if existing:
            return "Page with this slug already exists for this rover", 400
            
        page = DocPage(rover_id=rover.id, title=title, slug=slug, content=content, parent_id=parent_id, order=order)
        db.session.add(page)
        db.session.commit()
        return redirect(url_for('admin_rover_view', rover_id=rover.id))
        
    parent_pages = DocPage.query.filter_by(rover_id=rover.id, parent_id=None).all()
    return render_template('templates/admin_page_edit.html', rover=rover, page=None, parent_pages=parent_pages)

@app.route('/admin/page/<int:page_id>/edit', methods=['GET', 'POST'])
def admin_page_edit(page_id):
    page = DocPage.query.get_or_404(page_id)
    rover = db.session.get(Rover, page.rover_id)
    if request.method == 'POST':
        title = request.form.get('title')
        slug = request.form.get('slug').strip().lower().replace(' ', '-')
        content = request.form.get('content', '')
        parent_id = request.form.get('parent_id')
        order = request.form.get('order', 0)
        
        parent_id = int(parent_id) if parent_id and parent_id.isdigit() else None
        order = int(order) if order and str(order).isdigit() else 0
        
        if not title or not slug:
            return "Title and slug are required", 400
            
        existing = DocPage.query.filter(DocPage.rover_id == rover.id, DocPage.slug == slug, DocPage.id != page_id).first()
        if existing:
            return "Page with this slug already exists for this rover", 400
            
        if parent_id == page.id:
            parent_id = None
            
        page.title = title
        page.slug = slug
        page.content = content
        page.parent_id = parent_id
        page.order = order
        db.session.commit()
        return redirect(url_for('admin_rover_view', rover_id=rover.id))
        
    parent_pages = DocPage.query.filter(DocPage.rover_id == rover.id, DocPage.parent_id == None, DocPage.id != page.id).all()
    return render_template('templates/admin_page_edit.html', rover=rover, page=page, parent_pages=parent_pages)

@app.route('/admin/page/<int:page_id>/delete', methods=['POST'])
def admin_page_delete(page_id):
    page = DocPage.query.get_or_404(page_id)
    rover_id = page.rover_id
    db.session.delete(page)
    db.session.commit()
    return redirect(url_for('admin_rover_view', rover_id=rover_id))

# MKDocs Bulk Importer Handlers
@app.route('/admin/rover/sync-local-mkdocs', methods=['POST'])
def admin_rover_sync_local():
    """One-click importer for the workspace's local MKdocs folder."""
    local_mkdocs_path = os.path.join(app.root_path, 'MKdocs')
    if not os.path.exists(local_mkdocs_path):
        return jsonify({'success': False, 'message': 'MKdocs directory not found in workspace.'}), 404
        
    target_rover_id = request.form.get('rover_id')
    target_rover_id = int(target_rover_id) if target_rover_id and target_rover_id.isdigit() else None
    overwrite = request.form.get('overwrite') == '1' or request.form.get('overwrite') == 'true' or bool(target_rover_id)
    
    files_dict = {}
    for root, dirs, files in os.walk(local_mkdocs_path):
        for f in files:
            if f.startswith('.'):
                continue
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, local_mkdocs_path)
            with open(full_path, 'rb') as fp:
                files_dict[rel_path] = fp.read()
                
    try:
        rover, count = import_mkdocs_dataset(files_dict, target_rover_id=target_rover_id, overwrite=overwrite)
        return redirect(url_for('admin_rover_view', rover_id=rover.id))
    except Exception as e:
        return f"Local MKdocs Import failed: {str(e)}", 500

@app.route('/admin/rover/import-mkdocs', methods=['POST'])
def admin_rover_import_mkdocs():
    """Bulk import handler for MKDocs ZIP files or multi-file folder uploads."""
    target_rover_id = request.form.get('rover_id')
    target_rover_id = int(target_rover_id) if target_rover_id and target_rover_id.isdigit() else None
    overwrite = request.form.get('overwrite') == '1' or request.form.get('overwrite') == 'true' or request.form.get('overwrite') == 'on'
    custom_name = request.form.get('custom_name')
    custom_slug = request.form.get('custom_slug')
    
    files_dict = {}
    
    # 1. Process ZIP File
    if 'zip_file' in request.files and request.files['zip_file'].filename:
        zfile = request.files['zip_file']
        try:
            with zipfile.ZipFile(zfile.stream) as z:
                namelist = z.namelist()
                # Check for single common wrapper folder
                has_wrapper = False
                common_prefix = ""
                for name in namelist:
                    if name.endswith('mkdocs.yml') or name.endswith('mkdocs.yaml'):
                        parts = name.split('/')
                        if len(parts) > 1:
                            has_wrapper = True
                            common_prefix = parts[0] + '/'
                        break
                        
                for name in namelist:
                    if name.endswith('/') or '__MACOSX' in name or '/.' in name:
                        continue
                    clean_name = name
                    if has_wrapper and clean_name.startswith(common_prefix):
                        clean_name = clean_name[len(common_prefix):]
                    files_dict[clean_name] = z.read(name)
        except Exception as e:
            return f"Invalid ZIP file: {str(e)}", 400
            
    # 2. Process Multi-File Directory Upload
    elif 'folder_files' in request.files:
        uploaded_files = request.files.getlist('folder_files')
        # Check wrapper prefix
        prefix = ""
        for f in uploaded_files:
            if 'mkdocs.yml' in f.filename or 'mkdocs.yaml' in f.filename:
                parts = f.filename.replace('\\', '/').split('/')
                if len(parts) > 1:
                    prefix = parts[0] + '/'
                break
                
        for f in uploaded_files:
            if f.filename:
                clean_path = f.filename.replace('\\', '/')
                if prefix and clean_path.startswith(prefix):
                    clean_path = clean_path[len(prefix):]
                files_dict[clean_path] = f.read()
                
    if not files_dict:
        return "No documentation files received. Please upload a .zip archive or select a folder.", 400
        
    try:
        rover, count = import_mkdocs_dataset(
            files_dict, 
            target_rover_id=target_rover_id, 
            custom_name=custom_name, 
            custom_slug=custom_slug, 
            overwrite=overwrite
        )
        return redirect(url_for('admin_rover_view', rover_id=rover.id))
    except Exception as e:
        return f"MKDocs bulk import failed: {str(e)}", 500

# Admin AJAX Image Upload Handler
@app.route('/admin/upload-image', methods=['POST'])
def admin_upload_image():
    if 'image' not in request.files:
        return jsonify({'success': False, 'message': 'No image file found'}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400
        
    try:
        data = file.read()
        mime_type = file.mimetype or 'image/png'
        img = DocImage(filename=file.filename, mime_type=mime_type, data=data)
        db.session.add(img)
        db.session.commit()
        
        img_url = url_for('serve_doc_image', image_id=img.id)
        return jsonify({'success': True, 'url': img_url, 'filename': file.filename})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================
#     DOCUMENTATION VIEWER & SEARCH
# ============================================

def render_docs_home():
    """Renders the landing page for all documentation."""
    rovers = Rover.query.order_by(Rover.name).all()
    return render_template('templates/docs_home.html', rovers=rovers)

def render_docs_rover(rover_slug, page_path=None):
    """Renders the documentation system for a specific rover and page."""
    rover = Rover.query.filter_by(slug=rover_slug).first()
    if not rover:
        if is_docs_subdomain() and not rover_slug:
            return render_docs_home()
        abort(404)
        
    pages = DocPage.query.filter_by(rover_id=rover.id).order_by(DocPage.order, DocPage.title).all()
    
    if not pages:
        return render_template('templates/docs_view.html', 
                               rover=rover, 
                               current_page=None, 
                               content_html="<h2>Welcome to " + rover.name + " Documentation</h2><p>No documentation pages have been published yet. Please check back later or log in to the admin panel to add documentation.</p>",
                               nav_tree=[],
                               prev_page=None,
                               next_page=None,
                               is_subdomain=is_docs_subdomain())
                               
    nav_tree = build_nav_tree(pages)
    
    # If no path specified, default to first page
    if not page_path:
        first_page = pages[0]
        if is_docs_subdomain():
            return redirect(url_for('catch_all', subpath=f"{rover.slug}/{first_page.slug}"))
        else:
            return redirect(url_for('docs_page_sub', rover_slug=rover.slug, page_path=first_page.slug))
            
    # Find current page matching slug
    current_page = None
    for p in pages:
        if p.slug == page_path:
            current_page = p
            break
            
    if not current_page:
        abort(404)
        
    content_html = render_markdown(current_page.content)
    
    # Calculate prev/next navigation buttons
    prev_page = None
    next_page = None
    for i, p in enumerate(pages):
        if p.id == current_page.id:
            if i > 0:
                prev_page = pages[i-1]
            if i < len(pages) - 1:
                next_page = pages[i+1]
            break
            
    return render_template('templates/docs_view.html',
                           rover=rover,
                           current_page=current_page,
                           content_html=content_html,
                           nav_tree=nav_tree,
                           prev_page=prev_page,
                           next_page=next_page,
                           is_subdomain=is_docs_subdomain())

@app.route('/docs/<rover_slug>/search')
@app.route('/<rover_slug>/search')
def docs_search(rover_slug):
    """AJAX documentation search handler."""
    rover = Rover.query.filter_by(slug=rover_slug).first_or_404()
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
        
    results = DocPage.query.filter(
        DocPage.rover_id == rover.id,
        (DocPage.title.ilike(f'%{q}%')) | (DocPage.content.ilike(f'%{q}%'))
    ).order_by(DocPage.order, DocPage.title).all()
    
    is_sub = is_docs_subdomain()
    out = []
    for r in results:
        if is_sub:
            link = f"/{rover.slug}/{r.slug}"
        else:
            link = f"/docs/{rover.slug}/{r.slug}"
        out.append({
            'title': r.title,
            'link': link,
            'snippet': r.content[:120] + '...' if len(r.content) > 120 else r.content
        })
    return jsonify(out)

# Fallback Docs URL mappings
@app.route('/docs')
@app.route('/docs/')
def docs_home_sub():
    return render_docs_home()

@app.route('/docs/<rover_slug>')
@app.route('/docs/<rover_slug>/')
def docs_rover_sub(rover_slug):
    return render_docs_rover(rover_slug, None)

@app.route('/docs/<rover_slug>/<path:page_path>')
def docs_page_sub(rover_slug, page_path):
    return render_docs_rover(rover_slug, page_path)

# Subdomain / Catch-all routing handler
@app.route('/<path:subpath>')
def catch_all(subpath):
    if is_docs_subdomain():
        parts = subpath.strip('/').split('/', 1)
        rover_slug = parts[0]
        page_path = parts[1] if len(parts) > 1 else None
        return render_docs_rover(rover_slug, page_path)
    
    if os.path.exists(subpath) and not subpath.startswith('.') and not subpath.endswith('.py') and not subpath.endswith('.db'):
        return send_from_directory('.', subpath)
        
    abort(404)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=58055, debug=True)
