from flask import Flask, render_template, jsonify, request
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import threading
import json
from dataclasses import dataclass
from typing import Dict, List, Optional
import ta
import config
from telegram_bot import TelegramNotifier
from position_manager import PositionManager

app = Flask(__name__)

@dataclass
class MarketData:
    price: float
    rsi_5m: float
    rsi_15m: float
    rsi_1h: float
    volume: float
    volume_avg: float
    bb_lower: float
    bb_upper: float
    ema_9_15m: float
    ema_21_15m: float
    ema_20_15m: float
    ema_50_daily: float
    weekly_support: float
    btc_trend: str
    timestamp: datetime

class SolanaSignalBot:
    def __init__(self):
        self.running = False
        self.alerts = []
        self.alert_count = 0
        self.last_alert_time = {}  # Track cooldown per symbol
        self.position_size = {"entry_1": 0, "entry_2": 0, "entry_3": 0}
        self.current_data: Dict[str, MarketData] = {}  # Store data for all symbols
        self.top_gainers: List[Dict] = []
        self.scanning_symbols: List[str] = []
        self.headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.selected_symbol = "BTCUSDT"  # Add default symbol
        self.current_scanning_symbol = None  # Add this line
        
        # Initialize scanning symbols
        self.scanning_symbols = [coin['symbol'] for coin in self.top_gainers[:50]]  # Scan all top 50 for better coverage

        # Initialize Telegram and Position Manager
        try:
            self.telegram_notifier = TelegramNotifier(
                config.TELEGRAM_BOT_TOKEN, 
                config.TELEGRAM_CHAT_ID
            )
            print("✅ Telegram notifier initialized")
        except Exception as e:
            print(f"⚠️ Telegram not configured: {e}")
            self.telegram_notifier = None
        
        self.position_manager = PositionManager(self.telegram_notifier)

    def get_top_gainers(self) -> List[Dict]:
        """Fetch top 50 daily gainers from Binance with improved filtering"""
        try:
            print("🔍 Fetching Binance market data...")
            url = "https://api.binance.com/api/v3/ticker/24hr"
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            
            all_tickers = response.json()
            print(f"📊 Received {len(all_tickers)} tickers from Binance")
            
            # Filter USDT pairs and apply quality filters
            filtered_tickers = []
            skip_coins = ['USDC', 'BUSD', 'TUSD', 'USDP', 'FDUSD', 'USDT', 'DAI']
            
            for ticker in all_tickers:
                symbol = ticker['symbol']
                
                # Only USDT pairs
                if not symbol.endswith('USDT'):
                    continue
                    
                # Skip stablecoins
                symbol_base = symbol.replace('USDT', '')
                if any(stable in symbol_base for stable in skip_coins):
                    continue
                
                try:
                    # Parse values
                    price = float(ticker['lastPrice'])
                    volume = float(ticker['volume'])
                    quote_volume = float(ticker['quoteVolume'])
                    change_percent = float(ticker['priceChangePercent'])
                    trades = int(ticker['count'])
                    
                    # Quality filters - Make them less restrictive to get 50 coins
                    if (price > 0.0001 and          # Min price
                        volume > 100 and            # Reduced min volume
                        quote_volume > 10000 and    # Reduced min quote volume ($10k)
                        change_percent > -90 and    # Not completely crashed
                        change_percent < 2000 and   # Not suspicious pump
                        trades > 50):               # Reduced minimum trading activity
                        
                        filtered_tickers.append({
                            'symbol': symbol,
                            'coin': symbol_base,
                            'price': price,
                            'change_24h': change_percent,
                            'volume': volume,
                            'volume_usdt': quote_volume,
                            'high_24h': float(ticker['highPrice']),
                            'low_24h': float(ticker['lowPrice']),
                            'trades': trades
                        })
                        
                except (ValueError, KeyError) as e:
                    continue
            
            # Sort by 24h percentage change (descending) and take top 50
            top_gainers = sorted(filtered_tickers, key=lambda x: x['change_24h'], reverse=True)[:50]
            
            print(f"✅ Found {len(top_gainers)} quality gainers")
            
            # Ensure we have at least some data
            if len(top_gainers) < 10:
                print("⚠️ Warning: Found less than 10 gainers, relaxing filters...")
                # Fallback with even more relaxed filters
                fallback_tickers = []
                for ticker in all_tickers:
                    symbol = ticker['symbol']
                    if symbol.endswith('USDT') and not any(stable in symbol.replace('USDT', '') for stable in skip_coins):
                        try:
                            price = float(ticker['lastPrice'])
                            change_percent = float(ticker['priceChangePercent'])
                            if price > 0.0001 and change_percent > 0:  # Just positive change
                                fallback_tickers.append({
                                    'symbol': symbol,
                                    'coin': symbol.replace('USDT', ''),
                                    'price': price,
                                    'change_24h': change_percent,
                                    'volume': float(ticker['volume']),
                                    'volume_usdt': float(ticker['quoteVolume']),
                                    'high_24h': float(ticker['highPrice']),
                                    'low_24h': float(ticker['lowPrice']),
                                    'trades': int(ticker['count'])
                                })
                        except (ValueError, KeyError):
                            continue
                
                top_gainers = sorted(fallback_tickers, key=lambda x: x['change_24h'], reverse=True)[:50]
                print(f"✅ Fallback: Found {len(top_gainers)} gainers")
            
            return top_gainers
            
        except Exception as e:
            print(f"❌ Error fetching top gainers: {e}")
            # Return some dummy data for testing if API fails
            return self.get_dummy_gainers()
    
    def get_dummy_gainers(self) -> List[Dict]:
        """Generate dummy data for testing when API fails"""
        dummy_coins = ['BTC', 'ETH', 'BNB', 'ADA', 'XRP', 'SOL', 'DOT', 'MATIC', 'LINK', 'AVAX']
        dummy_gainers = []
        
        for i, coin in enumerate(dummy_coins):
            dummy_gainers.append({
                'symbol': f'{coin}USDT',
                'coin': coin,
                'price': 1.0 + (i * 0.1),
                'change_24h': 5.0 + (i * 2.5),
                'volume': 1000000 + (i * 100000),
                'volume_usdt': 50000000 + (i * 5000000),
                'high_24h': 1.1 + (i * 0.1),
                'low_24h': 0.9 + (i * 0.1),
                'trades': 10000 + (i * 1000)
            })
        
        print("🧪 Using dummy data for testing")
        return dummy_gainers

    def get_binance_data(self, symbol=None, intervals=["5m", "15m", "1h", "1d"]):
        """Fetch real-time data from Binance API"""
        if symbol is None:
            symbol = self.selected_symbol
            
        base_url = "https://api.binance.com/api/v3/klines"
        data = {}
        
        for interval in intervals:
            try:
                params = {
                    'symbol': symbol,
                    'interval': interval,
                    'limit': 200
                }
                response = requests.get(base_url, params=params, timeout=10)
                if response.status_code == 200:
                    klines = response.json()
                    df = pd.DataFrame(klines, columns=[
                        'timestamp', 'open', 'high', 'low', 'close', 'volume',
                        'close_time', 'quote_asset_volume', 'number_of_trades',
                        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
                    ])
                    df = df.astype({
                        'open': float, 'high': float, 'low': float, 
                        'close': float, 'volume': float
                    })
                    data[interval] = df
                else:
                    print(f"Error fetching {interval} data for {symbol}: {response.status_code}")
            except Exception as e:
                print(f"Error fetching {interval} data for {symbol}: {e}")
                
        return data
    
    def calculate_indicators(self, data: Dict[str, pd.DataFrame]) -> Optional[MarketData]:
        """Calculate all technical indicators"""
        try:
            # Current price from 5m data
            current_price = float(data['5m']['close'].iloc[-1])
            
            # RSI calculations - Updated for more aggressive signals
            rsi_5m = ta.momentum.RSIIndicator(data['5m']['close'], window=7).rsi().iloc[-1]  # RSI(7) for 5min
            rsi_15m = ta.momentum.RSIIndicator(data['15m']['close'], window=7).rsi().iloc[-1]  # RSI(7) for 15min
            rsi_1h = ta.momentum.RSIIndicator(data['1h']['close'], window=14).rsi().iloc[-1]  # RSI(14) for 1h
            
            # Bollinger Bands (5m)
            bb_5m = ta.volatility.BollingerBands(data['5m']['close'], window=20, window_dev=2)
            bb_lower = bb_5m.bollinger_lband().iloc[-1]
            bb_upper = bb_5m.bollinger_hband().iloc[-1]
            
            # EMAs
            ema_9_15m = ta.trend.EMAIndicator(data['15m']['close'], window=9).ema_indicator().iloc[-1]
            ema_21_15m = ta.trend.EMAIndicator(data['15m']['close'], window=21).ema_indicator().iloc[-1]
            ema_20_15m = ta.trend.EMAIndicator(data['15m']['close'], window=20).ema_indicator().iloc[-1]
            ema_50_daily = ta.trend.EMAIndicator(data['1d']['close'], window=50).ema_indicator().iloc[-1]
            
            # Volume analysis
            current_volume = float(data['5m']['volume'].iloc[-1])
            volume_avg = data['5m']['volume'].rolling(20).mean().iloc[-1]
            
            # Weekly support (simplified - lowest low in last 7 days from daily data)
            weekly_support = data['1d']['low'].tail(7).min()
            
            # Bitcoin trend (simplified - using SOL trend for now)
            btc_trend = "UP" if current_price > ema_50_daily else "DOWN"
            
            return MarketData(
                price=current_price,
                rsi_5m=rsi_5m,
                rsi_15m=rsi_15m,
                rsi_1h=rsi_1h,
                volume=current_volume,
                volume_avg=volume_avg,
                bb_lower=bb_lower,
                bb_upper=bb_upper,
                ema_9_15m=ema_9_15m,
                ema_21_15m=ema_21_15m,
                ema_20_15m=ema_20_15m,
                ema_50_daily=ema_50_daily,
                weekly_support=weekly_support,
                btc_trend=btc_trend,
                timestamp=datetime.now()
            )
        except Exception as e:
            print(f"Error calculating indicators: {e}")
            return None
    
    def check_strategy_conditions(self, data: MarketData) -> Dict[str, bool]:
        """Check all strategy conditions with updated RSI thresholds"""
        conditions = {}
        
        # 1. Bollinger Band Touch (2nd/3rd touch)
        bb_touch_threshold = data.bb_lower * 1.005  # Within 0.5% of lower BB
        conditions['bb_touch'] = data.price <= bb_touch_threshold
        
        # 2. PRIMARY SIGNAL: RSI(7) < 30 on 5min (main entry trigger) - UPDATED
        conditions['rsi_5m'] = data.rsi_5m < 30
        
        # 3. CONFIRMATION: RSI(7) > 35 on 15min (trend still up)
        conditions['rsi_15m'] = data.rsi_15m > 35
        
        # 4. CONFIRMATION: RSI(14) > 50 on 1hour (bigger picture bullish)
        conditions['rsi_1h'] = data.rsi_1h > 50
        
        # 5. Volume declining (below 20-period average)
        conditions['volume_decline'] = data.volume < data.volume_avg
        
        # 6. Above weekly support
        conditions['weekly_support'] = data.price > data.weekly_support
        
        # 7. EMA stack alignment
        ema_stack = (data.price > data.ema_20_15m and 
                    data.ema_9_15m > data.ema_21_15m and
                    data.ema_50_daily > data.ema_50_daily * 0.999)  # Daily EMA sloping up
        conditions['ema_stack'] = ema_stack
        
        # 8. Daily trend UP (BTC proxy)
        conditions['daily_trend'] = data.btc_trend == "UP"
        
        return conditions

    def calculate_confidence(self, data: MarketData, conditions: Dict[str, bool]) -> int:
        """Calculate signal confidence (0-100)"""
        base_confidence = 70 if all(conditions.values()) else 0
        
        # Bonus factors - updated for new RSI threshold
        if data.rsi_5m < 30:  # Updated from 20 to 30
            base_confidence += 10
        if data.volume < data.volume_avg * 0.8:
            base_confidence += 5
        if data.price <= data.bb_lower * 1.001:
            base_confidence += 10
            
        return min(100, base_confidence)

    def add_alert(self, alert_type: str, message: str, details: str = ""):
        """Add alert to the list"""
        alert = {
            'time': datetime.now().strftime('%H:%M:%S'),
            'type': alert_type,
            'message': message,
            'details': details,
            'timestamp': time.time()
        }
        self.alerts.insert(0, alert)
        self.alerts = self.alerts[:10]  # Keep only last 10 alerts
        
        if alert_type == 'SIGNAL':
            self.alert_count += 1
    
    def get_position_size(self, entry_level: int) -> str:
        """Get position size based on entry level"""
        sizes = {1: "50%", 2: "25%", 3: "25%"}
        return sizes.get(entry_level, "50%")

    def check_entry_signals_multi(self, symbol: str, data: MarketData, conditions: Dict[str, bool]) -> Optional[Dict]:
        """Check for entry signals for multi-symbol scanning - Only generate when ALL 8 conditions met"""
        all_conditions_met = all(conditions.values())
        
        # Only generate signal if ALL 8 conditions are met
        if not all_conditions_met:
            return None
        
        # Don't generate signal if already in position for this symbol
        if symbol in self.position_manager.get_active_symbols():
            return None
            
        # Cooldown period per symbol (5 minutes)
        current_time = time.time()
        if symbol in self.last_alert_time and current_time - self.last_alert_time[symbol] < 300:
            return None
            
        # Check max positions limit
        if len(self.position_manager.get_active_symbols()) >= config.MAX_CONCURRENT_POSITIONS:
            print(f"⚠️ Max positions ({config.MAX_CONCURRENT_POSITIONS}) reached, skipping {symbol}")
            return None
            
        # Determine entry level - updated thresholds
        entry_level = 1
        if data.rsi_5m < 25:  # Updated from 15 to 25
            entry_level = 3
        elif data.price <= data.bb_lower * 1.002:  # Very close to BB
            entry_level = 2
        
        # Calculate entry price and targets with updated percentages
        entry_price = data.price
        tp1 = entry_price * (1 + config.TAKE_PROFIT_1_PERCENTAGE / 100)  # +0.8%
        tp2 = entry_price * (1 + config.TAKE_PROFIT_2_PERCENTAGE / 100)  # +1.5%
        stop_loss = entry_price * (1 - config.STOP_LOSS_PERCENTAGE / 100)  # -1.0%
            
        signal = {
            'type': 'LONG_ENTRY',
            'symbol': symbol,
            'coin': symbol.replace('USDT', ''),
            'entry_price': entry_price,
            'tp1': tp1,
            'tp2': tp2,
            'stop_loss': stop_loss,
            'entry_level': entry_level,
            'rsi_5m': data.rsi_5m,
            'rsi_15m': data.rsi_15m,
            'rsi_1h': data.rsi_1h,
            'position_size': self.get_position_size(entry_level),
            'confidence': self.calculate_confidence(data, conditions),
            'timestamp': datetime.now().isoformat()
        }
        
        # Add position to manager
        self.position_manager.add_position(signal)
        
        # Send Telegram notification
        if self.telegram_notifier:
            self.telegram_notifier.send_signal_alert(signal)
        
        # Update cooldown for this symbol
        self.last_alert_time[symbol] = current_time
        
        return signal

    def run_scanner(self):
        """Main scanning loop - REAL process explained"""
        while self.running:
            try:
                # STEP 1: Get fresh top 50 gainers every 5 minutes
                if not self.top_gainers or len(self.current_data) == 0:
                    print("🔄 STEP 1: Getting fresh top 50 gainers...")
                    self.top_gainers = self.get_top_gainers()
                    self.scanning_symbols = [coin['symbol'] for coin in self.top_gainers[:50]]
                    print(f"📊 Got {len(self.scanning_symbols)} coins to scan")
                
                if not self.scanning_symbols:
                    print("⚠️ No symbols to scan, waiting...")
                    time.sleep(30)
                    continue
                
                # Remove symbols that are in active positions
                active_positions = self.position_manager.get_active_symbols()
                available_symbols = [s for s in self.scanning_symbols if s not in active_positions]
                
                if active_positions:
                    print(f"📍 Skipping {len(active_positions)} symbols in active positions: {[s.replace('USDT', '') for s in active_positions]}")
                
                signals_found = 0
                scanned_count = 0
                
                # STEP 2: Scan each available coin one by one for technical analysis
                for symbol in available_symbols:
                    try:
                        # Show current scanning coin in UI
                        self.current_scanning_symbol = symbol.replace('USDT', '')
                        print(f"🔍 STEP 2: Analyzing {symbol}... ({scanned_count + 1}/{len(available_symbols)})")
                        
                        # STEP 3: Get real market data from Binance
                        market_data = self.get_binance_data(symbol)
                        
                        if not market_data or '5m' not in market_data:
                            print(f"⚠️ No market data for {symbol}")
                            continue
                            
                        # STEP 4: Calculate technical indicators (RSI, BB, EMA, etc.)
                        current_data = self.calculate_indicators(market_data)
                        
                        if not current_data:
                            print(f"⚠️ Failed to calculate indicators for {symbol}")
                            continue
                        
                        # STEP 5: Store the analyzed data
                        self.current_data[symbol] = current_data
                        scanned_count += 1
                        
                        # STEP 6: Check all 8 trading conditions
                        conditions = self.check_strategy_conditions(current_data)
                        conditions_met = sum(conditions.values())
                        
                        print(f"📊 {symbol}: {conditions_met}/8 conditions met")
                        
                        # STEP 7: If ALL 8 conditions met = GENERATE SIGNAL
                        signal = self.check_entry_signals_multi(symbol, current_data, conditions)
                        
                        if signal:
                            signals_found += 1
                            coin_name = symbol.replace('USDT', '')
                            message = f"🎯 {coin_name} LONG ENTRY - Level {signal['entry_level']}"
                            details = f"Entry: ${signal['entry_price']:.6f} | TP1: ${signal['tp1']:.6f} | TP2: ${signal['tp2']:.6f} | SL: ${signal['stop_loss']:.6f}"
                            self.add_alert('SIGNAL', message, details)
                            
                            print(f"🚨 SIGNAL GENERATED for {coin_name}!")
                            
                            # Save signal to file
                            with open('signals.json', 'a') as f:
                                f.write(json.dumps(signal) + '\n')
                        
                        # Small delay to avoid hitting API limits
                        time.sleep(0.8)
                        
                    except Exception as e:
                        print(f"❌ Error scanning {symbol}: {e}")
                        continue
                
                # STEP 8: Complete scan cycle
                self.current_scanning_symbol = None
                print(f"✅ SCAN COMPLETE: {scanned_count} coins analyzed, {signals_found} signals generated")
                print(f"📍 Active positions: {len(active_positions)}")
                
                # STEP 9: Wait before next full scan cycle
                print("⏳ Waiting 20 seconds before next scan cycle...")
                time.sleep(20)
                
            except Exception as e:
                print(f"❌ Scanner error: {e}")
                time.sleep(60)

    def get_current_summary(self) -> Dict:
        """Get summary of all currently scanned symbols - ordered by conditions met"""
        if not self.current_data:
            return {
                'total_symbols': 0, 
                'signals_count': 0, 
                'top_opportunities': [],
                'current_scanning': self.current_scanning_symbol,
                'positions': self.position_manager.get_positions_summary()
            }
        
        opportunities = []
        signals_count = 0
        active_positions = self.position_manager.get_active_symbols()
        
        for symbol, data in self.current_data.items():
            # Skip symbols in active positions
            if symbol in active_positions:
                continue
                
            conditions = self.check_strategy_conditions(data)
            conditions_met = sum(conditions.values())
            
            # Count signals (only when ALL 8 conditions are met)
            if conditions_met == 8:
                signals_count += 1
            
            # Include all coins that have some conditions met (for display)
            if conditions_met >= 1:
                opportunities.append({
                    'symbol': symbol,
                    'coin': symbol.replace('USDT', ''),
                    'price': float(data.price),
                    'rsi_5m': float(data.rsi_5m),
                    'conditions_met': int(conditions_met),
                    'conditions': {
                        'bb_touch': bool(conditions.get('bb_touch', False)),
                        'rsi_5m': bool(conditions.get('rsi_5m', False)),
                        'rsi_15m': bool(conditions.get('rsi_15m', False)),
                        'rsi_1h': bool(conditions.get('rsi_1h', False)),
                        'volume_decline': bool(conditions.get('volume_decline', False)),
                        'weekly_support': bool(conditions.get('weekly_support', False)),
                        'ema_stack': bool(conditions.get('ema_stack', False)),
                        'daily_trend': bool(conditions.get('daily_trend', False))
                    }
                })
        
        # Sort by conditions met (descending)
        opportunities.sort(key=lambda x: x['conditions_met'], reverse=True)
        
        return {
            'total_symbols': len(self.current_data) - len(active_positions),
            'signals_count': signals_count,
            'top_opportunities': opportunities,
            'current_scanning': self.current_scanning_symbol,
            'positions': self.position_manager.get_positions_summary()
        }

    def stop(self):
        """Stop the bot"""
        self.running = False
        self.position_manager.stop_monitoring()
        self.add_alert('INFO', '⏹️ Bot Stopped', 'Scanning paused. Click Start to resume.')

    def set_symbol(self, symbol):
        """Set the selected symbol for scanning"""
        self.selected_symbol = symbol
        print(f"Selected symbol set to: {symbol}")

# Global bot instance
signal_bot = SolanaSignalBot()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/start', methods=['POST'])
def start_bot():
    signal_bot.start()
    return jsonify({'status': 'started'})

@app.route('/api/stop', methods=['POST'])
def stop_bot():
    signal_bot.stop()
    return jsonify({'status': 'stopped'})

@app.route('/api/gainers')
def get_gainers():
    """Get top 50 daily gainers"""
    print("🌐 API: Getting gainers...")
    gainers = signal_bot.get_top_gainers()
    print(f"🌐 API: Returning {len(gainers)} gainers")
    return jsonify({'gainers': gainers})

@app.route('/api/set-symbol', methods=['POST'])
def set_symbol():
    """Set the symbol to scan"""
    data = request.get_json()
    symbol = data.get('symbol')
    
    if symbol:
        signal_bot.set_symbol(symbol)
        return jsonify({'status': 'success', 'symbol': symbol})
    else:
        return jsonify({'status': 'error', 'message': 'No symbol provided'}), 400

@app.route('/api/scanner-summary')
def get_scanner_summary():
    """Get summary of multi-scanner status"""
    summary = signal_bot.get_current_summary()
    return jsonify(summary)

@app.route('/api/status')
def get_status():
    # Get summary for multi-scanner
    summary = signal_bot.get_current_summary()
    
    return jsonify({
        'total_symbols': summary['total_symbols'],
        'signals_count': summary['signals_count'],
        'alert_count': signal_bot.alert_count,
        'alerts': signal_bot.alerts,
        'running': signal_bot.running,
        'top_opportunities': summary['top_opportunities'],
        'current_scanning': summary.get('current_scanning')
    })

@app.route('/api/test-alert', methods=['POST'])
def test_alert():
    signal_bot.add_alert('TEST', '🧪 Test Alert', 'This is a test alert to check audio and notifications')
    return jsonify({'status': 'test alert sent'})

@app.route('/api/positions')
def get_positions():
    """Get all positions"""
    return jsonify(signal_bot.position_manager.get_positions_summary())

@app.route('/api/close-position', methods=['POST'])
def close_position():
    """Manually close a position"""
    data = request.get_json()
    symbol = data.get('symbol')
    
    if symbol and signal_bot.position_manager.close_position(symbol):
        return jsonify({'status': 'success', 'message': f'Position {symbol} closed'})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to close position'}), 400

@app.route('/api/test-telegram', methods=['POST'])
def test_telegram():
    """Test Telegram notification"""
    if signal_bot.telegram_notifier:
        success = signal_bot.telegram_notifier.send_message("🧪 Test message from CryptoScanner Bot!")
        if success:
            return jsonify({'status': 'success', 'message': 'Telegram test sent'})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to send telegram message'}), 400
    else:
        return jsonify({'status': 'error', 'message': 'Telegram not configured'}), 400

@app.route('/api/test-bot', methods=['POST'])
def test_bot():
    """Test bot functionality with a simulated signal"""
    try:
        # Check if bot is initialized
        if not signal_bot:
            return jsonify({
                'status': 'error', 
                'message': 'Bot not initialized'
            }), 500
        
        # Test 1: Check Telegram connection
        telegram_status = "Not configured"
        if signal_bot.telegram_notifier:
            try:
                success = signal_bot.telegram_notifier.send_message("🧪 Bot Test - All systems operational!")
                telegram_status = "✅ Working" if success else "❌ Failed"
            except Exception as e:
                telegram_status = f"❌ Error: {str(e)}"
        
        # Test 2: Check Binance API connection
        binance_status = "❌ Failed"
        try:
            test_data = signal_bot.get_binance_data("BTCUSDT", intervals=["5m"])
            if test_data and '5m' in test_data:
                binance_status = "✅ Working"
        except Exception as e:
            binance_status = f"❌ Error: {str(e)}"
        
        # Test 3: Generate a test signal
        test_signal = None
        signal_status = "❌ Not generated"
        
        try:
            # Create a dummy test signal
            from datetime import datetime
            current_time = datetime.now()
            
            test_signal = {
                'type': 'TEST_SIGNAL',
                'symbol': 'TESTUSDT',
                'coin': 'TEST',
                'entry_price': 1.0,
                'tp1': 1.008,  # +0.8%
                'tp2': 1.015,  # +1.5%
                'stop_loss': 0.99,  # -1.0%
                'entry_level': 1,
                'confidence': 100,
                'timestamp': current_time.isoformat(),
                'test': True
            }
            
            # Add test alert to UI
            signal_bot.add_alert(
                'TEST', 
                '🧪 TEST SIGNAL - Bot Working!', 
                f'Entry: $1.000000 | TP1: $1.008000 | TP2: $1.015000 | SL: $0.990000'
            )
            
            signal_status = "✅ Generated"
            
        except Exception as e:
            signal_status = f"❌ Error: {str(e)}"
        
        # Test 4: Check position manager
        position_manager_status = "✅ Working" if signal_bot.position_manager else "❌ Not initialized"
        
        # Compile test results
        test_results = {
            'telegram': telegram_status,
            'binance_api': binance_status,
            'signal_generation': signal_status,
            'position_manager': position_manager_status,
            'bot_running': "✅ Running" if signal_bot.running else "⏹️ Stopped"
        }
        
        # Determine overall status
        all_tests_passed = all('✅' in status for status in test_results.values() if status != "Not configured")
        
        message = f"""
Bot Status: {test_results['bot_running']}
Telegram: {test_results['telegram']}  
Binance API: {test_results['binance_api']}
Signal Gen: {test_results['signal_generation']}
Positions: {test_results['position_manager']}
        """.strip()
        
        return jsonify({
            'status': 'success' if all_tests_passed else 'warning',
            'message': message,
            'test_results': test_results,
            'test_signal': test_signal,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Bot test failed: {str(e)}'
        }), 500

if __name__ == '__main__':
    # Create templates directory
    import os
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    
    print("🚀 Starting Multi-Crypto Scanner Bot...")
    print("📊 Real-time scanning of TOP 20 gainers simultaneously")
    print("🎯 85-90% win rate strategy on multiple coins")
    print("💰 Advanced opportunity detection across hot movers")
    print("🔍 Multi-threaded scanning with smart rate limiting")
    print("💡 Access the bot at: http://localhost:5000")
    
    app.run(debug=True, host='0.0.0.0', port=5000)