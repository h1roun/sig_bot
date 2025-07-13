# Telegram Configuration
TELEGRAM_BOT_TOKEN = "7858800064:AAEhJVfdklh_JHIglWDb4ivQo0KFKRZQ7_o"  # Get from @BotFather
TELEGRAM_CHAT_ID = "5943535144"

# Trading Configuration
MAX_CONCURRENT_POSITIONS = 1  # Changed from 5 to 1 to only allow one position at a time

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

# Technical Parameters
MACD_CROSSOVER_THRESHOLD = 0.002  # How close to zero for MACD crossover detection
STOCH_DEEP_OVERSOLD = 20          # Deep oversold threshold for stochastic
STOCH_OVERSOLD = 30               # Regular oversold threshold for stochastic
STOCH_RECOVERY = 40               # Upper bound for recovery phase
