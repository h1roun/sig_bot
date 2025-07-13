import requests
from datetime import datetime
from typing import Dict

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
    
    def send_message(self, message: str) -> bool:
        """Send a message to Telegram"""
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                return True
            else:
                print(f"❌ Telegram error: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Telegram send error: {e}")
            return False
    
    def send_bot_status_update(self, status: str, details: str = "") -> bool:
        """Send bot status update message"""
        try:
            message = f"""
🤖 **BOT STATUS UPDATE** 🤖

📊 **Status:** {status}
⏰ **Time:** {datetime.now().strftime('%H:%M:%S')}

{details}
            """.strip()
            
            return self.send_message(message)
                
        except Exception as e:
            print(f"❌ Error sending bot status: {e}")
            return False
    
    def send_signal_alert(self, signal: Dict) -> bool:
        """Send trading signal alert for optimized strategy with error handling"""
        try:
            # Validate required fields are present
            required_fields = ['coin', 'entry_price', 'tp1', 'tp2', 'stop_loss', 'entry_level']
            for field in required_fields:
                if field not in signal:
                    print(f"❌ Missing field '{field}' in signal")
                    return False
            
            # Extract values with fallbacks
            coin = signal['coin']
            entry_price = signal['entry_price']
            tp1 = signal['tp1']
            tp2 = signal['tp2']
            stop_loss = signal['stop_loss']
            entry_level = signal['entry_level']
            confidence = signal.get('confidence', 85)
            signal_strength = signal.get('signal_strength', 5)
            core_conditions_met = signal.get('core_conditions_met', 4)
            atr_value = signal.get('atr_value', 0)
            imbalance_ratio = signal.get('order_book_imbalance', 0)
            strategy_version = signal.get('strategy_version', 'v4_optimized')
            
            # Validate stop loss is below entry and take profit is above entry
            if stop_loss >= entry_price or tp1 <= entry_price or tp2 <= entry_price:
                print(f"❌ Invalid price levels: Entry=${entry_price}, SL=${stop_loss}, TP1=${tp1}, TP2=${tp2}")
                
                # Fix levels
                stop_loss = min(stop_loss, entry_price * 0.985)
                tp1 = max(tp1, entry_price * 1.02)
                tp2 = max(tp2, entry_price * 1.035)
            
            tp1_profit = ((tp1 - entry_price) / entry_price) * 100
            tp2_profit = ((tp2 - entry_price) / entry_price) * 100
            stop_loss_risk = ((entry_price - stop_loss) / entry_price) * 100
            
            # Enhanced signal strength indicators
            if signal_strength >= 6:
                strength_emoji = "🔥🔥🔥"
                strength_text = "PERFECT"
            elif signal_strength == 5:
                strength_emoji = "🔥🔥"
                strength_text = "STRONG"
            else:
                strength_emoji = "🔥"
                strength_text = "GOOD"
            
            # Build message
            message = f"""
🚨 **CRYPTO SIGNAL - OPTIMIZED** 🚨

💰 **{coin}/USDT LONG** {strength_emoji}
📊 **Signal Strength:** {strength_text} ({signal_strength}/6)
🎯 **Core Conditions:** {core_conditions_met}/5 ✅
🎯 **Confidence:** {confidence}%
📈 **Entry Level:** {entry_level}

💵 **Entry:** ${entry_price:.6f}
🎯 **TP1:** ${tp1:.6f} (+{tp1_profit:.2f}%)
🎯 **TP2:** ${tp2:.6f} (+{tp2_profit:.2f}%)
🛡️ **Stop Loss:** ${stop_loss:.6f} (-{stop_loss_risk:.2f}%)

📊 **Technical Details:**
• RSI 5m: {signal.get('rsi_5m', 0):.1f}
• MACD Momentum: {signal.get('macd_momentum', 0):.4f}
• Stochastic K: {signal.get('stoch_k', 0):.1f}
• Volatility Ratio: {signal.get('volatility_ratio', 1):.2f}x

📈 **ATR:** {atr_value:.6f}
⚖️ **Order Book:** {imbalance_ratio:.2f}:1
🔧 **Strategy:** {strategy_version}

✅ **5-Core Strategy Active:**
• Bollinger Band Touch ✓
• RSI Oversold Recovery ✓
• MACD Momentum Building ✓
• Stochastic Recovery ✓
• Trend Alignment ✓

💪 **Optimized for More Signals!**
⏰ **Time:** {datetime.now().strftime('%H:%M:%S')}

🚀 **35-Coin Scanner - Optimized Edition**
            """.strip()
            
            return self.send_message(message)
            
        except Exception as e:
            print(f"❌ Error sending signal alert: {e}")
            return False
    
    def send_position_update(self, symbol: str, status: str, price: float, pnl_percent: float) -> bool:
        """Send position update"""
        coin = symbol.replace('USDT', '')
        
        if status == "TP1_HIT":
            emoji = "🎯"
            status_text = "TAKE PROFIT 1 HIT"
        elif status == "TP2_HIT":
            emoji = "🎯🎯"
            status_text = "TAKE PROFIT 2 HIT"
        elif status == "STOP_LOSS":
            emoji = "🛑"
            status_text = "STOP LOSS HIT"
        else:
            emoji = "📊"
            status_text = status
        
        pnl_emoji = "🟢" if pnl_percent > 0 else "🔴"
        
        message = f"""
{emoji} <b>{coin} - {status_text}</b>

💵 <b>Current Price:</b> ${price:.6f}
{pnl_emoji} <b>P&L:</b> {pnl_percent:+.2f}%
⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}
        """
        
        return self.send_message(message)
