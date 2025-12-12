import os
from flask import Flask, render_template, session, redirect, url_for, request, jsonify
from authlib.integrations.flask_client import OAuth
from datetime import datetime
import requests
import cloudinary
import cloudinary.uploader
from functools import wraps
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

# Filtro personalizado para convertir timestamps a fechas
@app.template_filter('timestamp_to_date')
def timestamp_to_date(timestamp):
    if timestamp:
        return datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M:%S')
    return 'N/A'

# Configuración de OAuth
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# Configuración de Cloudinary
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

# Configuración de MongoDB
mongo_client = MongoClient(os.getenv('MONGODB_URI'))
db = mongo_client['examen']
reviews_collection = db['reviews']

# Decorador para rutas protegidas
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Rutas de autenticación
@app.route('/')
def index():
    return render_template('index.html', user=session.get('user'))

@app.route('/login')
def login():
    redirect_uri = url_for('authorize', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/authorize')
def authorize():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')
    
    # Guardar información del token incluyendo timestamps
    session['user'] = {
        'email': user_info['email'],
        'name': user_info.get('name', ''),
        'token': token['access_token'],
        'token_issued_at': token.get('expires_at', 0) - token.get('expires_in', 3600),
        'token_expires_at': token.get('expires_at', 0)
    }
    return redirect(url_for('reviews'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

# Rutas principales
@app.route('/reviews')
@login_required
def reviews():
    return render_template('reviews.html', user=session['user'])

@app.route('/review/<review_id>')
@login_required
def review_detail(review_id):
    review = reviews_collection.find_one({'_id': ObjectId(review_id)})
    if not review:
        return "Reseña no encontrada", 404
    
    review['id'] = str(review['_id'])
    return render_template('review_detail.html', user=session['user'], review=review)

@app.route('/create-review')
@login_required
def create_review():
    return render_template('create_review.html', user=session['user'])

# API endpoints
@app.route('/api/reviews', methods=['GET'])
@login_required
def get_reviews():
    reviews = list(reviews_collection.find())
    # Convertir ObjectId a string para JSON
    for review in reviews:
        review['id'] = str(review['_id'])
        del review['_id']
        if 'created_at' in review:
            review['created_at'] = review['created_at'].isoformat()
    return jsonify(reviews)

@app.route('/api/reviews', methods=['POST'])
@login_required
def add_review():
    data = request.form
    establishment_name = data.get('establishment_name')
    address = data.get('address')
    rating = int(data.get('rating', 0))
    
    # Geocoding con Nominatim (OpenStreetMap)
    geocode_url = f"https://nominatim.openstreetmap.org/search?q={address}&format=json&limit=1"
    headers = {'User-Agent': 'ReViews/1.0'}
    response = requests.get(geocode_url, headers=headers)
    
    if not response.json():
        return jsonify({'error': 'Dirección no encontrada'}), 404
    
    geo_data = response.json()[0]
    lat = float(geo_data['lat'])
    lon = float(geo_data['lon'])
    
    # Subir imágenes a Cloudinary
    image_urls = []
    image_files = request.files.getlist('images')
    for image_file in image_files:
        if image_file:
            upload_result = cloudinary.uploader.upload(image_file)
            image_urls.append(upload_result['secure_url'])
    
    # Guardar en MongoDB
    review_data = {
        'establishment_name': establishment_name,
        'address': address,
        'latitude': lat,
        'longitude': lon,
        'rating': rating,
        'author_email': session['user']['email'],
        'author_name': session['user']['name'],
        'token': session['user']['token'],
        'token_issued_at': session['user']['token_issued_at'],
        'token_expires_at': session['user']['token_expires_at'],
        'images': image_urls,
        'created_at': datetime.utcnow()
    }
    
    result = reviews_collection.insert_one(review_data)
    review_data['id'] = str(result.inserted_id)
    del review_data['_id']
    
    return jsonify(review_data)

@app.route('/api/geocode', methods=['GET'])
@login_required
def geocode():
    address = request.args.get('address')
    if not address:
        return jsonify({'error': 'Dirección no proporcionada'}), 400
    
    geocode_url = f"https://nominatim.openstreetmap.org/search?q={address}&format=json&limit=1"
    headers = {'User-Agent': 'ReViews/1.0'}
    response = requests.get(geocode_url, headers=headers)
    
    if not response.json():
        return jsonify({'error': 'Dirección no encontrada'}), 404
    
    geo_data = response.json()[0]
    return jsonify({
        'latitude': float(geo_data['lat']),
        'longitude': float(geo_data['lon']),
        'display_name': geo_data.get('display_name', '')
    })

if __name__ == '__main__':
    app.run(debug=True)

if __name__ == '__main__':
    app.run(debug=True)
