from flask import Flask, render_template, request, redirect, url_for, send_from_directory, abort, session, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
import os
import markdown
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

db = SQLAlchemy(app)

# ============================================
#     DATABASE MODELS
# ============================================

class Rover(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    pages = db.relationship('DocPage', backref='rover', lazy=True, cascade="all, delete-orphan")

class DocPage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rover_id = db.Column(db.Integer, db.ForeignKey('rover.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), nullable=False) # e.g. 'introduction' or 'hardware/motors'
    content = db.Column(db.Text, nullable=False, default="") # markdown content
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
    status = db.Column(db.String(50), default="Pending") # Pending, Contacted, In Progress, Archived
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Ensure database tables are created
with app.app_context():
    db.create_all()

# ============================================
#     HELPER FUNCTIONS
# ============================================

def is_docs_subdomain():
    """Detects if the request is targeting the docs subdomain."""
    host = request.host.lower()
    return host.startswith('docs.')

def get_base_url():
    """Builds correct base url depending on subdomain or subdirectory usage."""
    # Useful to construct links dynamically
    host = request.host
    if is_docs_subdomain():
        return f"http://{host}"
    else:
        # Fallback format: http://localhost:5000/docs
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
            
    # Sort recursively by order then title
    def sort_tree(nodes):
        nodes.sort(key=lambda x: (x['page'].order or 0, x['page'].title.lower()))
        for node in nodes:
            sort_tree(node['children'])
            
    sort_tree(roots)
    return roots

def render_markdown(text):
    """Converts Markdown text into beautiful HTML using standard extensions."""
    md = markdown.Markdown(extensions=['fenced_code', 'tables', 'toc', 'nl2br', 'admonition', 'attr_list'])
    return md.convert(text)

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

@app.route('/api/request-quote', methods=['POST'])
def api_request_quote():
    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form

        product = data.get('product') or 'General Product Inquiry'
        full_name = data.get('full_name')
        email = data.get('email')
        phone = data.get('phone', '')
        company = data.get('company', '')
        use_case = data.get('use_case', '')
        quantity = data.get('quantity', '1 Unit')
        timeframe = data.get('timeframe', '')
        requirements = data.get('requirements', '')

        if not full_name or not email or not product:
            return jsonify({'status': 'error', 'message': 'Full name, email, and product selection are required.'}), 400

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
    if clean_name in ['products', 'services', 'news', 'about']:
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
    rover_data = []
    for r in rovers:
        page_count = DocPage.query.filter_by(rover_id=r.id).count()
        rover_data.append({
            'rover': r,
            'page_count': page_count
        })
    return render_template('templates/admin_dashboard.html', rovers=rover_data, quotes=quotes)

@app.route('/admin/quote/<int:quote_id>/status', methods=['POST'])
def admin_quote_status(quote_id):
    quote = QuoteRequest.query.get_or_404(quote_id)
    new_status = request.form.get('status', 'Pending')
    quote.status = new_status
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/quote/<int:quote_id>/delete', methods=['POST'])
def admin_quote_delete(quote_id):
    quote = QuoteRequest.query.get_or_404(quote_id)
    db.session.delete(quote)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/rover/new', methods=['POST'])
def admin_rover_new():
    name = request.form.get('name')
    slug = request.form.get('slug').strip().lower().replace(' ', '-')
    description = request.form.get('description')
    
    if not name or not slug:
        return "Name and slug are required", 400
        
    # Check duplicate slug
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
    # Fetch all pages for ordering and hierarchy display
    pages = DocPage.query.filter_by(rover_id=rover.id).order_by(DocPage.order, DocPage.title).all()
    nav_tree = build_nav_tree(pages)
    return render_template('templates/admin_rover.html', rover=rover, pages=pages, nav_tree=nav_tree)

# Documentation Page CRUD
@app.route('/admin/rover/<int:rover_id>/page/new', methods=['GET', 'POST'])
def admin_page_new(rover_id):
    rover = Rover.query.get_or_404(rover_id)
    if request.method == 'POST':
        title = request.form.get('title')
        slug = request.form.get('slug').strip().lower().replace(' ', '-')
        content = request.form.get('content', '')
        parent_id = request.form.get('parent_id')
        order = request.form.get('order', 0)
        
        # Parse parent_id
        parent_id = int(parent_id) if parent_id and parent_id.isdigit() else None
        order = int(order) if order and str(order).isdigit() else 0
        
        if not title or not slug:
            return "Title and slug are required", 400
            
        # Verify page slug is unique for this rover
        existing = DocPage.query.filter_by(rover_id=rover.id, slug=slug).first()
        if existing:
            return "Page with this slug already exists for this rover", 400
            
        page = DocPage(rover_id=rover.id, title=title, slug=slug, content=content, parent_id=parent_id, order=order)
        db.session.add(page)
        db.session.commit()
        return redirect(url_for('admin_rover_view', rover_id=rover.id))
        
    # Get potential parent pages
    parent_pages = DocPage.query.filter_by(rover_id=rover.id, parent_id=None).all()
    return render_template('templates/admin_page_edit.html', rover=rover, page=None, parent_pages=parent_pages)

@app.route('/admin/page/<int:page_id>/edit', methods=['GET', 'POST'])
def admin_page_edit(page_id):
    page = DocPage.query.get_or_404(page_id)
    rover = Rover.query.get(page.rover_id)
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
            
        # Check slug uniqueness excluding self
        existing = DocPage.query.filter(DocPage.rover_id == rover.id, DocPage.slug == slug, DocPage.id != page_id).first()
        if existing:
            return "Page with this slug already exists for this rover", 400
            
        # Prevent self-referencing hierarchy
        if parent_id == page.id:
            parent_id = None
            
        page.title = title
        page.slug = slug
        page.content = content
        page.parent_id = parent_id
        page.order = order
        db.session.commit()
        return redirect(url_for('admin_rover_view', rover_id=rover.id))
        
    # Get potential parent pages (excluding self to avoid loops)
    parent_pages = DocPage.query.filter(DocPage.rover_id == rover.id, DocPage.parent_id == None, DocPage.id != page.id).all()
    return render_template('templates/admin_page_edit.html', rover=rover, page=page, parent_pages=parent_pages)

@app.route('/admin/page/<int:page_id>/delete', methods=['POST'])
def admin_page_delete(page_id):
    page = DocPage.query.get_or_404(page_id)
    rover_id = page.rover_id
    db.session.delete(page)
    db.session.commit()
    return redirect(url_for('admin_rover_view', rover_id=rover_id))

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
        
        # Image URL to reference in markdown
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
        # If subdomain is used and no rover matches, check if we want to show docs home
        if is_docs_subdomain() and not rover_slug:
            return render_docs_home()
        abort(404)
        
    # Get all pages of the rover sorted by order
    pages = DocPage.query.filter_by(rover_id=rover.id).order_by(DocPage.order, DocPage.title).all()
    
    if not pages:
        # If no pages exist yet, show a welcome screen
        return render_template('templates/docs_view.html', 
                               rover=rover, 
                               current_page=None, 
                               content_html="<h2>Welcome to " + rover.name + " Documentation</h2><p>No documentation pages have been published yet. Please check back later or log in to the admin panel to add documentation.</p>",
                               nav_tree=[],
                               prev_page=None,
                               next_page=None,
                               is_subdomain=is_docs_subdomain())
                               
    # Build sidebar tree
    nav_tree = build_nav_tree(pages)
    
    # If no path specified, default to the first page (lowest order)
    if not page_path:
        first_page = pages[0]
        # Redirect to the specific slug for cleaner URLs
        if is_docs_subdomain():
            return redirect(url_for('catch_all', subpath=f"{rover.slug}/{first_page.slug}"))
        else:
            return redirect(url_for('docs_page_sub', rover_slug=rover.slug, page_path=first_page.slug))
            
    # Find current page
    current_page = None
    for p in pages:
        if p.slug == page_path:
            current_page = p
            break
            
    if not current_page:
        abort(404)
        
    # Render markdown content
    content_html = render_markdown(current_page.content)
    
    # Calculate prev/next buttons
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
        
    # Simple case-insensitive search in title and content
    results = DocPage.query.filter(
        DocPage.rover_id == rover.id,
        (DocPage.title.ilike(f'%{q}%')) | (DocPage.content.ilike(f'%{q}%'))
    ).order_by(DocPage.order, DocPage.title).all()
    
    is_sub = is_docs_subdomain()
    out = []
    for r in results:
        # Determine the link
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

# Fallback Docs URL mappings (when accessed as a subdirectory e.g. automindynamics.com/docs/)
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
    # If the subdomain is active, resolve the URL path
    if is_docs_subdomain():
        parts = subpath.strip('/').split('/', 1)
        rover_slug = parts[0]
        page_path = parts[1] if len(parts) > 1 else None
        return render_docs_rover(rover_slug, page_path)
    
    # Otherwise, check if this matches an HTML file in the workspace
    if os.path.exists(subpath) and not subpath.startswith('.') and not subpath.endswith('.py') and not subpath.endswith('.db'):
        return send_from_directory('.', subpath)
        
    abort(404)

if __name__ == '__main__':
    # Local dev server
    app.run(host='0.0.0.0', port=58055, debug=True)
