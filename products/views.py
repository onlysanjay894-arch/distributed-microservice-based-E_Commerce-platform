from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from decimal import Decimal, ROUND_HALF_UP
import logging

import razorpay

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    product as Product,
    category as Category,
    order as Order,
    order_item as OrderItem,
    Wishlist,
    Review,
    Coupon,
)


# Razorpay client configuration
razorpay_client = razorpay.Client(
    auth=(
        settings.RAZORPAY_KEY_ID,
        settings.RAZORPAY_KEY_SECRET,
    )
)


def home(request):
    products = Product.objects.all()
    categories = Category.objects.all()

    search = request.GET.get('search', '').strip()
    category_id = request.GET.get('category', '').strip()
    sort = request.GET.get('sort', '').strip()

    # Search product names and descriptions.
    if search:
        products = products.filter(
            name__icontains=search
        ) | products.filter(
            description__icontains=search
        )

    # Filter by category.
    if category_id:
        products = products.filter(
            category_id=category_id
        )

    # Sort products.
    if sort == 'price_low':
        products = products.order_by('price')
    elif sort == 'price_high':
        products = products.order_by('-price')
    elif sort == 'newest':
        products = products.order_by('-created_at')

    # Show 8 products per page.
    paginator = Paginator(products, 8)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'products': page_obj,
        'categories': categories,
        'page_obj': page_obj,
        'search': search,
        'selected_category': category_id,
        'sort': sort,
    }

    return render(request, 'home.html', context)


def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    cart_data = request.session.get('cart', {})
    key = str(product.id)

    try:
        quantity = int(request.GET.get('quantity', 1))
    except (ValueError, TypeError):
        quantity = 1

    quantity = max(quantity, 1)
    current_quantity = cart_data.get(key, 0)

    if product.stock <= 0:
        return HttpResponse(
            f'{product.name} is out of stock.'
        )

    if current_quantity + quantity > product.stock:
        return HttpResponse(
            f'Sorry, only {product.stock} units of '
            f'{product.name} are available.'
        )

    cart_data[key] = current_quantity + quantity
    request.session['cart'] = cart_data

    return redirect('cart')


def buy_now(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    try:
        quantity = int(request.GET.get('quantity', 1))
    except (ValueError, TypeError):
        quantity = 1

    quantity = max(quantity, 1)

    if product.stock <= 0 or quantity > product.stock:
        return HttpResponse(
            f'Sorry, only {product.stock} units of '
            f'{product.name} are available.'
        )

    request.session['cart'] = {
        str(product.id): quantity
    }

    return redirect('checkout')


def cart(request):
    cart_data = request.session.get('cart', {})
    products = Product.objects.filter(id__in=cart_data.keys())

    cart_items = []
    subtotal = Decimal('0.00')

    for product in products:
        quantity = cart_data.get(str(product.id), 0)

        if (
            not isinstance(quantity, int)
            or isinstance(quantity, bool)
            or quantity < 1
        ):
            continue

        total = product.price * quantity

        cart_items.append({
            'product': product,
            'quantity': quantity,
            'total': total,
        })

        subtotal += total

    return render(request, 'cart.html', {
        'cart_items': cart_items,
        'subtotal': subtotal,
    })


def increase_quantity(request, product_id):
    cart_data = request.session.get('cart', {})
    key = str(product_id)
    product = get_object_or_404(Product, id=product_id)

    if key in cart_data:
        quantity = cart_data[key]

        if (
            isinstance(quantity, int)
            and not isinstance(quantity, bool)
            and quantity < product.stock
        ):
            cart_data[key] = quantity + 1

    request.session['cart'] = cart_data
    return redirect('cart')


def decrease_quantity(request, product_id):
    cart_data = request.session.get('cart', {})
    key = str(product_id)

    if key in cart_data:
        cart_data[key] -= 1

        if cart_data[key] <= 0:
            del cart_data[key]

    request.session['cart'] = cart_data
    return redirect('cart')


def remove_from_cart(request, product_id):
    cart_data = request.session.get('cart', {})
    cart_data.pop(str(product_id), None)

    request.session['cart'] = cart_data
    return redirect('cart')


@login_required
def checkout(request):
    cart_data = request.session.get('cart', {})

    if not cart_data:
        return redirect('cart')

    def render_checkout(message=None, success=False):
        products = Product.objects.filter(
            id__in=cart_data.keys()
        )

        checkout_items = []
        subtotal = Decimal('0.00')

        for product in products:
            quantity = cart_data.get(str(product.id), 0)

            if (
                not isinstance(quantity, int)
                or isinstance(quantity, bool)
                or quantity < 1
            ):
                continue

            total = product.price * quantity

            checkout_items.append({
                'product': product,
                'quantity': quantity,
                'total': total,
            })

            subtotal += total

        coupon = None
        coupon_code = request.session.get('coupon_code', '')
        discount_amount = Decimal('0.00')

        if coupon_code:
            now = timezone.now()

            try:
                candidate = Coupon.objects.get(
                    code__iexact=coupon_code,
                    active=True,
                    valid_from__lte=now,
                    valid_until__gte=now,
                )

                if (
                    1 <= candidate.discount_percentage <= 100
                    and subtotal >= candidate.minimum_order_amount
                ):
                    coupon = candidate

                    discount_amount = (
                        subtotal
                        * Decimal(candidate.discount_percentage)
                        / Decimal('100')
                    ).quantize(
                        Decimal('0.01'),
                        rounding=ROUND_HALF_UP,
                    )
                else:
                    request.session.pop('coupon_code', None)
                    coupon_code = ''

            except Coupon.DoesNotExist:
                request.session.pop('coupon_code', None)
                coupon_code = ''

        discount_amount = min(discount_amount, subtotal)
        final_total = subtotal - discount_amount

        return render(request, 'checkout.html', {
            'checkout_items': checkout_items,
            'subtotal': subtotal,
            'coupon': coupon,
            'coupon_code': coupon_code,
            'discount_amount': discount_amount,
            'final_total': final_total,
            'error': message if not success else None,
            'success_message': message if success else None,
        })

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'apply_coupon':
            code = request.POST.get(
                'coupon_code', ''
            ).strip().upper()

            if not code:
                return render_checkout(
                    'Please enter a coupon code.'
                )

            now = timezone.now()

            try:
                coupon = Coupon.objects.get(
                    code__iexact=code,
                    active=True,
                    valid_from__lte=now,
                    valid_until__gte=now,
                )
            except Coupon.DoesNotExist:
                request.session.pop('coupon_code', None)

                return render_checkout(
                    'Invalid, expired, or inactive coupon code.'
                )

            if not 1 <= coupon.discount_percentage <= 100:
                return render_checkout(
                    'This coupon has an invalid discount.'
                )

            subtotal = Decimal('0.00')

            for product in Product.objects.filter(
                id__in=cart_data.keys()
            ):
                quantity = cart_data.get(str(product.id), 0)

                if (
                    isinstance(quantity, int)
                    and not isinstance(quantity, bool)
                    and quantity > 0
                ):
                    subtotal += product.price * quantity

            if subtotal < coupon.minimum_order_amount:
                return render_checkout(
                    f'Minimum order amount for this coupon is '
                    f'₹{coupon.minimum_order_amount}.'
                )

            request.session['coupon_code'] = coupon.code

            return render_checkout(
                f'Coupon {coupon.code} applied successfully!',
                success=True,
            )

        if action == 'remove_coupon':
            request.session.pop('coupon_code', None)

            return render_checkout(
                'Coupon removed.',
                success=True,
            )

        customer_name = request.POST.get(
            'customer_name', ''
        ).strip()

        phone = request.POST.get('phone', '').strip()
        address = request.POST.get('address', '').strip()

        if not customer_name or not phone or not address:
            return render_checkout(
                'Please fill all the fields.'
            )

        products = list(
            Product.objects.filter(id__in=cart_data.keys())
        )

        subtotal = Decimal('0.00')

        for product in products:
            quantity = cart_data.get(str(product.id), 0)

            if (
                not isinstance(quantity, int)
                or isinstance(quantity, bool)
                or quantity < 1
            ):
                return render_checkout(
                    'Invalid cart quantity.'
                )

            if quantity > product.stock:
                return render_checkout(
                    f'Sorry, only {product.stock} units of '
                    f'{product.name} are available.'
                )

            subtotal += product.price * quantity

        coupon = None
        discount_amount = Decimal('0.00')
        coupon_code = request.session.get('coupon_code', '')

        if coupon_code:
            now = timezone.now()

            try:
                candidate = Coupon.objects.get(
                    code__iexact=coupon_code,
                    active=True,
                    valid_from__lte=now,
                    valid_until__gte=now,
                )

                if (
                    1 <= candidate.discount_percentage <= 100
                    and subtotal >= candidate.minimum_order_amount
                ):
                    coupon = candidate

                    discount_amount = (
                        subtotal
                        * Decimal(candidate.discount_percentage)
                        / Decimal('100')
                    ).quantize(
                        Decimal('0.01'),
                        rounding=ROUND_HALF_UP,
                    )

            except Coupon.DoesNotExist:
                request.session.pop('coupon_code', None)

        discount_amount = min(discount_amount, subtotal)
        final_total = subtotal - discount_amount

        # Create the order and its items atomically.
        with transaction.atomic():
            locked_products = list(
                Product.objects.select_for_update().filter(
                    id__in=[product.id for product in products]
                )
            )

            for product in locked_products:
                quantity = cart_data.get(str(product.id), 0)

                if quantity > product.stock:
                    return render_checkout(
                        f'Sorry, only {product.stock} units of '
                        f'{product.name} are available.'
                    )

            new_order = Order.objects.create(
                user=request.user,
                customer_name=customer_name,
                phone=phone,
                address=address,
                total_amount=final_total,
                coupon=coupon,
                discount_amount=discount_amount,
                status='Pending',
            )

            for product in locked_products:
                quantity = cart_data[str(product.id)]

                OrderItem.objects.create(
                    order=new_order,
                    product=product,
                    quantity=quantity,
                    price=product.price,
                )

                product.stock -= quantity
                product.save(update_fields=['stock'])

            # Email after the database transaction commits.
            def send_checkout_confirmation():
                try:
                    customer_email = request.user.email

                    if not customer_email:
                        logging.warning(
                            'Order %s has no customer email.',
                            new_order.id,
                        )
                        return

                    send_mail(
                        subject=(
                            f'MyShop - Order #{new_order.id} Received'
                        ),
                        message=(
                            f'Hello {new_order.customer_name},\n\n'
                            f'Thank you for shopping with MyShop.\n\n'
                            f'Your order #{new_order.id} has been '
                            f'received.\n'
                            f'Order total: Rs. {new_order.total_amount}\n'
                            f'Order status: {new_order.status}\n\n'
                            f'Thank you,\nMyShop Team'
                        ),
                        from_email=None,
                        recipient_list=[customer_email],
                        fail_silently=False,
                    )

                except Exception:
                    logging.getLogger(__name__).exception(
                        'Failed to send checkout email for order %s',
                        new_order.id,
                    )

            transaction.on_commit(send_checkout_confirmation)

        request.session['cart'] = {}
        request.session.pop('coupon_code', None)

        return render(request, 'order_success.html', {
            'order': new_order,
        })

    return render_checkout()


def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    reviews = Review.objects.filter(
        product=product
    ).select_related('user').order_by('-created_at')

    average_rating = (
        sum(review.rating for review in reviews) / reviews.count()
        if reviews.exists()
        else 0
    )

    return render(request, 'product_detail.html', {
        'product': product,
        'reviews': reviews,
        'average_rating': average_rating,
        'review_count': reviews.count(),
    })


def register(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('home')
    else:
        form = UserCreationForm()

    return render(request, 'register.html', {
        'form': form,
    })


def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(
            request,
            data=request.POST,
        )

        if form.is_valid():
            login(request, form.get_user())
            return redirect('home')
    else:
        form = AuthenticationForm()

    return render(request, 'login.html', {
        'form': form,
    })


def logout_view(request):
    logout(request)
    return redirect('home')


@login_required
def my_orders(request):
    orders = Order.objects.filter(
        user=request.user
    ).order_by('-created_at')

    tracking_steps = [
        'Confirmed',
        'Processing',
        'Shipped',
        'Out for Delivery',
        'Delivered',
    ]

    status_positions = {
        'Pending': -1,
        'Confirmed': 0,
        'Processing': 1,
        'Shipped': 2,
        'Out for Delivery': 3,
        'Delivered': 4,
        'Cancelled': -1,
    }

    for order in orders:
        order.tracking_step = status_positions.get(
            order.status, -1
        )

    return render(request, 'my_orders.html', {
        'orders': orders,
        'tracking_steps': tracking_steps,
    })


@login_required
def add_to_wishlist(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    Wishlist.objects.get_or_create(
        user=request.user,
        product=product,
    )

    return redirect(
        'product_detail',
        product_id=product.id,
    )


@login_required
def my_wishlist(request):
    wishlist_items = Wishlist.objects.filter(
        user=request.user
    ).select_related('product').order_by('-created_at')

    return render(request, 'my_wishlist.html', {
        'wishlist_items': wishlist_items,
    })


@login_required
def remove_from_wishlist(request, product_id):
    Wishlist.objects.filter(
        user=request.user,
        product_id=product_id,
    ).delete()

    return redirect('my_wishlist')


@login_required
def move_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if product.stock <= 0:
        return HttpResponse(
            f'Sorry, {product.name} is currently out of stock.'
        )

    cart_data = request.session.get('cart', {})
    key = str(product.id)
    current_quantity = cart_data.get(key, 0)

    if current_quantity + 1 > product.stock:
        return HttpResponse(
            f'Sorry, only {product.stock} units of '
            f'{product.name} are available.'
        )

    cart_data[key] = current_quantity + 1
    request.session['cart'] = cart_data

    Wishlist.objects.filter(
        user=request.user,
        product=product,
    ).delete()

    return redirect('cart')


@login_required
def add_review(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if request.method != 'POST':
        return redirect(
            'product_detail',
            product_id=product.id,
        )

    if Review.objects.filter(
        user=request.user,
        product=product,
    ).exists():
        return HttpResponse(
            'You have already reviewed this product.'
        )

    try:
        rating = int(request.POST.get('rating', 0))
    except (ValueError, TypeError):
        rating = 0

    comment = request.POST.get('comment', '').strip()

    if rating < 1 or rating > 5:
        return HttpResponse(
            'Rating must be between 1 and 5.'
        )

    if not comment:
        return HttpResponse(
            'Please write a review.'
        )

    Review.objects.create(
        user=request.user,
        product=product,
        rating=rating,
        comment=comment,
    )

    return redirect(
        'product_detail',
        product_id=product.id,
    )


@login_required
@require_POST
def create_razorpay_order(request):
    cart_data = request.session.get('cart', {})

    if not cart_data:
        return JsonResponse(
            {'error': 'Your cart is empty.'},
            status=400,
        )

    try:
        products = list(
            Product.objects.filter(id__in=cart_data.keys())
        )

        if not products:
            return JsonResponse(
                {'error': 'No valid products were found.'},
                status=400,
            )

        # Validate the cart and calculate the subtotal.
        subtotal = Decimal('0.00')

        for product in products:
            quantity = cart_data.get(str(product.id))

            if (
                not isinstance(quantity, int)
                or isinstance(quantity, bool)
                or quantity < 1
            ):
                return JsonResponse(
                    {'error': 'Invalid cart quantity.'},
                    status=400,
                )

            if quantity > product.stock:
                return JsonResponse(
                    {
                        'error': (
                            f'Only {product.stock} units of '
                            f'{product.name} are available.'
                        )
                    },
                    status=400,
                )

            subtotal += product.price * quantity

        # Validate the coupon.
        coupon = None
        discount_amount = Decimal('0.00')
        coupon_code = request.session.get('coupon_code', '')

        if coupon_code:
            now = timezone.now()

            try:
                candidate = Coupon.objects.get(
                    code__iexact=coupon_code,
                    active=True,
                    valid_from__lte=now,
                    valid_until__gte=now,
                )

                if (
                    1 <= candidate.discount_percentage <= 100
                    and subtotal >= candidate.minimum_order_amount
                ):
                    coupon = candidate

                    discount_amount = (
                        subtotal
                        * Decimal(candidate.discount_percentage)
                        / Decimal('100')
                    ).quantize(
                        Decimal('0.01'),
                        rounding=ROUND_HALF_UP,
                    )

            except Coupon.DoesNotExist:
                request.session.pop('coupon_code', None)

        discount_amount = min(discount_amount, subtotal)
        final_total = subtotal - discount_amount

        if final_total <= 0:
            return JsonResponse(
                {
                    'error': (
                        'Payment amount must be greater than zero.'
                    )
                },
                status=400,
            )

        # Read and validate customer details.
        customer_name = request.POST.get(
            'customer_name', ''
        ).strip()

        customer_email = request.POST.get(
            'email', ''
        ).strip().lower()

        phone = request.POST.get('phone', '').strip()
        address = request.POST.get('address', '').strip()

        if not customer_name or not phone or not address:
            return JsonResponse(
                {'error': 'Please fill in all delivery details.'},
                status=400,
            )

        if not customer_email:
            return JsonResponse(
                {'error': 'Please enter your email address.'},
                status=400,
            )

        try:
            validate_email(customer_email)
        except ValidationError:
            return JsonResponse(
        {'error': 'Please enter a valid email address.'},
                status=400,
            )

        

        # Create the pending order and its items.
        with transaction.atomic():
            locked_products = list(
                Product.objects.select_for_update().filter(
                    id__in=[product.id for product in products]
                )
            )

            # Check stock again while the rows are locked.
            for product in locked_products:
                quantity = cart_data.get(str(product.id), 0)

                if quantity > product.stock:
                    return JsonResponse(
                        {
                            'error': (
                                f'Only {product.stock} units of '
                                f'{product.name} are available.'
                            )
                        },
                        status=400,
                    )

            new_order = Order.objects.create(
                user=request.user,
                customer_name=customer_name,
                email=customer_email,
                phone=phone,
                address=address,
                total_amount=final_total,
                coupon=coupon,
                discount_amount=discount_amount,
                status='Pending',
                payment_status='Pending',
            )

            for product in locked_products:
                OrderItem.objects.create(
                    order=new_order,
                    product=product,
                    quantity=cart_data[str(product.id)],
                    price=product.price,
                )

            # Create the matching Razorpay gateway order.
            gateway_order = razorpay_client.order.create({
                'amount': int(
                    (final_total * Decimal('100')).quantize(
                        Decimal('1'),
                        rounding=ROUND_HALF_UP,
                    )
                ),
                'currency': 'INR',
                'receipt': f'myshop_order_{new_order.id}',
            })

            new_order.razorpay_order_id = gateway_order['id']
            new_order.save(
                update_fields=['razorpay_order_id']
            )

        return JsonResponse({
            'myshop_order_id': new_order.id,
            'razorpay_order_id': gateway_order['id'],
            'amount': gateway_order['amount'],
            'currency': gateway_order['currency'],
            'key_id': settings.RAZORPAY_KEY_ID,
        })

    except Exception:
        logging.getLogger(__name__).exception(
            'Failed to create Razorpay order.'
        )

        return JsonResponse(
            {
                'error': (
                    'Unable to prepare your payment. '
                    'Please try again.'
                )
            },
            status=502,
        )


@login_required
@require_POST
def verify_payment(request):
    payment_id = request.POST.get(
        'razorpay_payment_id', ''
    ).strip()

    gateway_order_id = request.POST.get(
        'razorpay_order_id', ''
    ).strip()

    signature = request.POST.get(
        'razorpay_signature', ''
    ).strip()

    myshop_order_id = request.POST.get(
        'myshop_order_id', ''
    ).strip()

    # Validate required payment details.
    if not all([
        payment_id,
        gateway_order_id,
        signature,
        myshop_order_id,
    ]):
        return JsonResponse(
            {'error': 'Payment verification details are missing.'},
            status=400,
        )

    try:
        with transaction.atomic():
            # Find and lock the order belonging to this user.
            order = Order.objects.select_for_update().get(
                id=int(myshop_order_id),
                user=request.user,
                razorpay_order_id=gateway_order_id,
            )

            # Prevent duplicate stock reduction and email sending.
            if order.payment_status == 'Paid':
                if order.razorpay_payment_id == payment_id:
                    return JsonResponse({
                        'success': True,
                        'message': 'Payment already verified.',
                        'redirect_url': '/my-orders/',
                    })

                return JsonResponse(
                    {'error': 'This order has already been paid.'},
                    status=409,
                )

            # Verify the Razorpay payment signature.
            razorpay_client.utility.verify_payment_signature({
                'razorpay_order_id': gateway_order_id,
                'razorpay_payment_id': payment_id,
                'razorpay_signature': signature,
            })

            # Fetch payment details from Razorpay.
            payment = razorpay_client.payment.fetch(payment_id)

            expected_amount = int(
                (order.total_amount * Decimal('100')).quantize(
                    Decimal('1'),
                    rounding=ROUND_HALF_UP,
                )
            )

            # Validate payment details against this order.
            if (
                payment.get('order_id') != gateway_order_id
                or payment.get('amount') != expected_amount
                or payment.get('currency') != 'INR'
                or payment.get('status') != 'captured'
            ):
                return JsonResponse(
                    {
                        'error': (
                            'Payment is not captured or '
                            'does not match this order.'
                        )
                    },
                    status=400,
                )

            # Load order items.
            items = list(
                order.items.select_related('product')
            )

            # Lock products and check all stock before changing it.
            locked_products = {}

            for item in items:
                product = Product.objects.select_for_update().get(
                    id=item.product_id
                )

                locked_products[product.id] = product

                if product.stock < item.quantity:
                    return JsonResponse(
                        {
                            'error': (
                                'Payment was received, but stock '
                                'needs manual review. Contact support.'
                            )
                        },
                        status=409,
                    )

            # Reduce stock only after every stock check passes.
            for item in items:
                product = locked_products[item.product_id]
                product.stock -= item.quantity

                product.save(
                    update_fields=['stock']
                )

            # Mark the order as paid and confirmed.
            order.payment_status = 'Paid'
            order.razorpay_payment_id = payment_id
            order.status = 'Confirmed'

            order.save(update_fields=[
                'payment_status',
                'razorpay_payment_id',
                'status',
            ])

            # Define the email callback within this function.
            def send_order_confirmation():
                try:
                    customer_email = (order.email or '').strip()

                    if not customer_email:
                        logging.warning(
                            'Order %s has no customer email address.',
                            order.id,
                        )
                        return

                    send_mail(
                        subject=(
                            f'MyShop - Order #{order.id} Confirmed'
                        ),
                        message=(
                            f'Hello {order.customer_name},\n\n'
                            f'Thank you for shopping with MyShop!\n\n'
                            f'Your payment was successful, and your '
                            f'order #{order.id} is confirmed.\n\n'
                            f'Order total: Rs. {order.total_amount}\n'
                            f'Order status: {order.status}\n\n'
                            f'We will keep you updated about your order.'
                            f'\n\n'
                            f'Thank you,\nMyShop Team'
                        ),
                        from_email=None,
                        recipient_list=[customer_email],
                        fail_silently=False,
                    )

                    logging.info(
                        'Order confirmation email sent for order %s.',
                        order.id,
                    )

                except Exception:
                    logging.getLogger(__name__).exception(
                        'Failed to send confirmation email for order %s.',
                        order.id,
                    )

            # Execute the email callback only after the transaction commits.
            transaction.on_commit(send_order_confirmation)

        # Clear the cart after successful payment verification.
        request.session['cart'] = {}
        request.session.pop('coupon_code', None)

        return JsonResponse({
            'success': True,
            'message': 'Payment verified successfully.',
            'redirect_url': '/my-orders/',
        })

    except Order.DoesNotExist:
        return JsonResponse(
            {'error': 'Order not found.'},
            status=404,
        )

    except (ValueError, TypeError):
        return JsonResponse(
            {'error': 'Invalid order or payment details.'},
            status=400,
        )

    except Exception:
        logging.getLogger(__name__).exception(
            'Payment verification failed.'
        )

        return JsonResponse(
            {
                'error': (
                    'Unable to verify payment. '
                    'Please contact support before retrying.'
                )
            },
            status=400,
        )

 