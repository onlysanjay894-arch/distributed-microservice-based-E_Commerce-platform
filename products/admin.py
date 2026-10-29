from django.contrib import admin
from .models import (
    category,
    product,
    order,
    order_item,
    Wishlist,
    Review,
    Coupon,
)


admin.site.register(category)
admin.site.register(product)


@admin.register(order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'customer_name',
        'phone',
        'total_amount',
        'status',
        'created_at',
    )

    list_filter = ('status', 'created_at')
    search_fields = ('customer_name', 'phone')
    ordering = ('-created_at',)

    # Update order status directly from the order list
    list_editable = ('status',)

    # Number of orders shown per page
    list_per_page = 20


admin.site.register(order_item)
admin.site.register(Wishlist)
admin.site.register(Review)
admin.site.register(Coupon)