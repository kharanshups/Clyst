# type: ignore[import]
from datetime import date, datetime
import os
from dotenv import load_dotenv
import natural_search
import ai
import uuid
import firebase_config
import firebase_admin
from firebase_admin import auth

# Load environment variables from .env file
load_dotenv()

# Initialize Firebase Admin SDK
firebase_config.init_firebase_admin()
from werkzeug.utils import secure_filename
from flask import Flask, abort, render_template, redirect, url_for, flash, request, jsonify, session
import json
# Type hints for better IDE support
from typing import Optional, Dict, Any, List
from flask_bootstrap5 import Bootstrap
from flask_ckeditor import CKEditor
from flask_migrate import Migrate
# from flask_gravatar import Gravatar
from flask_login import UserMixin, login_user, LoginManager, current_user, logout_user, login_required
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship, DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, String, Text
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder='static')
# Load configuration from config.py
try:
    from config import GEMINI_API_KEY, FLASK_SECRET_KEY
except ImportError:
    GEMINI_API_KEY = None
    FLASK_SECRET_KEY = 'dev-secret-key-change-in-production'
app.config['SECRET_KEY'] = FLASK_SECRET_KEY
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['SESSION_PERMANENT'] = True
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

ckeditor = CKEditor(app)
Bootstrap(app)

# Configure Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Specify what view to redirect to when login is required
login_manager.login_message_category = 'info'  # Optional: use bootstrap info category for flash messages


# Configure Gravatar (commented out due to compatibility issues)
# gravatar = Gravatar(app, size=100, rating='g', default='retro', force_default=False, force_lower=False, use_ssl=False, base_url=None)

@login_manager.user_loader
def load_user(user_id):
    return db.get_or_404(User, user_id)


class Base(DeclarativeBase):
    pass


# Database configuration
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True  # Enable automatic reconnection
}

if os.getenv('FLASK_ENV') == 'production':
    # Use PostgreSQL for production (Railway, Render)
    DATABASE_URL = os.getenv('DATABASE_URL')
    if DATABASE_URL:
        app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL.replace('postgres://', 'postgresql://')
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///clyst.db'
else:
    # Use SQLite for development (store DB in Flask instance folder)
    os.makedirs(app.instance_path, exist_ok=True)
    db_path = os.path.join(app.instance_path, 'clyst.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'

# Initialize SQLAlchemy with the declarative base class
db = SQLAlchemy(model_class=Base)
db.init_app(app)

# Initialize Flask-Migrate
migrate = Migrate(app, db, compare_type=True, render_as_batch=True)

# Create database tables within app context if they don't exist
with app.app_context():
    try:
        db.create_all()
        print("✅ Database tables created successfully")
    except Exception as e:
        print(f"❌ Error creating database tables: {e}")
        if os.path.exists(db_path):
            os.remove(db_path)
            print("🔄 Removed corrupted database file")


# Database creation will be done at the end


def admin_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user is logged in
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        # If id is not 1 then return abort with 403 error
        if current_user.id != 1:
            return abort(403)
        # Otherwise continue with the route function
        return f(*args, **kwargs)

    return decorated_function


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_file(file, folder_name):
    if file and allowed_file(file.filename):
        # Generate unique filename
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"

        # Create folder if it doesn't exist
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], folder_name)
        os.makedirs(folder_path, exist_ok=True)

        # Save file
        file_path = os.path.join(folder_path, unique_filename)
        file.save(file_path)

        # Return URL path for database storage
        url_path = f"/static/uploads/{folder_name}/{unique_filename}"
        return url_path
    return None


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    name: Mapped[Optional[str]] = mapped_column(db.String(100))
    email: Mapped[Optional[str]] = mapped_column(db.String(100), unique=True)
    password_hash: Mapped[Optional[str]] = mapped_column(db.String(255))
    phone: Mapped[Optional[str]] = mapped_column(db.String(20))
    location: Mapped[Optional[str]] = mapped_column(db.String(150))
    created_at: Mapped[Optional[str]] = mapped_column(db.String(250))
    is_verified: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, server_default='0')
    verification_photo: Mapped[Optional[str]] = mapped_column(db.String(255), nullable=True)
    verification_date: Mapped[Optional[str]] = mapped_column(db.String(250), nullable=True)
    posts = relationship("Posts", back_populates="artist")
    products = relationship("Product", back_populates="artist")


class Posts(db.Model):
    __tablename__ = 'posts'

    post_id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    artist_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('users.id'))
    artist = relationship("User", back_populates="posts")
    post_title: Mapped[Optional[str]] = mapped_column(db.String(255))
    description: Mapped[Optional[str]] = mapped_column(db.Text)
    media_url: Mapped[Optional[str]] = mapped_column(db.String(255))
    created_at: Mapped[Optional[str]] = mapped_column(db.String(255))
    is_promoted: Mapped[bool] = mapped_column(db.Boolean, default=False)


class Product(db.Model):
    __tablename__ = 'products'

    product_id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    artist_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('users.id'))
    artist = relationship("User", back_populates="products")
    title: Mapped[Optional[str]] = mapped_column(db.String(150))
    description: Mapped[Optional[str]] = mapped_column(db.Text)
    price: Mapped[Optional[float]] = mapped_column(db.Numeric(10, 2))
    img_url: Mapped[Optional[str]] = mapped_column(db.String(255))
    created_at: Mapped[Optional[str]] = mapped_column(db.String(250))
    is_promoted: Mapped[bool] = mapped_column(db.Boolean, default=False)


class Comments(db.Model):
    __tablename__ = 'comments'

    comment_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    post_id = db.Column(
        db.Integer,
        db.ForeignKey('posts.post_id', ondelete='CASCADE'),
        nullable=False
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id'),
        nullable=False
    )
    content = db.Column(db.Text)
    created_at: Mapped[Optional[str]] = mapped_column(db.String(250))


class PostLike(db.Model):
    __tablename__ = 'post_likes'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.post_id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)


class ProductComments(db.Model):
    __tablename__ = 'product_comments'

    comment_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text)
    created_at: Mapped[Optional[str]] = mapped_column(db.String(250))


class ProductReview(db.Model):
    __tablename__ = 'product_reviews'

    review_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1..5
    title = db.Column(db.String(150))
    content = db.Column(db.Text)
    created_at: Mapped[Optional[str]] = mapped_column(db.String(250))
    updated_at: Mapped[Optional[str]] = mapped_column(db.String(250))


class Cart(db.Model):
    __tablename__ = 'carts'

    cart_id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at: Mapped[Optional[str]] = mapped_column(db.String(250))
    updated_at: Mapped[Optional[str]] = mapped_column(db.String(250))
    items = relationship("CartItem", back_populates="cart", cascade="all, delete-orphan")


class CartItem(db.Model):
    __tablename__ = 'cart_items'

    item_id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    cart_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('carts.cart_id'), nullable=False)
    product_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    quantity: Mapped[int] = mapped_column(db.Integer, default=1)
    added_at: Mapped[Optional[str]] = mapped_column(db.String(250))
    product = relationship("Product")
    cart = relationship("Cart", back_populates="items")
    added_at: Mapped[Optional[str]] = mapped_column(db.String(250))
    cart = relationship("Cart", back_populates="items")
    product = relationship("Product")


# ===== ORDER MODELS =====
class Order(db.Model):
    __tablename__ = 'orders'

    order_id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status: Mapped[str] = mapped_column(db.String(50), default='pending')  # pending, paid, shipped, delivered, canceled
    payment_status: Mapped[str] = mapped_column(db.String(50), default='unpaid')  # unpaid, paid, refunded
    payment_reference: Mapped[Optional[str]] = mapped_column(db.String(120))
    total_price: Mapped[Optional[float]] = mapped_column(db.Numeric(10, 2))
    shipping_name: Mapped[Optional[str]] = mapped_column(db.String(120))
    shipping_phone: Mapped[Optional[str]] = mapped_column(db.String(30))
    shipping_address: Mapped[Optional[str]] = mapped_column(db.Text)
    created_at: Mapped[Optional[str]] = mapped_column(db.String(250))
    updated_at: Mapped[Optional[str]] = mapped_column(db.String(250))

    user = relationship("User")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(db.Model):
    __tablename__ = 'order_items'

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False)
    product_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('products.product_id'), nullable=True)
    product_title: Mapped[Optional[str]] = mapped_column(db.String(200))
    product_img_url: Mapped[Optional[str]] = mapped_column(db.String(255))
    unit_price: Mapped[Optional[float]] = mapped_column(db.Numeric(10, 2))
    quantity: Mapped[int] = mapped_column(db.Integer, default=1)
    total_price: Mapped[Optional[float]] = mapped_column(db.Numeric(10, 2))

    order = relationship("Order", back_populates="items")
    product = relationship("Product")


# ===== FOLLOW/FOLLOWER SYSTEM =====
class Follow(db.Model):
    __tablename__ = 'follows'

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    follower_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # User who follows
    followed_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # User being followed
    created_at: Mapped[Optional[str]] = mapped_column(db.String(250))

    # Ensure unique follower-followed pairs
    __table_args__ = (db.UniqueConstraint('follower_id', 'followed_id', name='unique_follow'),)


# ===== HASHTAG SYSTEM =====
class Hashtag(db.Model):
    __tablename__ = 'hashtags'

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(db.String(100), unique=True, nullable=False)  # Without the # symbol
    created_at: Mapped[Optional[str]] = mapped_column(db.String(250))


class PostHashtag(db.Model):
    __tablename__ = 'post_hashtags'

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('posts.post_id', ondelete='CASCADE'), nullable=False)
    hashtag_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('hashtags.id', ondelete='CASCADE'), nullable=False)

    __table_args__ = (db.UniqueConstraint('post_id', 'hashtag_id', name='unique_post_hashtag'),)


class ProductHashtag(db.Model):
    __tablename__ = 'product_hashtags'

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('products.product_id', ondelete='CASCADE'), nullable=False)
    hashtag_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('hashtags.id', ondelete='CASCADE'), nullable=False)

    __table_args__ = (db.UniqueConstraint('product_id', 'hashtag_id', name='unique_product_hashtag'),)


# ===== MESSAGING MODELS =====
class Conversation(db.Model):
    __tablename__ = 'conversations'

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[Optional[int]] = mapped_column(db.Integer, db.ForeignKey('products.product_id'), nullable=True)
    buyer_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    seller_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status: Mapped[str] = mapped_column(db.String(20), default='open')
    created_at: Mapped[Optional[str]] = mapped_column(db.String(250))
    last_message_at: Mapped[Optional[str]] = mapped_column(db.String(250))

    product = relationship('Product')
    buyer = relationship('User', foreign_keys=[buyer_id])
    seller = relationship('User', foreign_keys=[seller_id])
    messages = relationship('Message', back_populates='conversation', cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('product_id', 'buyer_id', 'seller_id', name='unique_conv_product_buyer_seller'),
    )


class Message(db.Model):
    __tablename__ = 'messages'

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('conversations.id'), nullable=False)
    sender_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(db.Text)
    attachment_url: Mapped[Optional[str]] = mapped_column(db.String(255))
    created_at: Mapped[Optional[str]] = mapped_column(db.String(250))
    read_at: Mapped[Optional[str]] = mapped_column(db.String(250))

    conversation = relationship('Conversation', back_populates='messages')
    sender = relationship('User')


# ===== ANALYTICS MODELS =====
class ProductView(db.Model):
    __tablename__ = 'product_views'

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('products.product_id', ondelete='CASCADE'), nullable=False)
    artist_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    viewer_id: Mapped[Optional[int]] = mapped_column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(db.String(250))


class ProfileView(db.Model):
    __tablename__ = 'profile_views'

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    profile_user_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    viewer_id: Mapped[Optional[int]] = mapped_column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(db.String(250))


# ===== PAYMENTS (Dummy Gateway) =====
class Payment(db.Model):
    __tablename__ = 'payments'

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('orders.order_id', ondelete='CASCADE'), nullable=False)
    amount: Mapped[Optional[float]] = mapped_column(db.Numeric(10, 2))
    currency: Mapped[str] = mapped_column(db.String(10), default='INR')
    status: Mapped[str] = mapped_column(db.String(20), default='created')  # created, processing, paid, failed, canceled
    reference: Mapped[Optional[str]] = mapped_column(db.String(120))
    created_at: Mapped[Optional[str]] = mapped_column(db.String(250))
    updated_at: Mapped[Optional[str]] = mapped_column(db.String(250))


# ===== HELPER FUNCTIONS =====

def extract_hashtags(text):
    """Extract hashtags from text. Returns list of hashtag names (without #)"""
    import re
    if not text:
        return []
    # Match hashtags: # followed by word characters (letters, numbers, underscores)
    hashtags = re.findall(r'#(\w+)', text)
    # Convert to lowercase and remove duplicates while preserving order
    seen = set()
    unique_tags = []
    for tag in hashtags:
        tag_lower = tag.lower()
        if tag_lower not in seen:
            seen.add(tag_lower)
            unique_tags.append(tag_lower)
    return unique_tags


def save_hashtags_for_post(post_id, text):
    """Extract and save hashtags for a post"""
    hashtag_names = extract_hashtags(text)
    
    for tag_name in hashtag_names:
        # Get or create hashtag
        hashtag = db.session.execute(
            db.select(Hashtag).where(Hashtag.name == tag_name)
        ).scalar_one_or_none()
        
        if not hashtag:
            hashtag = Hashtag(name=tag_name, created_at=date.today().strftime('%B %d, %Y'))
            db.session.add(hashtag)
            db.session.flush()
        
        # Create post-hashtag association if it doesn't exist
        existing = db.session.execute(
            db.select(PostHashtag).where(
                PostHashtag.post_id == post_id,
                PostHashtag.hashtag_id == hashtag.id
            )
        ).scalar_one_or_none()
        
        if not existing:
            post_hashtag = PostHashtag(post_id=post_id, hashtag_id=hashtag.id)
            db.session.add(post_hashtag)


def save_hashtags_for_product(product_id, text):
    """Extract and save hashtags for a product"""
    hashtag_names = extract_hashtags(text)
    
    for tag_name in hashtag_names:
        # Get or create hashtag
        hashtag = db.session.execute(
            db.select(Hashtag).where(Hashtag.name == tag_name)
        ).scalar_one_or_none()
        
        if not hashtag:
            hashtag = Hashtag(name=tag_name, created_at=date.today().strftime('%B %d, %Y'))
            db.session.add(hashtag)
            db.session.flush()
        
        # Create product-hashtag association if it doesn't exist
        existing = db.session.execute(
            db.select(ProductHashtag).where(
                ProductHashtag.product_id == product_id,
                ProductHashtag.hashtag_id == hashtag.id
            )
        ).scalar_one_or_none()
        
        if not existing:
            product_hashtag = ProductHashtag(product_id=product_id, hashtag_id=hashtag.id)
            db.session.add(product_hashtag)


def linkify_hashtags(text):
    """Convert hashtags in text to clickable links, safely escaping other HTML."""
    import re
    from markupsafe import escape, Markup
    if not text:
        return ''
    # First escape any existing HTML to prevent injection
    escaped = escape(text)
    # Replace #hashtag with <a href="/hashtag/hashtag">#hashtag</a>
    pattern = re.compile(r'#(\w+)\b')
    def _repl(match: re.Match) -> str:
        tag = match.group(1)
        return f'<a href="/hashtag/{tag}" class="hashtag-link">#{tag}</a>'
    linked = pattern.sub(_repl, str(escaped))
    return Markup(linked)


# ========= Analytics dashboard =========
@app.route('/analytics')
@login_required
def analytics_dashboard():
    """Analytics for the logged-in artist (only visible to self)."""
    artist_id = current_user.id

    # Helper: last N day labels matching our stored created_at format
    def last_n_days(n: int):
        days = []
        for i in range(n - 1, -1, -1):
            d = datetime.today().date() - timedelta(days=i)
            days.append(d.strftime('%B %d, %Y'))
        return days

    from datetime import timedelta

    # Views
    product_views = db.session.execute(
        db.select(ProductView).where(ProductView.artist_id == artist_id)
    ).scalars().all()
    profile_views = db.session.execute(
        db.select(ProfileView).where(ProfileView.profile_user_id == artist_id)
    ).scalars().all()

    total_product_views = len(product_views)
    total_profile_views = len(profile_views)

    # Views trend (last 30 days)
    days30 = last_n_days(30)
    product_views_daily = [sum(1 for v in product_views if (v.created_at or '') == d) for d in days30]
    profile_views_daily = [sum(1 for v in profile_views if (v.created_at or '') == d) for d in days30]

    # Engagement
    artist_posts = db.session.execute(db.select(Posts).where(Posts.artist_id == artist_id)).scalars().all()
    post_ids = [p.post_id for p in artist_posts]
    total_post_likes = 0
    total_post_comments = 0
    if post_ids:
        total_post_likes = db.session.execute(
            db.select(db.func.count(PostLike.id)).where(PostLike.post_id.in_(post_ids))
        ).scalar() or 0
        total_post_comments = db.session.execute(
            db.select(db.func.count(Comments.comment_id)).where(Comments.post_id.in_(post_ids))
        ).scalar() or 0

    artist_products = db.session.execute(db.select(Product).where(Product.artist_id == artist_id)).scalars().all()
    product_ids = [p.product_id for p in artist_products]
    total_product_reviews = 0
    total_product_comments = 0
    if product_ids:
        total_product_reviews = db.session.execute(
            db.select(db.func.count(ProductReview.review_id)).where(ProductReview.product_id.in_(product_ids))
        ).scalar() or 0
        total_product_comments = db.session.execute(
            db.select(db.func.count(ProductComments.comment_id)).where(ProductComments.product_id.in_(product_ids))
        ).scalar() or 0

    # Sales & revenue
    oi_rows = []
    total_orders = 0
    paid_revenue = 0.0
    total_revenue = 0.0
    items_sold = 0

    if product_ids:
        # Join OrderItem -> Product -> Order
        join_stmt = (
            db.select(OrderItem, Order).join(Product, OrderItem.product_id == Product.product_id)
            .join(Order, OrderItem.order_id == Order.order_id)
            .where(Product.artist_id == artist_id)
        )
        result = db.session.execute(join_stmt).all()
        # Aggregate
        orders_seen = set()
        for oi, order in result:
            oi_rows.append({'oi': oi, 'order': order})
            total_revenue += float(oi.total_price or 0)
            items_sold += int(oi.quantity or 0)
            if order.order_id not in orders_seen:
                orders_seen.add(order.order_id)
            if (order.payment_status or '').lower() == 'paid' or (order.status or '').lower() in {'paid', 'shipped', 'delivered'}:
                paid_revenue += float(oi.total_price or 0)
        total_orders = len(orders_seen)

    # Revenue trend (last 30 days)
    revenue_daily = []
    for d in days30:
        rev = 0.0
        for row in oi_rows:
            if (row['order'].created_at or '') == d and ((row['order'].payment_status or '').lower() == 'paid' or (row['order'].status or '').lower() in {'paid', 'shipped', 'delivered'}):
                rev += float(row['oi'].total_price or 0)
        revenue_daily.append(rev)

    # Popular items
    # Top products by views
    top_product_views = {}
    for v in product_views:
        top_product_views[v.product_id] = top_product_views.get(v.product_id, 0) + 1
    top_products_by_views = []
    for pid, cnt in sorted(top_product_views.items(), key=lambda x: x[1], reverse=True)[:5]:
        prod = db.session.get(Product, pid)
        if prod:
            top_products_by_views.append({'title': prod.title, 'count': cnt, 'id': pid})

    # Top products by sales
    sales_by_product = {}
    for row in oi_rows:
        oi, order = row['oi'], row['order']
        sales_by_product[oi.product_id] = sales_by_product.get(oi.product_id, 0) + int(oi.quantity or 0)
    top_products_by_sales = []
    for pid, cnt in sorted(sales_by_product.items(), key=lambda x: x[1], reverse=True)[:5]:
        prod = db.session.get(Product, pid)
        if prod:
            top_products_by_sales.append({'title': prod.title, 'count': cnt, 'id': pid})

    # Top posts by engagement (likes + comments)
    post_eng = []
    for p in artist_posts:
        likes = db.session.execute(db.select(db.func.count(PostLike.id)).where(PostLike.post_id == p.post_id)).scalar() or 0
        comments = db.session.execute(db.select(db.func.count(Comments.comment_id)).where(Comments.post_id == p.post_id)).scalar() or 0
        post_eng.append({'title': p.post_title or f'Post #{p.post_id}', 'score': (likes + comments), 'id': p.post_id})
    top_posts_by_engagement = sorted(post_eng, key=lambda x: x['score'], reverse=True)[:5]

    # KPIs
    kpis = {
        'views': total_product_views + total_profile_views,
        'engagement': total_post_likes + total_post_comments + total_product_reviews + total_product_comments,
        'sales': items_sold,
        'revenue': paid_revenue
    }

    return render_template(
        'analytics.html',
        current_user=current_user,
        kpis=kpis,
        days=days30,
        product_views_daily=product_views_daily,
        profile_views_daily=profile_views_daily,
        revenue_daily=revenue_daily,
        total_orders=total_orders,
        total_revenue=total_revenue,
        paid_revenue=paid_revenue,
        items_sold=items_sold,
        top_products_by_views=top_products_by_views,
        top_products_by_sales=top_products_by_sales,
        top_posts_by_engagement=top_posts_by_engagement
    )


@app.route('/analytics/insights')
@login_required
def analytics_insights():
    """Generate AI-powered insights for the logged-in artisan."""
    try:
        artist_id = current_user.id
        
        # Fetch artisan's products with reviews and ratings
        products = db.session.execute(
            db.select(Product).where(Product.artist_id == artist_id)
        ).scalars().all()
        
        products_data = []
        for p in products:
            # Count views for this product
            views_count = db.session.execute(
                db.select(db.func.count(ProductView.id))
                .where(ProductView.product_id == p.product_id)
            ).scalar() or 0
            
            # Count reviews
            reviews_count = db.session.execute(
                db.select(db.func.count(ProductReview.review_id))
                .where(ProductReview.product_id == p.product_id)
            ).scalar() or 0
            
            # Calculate average rating
            avg_rating = db.session.execute(
                db.select(db.func.avg(ProductReview.rating))
                .where(ProductReview.product_id == p.product_id)
            ).scalar() or 0.0
            
            products_data.append({
                'title': p.title or 'Untitled',
                'description': p.description or '',
                'price': float(p.price or 0),
                'views': views_count,
                'reviews': reviews_count,
                'avg_rating': float(avg_rating)
            })
        
        # Fetch artisan's posts with engagement
        posts = db.session.execute(
            db.select(Posts).where(Posts.artist_id == artist_id)
        ).scalars().all()
        
        posts_data = []
        for p in posts:
            likes_count = db.session.execute(
                db.select(db.func.count(PostLike.id))
                .where(PostLike.post_id == p.post_id)
            ).scalar() or 0
            
            comments_count = db.session.execute(
                db.select(db.func.count(Comments.comment_id))
                .where(Comments.post_id == p.post_id)
            ).scalar() or 0
            
            posts_data.append({
                'title': p.post_title or 'Untitled',
                'likes': likes_count,
                'comments': comments_count
            })
        
        # Calculate revenue and sales
        product_ids = [p.product_id for p in products]
        total_orders = 0
        items_sold = 0
        total_revenue = 0.0
        paid_revenue = 0.0
        
        if product_ids:
            join_stmt = (
                db.select(OrderItem, Order)
                .join(Product, OrderItem.product_id == Product.product_id)
                .join(Order, OrderItem.order_id == Order.order_id)
                .where(Product.artist_id == artist_id)
            )
            result = db.session.execute(join_stmt).all()
            
            orders_seen = set()
            for oi, order in result:
                total_revenue += float(oi.total_price or 0)
                items_sold += int(oi.quantity or 0)
                
                if order.order_id not in orders_seen:
                    orders_seen.add(order.order_id)
                
                if (order.payment_status or '').lower() == 'paid' or (order.status or '').lower() in {'paid', 'shipped', 'delivered'}:
                    paid_revenue += float(oi.total_price or 0)
            
            total_orders = len(orders_seen)
        
        # Calculate total engagement
        total_likes = sum(p['likes'] for p in posts_data)
        total_comments = sum(p['comments'] for p in posts_data)
        total_reviews = sum(p['reviews'] for p in products_data)
        
        # Get top performing products
        top_products = sorted(products_data, key=lambda x: x['views'], reverse=True)[:3]
        top_products_formatted = [
            {'title': p['title'], 'metric': f"{p['views']} views"}
            for p in top_products
        ]
        
        # Check if there's enough data to generate insights
        if len(products_data) == 0 and len(posts_data) == 0:
            return jsonify({
                'success': False,
                'error': 'Not enough data to generate insights. Create some products or posts first!'
            }), 400
        
        # Prepare data for AI
        artisan_data = {
            'products': products_data,
            'posts': posts_data,
            'revenue': {
                'total_orders': total_orders,
                'items_sold': items_sold,
                'total': total_revenue,
                'paid': paid_revenue
            },
            'engagement': {
                'total_likes': total_likes,
                'total_comments': total_comments,
                'total_reviews': total_reviews
            },
            'top_products': top_products_formatted
        }
        
        # Get Groq API key from environment
        groq_api_key = os.environ.get('GROQ_API_KEY', 'your_groq_api_key_here')
        
        # Log for debugging
        print(f"Generating insights for artist {artist_id}")
        print(f"Data: {len(products_data)} products, {len(posts_data)} posts")
        
        # Generate insights
        result = ai.generate_artisan_insights(artisan_data, groq_api_key)
        
        if not result.get('ok'):
            return jsonify({
                'success': False,
                'error': result.get('error', 'Failed to generate insights')
            }), 500
        
        return jsonify({
            'success': True,
            'insights': result.get('insights', {})
        })
        
    except Exception as e:
        # Log the full error for debugging
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in analytics_insights: {error_details}")
        
        return jsonify({
            'success': False,
            'error': f'Error generating insights: {str(e)}'
        }), 500


@app.route('/analytics/competitive-pricing')
@login_required
def competitive_pricing_analysis():
    """AI-powered competitive pricing analysis based on product similarity."""
    try:
        artist_id = current_user.id
        include_external = request.args.get('external', 'false').lower() == 'true'
        
        # Get artisan's products
        artist_products = db.session.execute(
            db.select(Product).where(Product.artist_id == artist_id)
        ).scalars().all()
        
        if not artist_products:
            return jsonify({
                'success': False,
                'error': 'You need to create some products first to see competitive pricing analysis.'
            }), 400
        
        # Use the first product or most expensive product for analysis
        product_to_analyze = max(artist_products, key=lambda p: float(p.price or 0))
        
        # Calculate artist's average price
        artist_prices = [float(p.price or 0) for p in artist_products if p.price]
        artist_avg_price = sum(artist_prices) / len(artist_prices) if artist_prices else 0
        artist_min_price = min(artist_prices) if artist_prices else 0
        artist_max_price = max(artist_prices) if artist_prices else 0
        
        # Get all other products from marketplace (competitors)
        competitors_products = db.session.execute(
            db.select(Product)
            .where(Product.artist_id != artist_id)
            .where(Product.price.isnot(None))
            .order_by(Product.created_at.desc())
            .limit(50)  # Get recent products for AI analysis
        ).scalars().all()
        
        if not competitors_products:
            return jsonify({
                'success': False,
                'error': 'Not enough marketplace data yet for comparison.'
            }), 400
        
        # Prepare data for AI analysis
        product_data = {
            'title': product_to_analyze.title or 'Unknown',
            'description': product_to_analyze.description or '',
            'price': float(product_to_analyze.price or 0)
        }
        
        marketplace_data = []
        for p in competitors_products:
            artist = db.session.get(User, p.artist_id)
            marketplace_data.append({
                'title': p.title or 'Unknown',
                'description': p.description or '',
                'price': float(p.price or 0),
                'artist_name': artist.name if artist else 'Unknown',
                'product_id': p.product_id,
                'img_url': p.img_url
            })
        
        # Get Groq API key
        groq_api_key = os.environ.get('GROQ_API_KEY', 'your_groq_api_key_here')
        
        # Use AI to find similar products
        print(f"Analyzing product: {product_to_analyze.title}")
        print(f"Against {len(marketplace_data)} marketplace products")
        print(f"Include external sources: {include_external}")
        
        ai_result = ai.find_similar_products_and_pricing(
            product_data,
            marketplace_data,
            groq_api_key,
            include_external
        )
        
        if not ai_result.get('ok'):
            return jsonify({
                'success': False,
                'error': ai_result.get('error', 'Failed to analyze products')
            }), 500
        
        ai_analysis = ai_result.get('analysis', {})
        
        # Build similar products list with full details
        similar_products = []
        similar_indices = [item.get('index', 0) - 1 for item in ai_analysis.get('similar_products', [])]
        
        for idx, item in enumerate(ai_analysis.get('similar_products', [])):
            product_idx = item.get('index', 1) - 1
            if 0 <= product_idx < len(marketplace_data):
                p_data = marketplace_data[product_idx]
                p = competitors_products[product_idx]
                
                # Get review stats
                reviews = db.session.execute(
                    db.select(ProductReview).where(ProductReview.product_id == p.product_id)
                ).scalars().all()
                
                avg_rating = sum(r.rating for r in reviews) / len(reviews) if reviews else 0
                
                similar_products.append({
                    'product_id': p_data['product_id'],
                    'title': p_data['title'],
                    'price': p_data['price'],
                    'img_url': p_data['img_url'],
                    'artist_name': p_data['artist_name'],
                    'reviews_count': len(reviews),
                    'avg_rating': round(avg_rating, 1),
                    'price_difference': round(((p_data['price'] - product_data['price']) / product_data['price']) * 100, 1) if product_data['price'] > 0 else 0,
                    'similarity_score': item.get('similarity_score', 0),
                    'similarity_reason': item.get('reason', 'AI-matched similarity')
                })
        
        # Calculate market statistics
        market_prices = [float(p.price) for p in competitors_products if p.price]
        market_avg_price = sum(market_prices) / len(market_prices) if market_prices else 0
        market_median_price = sorted(market_prices)[len(market_prices)//2] if market_prices else 0
        
        # Get similar products' average price
        similar_prices = [p['price'] for p in similar_products]
        similar_avg_price = ai_analysis.get('pricing_analysis', {}).get('similar_avg_price', 
                                            sum(similar_prices) / len(similar_prices) if similar_prices else 0)
        
        # Build response
        response_data = {
            'your_products': {
                'count': len(artist_products),
                'avg_price': round(artist_avg_price, 2),
                'min_price': round(artist_min_price, 2),
                'max_price': round(artist_max_price, 2),
                'analyzed_product': product_to_analyze.title
            },
            'market': {
                'avg_price': round(market_avg_price, 2),
                'median_price': round(market_median_price, 2),
                'total_products': len(competitors_products)
            },
            'positioning': {
                'difference_percent': round(((product_data['price'] - similar_avg_price) / similar_avg_price * 100), 1) if similar_avg_price > 0 else 0,
                'label': ai_analysis.get('pricing_analysis', {}).get('your_position', 'competitive').title() + ' Pricing',
                'advice': ai_analysis.get('pricing_analysis', {}).get('recommendation', 'Your pricing is competitive.')
            },
            'similar_products': similar_products
        }
        
        # Add external market data if requested
        if include_external and 'external_market' in ai_analysis:
            response_data['external_market'] = ai_analysis['external_market']
        
        return jsonify({
            'success': True,
            'analysis': response_data,
            'ai_powered': True
        })
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in competitive_pricing_analysis: {error_details}")
        
        return jsonify({
            'success': False,
            'error': f'Error analyzing competitive pricing: {str(e)}'
        }), 500


# ========= Messaging routes =========
@app.route('/messages/start', methods=['POST'])
@login_required
def start_conversation():
    """Create or open a conversation for a product between buyer and seller; add first message."""
    try:
        product_id_raw = request.form.get('product_id', '')
        message_body = (request.form.get('message') or '').strip()
        product_id = int(product_id_raw) if product_id_raw else None

        if not product_id:
            return jsonify({'success': False, 'message': 'Missing product id'}), 400

        product = db.get_or_404(Product, product_id)
        seller_id = product.artist_id
        buyer_id = current_user.id

        if buyer_id == seller_id:
            return jsonify({'success': False, 'message': "You can't message yourself about your own product."}), 400

        if not message_body and 'attachment' not in request.files:
            return jsonify({'success': False, 'message': 'Please enter a message or attach a file.'}), 400

        # Find or create conversation
        existing = db.session.execute(
            db.select(Conversation).where(
                Conversation.product_id == product_id,
                Conversation.buyer_id == buyer_id,
                Conversation.seller_id == seller_id
            )
        ).scalar_one_or_none()

        if existing:
            conv = existing
        else:
            conv = Conversation(
                product_id=product_id,
                buyer_id=buyer_id,
                seller_id=seller_id,
                status='open',
                created_at=date.today().strftime('%B %d, %Y'),
                last_message_at=date.today().strftime('%B %d, %Y')
            )
            db.session.add(conv)
            db.session.flush()  # get id

        # Handle attachment (optional)
        attachment_url = None
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file and file.filename:
                uploaded = save_uploaded_file(file, 'messages')
                if uploaded:
                    attachment_url = uploaded

        msg = Message(
            conversation_id=conv.id,
            sender_id=current_user.id,
            body=message_body,
            attachment_url=attachment_url,
            created_at=date.today().strftime('%B %d, %Y')
        )
        conv.last_message_at = msg.created_at
        db.session.add(msg)
        db.session.commit()

        # Response
        url = url_for('view_conversation', conversation_id=conv.id)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'conversation_id': conv.id, 'url': url})
        return redirect(url)
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


@app.route('/messages/<int:conversation_id>')
@login_required
def view_conversation(conversation_id: int):
    conv = db.get_or_404(Conversation, conversation_id)
    # Authorization: must be a participant
    if current_user.id not in (conv.buyer_id, conv.seller_id):
        abort(403)

    # Mark all unread messages from the other user as read
    unread_messages = db.session.execute(
        db.select(Message).where(
            Message.conversation_id == conv.id,
            Message.sender_id != current_user.id,
            Message.read_at == None
        )
    ).scalars().all()
    
    if unread_messages:
        current_time = datetime.now().strftime('%B %d, %Y %H:%M:%S')
        for msg in unread_messages:
            msg.read_at = current_time
        db.session.commit()

    # Load messages ordered by id asc
    messages = db.session.execute(
        db.select(Message).where(Message.conversation_id == conv.id).order_by(Message.id.asc())
    ).scalars().all()

    # Load the other user (counterparty)
    other_user_id = conv.seller_id if current_user.id == conv.buyer_id else conv.buyer_id
    other_user = db.session.get(User, other_user_id)

    product = db.session.get(Product, conv.product_id) if conv.product_id else None

    return render_template('conversation.html',
                           current_user=current_user,
                           conv=conv,
                           product=product,
                           messages=messages,
                           other_user=other_user)


@app.route('/messages/<int:conversation_id>/send', methods=['POST'])
@login_required
def send_message(conversation_id: int):
    conv = db.get_or_404(Conversation, conversation_id)
    if current_user.id not in (conv.buyer_id, conv.seller_id):
        abort(403)

    body = (request.form.get('message') or '').strip()
    if not body and 'attachment' not in request.files:
        flash('Please type a message or attach a file.')
        return redirect(url_for('view_conversation', conversation_id=conversation_id))

    attachment_url = None
    if 'attachment' in request.files:
        file = request.files['attachment']
        if file and file.filename:
            up = save_uploaded_file(file, 'messages')
            if up:
                attachment_url = up

    msg = Message(
        conversation_id=conv.id,
        sender_id=current_user.id,
        body=body,
        attachment_url=attachment_url,
        created_at=date.today().strftime('%B %d, %Y')
    )
    conv.last_message_at = msg.created_at
    db.session.add(msg)
    db.session.commit()

    return redirect(url_for('view_conversation', conversation_id=conversation_id))


@app.route('/', methods=["GET", "POST"])
def home():
    # Optional natural language query parsing for posts
    q = (request.args.get('q') or '').strip()
    posts_query = db.select(Posts)
    if q:
        parsed = natural_search.parse_search_query(q)
        tokens = parsed.get('keywords', [])
        # Apply text filters across title/description
        joined_artist = False
        for tk in tokens:
            like = f"%{tk}%"
            if not joined_artist:
                posts_query = posts_query.join(Posts.artist)
                joined_artist = True
            posts_query = posts_query.where(
                (Posts.post_title.ilike(like)) | (Posts.description.ilike(like)) | (User.name.ilike(like))
            )
    result = db.session.execute(posts_query)
    posts = result.scalars().all()

    # Load comments per post and attach a simple comments list (with author info)
    for post in posts:
            # Linkify hashtags in post description
            if post.description:
                post.description = linkify_hashtags(post.description)
        
            comments_rows = db.session.execute(db.select(Comments).where(Comments.post_id == post.post_id)).scalars().all()
            comments_data = []
            for c in comments_rows:
                author = db.session.get(User, c.user_id)
                comments_data.append({
                    'id': c.comment_id,
                    'content': c.content,
                    'created_at': c.created_at,
                    'artist': {
                        'name': getattr(author, 'name', 'Unknown') if author else 'Unknown',
                        'email': getattr(author, 'email', '') if author else '',
                        'id': getattr(author, 'id', None) if author else None,
                    }
                })
            # Attach to post object so template can use post.comments
            setattr(post, 'comments', comments_data)

    return render_template("index.html", posts=posts, current_user=current_user, q=q)


@app.route('/products')
def products_page():
    # Optional natural language query parsing for products
    q = (request.args.get('q') or '').strip()
    sort_by = (request.args.get('sort') or 'newest').strip().lower()
    
    prod_query = db.select(Product)
    if q:
        parsed = natural_search.parse_search_query(q)
        tokens = parsed.get('keywords', [])
        max_price = parsed.get('max_price')
        min_price = parsed.get('min_price')
        joined_artist = False
        for tk in tokens:
            like = f"%{tk}%"
            if not joined_artist:
                prod_query = prod_query.join(Product.artist)
                joined_artist = True
            prod_query = prod_query.where(
                (Product.title.ilike(like)) | (Product.description.ilike(like)) | (User.name.ilike(like))
            )
        if max_price is not None:
            try:
                # Product.price is Numeric; cast comparison directly
                prod_query = prod_query.where(Product.price <= max_price)
            except Exception:
                pass
        if min_price is not None:
            try:
                prod_query = prod_query.where(Product.price >= min_price)
            except Exception:
                pass
    
    result = db.session.execute(prod_query)
    products = result.scalars().all()
    
    # Attach avg rating and review count to each product
    for product in products:
            # Linkify hashtags in product description
            if product.description:
                product.description = linkify_hashtags(product.description)
        
            reviews_rows = db.session.execute(
                db.select(ProductReview).where(ProductReview.product_id == product.product_id)
            ).scalars().all()
            total_rating = sum(int(r.rating or 0) for r in reviews_rows)
            avg_rating = (total_rating / len(reviews_rows)) if reviews_rows else 0
            setattr(product, 'avg_rating', avg_rating)
            setattr(product, 'reviews_count', len(reviews_rows))
    
    # Apply sorting
    if sort_by == 'popular':
        # Sort by average rating (descending), then by review count
        products.sort(key=lambda p: (p.avg_rating, p.reviews_count), reverse=True)
    elif sort_by == 'price_low':
        # Sort by price ascending
        products.sort(key=lambda p: float(p.price or 0))
    elif sort_by == 'price_high':
        # Sort by price descending
        products.sort(key=lambda p: float(p.price or 0), reverse=True)
    else:  # newest (default)
        # Sort by product_id descending (most recent first)
        products.sort(key=lambda p: p.product_id, reverse=True)
    
    return render_template('products.html', products=products, current_user=current_user, q=q, sort_by=sort_by)


@app.route("/login", methods=["GET", "POST"])
def login():
    # Get next page from query params
    next_page = request.args.get('next')
    
    # Debug/logging: show incoming request characteristics for Firebase flows
    try:
        print(f"[Auth][login] Incoming request: method={request.method}, content_type={request.content_type}, is_json={request.is_json}")
        if request.is_json:
            try:
                print("[Auth][login] request.json=", request.get_json())
            except Exception as _:
                print("[Auth][login] request.get_json() failed")
        else:
            print("[Auth][login] form keys=", dict(request.form))
        # Print cookie header presence (not full cookie for privacy)
        print("[Auth][login] Cookie header present:", bool(request.headers.get('Cookie')))
    except Exception as _:
        pass

    if request.method == "POST":
        # Check if Firebase ID token is provided (modern auth)
        firebase_token = request.form.get('firebase_token') or request.json.get('firebase_token') if request.is_json else None
        
        if firebase_token:
            # Firebase authentication flow
            decoded_token = firebase_config.verify_firebase_token(firebase_token)
            if decoded_token:
                firebase_uid = decoded_token.get('uid')
                email = decoded_token.get('email')
                if email:
                    email = email.strip().lower()
                phone = decoded_token.get('phone_number')
                name = decoded_token.get('name', email.split('@')[0] if email else 'User')
                
                # Find or create user
                user = db.session.execute(db.select(User).where(User.email == email)).scalar()
                if not user:
                    user = User(
                        name=name,
                        email=email,
                        phone=phone,
                        password_hash='',  # Firebase handles auth, no password needed
                        is_verified=bool(decoded_token.get('email_verified')),
                        created_at=date.today().strftime("%B %d, %Y")
                    )
                    db.session.add(user)
                    db.session.commit()
                    print(f"[Auth] Created new user from Firebase: email={email}, uid={firebase_uid}")
                else:
                    print(f"[Auth] Existing user logged in: email={email}")
                
                login_user(user)
                print(f"[Auth] login_user successful for: {email}")
                
                if request.is_json:
                    return jsonify({'success': True, 'redirect': next_page or url_for('home')})
                
                if next_page and next_page.startswith('/'):
                    return redirect(next_page)
                return redirect(url_for('home'))
            else:
                if request.is_json:
                    return jsonify({'success': False, 'error': 'Invalid Firebase token'}), 401
                flash('Authentication failed. Please try again.')
        else:
            # Legacy email/password flow (fallback)
            email = request.form.get('email')
            password = request.form.get('password')
            user = db.session.execute(db.select(User).where(User.email == email)).scalar()

            if user and password and user.password_hash and check_password_hash(user.password_hash, password):
                login_user(user)
                if next_page and next_page.startswith('/'):
                    return redirect(next_page)
                return redirect(url_for('home'))
            else:
                flash('Invalid email or password')

    return render_template("login.html", current_user=current_user, firebase_config=firebase_config.FIREBASE_WEB_CONFIG)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


@app.route("/delete_account", methods=["POST"])
@login_required
def delete_account():
    """
    Delete user account from local database and Firebase Authentication.
    Also deletes all associated posts, products, and other user data.
    """
    try:
        user_id = current_user.id
        user_email = current_user.email
        # Optional Firebase ID token from client, for REST deletion fallback
        payload = request.get_json(silent=True) or {}
        client_id_token = payload.get('firebase_token')
        
        # 1. Delete from Firebase Authentication (if user was created via Firebase)
        if user_email or client_id_token:
            # Try delete via Admin SDK (email) or REST (idToken) using helper
            try:
                from firebase_config import delete_firebase_user
                success, msg = delete_firebase_user(email=user_email, id_token=client_id_token)
                print(f"[DeleteAccount] Firebase delete: success={success}, msg={msg}")
            except Exception as e:
                print(f"[DeleteAccount] Firebase deletion attempt failed: {e}")
        
        # 2. Delete all user data from local database
        # Note: Most relations have CASCADE delete configured, but we'll be explicit
        
        # Delete user's posts (CASCADE will handle post_likes, comments, post_hashtags)
        Posts.query.filter_by(artist_id=user_id).delete(synchronize_session=False)
        
        # Delete user's products (CASCADE will handle product_comments, product_reviews, product_hashtags, cart_items with this product)
        Product.query.filter_by(artist_id=user_id).delete(synchronize_session=False)
        
        # Delete user's comments on other posts
        Comments.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        
        # Delete user's post likes
        PostLike.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        
        # Delete user's product comments
        ProductComments.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        
        # Delete user's product reviews
        ProductReview.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        
        # Delete user's cart (CASCADE will handle cart_items)
        Cart.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        
        # Delete user's orders (CASCADE will handle order_items and payments)
        Order.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        
        # Delete follow relationships
        Follow.query.filter((Follow.follower_id == user_id) | (Follow.followed_id == user_id)).delete(synchronize_session=False)
        
        # Delete conversations and messages (buyer/seller based)
        conversations = Conversation.query.filter(
            (Conversation.buyer_id == user_id) | (Conversation.seller_id == user_id)
        ).all()
        for conv in conversations:
            # Messages have relationship cascade, but explicitly clear to be safe
            Message.query.filter_by(conversation_id=conv.id).delete(synchronize_session=False)
            db.session.delete(conv)
        
        # Delete product and profile views (for both artist and viewer roles)
        ProductView.query.filter(
            (ProductView.artist_id == user_id) | (ProductView.viewer_id == user_id)
        ).delete(synchronize_session=False)
        ProfileView.query.filter_by(viewer_id=user_id).delete(synchronize_session=False)
        ProfileView.query.filter_by(profile_user_id=user_id).delete(synchronize_session=False)
        
        # Delete user's cart(s) and items using ORM cascade (avoid bulk delete bypassing cascade)
        user_carts = Cart.query.filter_by(user_id=user_id).all()
        for cart in user_carts:
            db.session.delete(cart)

        # Delete user's orders with items and payments
        user_orders = Order.query.filter_by(user_id=user_id).all()
        for order in user_orders:
            # Explicitly delete related payments and items for safety
            Payment.query.filter_by(order_id=order.order_id).delete(synchronize_session=False)
            OrderItem.query.filter_by(order_id=order.order_id).delete(synchronize_session=False)
            db.session.delete(order)

        # Finally, delete the user
        user = db.session.get(User, user_id) if hasattr(db.session, "get") else User.query.get(user_id)
        db.session.delete(user)
        
        # Commit all deletions
        db.session.commit()
        
        # Logout the user
        logout_user()
        
        flash('Your account has been permanently deleted.')
        print(f"[DeleteAccount] Successfully deleted user {user_email} (ID: {user_id})")
        
        return jsonify({'success': True, 'redirect': url_for('home')})
        
    except Exception as e:
        db.session.rollback()
        import traceback
        print(f"[DeleteAccount] Error deleting account: {e}")
        print(f"[DeleteAccount] Full traceback:")
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Failed to delete account. Please try again.'}), 500


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        # Check if Firebase ID token is provided (modern auth)
        firebase_token = request.form.get('firebase_token') or request.json.get('firebase_token') if request.is_json else None
        
        if firebase_token:
            # Firebase authentication flow (same as login - auto-creates user)
            decoded_token = firebase_config.verify_firebase_token(firebase_token)
            if decoded_token:
                firebase_uid = decoded_token.get('uid')
                email = decoded_token.get('email')
                if email:
                    email = email.strip().lower()
                phone_from_token = decoded_token.get('phone_number')
                name_from_token = decoded_token.get('name')
                
                # Get additional data from request if provided
                if request.is_json:
                    name = request.json.get('name') or name_from_token or (email.split('@')[0] if email else 'User')
                    phone = request.json.get('phone') or phone_from_token or ''
                else:
                    name = request.form.get('name') or name_from_token or (email.split('@')[0] if email else 'User')
                    phone = request.form.get('phone') or phone_from_token or ''
                
                # Check if user already exists
                user = db.session.execute(db.select(User).where(User.email == email)).scalar()
                if user:
                    if request.is_json:
                        return jsonify({'success': False, 'error': 'User already exists'}), 400
                    flash('Email already registered. Please login.')
                    return redirect(url_for('login'))
                
                # Create new user
                user = User(
                    name=name,
                    email=email,
                    phone=phone,
                    password_hash='',  # Firebase handles auth
                    is_verified=bool(decoded_token.get('email_verified')),
                    created_at=date.today().strftime("%B %d, %Y")
                )
                db.session.add(user)
                db.session.commit()
                
                login_user(user)
                
                if request.is_json:
                    return jsonify({'success': True, 'redirect': url_for('home')})
                return redirect(url_for('home'))
            else:
                if request.is_json:
                    return jsonify({'success': False, 'error': 'Invalid Firebase token'}), 401
                flash('Authentication failed. Please try again.')
        else:
            # Legacy flow (fallback for email/password)
            name = request.form.get('name')
            email = request.form.get('email')
            password = request.form.get('password')
            phone = request.form.get('phone')
            location = request.form.get('location')

            # Check if user already exists
            existing_user = db.session.execute(db.select(User).where(User.email == email)).scalar()
            if existing_user:
                flash('Email already registered')
                return render_template("register.html", current_user=current_user, firebase_config=firebase_config.FIREBASE_WEB_CONFIG)

            # Create new user
            if not password:
                flash('Password is required')
                return render_template("register.html", current_user=current_user, firebase_config=firebase_config.FIREBASE_WEB_CONFIG)

            new_user = User(
                name=name,
                email=email,
                password_hash=generate_password_hash(password),
                phone=phone,
                location=location,
                created_at=date.today().strftime("%B %d, %Y")
            )
            db.session.add(new_user)
            db.session.commit()

            login_user(new_user)
            return redirect(url_for('home'))

    return render_template("register.html", current_user=current_user, firebase_config=firebase_config.FIREBASE_WEB_CONFIG)


@app.route("/add", methods=["GET", "POST"])
@login_required
def add_posts():
    post_id = request.args.get('post_id')
    post = None
    if post_id:
        post = db.get_or_404(Posts, post_id)
        # Check if user owns this post
        if post.artist_id != current_user.id:
            abort(403)

    if request.method == 'POST':
        post_id = request.form.get('post_id')
        if post_id:
            post = db.get_or_404(Posts, post_id)
            # Check if user owns this post
            if post.artist_id != current_user.id:
                abort(403)

        # Handle image upload
        media_url = request.form.get('post_image', '')

        # Check if file was uploaded
        if 'post_image_file' in request.files:
            file = request.files['post_image_file']
            if file.filename != '':
                uploaded_path = save_uploaded_file(file, 'posts')
                if uploaded_path:
                    media_url = uploaded_path
                    
        # For editing, keep existing image if no new one provided
        if not media_url and post:
            media_url = post.media_url
        # For new posts, enforce image requirement
        elif not media_url and not post:
            message = 'Please provide an image URL or upload an image for the post.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': message})
            flash(message)
            return render_template("add_posts.html", current_user=current_user, post=post)

        if post:
            # Update existing post
            post.post_title = request.form['post_title']
            post.description = request.form['description']
            if media_url:  # Only update image if new one provided
                post.media_url = media_url
            post.is_promoted = request.form.get('is_promoted') == 'True'
        else:
            # Create new post
            post = Posts(
                artist_id=current_user.id,
                post_title=request.form['post_title'],
                description=request.form['description'],
                media_url=media_url,
                created_at=date.today().strftime("%B %d, %Y"),
                is_promoted=request.form.get('is_promoted') == 'True'
            )
            db.session.add(post)

        try:
            db.session.commit()
            
            # Extract and save hashtags from title and description
            combined_text = f"{request.form['post_title']} {request.form['description']}"
            save_hashtags_for_post(post.post_id, combined_text)
            db.session.commit()
            
            # If it's an AJAX request, return JSON response
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': True,
                    'message': 'Post updated successfully',
                    'post': {
                        'post_title': post.post_title,
                        'description': post.description or '',
                        'media_url': media_url if media_url != post.media_url else None
                    }
                })
            
            # For regular form submissions, redirect to home
            return redirect(url_for('home'))
        except Exception as e:
            db.session.rollback()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': False,
                    'message': str(e)
                }), 400
            flash('Error updating post: ' + str(e))
            return redirect(url_for('home'))
    
    # Pre-fill from query parameters for promotion or editing
    title = request.args.get('title', '')
    description = request.args.get('description', '')
    media_url = request.args.get('media_url', '')
    is_promoted = request.args.get('is_promoted', 'False')
    
    return render_template("add_posts.html", current_user=current_user, post=post, title=title, description=description, media_url=media_url, is_promoted=is_promoted)


@app.route("/promote_product/<int:product_id>", methods=["POST"])
@login_required
def promote_product(product_id):
    product = db.get_or_404(Product, product_id)
    if product.artist_id != current_user.id:
        abort(403)
    
    return redirect(url_for('add_posts', 
                            title=product.title, 
                            description=product.description, 
                            media_url=product.img_url,
                            is_promoted='True'))


@app.route("/add_products", methods=["GET", "POST"])
@login_required
def add_products():
    product_id = request.args.get('product_id')
    product = None
    if product_id:
        product = db.get_or_404(Product, product_id)
        # Check if user owns this product
        if product.artist_id != current_user.id:
            abort(403)

    if request.method == 'POST':
        # Handle image upload
        img_url = request.form.get('product_image', '')

        # Check if file was uploaded
        if 'product_image_file' in request.files:
            file = request.files['product_image_file']
            if file.filename != '':
                uploaded_path = save_uploaded_file(file, 'products')
                if uploaded_path:
                    img_url = uploaded_path

        # For editing, keep existing image if no new one provided
        if not img_url and product:
            img_url = product.img_url
        # For new products, enforce image requirement
        elif not img_url and not product:
            message = 'Please provide an image URL or upload an image for the product.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': message})
            flash(message)
            return render_template("add_products.html", current_user=current_user, product=product)

        if product:
            # Update existing product
            product.title = request.form['product_name']
            product.description = request.form.get('description', '')
            product.price = request.form['price']
            if img_url:  # Only update image if new one provided
                product.img_url = img_url
        else:
            # Create new product
            product = Product(
                artist_id=current_user.id,
                title=request.form['product_name'],
                description=request.form.get('description', ''),
                price=request.form['price'],
                img_url=img_url,
                created_at=date.today().strftime("%B %d, %Y")
            )
            db.session.add(product)

        try:
            db.session.commit()
            
            # Extract and save hashtags from title and description
            combined_text = f"{request.form['product_name']} {request.form.get('description', '')}"
            save_hashtags_for_product(product.product_id, combined_text)
            db.session.commit()
            
            # If it's an AJAX request, return JSON response
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': True,
                    'message': 'Product updated successfully',
                    'product': {
                        'title': product.title,
                        'price': str(product.price),
                        'description': product.description or '',
                        'img_url': img_url if img_url != product.img_url else None
                    }
                })
            
            # For regular form submissions, redirect to product page
            return redirect(url_for('product_buy', product_id=product.product_id))
        except Exception as e:
            db.session.rollback()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': False,
                    'message': str(e)
                }), 400
            flash('Error updating product: ' + str(e))
            return redirect(url_for('product_buy', product_id=product.product_id))
    
    return render_template("add_products.html", current_user=current_user, product=product)


@app.route('/api/generate_copy', methods=['POST'])
@login_required
def generate_copy():
    """
    Endpoint to generate title/description suggestions using AI.
    """
    try:
        data = request.get_json(silent=True) or {}
        content_type = data.get('type', 'post')
        prompt = data.get('prompt', '')
        description = data.get('description', '')
        image_url = data.get('image_url', '')
        image_base64 = data.get('image_base64')
        image_mime = data.get('image_mime')

        # Call AI function
        result = ai.generate_copy_suggestions(
            content_type=content_type,
            prompt=prompt,
            description=description,
            image_url=image_url,
            image_base64=image_base64,
            image_mime=image_mime,
            api_key=GEMINI_API_KEY
        )

        if result['ok']:
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/translate_listing', methods=['POST'])
@login_required
def translate_listing():
    """
    Translate a listing's title/description into a target language and suggest SEO phrases.
    """
    try:
        data = request.get_json(silent=True) or {}
        content_type = data.get('type', 'post')
        title = data.get('title', '')
        description = data.get('description', '')
        target_lang = data.get('target_lang', '')
        locale = data.get('locale', '')
        source_lang = data.get('source_lang', '')

        # Call AI function
        result = ai.translate_listing(
            content_type=content_type,
            title=title,
            description=description,
            target_lang=target_lang,
            locale=locale,
            source_lang=source_lang,
            api_key=GEMINI_API_KEY
        )

        if result['ok']:
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/delete_post")
@login_required
def delete_posts():
    post_id = request.args.get('post_id')
    post_to_delete = db.get_or_404(Posts, post_id)
    db.session.delete(post_to_delete)
    db.session.commit()
    return redirect(url_for('home'))


@app.route("/delete_product")
@login_required
def delete_products():
    product_id = request.args.get('product_id')
    product_to_delete = db.get_or_404(Product, product_id)
    db.session.delete(product_to_delete)
    db.session.commit()
    return redirect(url_for('products_page'))


def calculate_artisan_rating(artist_id):
    """Calculate overall artisan rating based on all their products' ratings"""
    # Get all products by this artisan
    products = db.session.execute(db.select(Product).where(Product.artist_id == artist_id)).scalars().all()
    
    if not products:
        return {'avg_rating': 0, 'total_reviews': 0, 'total_products': 0}
    
    total_rating = 0
    total_reviews = 0
    
    # Aggregate ratings from all products
    for product in products:
        reviews = db.session.execute(
            db.select(ProductReview).where(ProductReview.product_id == product.product_id)
        ).scalars().all()
        
        for review in reviews:
            total_rating += int(review.rating or 0)
            total_reviews += 1
    
    avg_rating = round(total_rating / total_reviews, 1) if total_reviews > 0 else 0
    
    return {
        'avg_rating': avg_rating,
        'total_reviews': total_reviews,
        'total_products': len(products)
    }


@app.route("/profile")
@login_required
def profile():
    # Get current user's posts and products
    user_posts = db.session.execute(db.select(Posts).where(Posts.artist_id == current_user.id)).scalars().all()
    user_products = db.session.execute(db.select(Product).where(Product.artist_id == current_user.id)).scalars().all()

    # Generate portfolio narrative
    from ai import generate_enhanced_portfolio_narrative

    # Convert posts to dictionaries for AI analysis
    posts_data = []
    for post in user_posts:
        posts_data.append({
            'post_title': post.post_title,
            'post_description': post.description,
            'media_url': post.media_url,
            'created_at': post.created_at
        })

    # Convert products to dictionaries for AI analysis
    products_data = []
    for product in user_products:
        products_data.append({
            'title': product.title,
            'description': product.description,
            'price': product.price,
            'img_url': product.img_url,
            'created_at': product.created_at
        })

    # Generate the portfolio narrative
    portfolio_narrative = generate_enhanced_portfolio_narrative(
        artist_name=current_user.name,
        posts=posts_data,
        products=products_data,
        user_location=current_user.location
    )

    # Calculate artisan rating
    artisan_rating = calculate_artisan_rating(current_user.id)

    # Get follower/following counts
    followers_count = db.session.execute(
        db.select(db.func.count(Follow.id)).where(Follow.followed_id == current_user.id)
    ).scalar()
    following_count = db.session.execute(
        db.select(db.func.count(Follow.id)).where(Follow.follower_id == current_user.id)
    ).scalar()

    # Query conversations where user is buyer or seller
    user_convos = db.session.execute(
        db.select(Conversation).where(
            (Conversation.buyer_id == current_user.id) | (Conversation.seller_id == current_user.id)
        ).order_by(Conversation.last_message_at.desc())
    ).scalars().all()

    # Prepare conversation list for inbox
    conversations = []
    unread_count = 0
    for convo in user_convos:
        # Determine the other user
        other_user = db.session.get(User, convo.seller_id if convo.buyer_id == current_user.id else convo.buyer_id)
        # Count unread messages for current user: messages sent by other user, unread (read_at is null)
        unread = db.session.execute(
            db.select(db.func.count(Message.id)).where(
                Message.conversation_id == convo.id,
                Message.sender_id != current_user.id,
                Message.read_at.is_(None)
            )
        ).scalar()
        unread_count += unread or 0
        conversations.append({
            'id': convo.id,
            'product': db.session.get(Product, convo.product_id),
            'other_user': other_user,
            'last_message_at': convo.last_message_at,
            'unread_count': unread or 0
        })

    return render_template("profile.html",
                           current_user=current_user,
                           profile_user=current_user,
                           posts=user_posts,
                           products=user_products,
                           followers_count=followers_count,
                           following_count=following_count,
                           is_following=False,
                           portfolio_narrative=portfolio_narrative,
                           artisan_rating=artisan_rating,
                           conversations=conversations,
                           unread_count=unread_count,
                           firebase_config=firebase_config.FIREBASE_WEB_CONFIG)


@app.route("/profile/<int:user_id>")
def view_profile(user_id):
    # Get user's posts and products for public profile view
    user = db.get_or_404(User, user_id)
    # Track a profile view (skip self-views)
    try:
        viewer_id = current_user.id if getattr(current_user, 'is_authenticated', False) else None
        if viewer_id is None or viewer_id != user_id:
            db.session.add(ProfileView(
                profile_user_id=user_id,
                viewer_id=viewer_id,
                created_at=date.today().strftime('%B %d, %Y')
            ))
            db.session.commit()
    except Exception:
        db.session.rollback()
    user_posts = db.session.execute(db.select(Posts).where(Posts.artist_id == user_id)).scalars().all()
    user_products = db.session.execute(db.select(Product).where(Product.artist_id == user_id)).scalars().all()

    # Generate portfolio narrative
    from ai import generate_enhanced_portfolio_narrative

    # Convert posts to dictionaries for AI analysis
    posts_data = []
    for post in user_posts:
        posts_data.append({
            'post_title': post.post_title,
            'post_description': post.description,
            'media_url': post.media_url,
            'created_at': post.created_at
        })

    # Convert products to dictionaries for AI analysis
    products_data = []
    for product in user_products:
        products_data.append({
            'title': product.title,
            'description': product.description,
            'price': product.price,
            'img_url': product.img_url,
            'created_at': product.created_at
        })

    # Generate the portfolio narrative
    portfolio_narrative = generate_enhanced_portfolio_narrative(
        artist_name=user.name,
        posts=posts_data,
        products=products_data,
        user_location=user.location
    )

    # Calculate artisan rating
    artisan_rating = calculate_artisan_rating(user_id)

    # Get follower/following counts
    followers_count = db.session.execute(
        db.select(db.func.count(Follow.id)).where(Follow.followed_id == user_id)
    ).scalar()
    following_count = db.session.execute(
        db.select(db.func.count(Follow.id)).where(Follow.follower_id == user_id)
    ).scalar()
    
    # Check if current user is following this user
    is_following = False
    if current_user.is_authenticated and current_user.id != user_id:
        is_following = db.session.execute(
            db.select(Follow).where(
                Follow.follower_id == current_user.id,
                Follow.followed_id == user_id
            )
        ).scalar_one_or_none() is not None

    # Query conversations for this user (if viewing own profile)
    conversations = []
    unread_count = 0
    if current_user.is_authenticated and current_user.id == user_id:
        user_convos = db.session.execute(
            db.select(Conversation).where(
                (Conversation.buyer_id == user_id) | (Conversation.seller_id == user_id)
            ).order_by(Conversation.last_message_at.desc())
        ).scalars().all()
        for convo in user_convos:
            other_user = db.session.get(User, convo.seller_id if convo.buyer_id == user_id else convo.buyer_id)
            unread = db.session.execute(
                db.select(db.func.count(Message.id)).where(
                    Message.conversation_id == convo.id,
                    Message.sender_id != user_id,
                    Message.read_at.is_(None)
                )
            ).scalar()
            unread_count += unread or 0
            conversations.append({
                'id': convo.id,
                'product': db.session.get(Product, convo.product_id),
                'other_user': other_user,
                'last_message_at': convo.last_message_at,
                'unread_count': unread or 0
            })
    return render_template("profile.html",
                           current_user=current_user,
                           profile_user=user,
                           posts=user_posts,
                           products=user_products,
                           followers_count=followers_count,
                           following_count=following_count,
                           is_following=is_following,
                           portfolio_narrative=portfolio_narrative,
                           artisan_rating=artisan_rating,
                           conversations=conversations,
                           unread_count=unread_count,
                           firebase_config=firebase_config.FIREBASE_WEB_CONFIG)


@app.route("/product/<int:product_id>")
def product_buy(product_id):
    product = db.get_or_404(Product, product_id)
    # Track a product view (skip if artist views own product)
    try:
        viewer_id = current_user.id if getattr(current_user, 'is_authenticated', False) else None
        if viewer_id is None or viewer_id != product.artist_id:
            db.session.add(ProductView(
                product_id=product.product_id,
                artist_id=product.artist_id,
                viewer_id=viewer_id,
                created_at=date.today().strftime('%B %d, %Y')
            ))
            db.session.commit()
    except Exception:
        db.session.rollback()
    # Load comments for this product
    comments_rows = db.session.execute(db.select(ProductComments).where(ProductComments.product_id == product.product_id)).scalars().all()
    comments_data = []
    for c in comments_rows:
        author = db.session.get(User, c.user_id)
        comments_data.append({
            'id': c.comment_id,
            'content': c.content,
            'created_at': c.created_at,
            'artist': {
                'name': getattr(author, 'name', 'Unknown') if author else 'Unknown',
                'email': getattr(author, 'email', '') if author else '',
                'id': getattr(author, 'id', None) if author else None,
            }
        })
    setattr(product, 'comments', comments_data)
    # Load reviews and compute average rating
    reviews_rows = db.session.execute(db.select(ProductReview).where(ProductReview.product_id == product.product_id)).scalars().all()
    reviews_data = []
    total_rating = 0
    ratings_map = {}
    for r in reviews_rows:
        author = db.session.get(User, r.user_id)
        reviews_data.append({
            'id': r.review_id,
            'rating': r.rating,
            'title': r.title,
            'content': r.content,
            'created_at': r.created_at,
            'artist': {
                'name': getattr(author, 'name', 'Unknown') if author else 'Unknown',
                'email': getattr(author, 'email', '') if author else '',
                'id': getattr(author, 'id', None) if author else None,
            }
        })
        try:
            total_rating += int(r.rating or 0)
        except Exception:
            pass
        ratings_map[r.user_id] = int(r.rating or 0)
    avg_rating = (total_rating / len(reviews_rows)) if reviews_rows else 0
    setattr(product, 'reviews', reviews_data)
    setattr(product, 'avg_rating', avg_rating)
    setattr(product, 'reviews_count', len(reviews_rows))
    setattr(product, 'ratings_map', ratings_map)
    try:
        setattr(product, 'current_user_rating', ratings_map.get(current_user.id) if current_user.is_authenticated else 0)
    except Exception:
        setattr(product, 'current_user_rating', 0)
    return render_template("product_buy.html",
                           current_user=current_user,
                           product=product)


@app.route('/product/<int:product_id>/chat', methods=["POST"])
def product_chat(product_id):
    """Handle product chatbot questions"""
    try:
        data = request.get_json()
        question = data.get('question', '').strip()
        
        if not question:
            return jsonify({'success': False, 'error': 'Question is required'}), 400
        
        # Get product data
        product = db.get_or_404(Product, product_id)
        artist = db.session.get(User, product.artist_id)
        
        product_data = {
            'title': product.title,
            'description': product.description or '',
            'price': product.price,
            'artist_name': artist.name if artist else 'Unknown Artist'
        }
        
        # Get Gemini API key from environment
        api_key = os.getenv('GEMINI_API_KEY')
        
        # Call the hybrid chatbot
        result = ai.chat_with_product(question, product_data, api_key)
        
        return jsonify({
            'success': True,
            'answer': result['answer'],
            'source': result['source'],
            'suggestions': result['suggestions']
        })
        
    except Exception as e:
        print(f"Product chat error: {e}")
        return jsonify({
            'success': False,
            'error': 'Sorry, I encountered an error. Please try contacting the seller directly.'
        }), 500


@app.route('/product/<int:product_id>/comment', methods=["POST"])
@login_required
def add_product_comment(product_id):
    content = (request.form.get('comment') or '').strip()
    if not content:
        flash('Review text cannot be empty')
        return redirect(url_for('product_buy', product_id=product_id))

    # Always create the visible comment (for backward-compatible UI)
    new_comment = ProductComments(
        product_id=product_id,
        user_id=current_user.id,
        content=content,
        created_at=date.today().strftime("%B %d, %Y")
    )
    db.session.add(new_comment)

    # Optionally create or update a star review when provided
    rating_raw = (request.form.get('rating') or '').strip()
    try:
        rating_val = int(rating_raw) if rating_raw else 0
    except Exception:
        rating_val = 0
    if 1 <= rating_val <= 5:
        existing = db.session.execute(
            db.select(ProductReview).where(
                ProductReview.product_id == product_id,
                ProductReview.user_id == current_user.id
            )
        ).scalar()
        if existing:
            existing.rating = rating_val
            existing.content = content or existing.content
            existing.updated_at = date.today().strftime("%B %d, %Y")
        else:
            db.session.add(ProductReview(
                product_id=product_id,
                user_id=current_user.id,
                rating=rating_val,
                title='',
                content=content,
                created_at=date.today().strftime("%B %d, %Y"),
                updated_at=date.today().strftime("%B %d, %Y"),
            ))

    db.session.commit()
    anchor = request.form.get('anchor')
    if anchor:
        return redirect(url_for('product_buy', product_id=product_id) + '#' + anchor)
    return redirect(url_for('product_buy', product_id=product_id))


@app.route('/product/<int:product_id>/review', methods=["POST"])
@login_required
def add_or_update_product_review(product_id):
    """Create or update a star review for a product. One review per user per product."""
    rating_raw = (request.form.get('rating') or '').strip()
    title = (request.form.get('title') or '').strip()
    content = (request.form.get('content') or '').strip()

    try:
        rating_val = int(rating_raw)
    except Exception:
        rating_val = 0
    if rating_val < 1 or rating_val > 5:
        flash('Please choose a rating between 1 and 5 stars.', 'error')
        return redirect(url_for('product_buy', product_id=product_id))

    # Check for existing review
    existing = db.session.execute(
        db.select(ProductReview).where(
            ProductReview.product_id == product_id,
            ProductReview.user_id == current_user.id
        )
    ).scalar()

    if existing:
        existing.rating = rating_val
        existing.title = title
        existing.content = content
        existing.updated_at = date.today().strftime("%B %d, %Y")
    else:
        new_r = ProductReview(
            product_id=product_id,
            user_id=current_user.id,
            rating=rating_val,
            title=title,
            content=content,
            created_at=date.today().strftime("%B %d, %Y"),
            updated_at=date.today().strftime("%B %d, %Y"),
        )
        db.session.add(new_r)

    db.session.commit()
    flash('Your review has been saved.', 'success')
    return redirect(url_for('product_buy', product_id=product_id))


@app.route('/product/review/<int:review_id>/delete', methods=['POST'])
@login_required
def delete_product_review(review_id):
    r = db.get_or_404(ProductReview, review_id)
    if r.user_id != current_user.id and current_user.id != 1:
        abort(403)
    product_id = r.product_id
    db.session.delete(r)
    db.session.commit()
    flash('Review deleted.', 'info')
    return redirect(url_for('product_buy', product_id=product_id))


@app.route('/product/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_product_comment(comment_id):
    comment = db.get_or_404(ProductComments, comment_id)
    if comment.user_id != current_user.id and current_user.id != 1:
        abort(403)
    product_id = comment.product_id
    user_id = comment.user_id
    db.session.delete(comment)
    
    # Also delete associated review if exists
    review = db.session.execute(
        db.select(ProductReview).where(
            ProductReview.product_id == product_id,
            ProductReview.user_id == user_id
        )
    ).scalar()
    if review:
        db.session.delete(review)
    
    db.session.commit()
    return redirect(url_for('product_buy', product_id=product_id) + '#product-' + str(product_id) + '-comments')


@app.route('/comment/<int:post_id>', methods=["POST"])
@login_required
def add_comments(post_id):
    """Create a comment for a given post_id. Expects form field 'comment'."""
    content = (request.form.get('comment') or '').strip()
    if not content:
        flash('Comment cannot be empty')
        return redirect(url_for('home'))

    new_comment = Comments(
        post_id=post_id,
        user_id=current_user.id,
        content=content,
        created_at=date.today().strftime("%B %d, %Y")
    )
    db.session.add(new_comment)
    db.session.commit()
    # Redirect back to the post anchor so the page doesn't jump to the top
    anchor = request.form.get('anchor')
    if anchor:
        return redirect(url_for('home') + '#' + anchor)
    return redirect(url_for('home'))


@app.route('/api/post/<int:post_id>/likes', methods=['GET'])
def get_post_likes(post_id):
    # Return total like count and whether current user liked (if authenticated)
    total = db.session.execute(db.select(PostLike).where(PostLike.post_id == post_id)).scalars().all()
    count = len(total)
    liked = False
    if current_user and getattr(current_user, 'is_authenticated', False):
        exists = db.session.execute(db.select(PostLike).where(PostLike.post_id == post_id, PostLike.user_id == current_user.id)).scalar()
        liked = bool(exists)
    return jsonify({'count': count, 'liked': liked})


@app.route('/api/post/<int:post_id>/like', methods=['POST'])
@login_required
def toggle_post_like(post_id):
    # Toggle like: if exists, remove; otherwise add
    existing = db.session.execute(db.select(PostLike).where(PostLike.post_id == post_id, PostLike.user_id == current_user.id)).scalar()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        liked = False
    else:
        nl = PostLike(post_id=post_id, user_id=current_user.id)
        db.session.add(nl)
        db.session.commit()
        liked = True

    total = db.session.execute(db.select(PostLike).where(PostLike.post_id == post_id)).scalars().all()
    return jsonify({'count': len(total), 'liked': liked})


@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = db.get_or_404(Comments, comment_id)
    # Allow delete if the current user created it or is admin (id == 1)
    if comment.user_id != current_user.id and current_user.id != 1:
        abort(403)
    post_id = comment.post_id
    db.session.delete(comment)
    db.session.commit()
    # Redirect back to the post anchor
    return redirect(url_for('home') + '#post-' + str(post_id))


@app.route("/verify-phone", methods=["GET", "POST"])
@login_required
def verify_otp():
    """Phone verification page before camera access"""
    show_otp = False
    submitted_phone = request.form.get("phone", current_user.phone if current_user.phone else "")
    
    if request.method == "POST":
        if "otp" in request.form:
            # Verify OTP (dummy check for now)
            if request.form["otp"] == "1234":
                session["phone_verified"] = True
                flash("Phone number verified successfully!", "success")
                return redirect(url_for("camera"))
            else:
                flash("Invalid OTP. Please try again.", "error")
                show_otp = True
        else:
            # Phone number submitted, show OTP field
            show_otp = True
            flash("OTP sent! (Demo: Use 1234)", "success")
    
    return render_template("verify_otp.html", 
                         current_user=current_user, 
                         show_otp=show_otp, 
                         submitted_phone=submitted_phone)

@app.route("/camera")
@login_required
def camera():
    """Camera page for verification purposes"""
    if not session.get("phone_verified"):
        return redirect(url_for("verify_otp"))
    return render_template("camera.html", current_user=current_user)

@app.route("/complete-verification", methods=["POST"])
@login_required
def complete_verification():
    """Complete the verification process"""
    if not session.get("phone_verified"):
        return jsonify({"success": False, "message": "Phone verification required"}), 400
    
    try:
        data = request.get_json()
        if not data or "photo" not in data:
            return jsonify({"success": False, "message": "Missing required data"}), 400

        # Save the verification photo
        photo_data = data["photo"]
        if photo_data.startswith('data:image'):
            # Extract the base64 part
            photo_data = photo_data.split(',')[1]
        
        # Generate unique filename
        filename = f"verification_{current_user.id}_{uuid.uuid4().hex[:8]}.jpg"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'verification', filename)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Save the image
        import base64
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(photo_data))
        
        # Update user verification status
        current_user.is_verified = True
        current_user.verification_photo = filename
        current_user.verification_date = str(date.today())
        db.session.commit()
        
        # Clear the session verification flag
        session.pop("phone_verified", None)
        
        flash("Congratulations! Your account is now verified.", "success")
        return jsonify({
            "success": True,
            "message": "Verification completed successfully",
            "redirect": url_for("profile")
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# ===== CART ROUTES =====

def get_or_create_cart(user_id):
    """Get existing cart or create new one for user"""
    try:
        cart = db.session.execute(db.select(Cart).where(Cart.user_id == user_id)).scalar()
        if not cart:
            cart = Cart(
                user_id=user_id,
                created_at=date.today().strftime("%B %d, %Y"),
                updated_at=date.today().strftime("%B %d, %Y")
            )
            db.session.add(cart)
            db.session.commit()
        return cart
    except Exception as e:
        db.session.rollback()
        raise e
        db.session.commit()
    return cart


@app.route("/cart")
@login_required
def view_cart():
    """View shopping cart"""
    try:
        cart = get_or_create_cart(current_user.id)
        cart_items = db.session.execute(
            db.select(CartItem).where(CartItem.cart_id == cart.cart_id)
        ).scalars().all()

        # Filter out items with deleted/missing products
        valid_items = [item for item in cart_items if item.product is not None]

        # Optionally, remove invalid ones automatically
        invalid_items = [item for item in cart_items if item.product is None]
        for bad_item in invalid_items:
            db.session.delete(bad_item)
        if invalid_items:
            db.session.commit()

        total_price = sum(item.quantity * float(item.product.price) for item in valid_items)

        return render_template(
            "cart.html",
            current_user=current_user,
            cart_items=valid_items,
            total_price=total_price
        )
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error accessing cart: {str(e)}")
        return f"Error accessing cart: {str(e)}", 500



@app.route("/cart/add/<int:product_id>", methods=["POST"])
@login_required
def add_to_cart(product_id):
    """Add product to cart"""
    product = db.get_or_404(Product, product_id)
    cart = get_or_create_cart(current_user.id)
    
    # Check if product already in cart
    existing_item = db.session.execute(
        db.select(CartItem).where(
            CartItem.cart_id == cart.cart_id,
            CartItem.product_id == product_id
        )
    ).scalar()
    
    if existing_item:
        existing_item.quantity += 1
    else:
        new_item = CartItem(
            cart_id=cart.cart_id,
            product_id=product_id,
            quantity=1,
            added_at=date.today().strftime("%B %d, %Y")
        )
        db.session.add(new_item)
    
    cart.updated_at = date.today().strftime("%B %d, %Y")
    db.session.commit()
    
    return jsonify({"success": True, "message": "Product added to cart"})


@app.route("/cart/update/<int:item_id>", methods=["POST"])
@login_required
def update_cart_item(item_id):
    """Update cart item quantity"""
    item = db.get_or_404(CartItem, item_id)
    cart = db.get_or_404(Cart, item.cart_id)
    
    # Ensure user owns this cart
    if cart.user_id != current_user.id:
        abort(403)
    
    quantity = request.json.get('quantity', 1)
    if quantity <= 0:
        db.session.delete(item)
    else:
        item.quantity = quantity
    
    cart.updated_at = date.today().strftime("%B %d, %Y")
    db.session.commit()
    
    return jsonify({"success": True, "message": "Cart updated"})


@app.route("/cart/remove/<int:item_id>", methods=["POST"])
@login_required
def remove_from_cart(item_id):
    """Remove item from cart"""
    item = db.get_or_404(CartItem, item_id)
    cart = db.get_or_404(Cart, item.cart_id)
    
    # Ensure user owns this cart
    if cart.user_id != current_user.id:
        abort(403)
    
    db.session.delete(item)
    cart.updated_at = date.today().strftime("%B %d, %Y")
    db.session.commit()
    
    return jsonify({"success": True, "message": "Item removed from cart"})


@app.route("/cart/clear", methods=["POST"])
@login_required
def clear_cart():
    """Clear entire cart"""
    cart = get_or_create_cart(current_user.id)
    
    # Delete all cart items
    db.session.execute(db.delete(CartItem).where(CartItem.cart_id == cart.cart_id))
    cart.updated_at = date.today().strftime("%B %d, %Y")
    db.session.commit()
    
    return jsonify({"success": True, "message": "Cart cleared"})


@app.route("/api/cart/count")
@login_required
def get_cart_count():
    """Get cart item count for navbar"""
    cart = db.session.execute(db.select(Cart).where(Cart.user_id == current_user.id)).scalar()
    if not cart:
        return jsonify({"count": 0})
    
    count = db.session.execute(
        db.select(db.func.sum(CartItem.quantity)).where(CartItem.cart_id == cart.cart_id)
    ).scalar() or 0
    
    return jsonify({"count": count})


# ===== CHECKOUT AND ORDERS =====
@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    """Checkout page to confirm shipping details and place order.
    POST creates an order from the user's cart and clears the cart.
    """
    # Load cart and validate
    cart = get_or_create_cart(current_user.id)
    cart_items = db.session.execute(
        db.select(CartItem).where(CartItem.cart_id == cart.cart_id)
    ).scalars().all()

    # Only include valid items (products that still exist)
    valid_items = [item for item in cart_items if item.product is not None]
    if request.method == 'POST':
        if not valid_items:
            flash('Your cart is empty.', 'error')
            return redirect(url_for('view_cart'))

        # Gather shipping info from form
        shipping_name = (request.form.get('shipping_name') or current_user.name or '').strip()
        shipping_phone = (request.form.get('shipping_phone') or current_user.phone or '').strip()
        shipping_address = (request.form.get('shipping_address') or current_user.location or '').strip()

        if not shipping_name or not shipping_phone or not shipping_address:
            flash('Please provide name, phone, and address for shipping.', 'error')
            return render_template(
                'checkout.html',
                current_user=current_user,
                cart_items=valid_items,
                subtotal=sum(i.quantity * float(i.product.price) for i in valid_items),
                shipping_name=shipping_name,
                shipping_phone=shipping_phone,
                shipping_address=shipping_address
            )

        # Compute totals
        subtotal = sum(i.quantity * float(i.product.price) for i in valid_items)
        total = subtotal  # Free shipping placeholder

        # Create Order
        new_order = Order(
            user_id=current_user.id,
            status='pending',
            payment_status='unpaid',
            total_price=total,
            shipping_name=shipping_name,
            shipping_phone=shipping_phone,
            shipping_address=shipping_address,
            created_at=date.today().strftime("%B %d, %Y"),
            updated_at=date.today().strftime("%B %d, %Y"),
        )
        db.session.add(new_order)
        db.session.flush()  # get order_id

        # Add OrderItems (snapshot of current product info)
        for ci in valid_items:
            db.session.add(OrderItem(
                order_id=new_order.order_id,
                product_id=ci.product_id,
                product_title=ci.product.title,
                product_img_url=ci.product.img_url,
                unit_price=ci.product.price,
                quantity=ci.quantity,
                total_price=ci.quantity * float(ci.product.price)
            ))

        # Clear cart
        db.session.execute(db.delete(CartItem).where(CartItem.cart_id == cart.cart_id))
        cart.updated_at = date.today().strftime("%B %d, %Y")
        db.session.commit()
        # Redirect to payment page to simulate payment (POST only)
        return redirect(url_for('pay_order', order_id=new_order.order_id))

    # GET: show checkout page populated from user/cart
    return render_template(
        'checkout.html',
        current_user=current_user,
        cart_items=valid_items,
        subtotal=sum(i.quantity * float(i.product.price) for i in valid_items),
        shipping_name=current_user.name or '',
        shipping_phone=current_user.phone or '',
        shipping_address=current_user.location or ''
    )


@app.route('/orders')
@login_required
def orders_list():
    """List current user's orders."""
    orders = db.session.execute(
        db.select(Order).where(Order.user_id == current_user.id).order_by(db.desc(Order.order_id))
    ).scalars().all()
    return render_template('orders.html', current_user=current_user, orders=orders)


@app.route('/orders/<int:order_id>')
@login_required
def order_detail(order_id: int):
    """Order details with items and status."""
    order = db.get_or_404(Order, order_id)
    if order.user_id != current_user.id and current_user.id != 1:
        abort(403)
    # Items are loaded via relationship
    return render_template('order_detail.html', current_user=current_user, order=order)


@app.route('/orders/<int:order_id>/cancel', methods=['POST'])
@login_required
def cancel_order(order_id: int):
    order = db.get_or_404(Order, order_id)
    if order.user_id != current_user.id and current_user.id != 1:
        abort(403)
    if order.status in ('pending',) and order.payment_status in ('unpaid',):
        order.status = 'canceled'
        order.updated_at = date.today().strftime("%B %d, %Y")
        db.session.commit()
        flash('Order canceled.', 'info')
    else:
        flash('Order cannot be canceled at this stage.', 'error')
    return redirect(url_for('order_detail', order_id=order_id))


@app.route('/admin/orders/<int:order_id>/status', methods=['POST'])
@admin_only
def admin_update_order_status(order_id: int):
    """Admin endpoint to update order and payment status. Expects form fields 'status' and optional 'payment_status'."""
    order = db.get_or_404(Order, order_id)
    status = (request.form.get('status') or '').strip().lower()
    payment_status = (request.form.get('payment_status') or '').strip().lower()
    allowed_status = {'pending', 'paid', 'shipped', 'delivered', 'canceled'}
    allowed_pay = {'', 'unpaid', 'paid', 'refunded'}
    if status and status in allowed_status:
        order.status = status
    if payment_status in allowed_pay and payment_status:
        order.payment_status = payment_status
    order.updated_at = date.today().strftime("%B %d, %Y")
    db.session.commit()
    flash('Order updated.', 'success')
    return redirect(url_for('order_detail', order_id=order_id))


@app.route('/pay/<int:order_id>')
@login_required
def pay_order(order_id: int):
    """Start a dummy payment for an order.
    Only order owner can pay.
    """
    order = db.get_or_404(Order, order_id)
    if order.user_id != current_user.id and current_user.id != 1:
        abort(403)
    # If already paid, go to order detail
    if (order.payment_status or '').lower() == 'paid':
        flash('Order already paid.', 'info')
        return redirect(url_for('order_detail', order_id=order_id))

    # Find or create a Payment record
    pay = db.session.execute(db.select(Payment).where(Payment.order_id == order_id).order_by(db.desc(Payment.id))).scalar()
    if not pay:
        pay = Payment(
            order_id=order_id,
            amount=order.total_price or 0,
            currency='INR',
            status='created',
            created_at=date.today().strftime('%B %d, %Y'),
            updated_at=date.today().strftime('%B %d, %Y'),
        )
        db.session.add(pay)
        db.session.commit()

    return render_template('payment.html', current_user=current_user, order=order, payment=pay)


@app.route('/pay/<int:order_id>/create', methods=['POST'])
@login_required
def create_payment(order_id: int):
    order = db.get_or_404(Order, order_id)
    if order.user_id != current_user.id and current_user.id != 1:
        abort(403)
    pay = db.session.execute(db.select(Payment).where(Payment.order_id == order_id).order_by(db.desc(Payment.id))).scalar()
    if not pay:
        pay = Payment(
            order_id=order_id,
            amount=order.total_price or 0,
            currency='INR',
            status='processing',
            created_at=date.today().strftime('%B %d, %Y'),
        )
        db.session.add(pay)
    else:
        pay.status = 'processing'
        pay.updated_at = date.today().strftime('%B %d, %Y')
    db.session.commit()
    # Simulate gateway redirect — go to simulate endpoint
    outcome = (request.form.get('outcome') or 'success').lower()
    return redirect(url_for('simulate_payment', order_id=order_id, payment_id=pay.id, outcome=outcome))


@app.route('/pay/<int:order_id>/simulate')
@login_required
def simulate_payment(order_id: int):
    outcome = (request.args.get('outcome') or 'success').lower()
    payment_id = request.args.get('payment_id')
    order = db.get_or_404(Order, order_id)
    if order.user_id != current_user.id and current_user.id != 1:
        abort(403)

    pay = None
    if payment_id:
        pay = db.session.get(Payment, int(payment_id))
    if not pay:
        pay = db.session.execute(db.select(Payment).where(Payment.order_id == order_id).order_by(db.desc(Payment.id))).scalar()
        if not pay:
            flash('Payment session not found.', 'error')
            return redirect(url_for('pay_order', order_id=order_id))

    if outcome == 'success':
        pay.status = 'paid'
        order.payment_status = 'paid'
        order.status = 'paid'
        order.updated_at = date.today().strftime('%B %d, %Y')
        msg = 'Payment successful! Thank you.'
        category = 'success'
    elif outcome == 'fail':
        pay.status = 'failed'
        msg = 'Payment failed. Please try again.'
        category = 'error'
    else:
        pay.status = 'canceled'
        msg = 'Payment canceled.'
        category = 'info'

    pay.updated_at = date.today().strftime('%B %d, %Y')
    db.session.commit()
    flash(msg, category)
    return redirect(url_for('order_detail', order_id=order_id))


@app.route("/follow/<int:user_id>", methods=["POST"])
@login_required
def follow_user(user_id):
    """Follow a user"""
    if user_id == current_user.id:
        return jsonify({'success': False, 'message': 'Cannot follow yourself'}), 400
    
    user_to_follow = db.get_or_404(User, user_id)
    
    # Check if already following
    existing_follow = db.session.execute(
        db.select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.followed_id == user_id
        )
    ).scalar_one_or_none()
    
    if existing_follow:
        return jsonify({'success': False, 'message': 'Already following this user'}), 400
    
    # Create follow relationship
    follow = Follow(
        follower_id=current_user.id,
        followed_id=user_id,
        created_at=date.today().strftime('%B %d, %Y')
    )
    db.session.add(follow)
    db.session.commit()
    
    # Get updated counts
    followers_count = db.session.execute(
        db.select(db.func.count(Follow.id)).where(Follow.followed_id == user_id)
    ).scalar()
    
    return jsonify({
        'success': True,
        'message': f'Now following {user_to_follow.name}',
        'followers_count': followers_count
    })


@app.route("/unfollow/<int:user_id>", methods=["POST"])
@login_required
def unfollow_user(user_id):
    """Unfollow a user"""
    follow = db.session.execute(
        db.select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.followed_id == user_id
        )
    ).scalar_one_or_none()
    
    if not follow:
        return jsonify({'success': False, 'message': 'Not following this user'}), 400
    
    db.session.delete(follow)
    db.session.commit()
    
    # Get updated counts
    followers_count = db.session.execute(
        db.select(db.func.count(Follow.id)).where(Follow.followed_id == user_id)
    ).scalar()
    
    return jsonify({
        'success': True,
        'message': 'Unfollowed successfully',
        'followers_count': followers_count
    })


@app.route("/hashtag/<tag_name>")
def view_hashtag(tag_name):
    """View all posts and products with a specific hashtag"""
    # Get the hashtag
    hashtag = db.session.execute(
        db.select(Hashtag).where(Hashtag.name == tag_name.lower())
    ).scalar_one_or_none()
    
    if not hashtag:
        flash(f'No content found for #{tag_name}', 'info')
        return redirect(url_for('home'))
    
    # Get all posts with this hashtag
    post_hashtags = db.session.execute(
        db.select(PostHashtag).where(PostHashtag.hashtag_id == hashtag.id)
    ).scalars().all()
    
    posts = []
    for ph in post_hashtags:
        post = db.session.get(Posts, ph.post_id)
        if post:
            posts.append(post)
    
    # Get all products with this hashtag
    product_hashtags = db.session.execute(
        db.select(ProductHashtag).where(ProductHashtag.hashtag_id == hashtag.id)
    ).scalars().all()
    
    products = []
    for prh in product_hashtags:
        product = db.session.get(Product, prh.product_id)
        if product:
            # Add rating info
            reviews = db.session.execute(
                db.select(ProductReview).where(ProductReview.product_id == product.product_id)
            ).scalars().all()
            avg_rating = sum(int(r.rating or 0) for r in reviews) / len(reviews) if reviews else 0
            setattr(product, 'avg_rating', round(avg_rating, 1))
            setattr(product, 'reviews_count', len(reviews))
            products.append(product)
    
    return render_template("hashtag.html", 
                          hashtag=tag_name, 
                          posts=posts, 
                          products=products,
                          current_user=current_user)


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()  # In case error occurred during database operations
    return render_template('500.html'), 500

if __name__ == "__main__":
    try:
        # Enable debug mode by default for direct python execution
        app.debug = True
        
        # Create database tables
        with app.app_context():
            db.create_all()
            print("✅ Database tables created successfully")
            
            # Test database connection
            db.session.execute(db.select(User).limit(1))
            print("✅ Database connection test successful")

        # Run the app
        app.run(port=3000)
    except Exception as e:
        print(f"❌ Error starting app: {e}")
        db.session.rollback()  # Rollback any failed transactions
        print("⚠️ If you're getting database errors, try these steps:")
        print("1. Delete the instance/clyst.db file")
        print("2. Run 'flask db upgrade' to recreate the database")
        print("3. Start the app again")
        raise
