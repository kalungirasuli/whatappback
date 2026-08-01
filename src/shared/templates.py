INTEREST_BODY = (
    "A buyer is interested in your product!\n\n"
    "Product: {product_name}\n"
    "Price: {price:,.0f} {currency}\n\n"
    "Reply to this message to respond to the buyer."
)

RESTOCK_BODY = (
    "Good news! A product you saved is back in stock.\n\n"
    "Product: {product_name}\n"
    "Price: {price:,.0f} {currency}\n\n"
    "Send a message to search for this product."
)

WELCOME_BUYER = (
    "Welcome to whatAppseller!\n\n"
    "Send a photo of what you're looking for, or describe it in text.\n"
    "I'll find the best matches from nearby merchants."
)

HELP_MERCHANT = (
    "Available commands:\n"
    "@register - Register your business\n"
    "@post [image] [caption] - Post a new product\n"
    "@edit [product_id] [field] [value] - Edit a product\n"
    "@stock [product_id] [qty] - Update stock\n"
    "@price [product_id] [amount] - Update price\n"
    "@delete [product_id] - Remove a product\n"
    "@help - Show this message"
)

WELCOME_MERCHANT = (
    "Your shop '{business_name}' is now active!\n\n"
    "You can start posting products with @post.\n"
    "Type @help to see all available commands."
)

STOCK_WARNING = (
    "Stock warning for your product '{product_name}'.\n"
    "Current stock: {stock_qty} units.\n"
    "Please restock or update via @stock {product_id} [qty]."
)
