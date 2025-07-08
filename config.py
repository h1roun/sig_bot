# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = "7858800064:AAEhJVfdklh_JHIglWDb4ivQo0KFKRZQ7_o"  # Get from @BotFather
TELEGRAM_CHAT_ID = "5943535144"     # Your actual chat ID

# Trading Configuration
POSITION_MONITORING_INTERVAL = 1    # Check positions every 1 second for scalping
MAX_CONCURRENT_POSITIONS = 5        # Increased from 3 to 5 for more active trading
STOP_LOSS_PERCENTAGE = 0.5          # Tighter 0.5% stop loss for scalping
TAKE_PROFIT_1_PERCENTAGE = 0.5      # First target at 0.5%
TAKE_PROFIT_2_PERCENTAGE = 1.0      # Second target at 1%

# Scalping Strategy Parameters
MIN_ORDER_BOOK_IMBALANCE = 1.2      # Lower threshold
MIN_DAILY_VOLUME_USD = 500000       # Lower minimum volume for more signals
SCALPING_COOLDOWN_SECONDS = 120     # 2 minute cooldown between signals for same coin
USE_BTC_CORRELATION = False         # Disable BTC correlation for more signals
REQUIRE_ALL_CONDITIONS = False      # Only require 6 out of 8 conditions
TREND_CONFIRMATION_TIMEFRAMES = ["5m"]  # Only use 5m for faster signals
