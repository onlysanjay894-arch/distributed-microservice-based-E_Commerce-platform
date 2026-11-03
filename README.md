# Distributed Microservice Based E-Commerce Platform

Live Demo: https://sanjay7008.pythonanywhere.com

A full-stack Django E-Commerce platform deployed on PythonAnywhere with product management, cart, checkout.

### Features
- Home / Featured Products
- Product Detail, Add to Cart, Checkout
- Admin Panel for product upload
- Media handling (fixed: MEDIA_URL + MEDIA_ROOT)
- Static files served via PythonAnywhere mapping

### Tech Stack
- Backend: Django (my_shop/settings.py)
- Frontend: HTML, Bootstrap, Django Templates (templates/home.html)
- DB: SQLite
- Deployment: PythonAnywhere

### Deployment Fix Applied
The images were 404 on live because settings.py was missing:
```python
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
