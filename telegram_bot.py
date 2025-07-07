import requests
import json
from datetime import datetime
from typing import Dict, Optional
import asyncio

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
    def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send message to Telegram"""
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return True
            
        except Exception as e:
            print(f"❌ Telegram send error: {e}")
            return False
    
    def send_signal_alert(self, signal: Dict) -> bool:
        """Send trading signal alert"""
        coin = signal['coin']
        entry_price = signal['entry_price']
        tp1 = signal['tp1']
        tp2 = signal['tp2']
        stop_loss = signal['stop_loss']
        entry_level = signal['entry_level']
        confidence = signal['confidence']
        
        message = f"""
🚨 <b>TRADING SIGNAL - {coin}</b> 🚨

💰 <b>Entry Price:</b> ${entry_price:.6f}
🎯 <b>Take Profit 1:</b> ${tp1:.6f} (+0.8%)
🎯 <b>Take Profit 2:</b> ${tp2:.6f} (+1.5%)
🛑 <b>Stop Loss:</b> ${stop_loss:.6f} (-1.0%)

📊 <b>Entry Level:</b> {entry_level}
🔥 <b>Confidence:</b> {confidence}%
⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}

<i>All 8/8 conditions met ✅</i>
        """
        
        return self.send_message(message)
    
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
