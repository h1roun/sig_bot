# Telegram Configuration
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"

# Trading Configuration
MAX_CONCURRENT_POSITIONS = 5

# Scanner Configuration
SCAN_INTERVAL = 12  # seconds between scan cycles
COOLDOWN_PERIOD = 180  # 3 minutes between signals for same coin

# Risk Management
DEFAULT_STOP_LOSS_PERCENT = 1.5
DEFAULT_TP1_PERCENT = 2.0
DEFAULT_TP2_PERCENT = 3.5

# Order Book Requirements
MIN_ORDER_BOOK_IMBALANCE = 1.1  # Relaxed from 1.3

# Strategy Parameters
MIN_CORE_CONDITIONS = 4  # out of 5 core conditions
MIN_RSI_OVERSOLD = 25
MAX_RSI_OVERSOLD = 55  # Adaptive based on volatility
