"""
URL configuration for my_shop project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from products.views import (home,
                            add_to_cart,
                            buy_now,
                            cart,
                            increase_quantity,
                            decrease_quantity,
                            remove_from_cart,
                            checkout,
                            checkout,
                            create_razorpay_order,
                            verify_payment,
                            product_detail,
                            register,
                            login_view,
                            logout_view,
                            my_orders,
                            add_to_wishlist,
                            my_wishlist,
                            remove_from_wishlist,
                            move_to_cart,
                            add_review,
                            

)
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path(
    'register/',
    register,
    name='register'
),
path(
    'login/',
    login_view,
    name='login'
),

path(
    'logout/',
    logout_view,
    name='logout'
),
    

    path(
    'add_to_cart/<int:product_id>/',
    add_to_cart,
    name='add_to_cart'),

    path(
    'buy_now/<int:product_id>/',
    buy_now,
    name='buy_now'
),
    path('cart/',cart, name='cart'),

    path(
    'product/<int:product_id>/',
    product_detail,
    name='product_detail'
),

    path(
        'cart/increase/<int:product_id>/',
        increase_quantity,
        name='increase_quantity'
    ),

    path(
        'cart/decrease/<int:product_id>/',
        decrease_quantity,
        name='decrease_quantity'
    ),

    path('cart/remove/<int:product_id>/',
         remove_from_cart,
         name='remove_from_cart'),

    path('checkout/',checkout,
         name='checkout'),

    path(
        'create-razorpay-order/',
        create_razorpay_order,
        name='create_razorpay_order'
    ),

    path(
        'verify-payment/',
        verify_payment,
        name='verify_payment'
    ),

    path(
    'my-orders/',
    my_orders,
    name='my_orders'
),

path(
    'wishlist/add/<int:product_id>/',
    add_to_wishlist,
    name='add_to_wishlist'
),

path(
    'my-wishlist/',
    my_wishlist,
    name='my_wishlist'
),

path(
    'wishlist/remove/<int:product_id>/',
    remove_from_wishlist,
    name='remove_from_wishlist'
),

path(
    'wishlist/move-to-cart/<int:product_id>/',
    move_to_cart,
    name='move_to_cart'
),

path(
    'review/add/<int:product_id>/',
    add_review,
    name='add_review'
),
   
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
