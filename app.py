from flask import Flask, render_template, request, redirect, url_for, send_from_directory, abort, session, jsonify, make_response, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re
import io
import zipfile
import shutil
import mimetypes
import markdown
import yaml
import base64
import requests
import threading
import time
from datetime import datetime, timedelta

try:
    from xhtml2pdf import pisa
except ImportError:
    pisa = None

app = Flask(__name__, template_folder='.')
app.secret_key = os.environ.get('SECRET_KEY', 'automind_secret_key_1298471298')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

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
    is_visible = db.Column(db.Boolean, default=True, nullable=False)
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

class AdminSetting(db.Model):
    __tablename__ = 'admin_setting'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

def get_admin_setting(key, default=None):
    """Retrieve persistent admin or integration setting."""
    try:
        setting = AdminSetting.query.filter_by(key=key).first()
        if setting and setting.value is not None:
            return setting.value
        return default
    except Exception:
        db.session.rollback()
        return default

def set_admin_setting(key, value):
    """Save persistent admin or integration setting."""
    try:
        setting = AdminSetting.query.filter_by(key=key).first()
        if not setting:
            setting = AdminSetting(key=key, value=value)
            db.session.add(setting)
        else:
            setting.value = value
            setting.updated_at = datetime.utcnow()
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"Error saving admin setting '{key}': {e}")
        return False

def verify_admin_password(candidate_password):
    """
    Cryptographically verifies candidate password against stored secure salted hash.
    Falls back to environment variable ADMIN_PASSWORD or 'admin123' if not yet customized.
    """
    if not candidate_password:
        return False
    stored_hash = get_admin_setting('admin_password_hash')
    if stored_hash:
        return check_password_hash(stored_hash, candidate_password)
    
    # Fallback to env variable or default if user hasn't changed it yet
    env_pass = os.environ.get('ADMIN_PASSWORD', 'admin123')
    return candidate_password == env_pass

def is_using_default_password():
    stored_hash = get_admin_setting('admin_password_hash')
    return stored_hash is None

def send_resend_quote_alert(quote_data, is_test=False):
    """
    Sends an immediate HTML email notification for quote inquiries via Resend API.
    Handles sandbox onboarding@resend.dev and verified custom domains automatically.
    """
    with app.app_context():
        # Check if email notifications are enabled
        enabled = get_admin_setting('resend_enabled', 'true')
        if enabled == 'false' and not is_test:
            return False, "Email alerts are disabled in settings."

        api_key = get_admin_setting('resend_api_key') or os.environ.get('RESEND_API_KEY')
        if not api_key:
            print("[Resend Notice] No RESEND_API_KEY configured. Quote saved to database without email alert.")
            return False, "No Resend API Key configured. Please enter your API key in Tech Console."

        api_key = api_key.strip()
        alert_recipient = get_admin_setting('resend_alert_email') or os.environ.get('ADMIN_ALERT_EMAIL', 'info@autominddynamics.com')
        alert_recipient = alert_recipient.strip()
        
        from_email = get_admin_setting('resend_from_email') or os.environ.get('RESEND_FROM_EMAIL', 'AutoMind Dynamics <onboarding@resend.dev>')
        from_email = from_email.strip()
        
        # Clean fallback for Resend testing domain
        if 'resend.dev' in from_email and '<' not in from_email:
            from_email = f"AutoMind Alerts <{from_email}>"

        subject_prefix = "[TEST ALERT] " if is_test else "🚀 New Quote Inquiry: "
        product_name = quote_data.get('product') or 'Robotics System Inquiry'
        customer_name = quote_data.get('full_name') or 'Prospective Client'
        subject = f"{subject_prefix}{product_name} - {customer_name}"
        
        phone_val = quote_data.get('phone') or ''
        phone_html = f"<a href='tel:{phone_val}' style='color:#60a5fa;'>{phone_val}</a>" if phone_val else "<span style='color:#64748b;'>Not provided</span>"
        
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>{subject}</title>
          <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #06070a; color: #e2e8f0; margin: 0; padding: 24px 12px; }}
            .email-container {{ max-width: 600px; margin: 0 auto; background: #0e1017; border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 14px; overflow: hidden; box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6); }}
            .header {{ background: linear-gradient(135deg, #111827 0%, #030712 100%); border-bottom: 2px solid #3b82f6; padding: 24px 28px; text-align: left; }}
            .header h1 {{ margin: 0; font-size: 19px; color: #ffffff; letter-spacing: 0.04em; text-transform: uppercase; font-weight: 800; }}
            .header p {{ margin: 5px 0 0 0; color: #94a3b8; font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; }}
            .content {{ padding: 28px; }}
            .status-chip {{ display: inline-block; padding: 4px 10px; border-radius: 99px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; background: {'rgba(16, 185, 129, 0.15)' if is_test else 'rgba(59, 130, 246, 0.15)'}; color: {'#34d399' if is_test else '#60a5fa'}; border: 1px solid {'rgba(16, 185, 129, 0.35)' if is_test else 'rgba(59, 130, 246, 0.35)'}; margin-bottom: 16px; }}
            .headline {{ font-size: 20px; font-weight: 700; color: #ffffff; margin-bottom: 22px; line-height: 1.35; }}
            .data-card {{ background: #141722; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 10px; padding: 18px; margin-bottom: 22px; }}
            .data-row {{ display: flex; justify-content: space-between; padding: 9px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.05); font-size: 13.5px; }}
            .data-row:last-child {{ border-bottom: none; }}
            .label {{ color: #94a3b8; font-weight: 500; min-width: 130px; }}
            .value {{ color: #ffffff; font-weight: 600; text-align: right; word-break: break-word; }}
            .value a {{ color: #60a5fa; text-decoration: none; }}
            .req-title {{ font-size: 12px; font-weight: 700; text-transform: uppercase; color: #94a3b8; margin-bottom: 8px; letter-spacing: 0.06em; }}
            .req-box {{ background: #141722; border-left: 3px solid #3b82f6; border-radius: 0 8px 8px 0; padding: 14px 16px; font-size: 13.5px; line-height: 1.55; color: #cbd5e1; margin-bottom: 26px; }}
            .btn-wrapper {{ text-align: center; margin: 30px 0 10px 0; }}
            .btn-action {{ display: inline-block; background: #3b82f6; color: #ffffff !important; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 13.5px; letter-spacing: 0.02em; box-shadow: 0 4px 20px rgba(59, 130, 246, 0.4); text-transform: uppercase; }}
            .footer {{ background: #07080c; padding: 18px 24px; border-top: 1px solid rgba(255, 255, 255, 0.06); text-align: center; font-size: 11.5px; color: #64748b; line-height: 1.6; }}
          </style>
        </head>
        <body>
          <div class="email-container">
            <div class="header">
              <h1>AUTOMIND DYNAMICS</h1>
              <p>Autonomous Ground Robotics & Defense Tele-Operations</p>
            </div>
            <div class="content">
              <div class="status-chip">{'VERIFICATION TEST' if is_test else 'NEW INBOUND QUOTE'}</div>
              <div class="headline">New Quote Request: {product_name}</div>
              
              <div class="data-card">
                <div class="data-row">
                  <span class="label">Customer Name:</span>
                  <span class="value">{customer_name}</span>
                </div>
                <div class="data-row">
                  <span class="label">Email:</span>
                  <span class="value"><a href="mailto:{quote_data.get('email')}">{quote_data.get('email')}</a></span>
                </div>
                <div class="data-row">
                  <span class="label">Phone:</span>
                  <span class="value">{phone_html}</span>
                </div>
                <div class="data-row">
                  <span class="label">Company / Org:</span>
                  <span class="value">{quote_data.get('company') or 'Individual Client'}</span>
                </div>
                <div class="data-row">
                  <span class="label">Target Product:</span>
                  <span class="value" style="color: #60a5fa;">{product_name}</span>
                </div>
                <div class="data-row">
                  <span class="label">Volume / Units:</span>
                  <span class="value">{quote_data.get('quantity', '1 Unit')}</span>
                </div>
                <div class="data-row">
                  <span class="label">Project Timeline:</span>
                  <span class="value">{quote_data.get('timeframe') or 'Standard Timeline'}</span>
                </div>
                <div class="data-row">
                  <span class="label">Target Use Case:</span>
                  <span class="value">{quote_data.get('use_case') or 'Industrial / Robotics Application'}</span>
                </div>
              </div>
              
              <div class="req-title">Client Requirements & Notes:</div>
              <div class="req-box">
                {quote_data.get('requirements') or 'No special technical notes specified.'}
              </div>
              
              <div class="btn-wrapper">
                <a href="https://autominddynamics.com/admin#quotes" class="btn-action">Open Tech Console Quotes</a>
              </div>
            </div>
            <div class="footer">
              AutoMind Dynamics Tech Console • Automated Real-time Alert System<br>
              Delivered via Resend Transactional API • {datetime.utcnow().strftime('%B %d, %Y - %H:%M UTC')}
            </div>
          </div>
        </body>
        </html>
        """

        text_content = f"""
AUTOMIND DYNAMICS - QUOTE REQUEST ALERT
--------------------------------------------------
Product: {product_name}
Customer: {customer_name}
Email: {quote_data.get('email')}
Phone: {phone_val or 'Not provided'}
Company: {quote_data.get('company') or 'Individual'}
Volume: {quote_data.get('quantity', '1 Unit')}
Timeline: {quote_data.get('timeframe') or 'Standard'}
Use Case: {quote_data.get('use_case') or 'Robotics Application'}

Requirements:
{quote_data.get('requirements') or 'None'}

Console: https://autominddynamics.com/admin#quotes
"""

        try:
            response = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "from": from_email,
                    "to": [alert_recipient],
                    "subject": subject,
                    "html": html_content,
                    "text": text_content
                },
                timeout=10
            )
            if response.status_code in [200, 201]:
                data = response.json()
                email_id = data.get('id', 'sent')
                print(f"[Resend Success] Email delivered. ID: {email_id}")
                return True, f"Delivered (Resend ID: {email_id})"
            else:
                err_data = response.text
                try:
                    err_json = response.json()
                    err_data = err_json.get('message', err_data)
                except Exception:
                    pass
                print(f"[Resend Error] Status {response.status_code}: {err_data}")
                return False, f"Resend API error ({response.status_code}): {err_data}"
        except Exception as e:
            print(f"[Resend Exception] {e}")
            return False, str(e)

def run_migrations():
    """Ensures database schema migrations are applied across SQLite and PostgreSQL."""
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        if 'rover' in tables:
            columns = [col['name'] for col in inspector.get_columns('rover')]
            if 'is_visible' not in columns:
                # PostgreSQL requires BOOLEAN DEFAULT TRUE (integer 1 causes type mismatch)
                db.session.execute(text("ALTER TABLE rover ADD COLUMN is_visible BOOLEAN DEFAULT TRUE"))
                db.session.execute(text("UPDATE rover SET is_visible = TRUE WHERE is_visible IS NULL"))
                db.session.commit()
                print("Database migration: successfully added 'is_visible' column to 'rover' table.")
    except Exception as e:
        db.session.rollback()
        print(f"Migration check notice: {e}")
        try:
            db.session.execute(text("ALTER TABLE rover ADD COLUMN is_visible BOOLEAN DEFAULT TRUE"))
            db.session.commit()
            print("Direct ALTER TABLE succeeded.")
        except Exception as inner_e:
            db.session.rollback()
            print(f"Direct ALTER TABLE notice: {inner_e}")

# Ensure database tables are created
with app.app_context():
    db.create_all()
    run_migrations()

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
#     DOCUMENTATION EXPORT & PDF GENERATION
# ============================================

def export_rover_mkdocs_zip(rover):
    """
    Exports a complete, production-ready MkDocs project (.zip) from a Rover and its DocPages.
    Includes mkdocs.yml, structured docs/ markdown files matching the page tree hierarchy,
    referenced images in docs/assets/images/, and a quickstart README.md.
    """
    pages = DocPage.query.filter_by(rover_id=rover.id).order_by(DocPage.order, DocPage.title).all()
    
    page_dict = {p.id: p for p in pages}
    children_map = {}
    top_pages = []
    for p in pages:
        if p.parent_id and p.parent_id in page_dict:
            children_map.setdefault(p.parent_id, []).append(p)
        else:
            top_pages.append(p)

    def get_page_rel_path(page):
        clean_slug = page.slug.strip().strip('/')
        if not clean_slug or clean_slug == 'index':
            return 'index.md'
        if not clean_slug.endswith('.md'):
            return f"{clean_slug}.md"
        return clean_slug

    def build_nav_tree_yaml(nodes):
        nav_list = []
        for n in nodes:
            rel_file = get_page_rel_path(n)
            kids = children_map.get(n.id, [])
            if kids:
                sub_nav = [{n.title: rel_file}]
                sub_nav.extend(build_nav_tree_yaml(kids))
                nav_list.append({n.title: sub_nav})
            else:
                nav_list.append({n.title: rel_file})
        return nav_list

    nav_yaml = build_nav_tree_yaml(top_pages) if top_pages else [{'Home': 'index.md'}]

    mkdocs_config = {
        'site_name': rover.name,
        'site_description': rover.description or f"Official technical documentation for {rover.name}",
        'site_author': "Automind Dynamics",
        'theme': {
            'name': 'material',
            'palette': [
                {'scheme': 'slate', 'primary': 'blue', 'accent': 'cyan'},
                {'scheme': 'default', 'primary': 'blue', 'accent': 'cyan'}
            ],
            'features': [
                'navigation.instant',
                'navigation.tracking',
                'navigation.sections',
                'navigation.top',
                'content.code.copy',
                'search.suggest',
                'search.highlight'
            ]
        },
        'markdown_extensions': [
            'admonition',
            'tables',
            'attr_list',
            'def_list',
            'fenced_code',
            'toc',
            'pymdownx.superfences',
            'pymdownx.details',
            'pymdownx.tabbed',
            'pymdownx.highlight',
            'pymdownx.inlinehilite',
            'pymdownx.tasklist'
        ],
        'nav': nav_yaml
    }

    all_db_images = DocImage.query.all()
    img_by_id = {img.id: img for img in all_db_images}
    img_by_name = {img.filename: img for img in all_db_images}

    def resolve_doc_image(ref):
        if not ref:
            return None
        if '/docs/image/' in ref:
            m = re.search(r'/docs/image/(\d+)', ref)
            if m and int(m.group(1)) in img_by_id:
                return img_by_id[int(m.group(1))]
        base = os.path.basename(ref.split('?')[0].split('#')[0])
        if base and base in img_by_name:
            return img_by_name[base]
        return None

    extracted_images = {}

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('mkdocs.yml', yaml.dump(mkdocs_config, sort_keys=False, allow_unicode=True))
        
        readme_content = f"""# {rover.name} - Documentation Project
Exported from Automind Dynamics Web Platform on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}.

## Quickstart: Previewing Locally with MkDocs
1. Install MkDocs and Material theme:
   ```bash
   pip install mkdocs mkdocs-material pymdown-extensions
   ```
2. Run local live-reloading server:
   ```bash
   mkdocs serve
   ```
3. Open your browser at http://127.0.0.1:8000/

## Re-importing into Automind Dynamics
After editing markdown files in `docs/` or adding new sections in `mkdocs.yml`:
1. Compress this directory into a `.zip` file.
2. In Automind Admin Dashboard, click **Import MkDocs Package** (or **Bulk Import MKDocs** on the system view) to update the database.
"""
        zf.writestr('README.md', readme_content)

        if not pages:
            zf.writestr('docs/index.md', f"# {rover.name}\n\n*Welcome to the documentation for {rover.name}.*")
        else:
            for p in pages:
                rel_file = get_page_rel_path(p)
                content = p.content or f"# {p.title}\n\n*No content published yet.*"
                
                depth = len(rel_file.split('/')) - 1
                asset_prefix = ('../' * depth) + 'assets/images/'
                
                def sub_md_img(m):
                    alt, src = m.group(1), m.group(2)
                    img = resolve_doc_image(src)
                    if img:
                        safe_name = secure_filename(img.filename) or f"image_{img.id}.png"
                        extracted_images[safe_name] = img.data
                        return f"![{alt}]({asset_prefix}{safe_name})"
                    return m.group(0)

                def sub_html_img(m):
                    tag = m.group(0)
                    src = m.group(1)
                    img = resolve_doc_image(src)
                    if img:
                        safe_name = secure_filename(img.filename) or f"image_{img.id}.png"
                        extracted_images[safe_name] = img.data
                        return tag.replace(src, f"{asset_prefix}{safe_name}")
                    return tag

                content = re.sub(r'!\[(.*?)\]\((.*?)\)', sub_md_img, content)
                content = re.sub(r'<img[^>]+src=[\"\']([^\"\']+)[\"\']', sub_html_img, content)
                zf.writestr(f"docs/{rel_file}", content)

        for fname, img_bytes in extracted_images.items():
            zf.writestr(f"docs/assets/images/{fname}", img_bytes)

    zip_buffer.seek(0)
    return zip_buffer

def generate_rover_pdf(rover):
    """
    Generates a high-quality multi-page PDF document combining all pages of the Rover.
    Includes Automind Dynamics cover page, Table of Contents, syntax-highlighted code,
    inlined images, and running headers/footers with page numbers.
    """
    if pisa is None:
        raise RuntimeError("xhtml2pdf is not installed. Please install it using: pip install xhtml2pdf")

    pages = DocPage.query.filter_by(rover_id=rover.id).order_by(DocPage.order, DocPage.title).all()

    all_db_images = DocImage.query.all()
    img_by_id = {img.id: img for img in all_db_images}
    img_by_name = {img.filename: img for img in all_db_images}

    def resolve_doc_image(ref):
        if not ref:
            return None
        if '/docs/image/' in ref:
            m = re.search(r'/docs/image/(\d+)', ref)
            if m and int(m.group(1)) in img_by_id:
                return img_by_id[int(m.group(1))]
        base = os.path.basename(ref.split('?')[0].split('#')[0])
        if base and base in img_by_name:
            return img_by_name[base]
        return None

    html_parts = []
    html_parts.append(f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {{
        size: a4 portrait;
        margin-top: 2.2cm;
        margin-bottom: 2.2cm;
        margin-left: 1.8cm;
        margin-right: 1.8cm;
        @frame header {{
            -pdf-frame-content: pdfHeader;
            top: 0.7cm;
            margin-left: 1.8cm;
            margin-right: 1.8cm;
            height: 1.3cm;
        }}
        @frame footer {{
            -pdf-frame-content: pdfFooter;
            bottom: 0.7cm;
            margin-left: 1.8cm;
            margin-right: 1.8cm;
            height: 1.3cm;
        }}
    }}
    body {{
        font-family: Helvetica, Arial, sans-serif;
        font-size: 9.5pt;
        color: #1e293b;
        line-height: 1.5;
    }}
    h1 {{
        color: #0f172a;
        font-size: 18pt;
        margin-top: 14pt;
        margin-bottom: 8pt;
        font-weight: bold;
    }}
    h2 {{
        color: #1e293b;
        font-size: 13pt;
        margin-top: 14pt;
        margin-bottom: 6pt;
        border-bottom: 0.5pt solid #cbd5e1;
        padding-bottom: 2pt;
    }}
    h3 {{
        color: #334155;
        font-size: 11pt;
        margin-top: 10pt;
        margin-bottom: 4pt;
    }}
    p {{
        margin-bottom: 6pt;
    }}
    ul, ol {{
        margin-top: 4pt;
        margin-bottom: 8pt;
        padding-left: 16pt;
    }}
    li {{
        margin-bottom: 2pt;
    }}
    pre, code {{
        font-family: Courier, monospace;
        background-color: #f1f5f9;
        font-size: 8pt;
    }}
    pre {{
        padding: 8pt;
        border: 0.5pt solid #cbd5e1;
        margin: 6pt 0;
    }}
    code {{
        padding: 1pt 3pt;
    }}
    table {{
        width: 100%;
        margin: 8pt 0;
        border: 0.5pt solid #94a3b8;
    }}
    th, td {{
        border: 0.5pt solid #cbd5e1;
        padding: 4pt 6pt;
        text-align: left;
        font-size: 8.5pt;
    }}
    th {{
        background-color: #f1f5f9;
        font-weight: bold;
        color: #0f172a;
    }}
    blockquote, .admonition {{
        border-left: 3pt solid #2563eb;
        background-color: #eff6ff;
        padding: 6pt 10pt;
        margin: 6pt 0;
        font-size: 9pt;
    }}
    img {{
        max-width: 100%;
        height: auto;
        margin: 6pt 0;
    }}
    .page-break {{
        page-break-before: always;
    }}
    .cover {{
        text-align: center;
        margin-top: 140pt;
        margin-bottom: 120pt;
    }}
    .cover-brand {{
        font-size: 13pt;
        font-weight: bold;
        color: #2563eb;
        letter-spacing: 2px;
        text-transform: uppercase;
        margin-bottom: 15pt;
    }}
    .cover-title {{
        font-size: 24pt;
        font-weight: bold;
        color: #0f172a;
        margin-bottom: 12pt;
        line-height: 1.2;
    }}
    .cover-subtitle {{
        font-size: 11.5pt;
        color: #475569;
        margin-bottom: 28pt;
    }}
    .cover-meta {{
        font-size: 9pt;
        color: #94a3b8;
        border-top: 0.5pt solid #e2e8f0;
        padding-top: 12pt;
        display: inline-block;
        width: 70%;
    }}
    .toc-title {{
        font-size: 16pt;
        font-weight: bold;
        color: #0f172a;
        border-bottom: 1.5pt solid #2563eb;
        padding-bottom: 4pt;
        margin-bottom: 14pt;
    }}
    .toc-item {{
        padding: 3.5pt 0;
        border-bottom: 0.5pt dotted #e2e8f0;
    }}
    .toc-number {{
        font-weight: bold;
        color: #2563eb;
        margin-right: 4pt;
    }}
    .toc-slug {{
        color: #64748b;
        font-size: 8.5pt;
    }}
</style>
</head>
<body>
    <div id="pdfHeader" style="font-size: 8pt; color: #64748b; border-bottom: 0.5pt solid #cbd5e1; padding-bottom: 3pt;">
        <span style="font-weight: bold; color: #0f172a;">AUTOMIND DYNAMICS</span> &bull; {rover.name}
    </div>

    <div id="pdfFooter" style="font-size: 8pt; color: #94a3b8; border-top: 0.5pt solid #e2e8f0; padding-top: 3pt;">
        <table style="width: 100%; border: none;">
            <tr>
                <td style="border: none; text-align: left; font-size: 8pt; color: #94a3b8;">Technical Documentation & Manual</td>
                <td style="border: none; text-align: right; font-size: 8pt; color: #94a3b8;">Page <pdf:pagenumber/> of <pdf:pagecount/></td>
            </tr>
        </table>
    </div>

    <div class="cover">
        <div class="cover-brand">Automind Dynamics</div>
        <div class="cover-title">{rover.name}</div>
        <div class="cover-subtitle">{rover.description or 'Official Technical Manual & Operational Documentation'}</div>
        <div class="cover-meta">
            <div><strong>Format:</strong> Complete Reference Manual &bull; <strong>Status:</strong> Released</div>
            <div style="margin-top: 4pt;">Exported: {datetime.utcnow().strftime('%B %d, %Y')} &bull; Route: /docs/{rover.slug}</div>
        </div>
    </div>

    <div class="page-break"></div>
    <div class="toc-title">Table of Contents</div>
""")

    if not pages:
        html_parts.append("<p><em>No documentation pages have been published yet.</em></p>")
    else:
        for idx, p in enumerate(pages, 1):
            html_parts.append(f"""
            <div class="toc-item">
                <span class="toc-number">{idx}.</span>
                <strong>{p.title}</strong>
                <span class="toc-slug">(/{p.slug})</span>
            </div>
            """)

        for idx, p in enumerate(pages, 1):
            raw_content = p.content or ""
            def sub_md(m):
                alt, src = m.group(1), m.group(2)
                img = resolve_doc_image(src)
                if img:
                    b64 = base64.b64encode(img.data).decode('utf-8')
                    return f'![{alt}](data:{img.mime_type};base64,{b64})'
                return m.group(0)
            raw_content = re.sub(r'!\[(.*?)\]\((.*?)\)', sub_md, raw_content)

            def sub_html(m):
                tag = m.group(0)
                src = m.group(1)
                img = resolve_doc_image(src)
                if img:
                    b64 = base64.b64encode(img.data).decode('utf-8')
                    return tag.replace(src, f'data:{img.mime_type};base64,{b64}')
                return tag
            raw_content = re.sub(r'<img[^>]+src=[\"\']([^\"\']+)[\"\']', sub_html, raw_content)

            rendered_page_html = render_markdown(raw_content)
            rendered_page_html = re.sub(r'<input[^>]+type=[\"\']radio[\"\'][^>]*>', '', rendered_page_html)

            html_parts.append(f"""
            <div class="page-break">
                <h1 style="border-bottom: 1.5pt solid #2563eb; padding-bottom: 4pt;">
                    <span style="color: #64748b; font-size: 13pt; margin-right: 4pt;">{idx}.</span> {p.title}
                </h1>
                {rendered_page_html}
            </div>
            """)

    html_parts.append("</body></html>")
    full_html = "".join(html_parts)

    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(full_html, dest=pdf_buffer)
    if pisa_status.err:
        raise RuntimeError(f"PDF generation failed with error code {pisa_status.err}")
    pdf_buffer.seek(0)
    return pdf_buffer

def render_docs_print(rover_slug):
    """Renders the comprehensive, printable continuous manual view for a rover."""
    rover = Rover.query.filter_by(slug=rover_slug).first_or_404()
    pages = DocPage.query.filter_by(rover_id=rover.id).order_by(DocPage.order, DocPage.title).all()
    
    rendered_pages = []
    for p in pages:
        rendered_pages.append({
            'page': p,
            'html': render_markdown(p.content or '')
        })
        
    return render_template(
        'templates/docs_print.html',
        rover=rover,
        pages=pages,
        rendered_pages=rendered_pages,
        generated_date=datetime.utcnow().strftime('%B %d, %Y'),
        is_subdomain=is_docs_subdomain()
    )

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

        # Trigger Resend email alert in background thread
        quote_payload = {
            'id': quote.id,
            'product': quote.product,
            'full_name': quote.full_name,
            'email': quote.email,
            'phone': quote.phone,
            'company': quote.company,
            'use_case': quote.use_case,
            'quantity': quote.quantity,
            'timeframe': quote.timeframe,
            'requirements': quote.requirements
        }
        try:
            threading.Thread(target=send_resend_quote_alert, args=(quote_payload,), daemon=True).start()
        except Exception as alert_err:
            print(f"[Alert Thread Notice] Failed to spawn alert thread: {alert_err}")

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

LOGIN_ATTEMPTS = {}  # ip -> {'count': int, 'locked_until': datetime}

@app.before_request
def admin_auth_check():
    """Ensure routes under /admin require authentication (except login)."""
    if request.path.startswith('/admin') and request.path != '/admin/login':
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip and ',' in client_ip:
        client_ip = client_ip.split(',')[0].strip()
    if not client_ip:
        client_ip = 'unknown'

    # Check if client IP is currently in security lockout
    attempt_info = LOGIN_ATTEMPTS.get(client_ip)
    now = datetime.utcnow()
    if attempt_info and attempt_info.get('locked_until') and attempt_info['locked_until'] > now:
        remaining_seconds = int((attempt_info['locked_until'] - now).total_seconds())
        remaining_minutes = max(1, (remaining_seconds // 60) + 1)
        error = f"Security Lockout: Too many failed passcode attempts. Console access locked for {remaining_minutes} more minute(s)."
        return render_template('templates/admin_login.html', error=error)

    if request.method == 'POST':
        password = (request.form.get('password') or '').strip()
        
        if verify_admin_password(password):
            # Reset failed login tracking on success
            LOGIN_ATTEMPTS.pop(client_ip, None)
            
            # Reset and re-create session to prevent session fixation attacks
            session.clear()
            session['admin_logged_in'] = True
            session.permanent = True
            return redirect(url_for('admin_dashboard'))
        else:
            # Artificially delay response slightly to deter brute-force and dictionary bots
            time.sleep(0.5)
            
            if client_ip not in LOGIN_ATTEMPTS:
                LOGIN_ATTEMPTS[client_ip] = {'count': 1, 'locked_until': None}
            else:
                LOGIN_ATTEMPTS[client_ip]['count'] += 1
                
            failed_count = LOGIN_ATTEMPTS[client_ip]['count']
            if failed_count >= 5:
                LOGIN_ATTEMPTS[client_ip]['locked_until'] = now + timedelta(minutes=15)
                error = "Security Lockout: 5 consecutive failed passcode attempts. Console access locked for 15 minutes."
            else:
                attempts_left = max(0, 5 - failed_count)
                error = f"Invalid passcode. {attempts_left} attempt(s) remaining before security lockout."

    return render_template('templates/admin_login.html', error=error)

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/admin/')
def admin_dashboard():
    try:
        rovers = Rover.query.order_by(Rover.created_at.desc()).all()
    except Exception:
        db.session.rollback()
        run_migrations()
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

    # Security & Resend Notification State
    has_custom_pass = not is_using_default_password()
    resend_key = get_admin_setting('resend_api_key') or os.environ.get('RESEND_API_KEY', '')
    resend_alert_email = get_admin_setting('resend_alert_email') or os.environ.get('ADMIN_ALERT_EMAIL', 'info@autominddynamics.com')
    resend_from_email = get_admin_setting('resend_from_email') or os.environ.get('RESEND_FROM_EMAIL', 'AutoMind Dynamics <onboarding@resend.dev>')
    resend_enabled = get_admin_setting('resend_enabled', 'true') == 'true'

    masked_key = ""
    if resend_key:
        if len(resend_key) > 8:
            masked_key = resend_key[:6] + "..." + resend_key[-4:]
        else:
            masked_key = "••••••••••••"

    security = {
        'is_default_password': not has_custom_pass,
        'password_changed_at': get_admin_setting('admin_password_changed_at', 'Default / Unchanged'),
        'resend_configured': bool(resend_key),
        'resend_enabled': resend_enabled,
        'resend_api_key_masked': masked_key,
        'resend_alert_email': resend_alert_email,
        'resend_from_email': resend_from_email,
        'has_api_key': bool(resend_key)
    }

    return render_template('templates/admin_dashboard.html', rovers=rover_data, quotes=quotes, softwares=softwares, stats=stats, security=security)

@app.route('/admin/change-password', methods=['POST'])
def admin_change_password():
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    
    current_password = (request.form.get('current_password') or '').strip()
    new_password = (request.form.get('new_password') or '').strip()
    confirm_password = (request.form.get('confirm_password') or '').strip()
    
    if not current_password or not new_password or not confirm_password:
        return jsonify({'status': 'error', 'message': 'All password fields are required.'}), 400
        
    if not verify_admin_password(current_password):
        return jsonify({'status': 'error', 'message': 'Current passcode is incorrect.'}), 400
        
    if len(new_password) < 8:
        return jsonify({'status': 'error', 'message': 'New passcode must be at least 8 characters long.'}), 400
        
    if new_password == current_password:
        return jsonify({'status': 'error', 'message': 'New passcode cannot be identical to current passcode.'}), 400
        
    if new_password != confirm_password:
        return jsonify({'status': 'error', 'message': 'New passcode and confirmation do not match.'}), 400

    # Disallow common weak passwords
    weak_passwords = ['admin', 'admin123', 'admin1234', 'password', 'password123', '12345678', 'automind', 'automind123']
    if new_password.lower() in weak_passwords:
        return jsonify({'status': 'error', 'message': 'Passcode is too common or easily guessable. Please choose a strong, unique passcode.'}), 400

    # Ensure minimum complexity: at least one letter and at least one digit
    has_letter = any(c.isalpha() for c in new_password)
    has_digit = any(c.isdigit() for c in new_password)
    if not has_letter or not has_digit:
        return jsonify({'status': 'error', 'message': 'Passcode must contain a mixture of letters and numbers for high security.'}), 400

    # Hash using salted cryptographic algorithm (scrypt / pbkdf2)
    new_hash = generate_password_hash(new_password)
    set_admin_setting('admin_password_hash', new_hash)
    set_admin_setting('admin_password_changed_at', datetime.utcnow().strftime('%B %d, %Y - %H:%M UTC'))
    
    # Clear any rate limit lockout for this IP
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip and ',' in client_ip:
        client_ip = client_ip.split(',')[0].strip()
    if client_ip:
        LOGIN_ATTEMPTS.pop(client_ip, None)
        
    return jsonify({
        'status': 'success',
        'message': 'Passcode updated successfully! Encrypted with cryptographic salted hashing.'
    }), 200

@app.route('/admin/settings/email', methods=['POST'])
def admin_settings_email():
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    
    api_key = (request.form.get('resend_api_key') or '').strip()
    alert_email = (request.form.get('resend_alert_email') or '').strip()
    from_email = (request.form.get('resend_from_email') or '').strip()
    enabled = request.form.get('resend_enabled') in ['1', 'true', 'on']
    
    if api_key and not api_key.startswith('•••'):
        # Validate Resend API key format (usually starts with re_)
        if not api_key.startswith('re_'):
            return jsonify({'status': 'error', 'message': "Invalid Resend API Key format. Resend keys typically begin with 're_'."}), 400
        set_admin_setting('resend_api_key', api_key)
        
    if alert_email:
        if '@' not in alert_email or '.' not in alert_email:
            return jsonify({'status': 'error', 'message': 'Please enter a valid recipient email address.'}), 400
        set_admin_setting('resend_alert_email', alert_email)
        
    if from_email:
        set_admin_setting('resend_from_email', from_email)
        
    set_admin_setting('resend_enabled', 'true' if enabled else 'false')
    
    return jsonify({
        'status': 'success',
        'message': 'Resend email alert configuration saved successfully!'
    }), 200

@app.route('/admin/settings/test-email', methods=['POST'])
def admin_settings_test_email():
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    
    test_quote = {
        'id': 9999,
        'full_name': 'Automind Security Bot',
        'email': 'verification@autominddynamics.com',
        'phone': '+1 (555) 019-2834',
        'company': 'AutoMind Dynamics Internal Verification',
        'product': 'GEFIER R1 - Autonomous Defense Platform',
        'quantity': '2 Units',
        'timeframe': 'Immediate Deployment',
        'use_case': 'Security & Email Infrastructure Verification',
        'requirements': 'This is an automated verification email triggered from the Tech Console to confirm that your Resend.com API integration is operational and receiving quote alerts in real-time.'
    }
    
    success, msg = send_resend_quote_alert(test_quote, is_test=True)
    if success:
        return jsonify({'status': 'success', 'message': f'Test email delivered! {msg}'}), 200
    else:
        return jsonify({'status': 'error', 'message': f'Email delivery failed: {msg}'}), 400

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
    is_visible_val = request.form.get('is_visible')
    is_visible = (is_visible_val in ['1', 'true', 'True', 'on']) if is_visible_val is not None else True
    
    if not name or not slug:
        return "Name and slug are required", 400
        
    existing = Rover.query.filter_by(slug=slug).first()
    if existing:
        return "Rover with this slug already exists", 400
        
    rover = Rover(name=name, slug=slug, description=description, is_visible=is_visible)
    db.session.add(rover)
    db.session.commit()
    return redirect(url_for('admin_dashboard') + '#systems')

@app.route('/admin/rover/<int:rover_id>/edit', methods=['POST'])
def admin_rover_edit(rover_id):
    rover = Rover.query.get_or_404(rover_id)
    name = request.form.get('name')
    slug = request.form.get('slug').strip().lower().replace(' ', '-')
    description = request.form.get('description')
    is_visible_val = request.form.get('is_visible')
    
    if not name or not slug:
        return "Name and slug are required", 400
        
    existing = Rover.query.filter(Rover.slug == slug, Rover.id != rover_id).first()
    if existing:
        return "Rover with this slug already exists", 400
        
    rover.name = name
    rover.slug = slug
    rover.description = description
    rover.is_visible = (is_visible_val in ['1', 'true', 'True', 'on'])
    db.session.commit()
    return redirect(url_for('admin_dashboard') + '#systems')

@app.route('/admin/rover/<int:rover_id>/toggle-visibility', methods=['POST'])
def admin_rover_toggle_visibility(rover_id):
    rover = Rover.query.get_or_404(rover_id)
    if request.is_json and 'is_visible' in request.json:
        rover.is_visible = bool(request.json['is_visible'])
    elif request.form.get('is_visible') is not None:
        rover.is_visible = request.form.get('is_visible') in ['1', 'true', 'True', 'on']
    else:
        rover.is_visible = not (rover.is_visible is True)
    db.session.commit()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or request.args.get('format') == 'json':
        return jsonify({'success': True, 'rover_id': rover.id, 'is_visible': rover.is_visible})
    return redirect(url_for('admin_dashboard') + '#systems')

@app.route('/admin/rover/<int:rover_id>/duplicate', methods=['POST'])
def admin_rover_duplicate(rover_id):
    original = Rover.query.get_or_404(rover_id)
    
    # Generate unique name
    base_name = f"{original.name} (Copy)"
    new_name = base_name
    counter = 2
    while Rover.query.filter_by(name=new_name).first():
        new_name = f"{original.name} (Copy {counter})"
        counter += 1
        
    # Generate unique slug
    base_slug = f"{original.slug}-copy"
    new_slug = base_slug
    counter = 2
    while Rover.query.filter_by(slug=new_slug).first():
        new_slug = f"{original.slug}-copy-{counter}"
        counter += 1
        
    # Create duplicated rover (defaults to private so it can be reviewed before making public)
    new_rover = Rover(
        name=new_name,
        slug=new_slug,
        description=original.description,
        is_visible=False
    )
    db.session.add(new_rover)
    db.session.flush()
    
    # Duplicate all DocPages preserving parent-child hierarchy
    orig_pages = DocPage.query.filter_by(rover_id=original.id).order_by(DocPage.id).all()
    old_to_new_id = {}
    
    # Pass 1: Clone DocPage records
    for p in orig_pages:
        new_page = DocPage(
            rover_id=new_rover.id,
            title=p.title,
            slug=p.slug,
            content=p.content,
            parent_id=None,
            order=p.order
        )
        db.session.add(new_page)
        db.session.flush()
        old_to_new_id[p.id] = new_page.id
        
    # Pass 2: Re-link parent_id hierarchy
    for p in orig_pages:
        if p.parent_id and p.parent_id in old_to_new_id:
            new_child_id = old_to_new_id[p.id]
            new_parent_id = old_to_new_id[p.parent_id]
            db.session.query(DocPage).filter_by(id=new_child_id).update({'parent_id': new_parent_id})
            
    db.session.commit()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({
            'success': True,
            'new_rover_id': new_rover.id,
            'new_name': new_rover.name,
            'new_slug': new_rover.slug,
            'message': f"Duplicated '{original.name}' successfully."
        })
    return redirect(url_for('admin_dashboard') + '#systems')

@app.route('/admin/rover/<int:rover_id>/delete', methods=['POST'])
def admin_rover_delete(rover_id):
    rover = Rover.query.get_or_404(rover_id)
    db.session.delete(rover)
    db.session.commit()
    return redirect(url_for('admin_dashboard') + '#systems')

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

@app.route('/admin/rover/<int:rover_id>/download/mkdocs')
def admin_rover_download_mkdocs(rover_id):
    """Downloads full MkDocs project package as a ZIP archive for admin."""
    rover = Rover.query.get_or_404(rover_id)
    zip_buf = export_rover_mkdocs_zip(rover)
    return send_file(
        zip_buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f"{rover.slug}-mkdocs.zip"
    )

@app.route('/admin/rover/<int:rover_id>/download/pdf')
def admin_rover_download_pdf(rover_id):
    """Downloads full documentation manual as a PDF for admin."""
    rover = Rover.query.get_or_404(rover_id)
    try:
        pdf_buf = generate_rover_pdf(rover)
        return send_file(
            pdf_buf,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"{rover.slug}-documentation.pdf"
        )
    except Exception as e:
        return f"PDF generation failed: {str(e)}", 500


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
    """Renders the landing page for all documentation (only public/visible rovers)."""
    try:
        rovers = Rover.query.filter(Rover.is_visible == True).order_by(Rover.name).all()
    except Exception as e:
        db.session.rollback()
        run_migrations()
        try:
            rovers = Rover.query.filter(Rover.is_visible == True).order_by(Rover.name).all()
        except Exception:
            db.session.rollback()
            from sqlalchemy import text
            res = db.session.execute(text("SELECT id, name, slug, description FROM rover ORDER BY name"))
            rovers = [type('RoverFallback', (), {'id': r[0], 'name': r[1], 'slug': r[2], 'description': r[3], 'is_visible': True}) for r in res]
    return render_template('templates/docs_home.html', rovers=rovers)

def render_docs_rover(rover_slug, page_path=None):
    """Renders the documentation system for a specific rover and page."""
    try:
        rover = Rover.query.filter_by(slug=rover_slug).first()
    except Exception as e:
        db.session.rollback()
        run_migrations()
        try:
            rover = Rover.query.filter_by(slug=rover_slug).first()
        except Exception:
            db.session.rollback()
            from sqlalchemy import text
            res = db.session.execute(text("SELECT id, name, slug, description FROM rover WHERE slug = :slug LIMIT 1"), {'slug': rover_slug}).fetchone()
            if res:
                rover = type('RoverFallback', (), {'id': res[0], 'name': res[1], 'slug': res[2], 'description': res[3], 'is_visible': True})
            else:
                rover = None
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

@app.route('/docs/<rover_slug>/download/mkdocs')
def docs_download_mkdocs(rover_slug):
    """Downloads full MkDocs project package as a ZIP archive for public visitors."""
    rover = Rover.query.filter_by(slug=rover_slug).first_or_404()
    zip_buf = export_rover_mkdocs_zip(rover)
    return send_file(
        zip_buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f"{rover.slug}-mkdocs.zip"
    )

@app.route('/docs/<rover_slug>/download/pdf')
def docs_download_pdf(rover_slug):
    """Downloads full documentation manual as a PDF for public visitors."""
    rover = Rover.query.filter_by(slug=rover_slug).first_or_404()
    try:
        pdf_buf = generate_rover_pdf(rover)
        return send_file(
            pdf_buf,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"{rover.slug}-documentation.pdf"
        )
    except Exception as e:
        return f"PDF generation failed: {str(e)}", 500

@app.route('/docs/<rover_slug>/print')
def docs_print_view(rover_slug):
    """Renders comprehensive printable manual view for a rover."""
    return render_docs_print(rover_slug)

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
        if page_path == 'download/mkdocs':
            return docs_download_mkdocs(rover_slug)
        elif page_path == 'download/pdf':
            return docs_download_pdf(rover_slug)
        elif page_path == 'print':
            return docs_print_view(rover_slug)
        return render_docs_rover(rover_slug, page_path)
    
    if os.path.exists(subpath) and not subpath.startswith('.') and not subpath.endswith('.py') and not subpath.endswith('.db'):
        return send_from_directory('.', subpath)
        
    abort(404)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=58055, debug=True)
